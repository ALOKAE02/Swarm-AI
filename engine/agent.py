"""One chaotic browser agent: observe page -> Nemotron Nano picks next action
(JSON) -> execute -> run detectors -> emit Findings.

If Nano errors or returns junk, a random fallback policy keeps the agent moving
so the demo never stalls (and credits aren't burned on retries).
"""
from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page

from contract import Finding, append_jsonl
from detectors import SELECTOR_JS, Detectors

ELEMENTS_JS = "() => {" + SELECTOR_JS + """
  const sel = 'a[href], button, input, select, textarea, [role=button], [onclick], summary';
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none') continue;
    out.push({
      selector: __sqaSelector(el),
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      text: (el.innerText || el.value || el.getAttribute('placeholder') || el.getAttribute('aria-label') || '').trim().slice(0, 40),
    });
    if (out.length >= 25) break;
  }
  return out;
}
"""

ACTIONS = ("click", "rage_click", "type", "scroll", "resize", "throttle", "press", "wait")

SYSTEM = """You are a chaotic QA tester controlling a web browser. Your goal is to break the page.
Persona: {name}. {brief}

Reply with ONE JSON object and nothing else, using one of these shapes:
{{"action":"click","selector":"<css>"}}
{{"action":"rage_click","selector":"<css>"}}            (clicks it 6 times very fast)
{{"action":"type","selector":"<css>","text":"<input>"}}
{{"action":"scroll","dy":<pixels, negative = up>}}
{{"action":"resize","width":<px>,"height":<px>}}
{{"action":"throttle","mode":"offline|slow|online"}}
{{"action":"press","key":"Tab|Enter|Escape|Space|ArrowDown"}}
{{"action":"wait","ms":<0-1500>}}
Use selectors ONLY from the element list. Vary your actions; do not repeat the same one forever."""


class Agent:
    def __init__(self, idx: int, persona: dict, browser: Browser, url: str,
                 seen: set, findings_path: str, shots_dir: str,
                 on_finding: Callable[[Finding], Awaitable[None] | None] | None = None,
                 window_pos: tuple[int, int] | None = None,
                 use_llm: bool = True, max_steps: int = 12):
        self.idx, self.persona, self.browser, self.url = idx, persona, browser, url
        self.seen, self.findings_path, self.shots_dir = seen, findings_path, shots_dir
        self.on_finding = on_finding
        self.use_llm, self.max_steps = use_llm, max_steps
        self.history: list[str] = []
        self.ctx: BrowserContext | None = None
        self.page: Page | None = None
        self.det: Detectors | None = None
        self.client = None
        if use_llm:  # lazy import so --no-llm works without the openai package
            import llm
            self._llm = llm
            self.client = llm.async_client()
        self.origin = urlparse(url).netloc
        self.cdp = None

    # ------------------------------------------------------------------
    async def run(self) -> list[Finding]:
        w, h = self.persona["viewport"]
        self.ctx = await self.browser.new_context(viewport={"width": w, "height": h})
        self.page = await self.ctx.new_page()
        self.det = Detectors(self.page, self.seen)
        await self.det.install()
        try:
            self.cdp = await self.ctx.new_cdp_session(self.page)
            await self.cdp.send("Network.enable")
        except Exception:
            self.cdp = None
        found: list[Finding] = []
        try:
            await self.page.goto(self.url, wait_until="load", timeout=30000)
            found += await self._collect()          # bugs present on first load
            for _ in range(self.max_steps):
                action = await self._decide()
                desc = await self._execute(action)
                self.history.append(desc)
                found += await self._collect()
                await self._stay_on_origin()
        except Exception as e:                       # a dead agent must not kill the swarm
            print(f"[agent {self.idx}] stopped: {e}")
        finally:
            await self.ctx.close()
        return found

    # ------------------------------------------------------------------
    async def _decide(self) -> dict:
        try:
            elements = await self.page.evaluate(ELEMENTS_JS)
        except Exception:
            elements = []
        if not self.use_llm or not elements:
            return self._fallback(elements)
        user = (f"URL: {self.page.url}\nViewport: {self.page.viewport_size}\n"
                f"Recent actions: {self.history[-5:]}\n"
                f"Elements: {json.dumps(elements)}\nNext action JSON:")
        try:
            r = await self.client.chat.completions.create(
                model=self._llm.NANO, temperature=0.9, max_tokens=300,
                messages=[
                    {"role": "system", "content": SYSTEM.format(**self.persona)},
                    {"role": "user", "content": user},
                ])
            act = self._llm.extract_json(r.choices[0].message.content or "")
            if act and act.get("action") in ACTIONS:
                return act
        except Exception as e:
            print(f"[agent {self.idx}] nano error, using fallback: {e}")
        return self._fallback(elements)

    @staticmethod
    def _fallback(elements: list[dict]) -> dict:
        r = random.random()
        if elements and r < 0.45:
            return {"action": "rage_click", "selector": random.choice(elements)["selector"]}
        inputs = [e for e in elements if e["tag"] in ("input", "textarea")]
        if inputs and r < 0.75:
            junk = random.choice(["", "😀" * 50, "<script>alert(1)</script>", "-1", "null", "A" * 5000])
            return {"action": "type", "selector": random.choice(inputs)["selector"], "text": junk}
        if r < 0.9:
            return {"action": "scroll", "dy": random.choice([600, -300, 1500])}
        return {"action": "resize", "width": random.choice([320, 768, 1920]), "height": 800}

    # ------------------------------------------------------------------
    async def _execute(self, a: dict) -> str:
        p, kind = self.page, a["action"]
        sel = a.get("selector", "")
        try:
            if kind in ("click", "rage_click") and sel:
                n = 6 if kind == "rage_click" else 1
                for _ in range(n):
                    await p.click(sel, timeout=1500, no_wait_after=True)
                    if n > 1:
                        await asyncio.sleep(0.04)
                return f"{kind} {sel}"
            if kind == "type" and sel:
                await p.fill(sel, str(a.get("text", "")), timeout=1500)
                return f"type {sel} {str(a.get('text', ''))[:30]!r}"
            if kind == "scroll":
                await p.mouse.wheel(0, int(a.get("dy", 600)))
                return f"scroll {a.get('dy', 600)}"
            if kind == "resize":
                w, h = int(a.get("width", 375)), int(a.get("height", 812))
                await p.set_viewport_size({"width": max(280, w), "height": max(400, h)})
                return f"resize {w}x{h}"
            if kind == "throttle" and self.cdp:
                mode = a.get("mode", "slow")
                cond = {"offline": dict(offline=True, latency=0, downloadThroughput=0, uploadThroughput=0),
                        "slow": dict(offline=False, latency=800, downloadThroughput=50_000, uploadThroughput=20_000),
                        "online": dict(offline=False, latency=0, downloadThroughput=-1, uploadThroughput=-1)}[mode if mode in ("offline", "slow", "online") else "slow"]
                await self.cdp.send("Network.emulateNetworkConditions", cond)
                return f"throttle {mode}"
            if kind == "press":
                await p.keyboard.press(str(a.get("key", "Tab")))
                return f"press {a.get('key', 'Tab')}"
            if kind == "wait":
                await asyncio.sleep(min(1.5, int(a.get("ms", 300)) / 1000))
                return "wait"
        except Exception as e:
            return f"{kind} {sel} (failed: {type(e).__name__})"
        return f"{kind} (noop)"

    async def _stay_on_origin(self) -> None:
        if urlparse(self.page.url).netloc != self.origin:
            await self.page.goto(self.url, wait_until="load", timeout=30000)

    # ------------------------------------------------------------------
    async def _collect(self) -> list[Finding]:
        out: list[Finding] = []
        for bug in await self.det.drain():
            vp = self.page.viewport_size or {"width": 0, "height": 0}
            f = Finding(
                url=self.url, persona=self.persona["name"],
                viewport=f"{vp['width']}x{vp['height']}",
                actions=self.history[-6:], bug_type=bug.bug_type,
                message=bug.message, stack=bug.stack, dom=bug.dom, selector=bug.selector,
            )
            try:
                shot = Path(self.shots_dir) / f"{f.id}.png"
                shot.parent.mkdir(parents=True, exist_ok=True)
                await self.page.screenshot(path=str(shot))
                f.screenshot = str(shot)
            except Exception:
                pass
            append_jsonl(self.findings_path, f)
            if self.on_finding:
                res = self.on_finding(f)
                if asyncio.iscoroutine(res):
                    await res
            print(f"[agent {self.idx}] FOUND {f.id} {f.bug_type}: {f.message[:80]}")
            out.append(f)
        return out
