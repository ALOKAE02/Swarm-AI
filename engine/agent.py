"""One chaotic browser agent.

Loop: observe page -> plan 1-4 actions (Nemotron Nano, or the coverage-guided
heuristic) -> execute each -> run detectors after each -> emit Findings with a
replayable repro trail. Agents share a URL frontier, so they split the site
between them, and they recover on their own from hung or crashed tabs.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from collections import Counter
from pathlib import Path

from contract import Finding, append_jsonl
from detectors import Detectors, route
from executor import NAV_ACTIONS, Executor, describe, dismiss_overlays
from observe import snapshot
from policy import HeuristicPolicy, NanoPolicy, el_key

COLORS = ["#d9363e", "#2563eb", "#0f7f58", "#b45309", "#7c3aed", "#0e7490", "#be185d", "#4d7c0f"]

BUG_TITLES = {
    "console_error": "Crash caught", "unhandled_promise": "Unhandled promise", "layout_overflow": "Layout overflow",
    "network_error": "Server error", "broken_resource": "Broken file", "blank_screen": "Blank screen",
    "unresponsive": "Page froze", "xss": "Script injection",
}

# Demo overlay: a real arrow cursor with a name tag (like multiplayer cursors),
# a thin ring on each press, a keycap for keyboard agents, and on a bug a quiet
# notification plus an outline on the element that broke. pointer-events:none
# throughout, and every node is tagged data-sqa-ui so detectors ignore it.
UI_JS = r"""
(() => {
  if (window.__sqaUI) return;
  window.__sqaUI = true;
  const NAME = __LABEL__, C = __COLOR__;
  const mk = (tag, cls) => { const d = document.createElement(tag); if (cls) d.className = cls; d.setAttribute('data-sqa-ui', ''); return d; };
  let root = null, cur = null, keyEl = null, last = {x: -60, y: -60}, keyTimer = 0;
  const CSS = `
    .sqa-root{position:fixed;inset:0;pointer-events:none;z-index:2147483647;font:600 11px/1.25 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
    .sqa-cur{position:absolute;left:0;top:0;will-change:transform;filter:drop-shadow(0 1px 1.2px rgba(0,0,0,.38))}
    .sqa-cur svg{display:block}
    .sqa-tag{position:absolute;left:15px;top:19px;white-space:nowrap;padding:3px 7px 3px;border-radius:6px;background:${C};color:#fff}
    .sqa-ring{position:absolute;width:24px;height:24px;margin:-12px 0 0 -12px;border-radius:50%;border:1.5px solid ${C};opacity:0;animation:sqaRing .42s cubic-bezier(.2,.7,.3,1)}
    @keyframes sqaRing{0%{transform:scale(.3);opacity:.85}100%{transform:scale(1.2);opacity:0}}
    .sqa-key{position:absolute;left:12px;bottom:12px;min-width:26px;text-align:center;padding:5px 9px;border-radius:7px;background:#fff;color:#1b1f1d;border:1px solid #cfd4cc;box-shadow:0 2px 0 #cfd4cc;opacity:0;transform:translateY(4px);transition:opacity .12s,transform .12s}
    .sqa-key.on{opacity:1;transform:none}
    .sqa-hl{position:absolute;border:2px solid #e5484d;border-radius:7px;box-shadow:0 0 0 4px rgba(229,72,77,.16);animation:sqaHl 2.8s ease forwards}
    @keyframes sqaHl{0%{opacity:0;transform:scale(1.03)}8%{opacity:1;transform:none}82%{opacity:1}100%{opacity:0}}
    .sqa-note{position:absolute;right:14px;top:14px;width:min(330px,calc(100% - 28px));box-sizing:border-box;padding:11px 13px 11px;border-radius:12px;background:#fff;color:#1b1f1d;border:1px solid #e2e5df;box-shadow:0 10px 30px rgba(16,24,20,.16),0 1px 2px rgba(16,24,20,.06);animation:sqaIn .3s cubic-bezier(.2,.8,.2,1),sqaOut .35s ease 4.4s forwards}
    .sqa-note b{display:flex;align-items:center;gap:7px;font-size:12.5px;font-weight:650}
    .sqa-note b::before{content:"";flex:none;width:8px;height:8px;border-radius:50%;background:#e5484d}
    .sqa-note p{margin:4px 0 0;font-weight:500;font-size:12px;color:#454c47;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
    .sqa-note small{display:block;margin-top:6px;font-weight:500;font-size:11px;color:#7a817c}
    @keyframes sqaIn{from{opacity:0;transform:translateY(-6px) scale(.985)}}
    @keyframes sqaOut{to{opacity:0;transform:translateY(-4px)}}
    @media (prefers-reduced-motion: reduce){.sqa-root *{animation-duration:1ms!important}}`;
  const place = (x, y) => { last = {x, y}; if (cur) cur.style.transform = `translate(${x}px,${y}px)`; };
  const mount = () => {
    if (!document.documentElement || !document.body) return setTimeout(mount, 30);
    if (root) { if (!root.isConnected) document.documentElement.appendChild(root); return; }
    root = mk('div', 'sqa-root');
    const style = mk('style'); style.textContent = CSS;
    cur = mk('div', 'sqa-cur');
    cur.innerHTML = '<svg width="17" height="22" viewBox="0 0 17 22" aria-hidden="true"><path d="M1.6 1.4v16.1l4.1-3.9 2.9 6.6 2.8-1.2-2.8-6.4h5.7z" fill="' + C + '" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    const tag = mk('span', 'sqa-tag'); tag.textContent = NAME; cur.appendChild(tag);
    keyEl = mk('div', 'sqa-key');
    root.append(style, cur, keyEl);
    document.documentElement.appendChild(root);
    place(last.x, last.y);
    new MutationObserver(() => { if (!root.isConnected) document.documentElement.appendChild(root); })
      .observe(document.documentElement, {childList: true});
  };
  addEventListener('mousemove', (e) => place(e.clientX, e.clientY), true);
  addEventListener('mousedown', (e) => {
    if (!root) return;
    const r = mk('div', 'sqa-ring'); r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    root.appendChild(r); setTimeout(() => r.remove(), 450);
  }, true);
  const KEYS = {Tab: 'Tab', Enter: 'Enter', Escape: 'Esc', ' ': 'Space', ArrowDown: '↓', ArrowUp: '↑', Backspace: '⌫'};
  addEventListener('keydown', (e) => {
    const k = KEYS[e.key];
    if (!k || !keyEl) return;
    keyEl.textContent = k; keyEl.classList.remove('on'); void keyEl.offsetWidth; keyEl.classList.add('on');
    clearTimeout(keyTimer); keyTimer = setTimeout(() => keyEl.classList.remove('on'), 650);
  }, true);
  mount();
  window.__sqaBug = (title, detail, meta, selector) => {
    mount();
    if (!root) return;
    let el = null;
    try { el = selector ? document.querySelector(selector) : null; } catch (e) {}
    if (el) {
      const r = el.getBoundingClientRect();
      if (r.width && r.height) {
        const hl = mk('div', 'sqa-hl');
        Object.assign(hl.style, {left: (r.left - 4) + 'px', top: (r.top - 4) + 'px',
                                 width: (r.width + 8) + 'px', height: (r.height + 8) + 'px'});
        root.appendChild(hl); setTimeout(() => hl.remove(), 2900);
      }
    }
    const n = mk('div', 'sqa-note');
    const b = document.createElement('b'), p = document.createElement('p'), s = document.createElement('small');
    b.textContent = title; p.textContent = detail; s.textContent = meta;
    n.append(b, p, s); root.appendChild(n); setTimeout(() => n.remove(), 4800);
  };
})();
"""


def note_text(f) -> str:
    """Plain-language line for the on-screen notification."""
    import re
    msg = re.sub(r"^Uncaught\s+", "", f.message)
    if f.bug_type == "layout_overflow":
        m = re.search(r"(\d+)px wide in a (\d+)px", msg)
        cm = re.search(r'class="([\w-]+)', f.dom or "")
        cause = cm.group(1).replace("-", " ").replace("_", " ") if cm else ""
        if m:
            return f"Page is {m.group(1)}px wide on a {m.group(2)}px screen" + (f". Cause: {cause}." if cause else ".")
    if f.bug_type == "unhandled_promise":
        return f"Promise rejected and nothing caught it: {msg}"
    if f.bug_type == "blank_screen":
        return "The page went white and no error was thrown."
    if f.bug_type == "xss":
        return "Text typed into the page ran as a script."
    return msg


class Agent:
    def __init__(self, idx: int, persona: dict, browser, state, cfg, llm=None, on_finding=None):
        self.idx, self.persona, self.browser, self.state, self.cfg = idx, persona, browser, state, cfg
        self.on_finding = on_finding
        self.rng = random.Random(cfg.seed * 7919 + idx) if cfg.seed is not None else random.Random()
        self.heuristic = HeuristicPolicy(persona, state, self.rng)
        self.policy = NanoPolicy(persona, state, llm, self.heuristic) if llm else None
        self.page = self.ctx = self.det = self.ex = None
        self.steps = 0
        self.deadline = time.time() + cfg.minutes * 60 if cfg.minutes else None
        self.history: list[str] = []
        self.done_on: dict[str, list[str]] = {}
        self.page_actions: Counter = Counter()
        self.trail: list[dict] = []
        self.trail_vp: dict = {}
        self.fails = 0
        self.offline_steps = 0
        self.dead = False
        self.last_url = state.start_url
        self.found: list[Finding] = []

    # ---- lifecycle ---------------------------------------------------------
    async def run(self) -> list[Finding]:
        cfg = self.cfg
        kw = dict(ignore_https_errors=True)
        if cfg.tile:
            kw["no_viewport"] = True
        else:
            w, h = self.persona["viewport"]
            kw["viewport"] = {"width": w, "height": h}
        if cfg.storage_state:
            kw["storage_state"] = cfg.storage_state
        self.ctx = await self.browser.new_context(**kw)
        self.ctx.on("page", lambda p: asyncio.ensure_future(self._close_popup(p)))
        self.det = Detectors(self.state.start_url, self.state.seen, cfg.detectors, cfg.include_third_party)
        await self.det.install(self.ctx)
        if cfg.show_ui:
            label = self.persona.get("tag") or self.persona["name"]
            await self.ctx.add_init_script(UI_JS.replace("__LABEL__", json.dumps(label))
                                           .replace("__COLOR__", json.dumps(COLORS[self.idx % len(COLORS)])))
        self.state.emit("agent_start", agent=self.idx, persona=self.persona["name"],
                        tag=self.persona.get("tag", ""), viewport=list(self.persona["viewport"]))
        try:
            await self._new_page()
            await self._do({"action": "goto", "url": self.state.start_url}, "open the app", "start")
            if self.idx > 0 and cfg.spread:   # fan out across the site immediately
                obs = await self._observe()
                if obs:
                    self.state.add_links(obs["links"])
                    self.state.note_features(obs["url"], obs["elements"])
                    url = self.state.pick_url(self.rng, exclude=self.page.url, prefer=self.persona.get("prefer"))
                    if url:
                        await self._do({"action": "goto", "url": url}, "spread out to another page", "frontier")
            while not self._done():
                if self.dead:
                    await self._recover()
                    continue
                obs = await self._observe()
                if obs is None:
                    await self._recover()
                    continue
                self.state.add_links(obs["links"])
                self.state.note_features(obs["url"], obs["elements"])
                here = route(obs["url"])
                if self._should_jump(here, obs):
                    url = self.state.pick_url(self.rng, exclude=obs["url"], prefer=self.persona.get("prefer"))
                    self.page_actions[here] = 0
                    if url:
                        await self._do({"action": "goto", "url": url}, "explore a less-visited page", "frontier")
                        continue
                done_here = self.done_on.setdefault(here, [])
                found_here = self.state.found_on.get(here, set())
                if self.policy:
                    thought, steps, source = await self.policy.plan(obs, here, done_here, found_here)
                else:
                    thought, steps = self.heuristic.plan(obs, here)
                    source = "heuristic"
                self.state.plans[source] += 1
                self.state.emit("plan", agent=self.idx, persona=self.persona["name"], source=source,
                                thought=thought, steps=[describe(s) for s in steps])
                for st in steps:
                    before = self.page.url
                    await self._do(st, thought, source)
                    if self._done() or self.dead or self.page.url != before:
                        break
                    if cfg.human:                     # a person looks before the next move
                        await asyncio.sleep(self.rng.uniform(0.15, 0.5))
        except Exception as e:  # a dead agent must never kill the swarm
            print(f"[agent {self.idx}] stopped: {type(e).__name__}: {str(e)[:120]}")
            self.state.emit("agent_error", agent=self.idx, error=str(e).split("\n")[0][:200])
        finally:
            self.state.emit("agent_done", agent=self.idx, steps=self.steps, findings=len(self.found))
            try:
                await self.ctx.close()
            except Exception:
                pass
        return self.found

    async def _new_page(self) -> None:
        self.page = await self.ctx.new_page()
        self.det.attach(self.page)
        self.ex = Executor(self.page, self.det, self.rng, human=self.cfg.human)
        if self.cfg.on_frame:
            await self._start_screencast()

    async def _start_screencast(self) -> None:
        """Stream the agent's tab as JPEG frames (CDP screencast) to the live UI."""
        try:
            cdp = await self.ctx.new_cdp_session(self.page)
        except Exception:
            return
        last = [0.0]
        min_gap = 1.0 / max(1, self.cfg.frame_fps)

        def on_frame(params):
            asyncio.ensure_future(cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]}))
            now = time.time()
            if now - last[0] < min_gap:
                return
            last[0] = now
            meta = params.get("metadata") or {}
            try:
                self.cfg.on_frame({"kind": "frame", "agent": self.idx, "data": params["data"],
                                   "w": meta.get("deviceWidth"), "h": meta.get("deviceHeight")})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", on_frame)
        try:
            await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 62, "maxWidth": 760,
                                                    "maxHeight": 760, "everyNthFrame": 3})
        except Exception:
            pass

    async def _close_popup(self, p) -> None:
        await asyncio.sleep(0.3)
        if p is not self.page:
            try:
                await p.close()
            except Exception:
                pass

    async def _recover(self) -> None:
        """Replace a hung/crashed tab and continue from the last good URL."""
        self.dead = False
        try:
            await asyncio.wait_for(self.page.close(run_before_unload=False), 5)
        except Exception:
            pass
        await self._new_page()
        await self._do({"action": "goto", "url": self.last_url}, "recover after a dead tab", "recover")

    def _done(self) -> bool:
        if self.state.stopped:
            return True
        if self.deadline:
            return time.time() >= self.deadline
        return self.steps >= self.cfg.max_steps

    def _should_jump(self, here: str, obs: dict) -> bool:
        budget = max(3, self.cfg.page_budget // 2) if self.persona.get("explorer") else self.cfg.page_budget
        exhausted = self.page_actions[here] >= 3 and self.heuristic.page_novelty(obs, here) < 0.2
        if self.det.dead_urls:
            self.state.mark_dead(self.det.dead_urls)
        if self.state.is_dead(obs["url"]):
            return True                       # a 404 page: reported once, nothing more to test here
        return (self.page_actions[here] >= budget or self.fails >= 3 or not obs["elements"]
                or exhausted or self.rng.random() < 0.03)

    async def _observe(self) -> dict | None:
        for _ in range(2):
            try:
                return await asyncio.wait_for(snapshot(self.page), 6.0)
            except asyncio.TimeoutError:
                return None
            except Exception:
                await asyncio.sleep(0.5)    # navigation in flight: try again
        return None

    # ---- one action ----------------------------------------------------------
    async def _do(self, step: dict, thought: str, source: str) -> None:
        here = route(self.page.url)
        try:
            desc, ok = await asyncio.wait_for(self.ex.perform(step), 12)
        except asyncio.TimeoutError:
            desc, ok = describe(step) + " (timed out)", False
        self.steps += 1
        self.state.actions += 1
        if not ok:
            self.state.failed_actions += 1
        self.fails = 0 if ok else self.fails + 1
        if step.get("sqa") or step.get("selector"):
            self.state.touch(here, el_key(step))
        self.page_actions[here] += 1
        self.history.append(desc)
        self.done_on.setdefault(here, []).append(desc)

        # repro trail: anchored at the last full navigation
        clean = {k: v for k, v in step.items() if k != "sqa"}
        if step["action"] in NAV_ACTIONS:
            self.trail = [{"action": "goto", "url": self.page.url}]
            self.trail_vp = await self._viewport()
        else:
            self.trail.append(clean)
            if len(self.trail) > 25:
                self.trail = self.trail[:1] + self.trail[-24:]
        on_site = self.state.normalize(self.page.url) is not None
        if ok and on_site and (step["action"] in NAV_ACTIONS or self.page.url != self.last_url):
            self.state.mark_visit(self.page.url)
        if ok and on_site:
            self.last_url = self.page.url
        if not on_site and not self.page.url.startswith(self.state.start_url):
            # Back past the first page, an external link, a download: return to the app.
            try:
                await self.page.goto(self.last_url, wait_until="load", timeout=20000)
                await self.ex.restore_cursor()
                self.trail = [{"action": "goto", "url": self.page.url}]
            except Exception:
                pass

        self.state.emit("action", agent=self.idx, persona=self.persona["name"], source=source,
                        desc=desc, ok=ok, page=route(self.page.url),
                        step={k: step[k] for k in ("action", "label", "text", "key", "dy", "width", "height",
                                                   "mode", "url", "submit", "times") if k in step})
        if self.ex.offline:                     # never stay offline for long
            self.offline_steps += 1
            if self.offline_steps >= 4:
                await self.ex.set_network("online")
        else:
            self.offline_steps = 0
        await self._collect(thought)

    async def _viewport(self) -> dict:
        vp = self.page.viewport_size
        if vp:
            return {"width": vp["width"], "height": vp["height"]}
        try:
            return await asyncio.wait_for(
                self.page.evaluate("() => ({width: innerWidth, height: innerHeight})"), 3)
        except Exception:
            w, h = self.persona["viewport"]
            return {"width": w, "height": h}

    async def _collect(self, thought: str) -> None:
        bugs = await self.det.drain(settle=self.cfg.settle)
        for bug in bugs:
            if bug.fatal:
                self.dead = True
            if bug.bug_type == "_recover":
                continue
            vp = await self._viewport() if not bug.fatal else self.trail_vp
            repro = []
            if self.trail_vp:
                repro.append({"action": "set_viewport", **self.trail_vp})
            repro += self.trail
            f = Finding(
                url=self.state.start_url, persona=self.persona["name"],
                viewport=f"{vp.get('width', 0)}x{vp.get('height', 0)}",
                actions=self.history[-6:], bug_type=bug.bug_type, message=bug.message[:1000],
                stack=bug.stack[:4000], dom=bug.dom, selector=bug.selector, severity=bug.severity,
                page_url=bug.page_url, agent=self.idx, intent=thought, repro=repro, run_id=self.state.run_id,
            )
            if not bug.fatal:
                try:
                    shot = Path(self.cfg.shots_dir) / f"{f.id}.png"
                    shot.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.wait_for(self.page.screenshot(path=str(shot)), 6)
                    f.screenshot = shot.as_posix()
                except Exception:
                    pass
            append_jsonl(self.cfg.findings_path, f)
            self.state.findings.append(f)
            self.state.found_on[route(f.page_url)].add(f.bug_type)
            self.found.append(f)
            self.state.emit("finding", agent=self.idx, id=f.id, bug_type=f.bug_type,
                            severity=f.severity, message=f.message[:200], page=route(f.page_url))
            print(f"[agent {self.idx}] {f.severity.upper():<6} {f.id} {f.bug_type}: {f.message[:90]}")
            if self.cfg.show_ui and not bug.fatal:
                target = f.selector or next((s.get("selector") for s in reversed(self.trail) if s.get("selector")), "")
                who = self.persona.get("tag") or self.persona["name"]
                try:
                    await asyncio.wait_for(self.page.evaluate(
                        "a => window.__sqaBug && window.__sqaBug(a[0], a[1], a[2], a[3])",
                        [BUG_TITLES.get(f.bug_type, "Bug caught"), note_text(f)[:160],
                         f"{f.id}, found by {who.lower()}", target]), 2)
                except Exception:
                    pass
            if self.on_finding:
                try:
                    res = self.on_finding(f)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:
                    print(f"[agent {self.idx}] on_finding callback failed: {e}")
        if self.dead:
            await self._recover()
