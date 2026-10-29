"""SwarmQA orchestrator.

    python swarm.py https://staging.example.com --agents 4
    python swarm.py http://localhost:5173 --agents 8 --headed --tile      # hero-shot mode
    python swarm.py http://localhost:5173 --no-llm                        # random policy, no API calls
    python swarm.py --stub                                                # fake findings, no browser (for Alok/Gagana)

Findings are appended to findings.jsonl (see contract.py).
"""
from __future__ import annotations

import argparse
import asyncio
import math
import time
from pathlib import Path

from contract import Finding, append_jsonl


def tile_args(i: int, n: int, screen_w: int = 1920, screen_h: int = 1080) -> list[str]:
    """Chromium flags that place window i of n in a grid on one screen."""
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    w, h = screen_w // cols, screen_h // rows
    x, y = (i % cols) * w, (i // cols) * h
    return [f"--window-position={x},{y}", f"--window-size={w},{h}"]


async def run_swarm(url: str, agents: int = 4, headed: bool = False, tile: bool = False,
                    use_llm: bool = True, max_steps: int = 12,
                    findings_path: str = "findings.jsonl", shots_dir: str = "shots",
                    on_finding=None, screen: tuple[int, int] = (1920, 1080)) -> list[Finding]:
    # Imported lazily so --stub works without Playwright/OpenAI installed.
    from playwright.async_api import async_playwright
    from agent import Agent
    from personas import pick

    seen: set = set()
    personas = pick(agents)
    t0 = time.time()
    async with async_playwright() as pw:
        # In tiled mode each agent gets its own browser process so we can place
        # real OS windows; viewport=None would follow the window size, but we keep
        # persona viewports for layout-bug coverage and tile the windows around them.
        browsers = []
        for i in range(agents):
            args = tile_args(i, agents, *screen) if (headed and tile) else []
            browsers.append(await pw.chromium.launch(headless=not headed, args=args))
        try:
            tasks = [
                Agent(i, personas[i], browsers[i], url, seen, findings_path, shots_dir,
                      on_finding=on_finding, use_llm=use_llm, max_steps=max_steps).run()
                for i in range(agents)
            ]
            results = await asyncio.gather(*tasks)
        finally:
            for b in browsers:
                await b.close()
    findings = [f for r in results for f in r]
    print(f"\nSwarm done in {time.time() - t0:.1f}s: {len(findings)} unique finding(s) -> {findings_path}")
    return findings


def run_stub(findings_path: str, delay: float = 1.5) -> None:
    """Emit three realistic fake Findings (one per planted bug) so the dashboard
    and fix-brain can be built without the engine."""
    fakes = [
        dict(persona="impatient rage-clicker", viewport="1280x800",
             actions=["click #buy", "click #buy", "click #buy"],
             bug_type="console_error",
             message="Cannot read properties of undefined (reading 'id')",
             stack="TypeError: Cannot read properties of undefined (reading 'id')\n    at handleBuy (Buy.jsx:14:22)",
             dom="<button id=\"buy\">Buy</button>", selector="#buy"),
        dict(persona="mobile thumb-tapper", viewport="375x812",
             actions=["scroll 600", "resize 375x812"],
             bug_type="layout_overflow",
             message="Horizontal overflow: content is 612px wide in a 375px viewport",
             dom="<table class=\"pricing\" style=\"width:600px\">...</table>", selector="table.pricing"),
        dict(persona="malicious form-filler", viewport="1280x800",
             actions=["type #email 'null'", "click #submit"],
             bug_type="unhandled_promise",
             message="Failed to fetch /api/subscribe (422)",
             stack="Error: Failed to fetch\n    at onSubmit (Signup.jsx:31:11)",
             dom="<button id=\"submit\">Subscribe</button>", selector="#submit"),
    ]
    for fk in fakes:
        f = Finding(url="http://localhost:5173", **fk)
        append_jsonl(findings_path, f)
        print("stub finding:", f.id, f.bug_type)
        time.sleep(delay)


def main() -> None:
    ap = argparse.ArgumentParser(description="SwarmQA chaos engine")
    ap.add_argument("url", nargs="?", help="staging URL to attack")
    ap.add_argument("--agents", type=int, default=4)
    ap.add_argument("--steps", type=int, default=12, help="max actions per agent")
    ap.add_argument("--headed", action="store_true", help="show the browser windows")
    ap.add_argument("--tile", action="store_true", help="with --headed: tile windows on one screen")
    ap.add_argument("--screen", default="1920x1080", help="screen size for tiling, e.g. 2560x1440")
    ap.add_argument("--no-llm", action="store_true", help="random policy instead of Nemotron Nano")
    ap.add_argument("--stub", action="store_true", help="write fake findings and exit")
    ap.add_argument("--out", default="findings.jsonl")
    ap.add_argument("--shots", default="shots")
    a = ap.parse_args()

    if a.stub:
        run_stub(a.out)
        return
    if not a.url:
        ap.error("url is required unless --stub")
    sw, sh = (int(x) for x in a.screen.lower().split("x"))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(run_swarm(a.url, a.agents, a.headed, a.tile, not a.no_llm,
                          a.steps, a.out, a.shots, screen=(sw, sh)))


if __name__ == "__main__":
    main()
