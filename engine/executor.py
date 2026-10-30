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
import math
import random
import re
import time

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
    """human=True drives the page like a person: curved, eased mouse paths with
    Fitts-law timing and occasional overshoot, off-centre clicks with a real
    press, key-by-key typing (long junk is pasted), and scrolling in eased wheel
    bursts. Used for headed/demo runs; headless runs stay fast and direct."""

    def __init__(self, page, detectors=None, rng: random.Random | None = None, human: bool = False):
        self.page = page
        self.det = detectors
        self.rng = rng or random.Random()
        self.human = human
        self.slow = False
        self.cdp = None
        self.offline = False
        self.mx = self.my = None

    # ---- human motion ----------------------------------------------------
    async def _vp(self) -> tuple[int, int]:
        vp = self.page.viewport_size
        if vp:
            return vp["width"], vp["height"]
        try:
            w, h = await self.page.evaluate("() => [innerWidth, innerHeight]")
            return int(w), int(h)
        except Exception:
            return 1280, 800

    async def _ensure_cursor(self) -> None:
        if self.mx is None:
            w, h = await self._vp()
            self.mx, self.my = w * self.rng.uniform(0.35, 0.65), h * self.rng.uniform(0.3, 0.6)
            await self.page.mouse.move(self.mx, self.my)

    async def _path(self, x0, y0, x1, y1, dur) -> None:
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / d, dx / d
        bend = self.rng.uniform(-0.16, 0.16) * d
        c1 = (x0 + dx * 0.28 + nx * bend, y0 + dy * 0.28 + ny * bend)
        c2 = (x0 + dx * 0.72 + nx * bend * 0.45, y0 + dy * 0.72 + ny * bend * 0.45)
        steps = 6 if self.slow else min(28, max(6, int(dur * 45)))
        t_start = time.monotonic()
        for i in range(1, steps + 1):
            t = i / steps
            s = t * t * t * (10 - 15 * t + 6 * t * t)          # minimum-jerk easing
            u = 1 - s
            px = u ** 3 * x0 + 3 * u * u * s * c1[0] + 3 * u * s * s * c2[0] + s ** 3 * x1
            py = u ** 3 * y0 + 3 * u * u * s * c1[1] + 3 * u * s * s * c2[1] + s ** 3 * y1
            if i < steps:
                px += self.rng.uniform(-0.4, 0.4)
                py += self.rng.uniform(-0.4, 0.4)
            t_move = time.monotonic()
            await self.page.mouse.move(px, py)
            if time.monotonic() - t_move > 0.12:
                self.slow = True              # heavy page: the renderer can't keep up with smooth motion
            if time.monotonic() - t_start > dur * 2 + 0.3:
                await self.page.mouse.move(x1, y1)
                break
            await asyncio.sleep(dur / steps)
        self.mx, self.my = x1, y1

    async def move_to(self, x: float, y: float) -> None:
        await self._ensure_cursor()
        d = math.hypot(x - self.mx, y - self.my)
        if d < 2:
            return
        dur = min(0.85, 0.16 + 0.1 * math.log2(1 + d / 28)) * self.rng.uniform(0.85, 1.15)
        if d > 260 and self.rng.random() < 0.55:                # overshoot, then correct
            k = self.rng.uniform(8, 16) / d
            ox, oy = x + (x - self.mx) * k, y + (y - self.my) * k
            await self._path(self.mx, self.my, ox, oy, dur * 0.85)
            await self._path(ox, oy, x, y, self.rng.uniform(0.08, 0.15))
        else:
            await self._path(self.mx, self.my, x, y, dur)

    async def human_scroll(self, dy: float) -> None:
        await self._ensure_cursor()
        step = 300 if self.slow else 100
        ticks = max(1, min(24, int(abs(dy) // step)))
        step = abs(dy) / ticks
        sign = 1 if dy > 0 else -1
        for i in range(ticks):
            await self.page.mouse.wheel(0, step * sign)
            await asyncio.sleep(0.016 + 0.03 * (i / ticks) ** 2)   # fast flick, easing out
            if i and i % 6 == 0 and self.rng.random() < 0.5:
                await asyncio.sleep(self.rng.uniform(0.12, 0.3))   # glance, keep going
        await asyncio.sleep(self.rng.uniform(0.1, 0.25))

    async def _target(self, loc):
        """A natural point on the element (not dead centre), scrolling to it first."""
        box = await loc.bounding_box()
        if not box:
            return None
        w, h = await self._vp()
        if box["y"] < 64 or box["y"] + box["height"] > h - 24:
            await self.human_scroll(box["y"] + box["height"] / 2 - h * 0.45)
            box = await loc.bounding_box()
            if not box or box["y"] < 0 or box["y"] + box["height"] > h:
                await loc.scroll_into_view_if_needed(timeout=1500)
                box = await loc.bounding_box()
            if not box:
                return None
        fx = min(0.8, max(0.2, self.rng.gauss(0.5, 0.14)))
        fy = min(0.75, max(0.25, self.rng.gauss(0.5, 0.14)))
        return box["x"] + box["width"] * fx, box["y"] + box["height"] * fy

    async def human_click(self, loc, rage: int = 0, double: bool = False) -> bool:
        pt = await self._target(loc)
        if not pt:
            return False
        await self.move_to(*pt)
        await asyncio.sleep(self.rng.uniform(0.04, 0.12))       # aim settles
        m = self.page.mouse
        if rage:
            for _ in range(rage):
                await m.down()
                await asyncio.sleep(self.rng.uniform(0.025, 0.05))
                await m.up()
                await asyncio.sleep(self.rng.uniform(0.05, 0.09))
                self.mx += self.rng.uniform(-2.5, 2.5)
                self.my += self.rng.uniform(-2.5, 2.5)
                await m.move(self.mx, self.my)
        else:
            for _ in range(2 if double else 1):
                await m.down()
                await asyncio.sleep(self.rng.uniform(0.05, 0.11))
                await m.up()
                if double:
                    await asyncio.sleep(0.07)
        return True

    async def human_type(self, loc, text: str, submit: bool) -> None:
        if not await self.human_click(loc):
            await loc.focus(timeout=1500)
        kb = self.page.keyboard
        await asyncio.sleep(self.rng.uniform(0.12, 0.3))
        await kb.press("ControlOrMeta+A")
        if not text:
            await kb.press("Backspace")
        elif len(text) > 48:                                    # nobody types 5,000 A's: paste it
            await asyncio.sleep(self.rng.uniform(0.2, 0.4))
            await kb.insert_text(text)
        else:
            for ch in text:
                await kb.type(ch)
                delay = self.rng.lognormvariate(-2.9, 0.35)       # ~55 ms median
                if ch == " ":
                    delay += 0.04
                if self.rng.random() < 0.03:
                    delay += self.rng.uniform(0.2, 0.45)          # brief hesitation
                await asyncio.sleep(delay)
        if submit:
            await asyncio.sleep(self.rng.uniform(0.2, 0.45))
            await kb.press("Enter")

    async def restore_cursor(self) -> None:
        """After a navigation the overlay is new; put the cursor back where it was
        (or place it for the first time, so keyboard-only agents are visible too)."""
        if self.human and self.mx is None:
            try:
                await self._ensure_cursor()
            except Exception:
                pass
        elif self.human:
            try:
                await self.page.mouse.move(self.mx + 0.5, self.my)
            except Exception:
                pass

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
                if self.human and a in ("click", "check", "dblclick", "rage_click", "hover", "type"):
                    if a == "type":
                        await self.human_type(loc, expand(step.get("text", "")), bool(step.get("submit")))
                        return desc, True
                    if a == "hover":
                        pt = await self._target(loc)
                        if pt:
                            await self.move_to(*pt)
                            await asyncio.sleep(self.rng.uniform(0.35, 0.8))
                        return desc, bool(pt)
                    ok = await self.human_click(loc, rage=int(step.get("times", 6)) if a == "rage_click" else 0,
                                                double=a == "dblclick")
                    return (desc, True) if ok else (desc + " (not visible)", False)
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
                    if self.human:
                        pt = await self._target(loc)
                        if pt:
                            await self.move_to(*pt)
                            await asyncio.sleep(self.rng.uniform(0.2, 0.5))
                    n = await loc.evaluate("el => el.options ? el.options.length : 0")
                    if n:
                        idx = step.get("index")
                        idx = int(idx) if isinstance(idx, int) else self.rng.randrange(n)
                        step["index"] = idx
                        await loc.select_option(index=min(idx, n - 1), timeout=1500)
                return desc, True
            if a == "press":
                if self.human:
                    await asyncio.sleep(self.rng.uniform(0.1, 0.3))
                await p.keyboard.press(str(step.get("key", "Tab")))
                return desc, True
            if a == "scroll":
                if self.human:
                    await self.human_scroll(int(step.get("dy", 800)))
                else:
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
                await self.restore_cursor()
                return desc, True
            if a == "back":
                await p.go_back(wait_until="load", timeout=8000)
                await self.restore_cursor()
                return desc, True
            if a == "forward":
                await p.go_forward(wait_until="load", timeout=8000)
                await self.restore_cursor()
                return desc, True
            if a == "reload":
                await p.reload(wait_until="load", timeout=15000)
                await self.restore_cursor()
                return desc, True
            if a == "wait":
                await asyncio.sleep(min(2.0, max(0, int(step.get("ms", 400))) / 1000))
                return desc, True
        except Exception as e:
            reason = re.sub(r"\s+", " ", str(e).split("\n")[0])[:60]
            return f"{desc} (failed: {type(e).__name__}: {reason})", False
        return desc + " (unknown action)", False
