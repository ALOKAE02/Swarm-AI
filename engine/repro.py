"""Replay a Finding's recorded steps in a fresh browser to prove it is real,
shrink it to the minimal steps, or verify a fix (bug gone after the patch).

    python repro.py f_0007                       # reproduce one finding (findings.jsonl)
    python repro.py f_0007 --headed              # watch it happen
    python repro.py f_0007 --minimize            # shortest step list that still breaks
    python repro.py --all                        # verify every finding, print a table
    python repro.py f_0007 --findings other.jsonl

From Python (fix-brain "verify the patch" step):
    from repro import reproduces
    still_broken = asyncio.run(reproduces(finding_dict))
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from detectors import Detectors, bug_key
from executor import Executor


def _key(f: dict) -> tuple:
    return bug_key(f["bug_type"], f["message"], f.get("selector", ""), f.get("page_url", ""), f.get("dom", ""))


async def replay(finding: dict, steps: list[dict] | None = None, headed: bool = False) -> list:
    """Run the steps in a fresh context; return every bug the detectors saw."""
    from playwright.async_api import async_playwright
    steps = [dict(s) for s in (finding.get("repro") or [] if steps is None else steps)]
    vp = next(({"width": s["width"], "height": s["height"]} for s in steps if s["action"] == "set_viewport"), None)
    if vp is None:
        w, h = (int(x) for x in (finding.get("viewport") or "1280x800").split("x"))
        vp = {"width": w, "height": h}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed, slow_mo=300 if headed else 0)
        try:
            ctx = await browser.new_context(viewport=vp, ignore_https_errors=True)
            det = Detectors(finding.get("page_url") or finding["url"], set())
            await det.install(ctx)
            page = await ctx.new_page()
            det.attach(page)
            det.had_content = True   # we are checking a known finding, not hunting
            ex = Executor(page, det)
            bugs = []
            for st in steps:
                if st["action"] == "set_viewport":
                    continue
                try:
                    await asyncio.wait_for(ex.perform(st), 25)
                except asyncio.TimeoutError:
                    pass
                bugs += await det.drain()
            bugs += await det.drain(settle=1.0)
            if headed:
                await asyncio.sleep(2)
        finally:
            await browser.close()
    return bugs


async def reproduces(finding: dict, steps: list[dict] | None = None, tries: int = 2) -> bool:
    """True if replaying the steps triggers the same bug again."""
    want = _key(finding)
    for _ in range(tries):
        bugs = await replay(finding, steps)
        if any(bug_key(b.bug_type, b.message, b.selector, b.page_url, b.dom) == want for b in bugs):
            return True
    return False


async def minimize(finding: dict) -> list[dict]:
    """Greedy delta-debugging: drop each step that isn't needed to break the page."""
    steps = list(finding.get("repro") or [])
    head = sum(1 for s in steps[:2] if s["action"] in ("set_viewport", "goto"))
    i = len(steps) - 1
    while i >= head:
        candidate = steps[:i] + steps[i + 1:]
        if await reproduces(finding, candidate, tries=1):
            steps = candidate
        i -= 1
    return steps


def load(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


async def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Replay / minimize / verify Swarm AI findings")
    ap.add_argument("id", nargs="?", help="finding id, e.g. f_0007")
    ap.add_argument("--findings", default="findings.jsonl")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--minimize", action="store_true")
    ap.add_argument("--all", action="store_true", help="verify every finding in the file")
    a = ap.parse_args()
    findings = load(a.findings)
    if a.all:
        ok = 0
        for f in findings:
            r = await reproduces(f)
            ok += r
            print(f"{f['id']}  {'REPRODUCED' if r else 'not reproduced':<15} {f['bug_type']:<18} {f['message'][:60]}")
        print(f"\n{ok}/{len(findings)} findings reproduced from their recorded steps")
        return
    f = next((x for x in findings if x["id"] == a.id), None)
    if not f:
        sys.exit(f"{a.id} not found in {a.findings}")
    print(f"{f['id']} {f['bug_type']}: {f['message'][:100]}")
    for s in f.get("repro") or []:
        print("  ", json.dumps(s, ensure_ascii=False)[:140])
    if a.headed:
        await replay(f, headed=True)
    hit = await reproduces(f)
    print("REPRODUCED" if hit else "NOT reproduced (flaky, state-dependent, or already fixed)")
    if hit and a.minimize:
        steps = await minimize(f)
        print(f"\nMinimal repro ({len(steps)} of {len(f['repro'])} steps):")
        for s in steps:
            print("  ", json.dumps(s, ensure_ascii=False)[:140])


if __name__ == "__main__":
    asyncio.run(main())
