"""SwarmQA orchestrator.

    python swarm.py http://localhost:5173 --agents 6                    # Nano-driven swarm
    python swarm.py http://localhost:5173 --agents 8 --headed --tile    # hero-shot mode
    python swarm.py http://localhost:5173 --minutes 3                   # time budget instead of steps
    python swarm.py http://localhost:5173 --no-llm                      # heuristic only, zero API calls
    python swarm.py --stub                                              # fake findings, no browser

Outputs (all JSON lines / JSON, safe to tail live):
    findings.jsonl     one Finding per bug (see contract.py)
    events.jsonl       live agent activity: plans, actions, findings (for the dashboard)
    run_summary.json   coverage, findings by type/severity, Nano calls/tokens/cost
    shots/             one screenshot per finding
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from contract import BUG_TYPES, CORE_TYPES, Finding, append_jsonl, seed_ids_from


@dataclass
class Config:
    findings_path: str = "findings.jsonl"
    shots_dir: str = "shots"
    max_steps: int = 30
    minutes: float | None = None
    settle: float = 0.3
    page_budget: int = 10
    seed: int | None = None
    detectors: tuple = field(default_factory=lambda: BUG_TYPES)
    include_third_party: bool = False
    storage_state: str | None = None
    tile: bool = False
    show_ui: bool = False
    spread: bool = True


def tile_args(i: int, n: int, screen_w: int = 1920, screen_h: int = 1080) -> list[str]:
    """Chromium flags that place window i of n in a grid on one screen."""
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    w, h = screen_w // cols, screen_h // rows
    x, y = (i % cols) * w, (i // cols) * h
    return [f"--window-position={x},{y}", f"--window-size={w},{h}"]


def parse_detectors(spec: str | tuple | list | None) -> tuple:
    if spec is None or spec == "all":
        return BUG_TYPES
    if spec == "core":
        return CORE_TYPES
    if isinstance(spec, str):
        spec = [s.strip() for s in spec.split(",") if s.strip()]
    bad = [s for s in spec if s not in BUG_TYPES]
    if bad:
        raise ValueError(f"unknown detector(s) {bad}; choose from {BUG_TYPES}")
    return tuple(spec)


async def run_swarm(url: str, agents: int = 4, headed: bool = False, tile: bool = False,
                    use_llm: bool = True, max_steps: int = 30,
                    findings_path: str = "findings.jsonl", shots_dir: str = "shots",
                    on_finding=None, screen: tuple[int, int] = (1920, 1080), *,
                    minutes: float | None = None, slowmo: int = 0, seed: int | None = None,
                    llm_calls: int = 400, llm_concurrency: int = 8, detectors="all",
                    include_third_party: bool = False, storage_state: str | None = None,
                    events_path: str | None = "events.jsonl",
                    summary_path: str | None = "run_summary.json", fresh: bool = False,
                    page_budget: int = 10, show_ui: bool | None = None) -> list[Finding]:
    # Lazy imports so --stub works without Playwright/OpenAI installed.
    from playwright.async_api import async_playwright
    from agent import Agent
    from personas import pick
    from state import SwarmState

    if fresh:
        for p in (findings_path, events_path):
            if p and Path(p).exists():
                Path(p).unlink()
    seed_ids_from(findings_path)
    run_id = uuid.uuid4().hex[:6]
    cfg = Config(findings_path=findings_path, shots_dir=shots_dir, max_steps=max_steps, minutes=minutes,
                 page_budget=page_budget, seed=seed, detectors=parse_detectors(detectors),
                 include_third_party=include_third_party, storage_state=storage_state,
                 tile=headed and tile, show_ui=headed if show_ui is None else show_ui)
    state = SwarmState(url, run_id, events_path)

    llm = None
    if use_llm:
        try:
            from llm import LLM
            llm = LLM(max_concurrency=llm_concurrency, max_calls=llm_calls)
        except Exception as e:
            print(f"Nano unavailable ({e}); running the heuristic planner instead.")

    personas = pick(agents)
    budget = f"{minutes} min" if minutes else f"{max_steps} actions/agent"
    print(f"SwarmQA run {run_id}: {agents} agents on {url} | {budget} | "
          f"planner: {'Nemotron Nano + heuristic fallback' if llm else 'heuristic'}")
    state.emit("run_start", url=url, agents=agents, personas=[p["name"] for p in personas],
               planner="nano" if llm else "heuristic")

    async with async_playwright() as pw:
        browsers = []
        if headed and tile:   # one process per agent so each window can be placed
            for i in range(agents):
                browsers.append(await pw.chromium.launch(headless=False, slow_mo=slowmo,
                                                         args=tile_args(i, agents, *screen)))
        else:                 # one process, many isolated contexts: far lighter
            shared = await pw.chromium.launch(headless=not headed, slow_mo=slowmo)
            browsers = [shared] * agents
        try:
            swarm = [Agent(i, personas[i], browsers[i], state, cfg, llm, on_finding) for i in range(agents)]
            results = await asyncio.gather(*(a.run() for a in swarm), return_exceptions=True)
        finally:
            for b in set(browsers):
                try:
                    await b.close()
                except Exception:
                    pass

    findings = [f for r in results if isinstance(r, list) for f in r]
    summary = state.summary(llm.stats() if llm else None)
    state.emit("run_done", **{k: v for k, v in summary.items() if k != "run_id"})
    if summary_path:
        Path(summary_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print_summary(summary, findings_path)
    return findings


def print_summary(s: dict, findings_path: str) -> None:
    print(f"\nRun {s['run_id']} done in {s['seconds']}s: {s['actions']} actions "
          f"({s['failed_actions']} failed), {s['pages_visited']}/{s['pages_discovered']} pages visited, "
          f"{s['elements_exercised']} elements exercised")
    sev = s["by_severity"]
    print(f"Findings: {s['findings']}  (high {sev.get('high', 0)}, medium {sev.get('medium', 0)}, "
          f"low {sev.get('low', 0)})  -> {findings_path}")
    for t, n in sorted(s["by_type"].items(), key=lambda kv: -kv[1]):
        print(f"  {t:<18} {n}")
    llm = s.get("llm") or {}
    if llm:
        print(f"Nano: {llm['calls']} calls ({llm['failed']} failed, {llm['unparsed']} unparsable), "
              f"{llm['prompt_tokens']:,} in / {llm['completion_tokens']:,} out tokens, "
              f"~${llm['est_cost_usd']:.4f}; plans {s['plans']}")


def run_stub(findings_path: str, delay: float = 1.5) -> None:
    """Emit realistic fake Findings so the dashboard and fix-brain can be built
    without the engine."""
    fakes = [
        dict(persona="impatient rage-clicker", viewport="1280x800", severity="high",
             actions=["rage_click #buy"], bug_type="console_error",
             message="Cannot read properties of undefined (reading 'id')",
             stack="TypeError: Cannot read properties of undefined (reading 'id')\n    at handleBuy (Buy.jsx:14:22)",
             dom="<button id=\"buy\">Buy</button>", selector="#buy", intent="hammer the buy button",
             page_url="http://localhost:5173/"),
        dict(persona="mobile thumb-tapper", viewport="375x812", severity="medium",
             actions=["scroll 600", "resize 375x812"], bug_type="layout_overflow",
             message="Horizontal overflow: content is 612px wide in a 375px viewport; "
                     "root cause table.pricing extends to 612px",
             dom="<table class=\"pricing\" style=\"width:600px\">...</table>", selector="table.pricing",
             intent="check the pricing page on a phone", page_url="http://localhost:5173/pricing"),
        dict(persona="malicious form-filler", viewport="1280x800", severity="high",
             actions=["type #email 'null' + Enter"], bug_type="unhandled_promise",
             message="Failed to fetch /api/subscribe (422)",
             stack="Error: Failed to fetch\n    at onSubmit (Signup.jsx:31:11)",
             dom="<button id=\"submit\">Subscribe</button>", selector="#submit",
             intent="submit junk to the signup form", page_url="http://localhost:5173/signup"),
    ]
    seed_ids_from(findings_path)
    for fk in fakes:
        f = Finding(url="http://localhost:5173", **fk)
        append_jsonl(findings_path, f)
        print("stub finding:", f.id, f.bug_type)
        time.sleep(delay)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):      # Windows consoles + emoji payloads
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="SwarmQA chaos engine")
    ap.add_argument("url", nargs="?", help="staging URL to attack (only sites you own or may test)")
    ap.add_argument("--agents", type=int, default=4)
    ap.add_argument("--steps", type=int, default=30, help="max actions per agent")
    ap.add_argument("--minutes", type=float, default=None, help="time budget per agent (overrides --steps)")
    ap.add_argument("--headed", action="store_true", help="show the browser windows (with cursor overlay)")
    ap.add_argument("--tile", action="store_true", help="with --headed: tile windows on one screen")
    ap.add_argument("--screen", default="1920x1080", help="screen size for tiling, e.g. 2560x1440")
    ap.add_argument("--slowmo", type=int, default=0, help="ms delay per browser action (nicer on video)")
    ap.add_argument("--no-ui", action="store_true", help="headed mode without cursor/badge/alarm overlay")
    ap.add_argument("--no-llm", action="store_true", help="heuristic planner only, no API calls")
    ap.add_argument("--llm-calls", type=int, default=400, help="hard cap on Nano calls per run")
    ap.add_argument("--detectors", default="all", help="all | core | comma list, e.g. console_error,xss")
    ap.add_argument("--include-third-party", action="store_true", help="also report third-party script errors")
    ap.add_argument("--storage-state", default=None, help="logged-in session from login.py")
    ap.add_argument("--page-budget", type=int, default=10, help="actions on one page before exploring")
    ap.add_argument("--seed", type=int, default=None, help="make heuristic choices reproducible")
    ap.add_argument("--fresh", action="store_true", help="clear findings/events files first")
    ap.add_argument("--stub", action="store_true", help="write fake findings and exit")
    ap.add_argument("--out", default="findings.jsonl")
    ap.add_argument("--events", default="events.jsonl")
    ap.add_argument("--summary", default="run_summary.json")
    ap.add_argument("--shots", default="shots")
    a = ap.parse_args()

    if a.stub:
        run_stub(a.out)
        return
    if not a.url:
        ap.error("url is required unless --stub")
    sw, sh = (int(x) for x in a.screen.lower().split("x"))
    asyncio.run(run_swarm(
        a.url, a.agents, a.headed, a.tile, not a.no_llm, a.steps, a.out, a.shots, screen=(sw, sh),
        minutes=a.minutes, slowmo=a.slowmo, seed=a.seed, llm_calls=a.llm_calls, detectors=a.detectors,
        include_third_party=a.include_third_party, storage_state=a.storage_state,
        events_path=a.events, summary_path=a.summary, fresh=a.fresh, page_budget=a.page_budget,
        show_ui=False if a.no_ui else None))


if __name__ == "__main__":
    main()
