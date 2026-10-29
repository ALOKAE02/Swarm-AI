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

COLORS = ["#ff2d55", "#0a84ff", "#30d158", "#ff9f0a", "#bf5af2", "#64d2ff", "#ffd60a", "#ff6482"]

UI_JS = r"""
(() => {
  if (window.__sqaUI) return;
  window.__sqaUI = true;
  const LABEL = __LABEL__, C = __COLOR__;
  const mk = (cls) => { const d = document.createElement('div'); d.className = cls; d.setAttribute('data-sqa-ui', ''); return d; };
  const mount = () => {
    if (!document.documentElement || !document.body) return setTimeout(mount, 30);
    const css = document.createElement('style');
    css.setAttribute('data-sqa-ui', '');
    css.textContent = `
      .sqa-cur{position:fixed;z-index:2147483647;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;
        background:${C};box-shadow:0 0 0 3px #fffc,0 0 14px ${C};pointer-events:none;left:-50px;top:-50px}
      .sqa-rip{position:fixed;z-index:2147483646;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;
        border:3px solid ${C};pointer-events:none;animation:sqaR .45s ease-out forwards}
      .sqa-badge{position:fixed;z-index:2147483647;left:8px;top:8px;padding:4px 10px;border-radius:999px;
        background:#111d;color:#fff;font:600 12px/1.4 system-ui,sans-serif;pointer-events:none;border-left:4px solid ${C}}
      .sqa-alarm{position:fixed;z-index:2147483647;inset:0;border:7px solid #ff2d55;pointer-events:none;animation:sqaF 3.5s forwards}
      .sqa-toast{position:fixed;z-index:2147483647;left:50%;bottom:22px;transform:translateX(-50%);max-width:92%;
        padding:10px 16px;border-radius:10px;background:#ff2d55;color:#fff;font:600 14px/1.35 system-ui,sans-serif;
        pointer-events:none;animation:sqaF 3.5s forwards;box-shadow:0 6px 24px #0006}
      @keyframes sqaR{from{transform:scale(.3);opacity:1}to{transform:scale(1.7);opacity:0}}
      @keyframes sqaF{0%,80%{opacity:1}100%{opacity:0}}`;
    document.documentElement.appendChild(css);
    const cur = mk('sqa-cur'), badge = mk('sqa-badge');
    badge.textContent = LABEL;
    document.documentElement.append(cur, badge);
    addEventListener('mousemove', (e) => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', (e) => {
      const r = mk('sqa-rip'); r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.documentElement.appendChild(r); setTimeout(() => r.remove(), 500);
    }, true);
  };
  mount();
  window.__sqaAlarm = (msg) => {
    const a = mk('sqa-alarm'), t = mk('sqa-toast');
    t.textContent = msg;
    document.documentElement.append(a, t);
    setTimeout(() => { a.remove(); t.remove(); }, 3600);
  };
})();
"""


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
            label = f"agent {self.idx} · {self.persona['name']}"
            await self.ctx.add_init_script(UI_JS.replace("__LABEL__", json.dumps(label))
                                           .replace("__COLOR__", json.dumps(COLORS[self.idx % len(COLORS)])))
        self.state.emit("agent_start", agent=self.idx, persona=self.persona["name"])
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
        except Exception as e:  # a dead agent must never kill the swarm
            print(f"[agent {self.idx}] stopped: {type(e).__name__}: {str(e)[:120]}")
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
        self.ex = Executor(self.page, self.det, self.rng)

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
        if self.deadline:
            return time.time() >= self.deadline
        return self.steps >= self.cfg.max_steps

    def _should_jump(self, here: str, obs: dict) -> bool:
        budget = max(3, self.cfg.page_budget // 2) if self.persona.get("explorer") else self.cfg.page_budget
        exhausted = self.page_actions[here] >= 3 and self.heuristic.page_novelty(obs, here) < 0.2
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
            desc, ok = await asyncio.wait_for(self.ex.perform(step), 25)
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
        if ok and (step["action"] in NAV_ACTIONS or self.page.url != self.last_url):
            self.state.mark_visit(self.page.url)
        if ok:
            self.last_url = self.page.url

        self.state.emit("action", agent=self.idx, persona=self.persona["name"], source=source,
                        desc=desc, ok=ok, page=route(self.page.url))
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
                try:
                    await asyncio.wait_for(self.page.evaluate(
                        "m => window.__sqaAlarm && window.__sqaAlarm(m)",
                        f"BUG · {f.bug_type} · {f.message[:140]}"), 2)
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
