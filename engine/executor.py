"""Executes one step on a page. Shared by live agents and by repro replay, so a
recorded finding replays with exactly the same mechanics.

A step is a dict, e.g.
  {"action": "rage_click", "selector": "#buy", "sqa": "e4", "label": "Buy"}
  {"action": "type", "selector": "input[name=\"email\"]", "text": "$XSS", "submit": true}
  {"action": "goto", "url": "http://localhost:5173/#/pricing"}
"sqa" is the live snapshot id (fast path); "selector" is the stable fallback
that repro uses.
"""
from __future__ import annotations

import asyncio
import random
import re

from personas import expand

NAV_ACTIONS = ("goto", "back", "forward", "reload")

ACCEPT_JS = r"""
() => {
  const rx = /^\s*(accept( all)?( cookies)?|allow all( cookies)?|i agree|agree|got it|ok(ay)?|i understand)\s*$/i;
  for (const el of document.querySelectorAll('button,a,[role=button]')) {
    const t = (el.innerText || el.getAttribute('aria-label') || '').trim();
    if (!rx.test(t)) continue;
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const p = getComputedStyle(e).position;
      if (p === 'fixed' || p === 'sticky') { el.click(); return t; }
    }
  }
  return '';
}
"""


async def dismiss_overlays(page) -> str:
    """Click an obvious cookie/consent button so it doesn't block every click."""
    try:
        return await asyncio.wait_for(page.evaluate(ACCEPT_JS), 2.0) or ""
    except Exception:
        return ""


async def locate(page, step: dict):
    sqa = step.get("sqa")
    if sqa:
        loc = page.locator(f'[data-sqa="{sqa}"]')
        try:
            if await loc.count() == 1:
                return loc
        except Exception:
            pass
    sel = step.get("selector")
    if sel:
        try:
            loc = page.locator(sel)
            if await loc.count() >= 1:
                return loc.first
        except Exception:
            pass
    label = step.get("label")
    if label:
        try:
            loc = page.get_by_text(label, exact=True)
            if await loc.count() >= 1:
                return loc.first
        except Exception:
            pass
    return None


def describe(step: dict) -> str:
    a = step["action"]
    target = step.get("selector") or step.get("label") or ""
    if a == "type":
        t = str(step.get("text", ""))
        shown = t if t.startswith("$") else repr(expand(t)[:30])
        return f"type {target} {shown}" + (" + Enter" if step.get("submit") else "")
    if a in ("click", "rage_click", "dblclick", "hover", "select", "check"):
        return f"{a} {target}"
    if a == "press":
        return f"press {step.get('key')}"
    if a == "scroll":
        return f"scroll {step.get('dy')}"
    if a == "resize":
        return f"resize {step.get('width')}x{step.get('height')}"
    if a == "set_viewport":
        return f"viewport {step.get('width')}x{step.get('height')}"
    if a == "throttle":
        return f"network {step.get('mode')}"
    if a == "goto":
        return f"goto {step.get('url')}"
    if a == "wait":
        return f"wait {step.get('ms')}ms"
    return a


class Executor:
    def __init__(self, page, detectors=None, rng: random.Random | None = None):
        self.page = page
        self.det = detectors
        self.rng = rng or random.Random()
        self.cdp = None
        self.offline = False

    async def _cdp(self):
        if self.cdp is None:
            try:
                self.cdp = await self.page.context.new_cdp_session(self.page)
                await self.cdp.send("Network.enable")
            except Exception:
                self.cdp = False
        return self.cdp or None

    async def set_network(self, mode: str) -> None:
        cdp = await self._cdp()
        if not cdp:
            return
        cond = {
            "offline": dict(offline=True, latency=0, downloadThroughput=0, uploadThroughput=0),
            "slow": dict(offline=False, latency=1200, downloadThroughput=40_000, uploadThroughput=20_000),
            "online": dict(offline=False, latency=0, downloadThroughput=-1, uploadThroughput=-1),
        }.get(mode, None)
        if cond is None:
            return
        await cdp.send("Network.emulateNetworkConditions", cond)
        self.offline = mode == "offline"
        if self.det:
            self.det.set_offline(self.offline)

    async def perform(self, step: dict) -> tuple[str, bool]:
        """Run one step. Returns (description, ok). Never raises."""
        p, a = self.page, step.get("action")
        desc = describe(step) if a else "noop"
        try:
            if a in ("click", "rage_click", "dblclick", "hover", "type", "select", "check"):
                loc = await locate(p, step)
                if loc is None:
                    return desc + " (element gone)", False
                if a == "click" or a == "check":
                    await loc.click(timeout=1500, no_wait_after=True)
                elif a == "dblclick":
                    await loc.dblclick(timeout=1500, no_wait_after=True)
                elif a == "hover":
                    await loc.hover(timeout=1500)
                elif a == "rage_click":
                    # Real rage: hammer the same screen point, whatever ends up under it.
                    await loc.scroll_into_view_if_needed(timeout=1500)
                    box = await loc.bounding_box()
                    if not box:
                        return desc + " (not visible)", False
                    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    for _ in range(int(step.get("times", 6))):
                        await p.mouse.click(x, y)
                        await asyncio.sleep(0.035)
                elif a == "type":
                    await loc.fill(expand(step.get("text", "")), timeout=1500)
                    if step.get("submit"):
                        await loc.press("Enter", timeout=1500, no_wait_after=True)
                elif a == "select":
                    n = await loc.evaluate("el => el.options ? el.options.length : 0")
                    if n:
                        idx = step.get("index")
                        idx = int(idx) if isinstance(idx, int) else self.rng.randrange(n)
                        step["index"] = idx
                        await loc.select_option(index=min(idx, n - 1), timeout=1500)
                return desc, True
            if a == "press":
                await p.keyboard.press(str(step.get("key", "Tab")))
                return desc, True
            if a == "scroll":
                await p.mouse.wheel(0, int(step.get("dy", 800)))
                return desc, True
            if a in ("resize", "set_viewport"):
                w, h = int(step.get("width", 375)), int(step.get("height", 812))
                await p.set_viewport_size({"width": max(280, min(w, 2560)), "height": max(400, min(h, 1600))})
                return desc, True
            if a == "throttle":
                await self.set_network(str(step.get("mode", "slow")))
                return desc, True
            if a == "goto":
                await p.goto(step["url"], wait_until="load", timeout=20000)
                await dismiss_overlays(p)
                return desc, True
            if a == "back":
                await p.go_back(wait_until="load", timeout=8000)
                return desc, True
            if a == "forward":
                await p.go_forward(wait_until="load", timeout=8000)
                return desc, True
            if a == "reload":
                await p.reload(wait_until="load", timeout=15000)
                return desc, True
            if a == "wait":
                await asyncio.sleep(min(2.0, max(0, int(step.get("ms", 400))) / 1000))
                return desc, True
        except Exception as e:
            reason = re.sub(r"\s+", " ", str(e).split("\n")[0])[:60]
            return f"{desc} (failed: {type(e).__name__}: {reason})", False
        return desc + " (unknown action)", False
