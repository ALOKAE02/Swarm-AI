"""Action planners.

HeuristicPolicy: coverage-guided chaos. Prefers elements nobody has touched on
this route yet, respects overlays (acts on the modal, not what's behind it),
chains realistic sequences (type -> submit, offline -> submit -> online) and
follows each persona's style. Runs with no API calls at all.

NanoPolicy: Nemotron Nano plans 1-4 actions per call from a compact page
summary (elements as short ids, least-explored routes, what was already tried,
what already broke). One call drives several actions, so it is ~3x cheaper
than one call per action. Any failure falls back to the heuristic instantly.
"""
from __future__ import annotations

import random
import re
from urllib.parse import urljoin, urlparse

from personas import HOSTILE, PAYLOADS

DANGER = re.compile(r"log ?out|sign ?out|delete (my )?account|deactivate|unsubscribe|close account", re.I)
PRIMARY = re.compile(r"add|buy|submit|save|generate|join|send|create|checkout|load|more|next|apply|"
                     r"confirm|continue|search|upload|pay|order|register|sign ?up|start|run|post", re.I)
CLICKABLE = {"button", "link", "checkbox", "radio", "tab", "menuitem", "switch", "summary", "option",
             "menuitemcheckbox", "treeitem"}
TYPABLE = {"input", "textarea", "editable"}
WIDTHS = [320, 360, 375, 414, 600, 768, 1024, 1280, 1920]
NICE_TEXT = ["$EMAIL", "hello", "Kabir", "42", "test", "a"]


def el_key(el: dict) -> str:
    return el.get("selector") or f"{el.get('kind')}:{el.get('label')}"


def to_step(action: str, el: dict, **extra) -> dict:
    return {"action": action, "sqa": el["id"], "selector": el.get("selector", ""),
            "label": el.get("label", ""), **extra}


class HeuristicPolicy:
    def __init__(self, persona: dict, state, rng: random.Random):
        self.persona, self.state, self.rng = persona, state, rng
        self.explorer = persona.get("explorer", False)

    def score(self, el: dict, route: str) -> float:
        kind = el["kind"]
        base = {"button": 3.0, "checkbox": 2.5, "radio": 2.0, "summary": 2.0, "select": 2.0,
                "input": 3.0, "textarea": 3.0, "editable": 2.5,
                "link": 3.0 if self.explorer else 1.2}.get(kind, 2.0)
        if el.get("submit") or PRIMARY.search(el.get("label", "")):
            base *= 1.6
        if el.get("inView"):
            base *= 1.6
        if el.get("covered"):
            base *= 0.03
        if el.get("disabled") or DANGER.search(el.get("label", "")):
            return 0.0
        if kind == "link" and el.get("href") and self.state.normalize(el["href"]) is None:
            return 0.0                                         # external / download link
        if self.state.is_chrome(el.get("selector", "")):
            base *= 0.35                                       # nav/footer: same on every page
        return base * self.novelty(el, route)

    def novelty(self, el: dict, route: str) -> float:
        return (1.0 / (1 + self.state.touched(route, el_key(el)))) ** 1.5

    def page_novelty(self, obs: dict, route: str) -> float:
        """Best novelty left on this page; low means everything was tried."""
        vals = [self.novelty(e, route) for e in obs["elements"]
                if not e.get("disabled") and not e.get("covered") and not self.state.is_chrome(e.get("selector", ""))]
        return max(vals) if vals else 0.0

    def ranked(self, obs: dict, route: str) -> list[dict]:
        return sorted(obs["elements"], key=lambda e: -self.score(e, route))

    def _pick(self, els: list[dict], route: str) -> dict | None:
        weights = [self.score(e, route) for e in els]
        if not els or sum(weights) <= 0:
            return None
        return self.rng.choices(els, weights=weights, k=1)[0]

    def _text(self) -> str:
        hostile = self.persona["name"].startswith("malicious") or self.rng.random() < 0.35
        if hostile and self.rng.random() < 0.3:    # injection probes are the highest-signal input
            return self.rng.choice(["$XSS", "$XSS2"])
        return self.rng.choice(HOSTILE if hostile else NICE_TEXT)

    def _submit_for(self, el: dict, obs: dict) -> dict | None:
        g = el.get("group")
        if not g:
            return None
        for other in obs["elements"]:
            if other["group"] == g and other["kind"] == "button" and not other.get("disabled") and (
                    other.get("submit") or PRIMARY.search(other.get("label", ""))):
                return other
        return None

    def _fill_form(self, group: str, obs: dict) -> list[dict]:
        steps, submit = [], None
        for e in obs["elements"]:
            if e["group"] != group or e.get("disabled") or e.get("covered"):
                continue
            if e["kind"] in TYPABLE:
                steps.append(to_step("type", e, text=self._text()))
            elif e["kind"] == "select":
                steps.append(to_step("select", e))
            elif e["kind"] in ("checkbox", "radio") and self.rng.random() < 0.7:
                steps.append(to_step("click", e))
            elif e["kind"] == "button" and (e.get("submit") or PRIMARY.search(e.get("label", ""))):
                submit = submit or e
        steps = steps[:6]
        if not steps:
            return []
        if submit:
            steps.append(to_step("click", submit))
        elif steps[-1]["action"] == "type":
            steps[-1]["submit"] = True
        return steps

    def plan(self, obs: dict, route: str) -> tuple[str, list[dict]]:
        els = obs["elements"]
        clickables = [e for e in els if e["kind"] in CLICKABLE or e["tag"] == "button"]
        typables = [e for e in els if e["kind"] in TYPABLE]
        selects = [e for e in els if e["kind"] == "select"]
        weights = dict(self.persona.get("weights", {"click": 1}))
        weights.setdefault("press", 0.4)          # everyone hits Escape/Enter sometimes
        if not clickables:
            for k in ("click", "rage_click", "hover", "dblclick"):
                weights.pop(k, None)
        if not typables:
            weights.pop("type", None)
        if not selects:
            weights.pop("select", None)
        if obs["scrollH"] > obs["vh"] * 1.3:
            weights["scroll"] = weights.get("scroll", 0.5) * 1.6
        # Don't keep choosing an action whose every target was already hammered.
        pools = {"click": clickables, "rage_click": clickables, "hover": clickables, "dblclick": clickables,
                 "type": typables, "select": selects}
        for k, pool in pools.items():
            if k in weights:
                best = max((self.score(e, route) for e in pool), default=0.0)
                weights[k] *= min(1.0, 0.15 + best / 3.0)
        weights = {k: v for k, v in weights.items() if v > 0}
        if not weights:
            weights = {"scroll": 1, "press": 1}
        rng = self.rng
        modal = obs.get("modal") or sum(1 for e in els if e.get("covered")) >= 3
        if modal and rng.random() < 0.4:
            # Real users mash Escape at dialogs; leaked key listeners and
            # double-close bugs live exactly here.
            n = rng.choice([2, 2, 3])
            return "mash Escape at the dialog", [{"action": "press", "key": "Escape"} for _ in range(n)]
        kind = rng.choices(list(weights), weights=list(weights.values()), k=1)[0]

        if kind in ("click", "rage_click", "hover", "dblclick"):
            el = self._pick(clickables, route)
            if el:
                return f"{kind.replace('_', '-')} '{el['label'][:30]}'", [to_step(kind, el)]
        if kind == "type":
            el = self._pick(typables, route)
            fill_all = 0.7 if self.persona["name"].startswith("malicious") else 0.4
            if el and el.get("group") and rng.random() < fill_all:
                steps = self._fill_form(el["group"], obs)
                if steps:
                    return f"fill the whole form with junk and submit", steps
            if el:
                text = self._text()
                steps = [to_step("type", el, text=text)]
                if rng.random() < 0.75:
                    sub = self._submit_for(el, obs)
                    if sub and rng.random() < 0.6:
                        steps.append(to_step("click", sub))
                    else:
                        steps[0]["submit"] = True
                return f"feed {text} into '{el['label'][:25]}'", steps
        if kind == "select":
            el = self._pick(selects, route)
            if el:
                return f"pick an option in '{el['label'][:25]}'", [to_step("select", el)]
        if kind == "press":
            if self.persona["name"].startswith("keyboard"):
                keys = [rng.choice(["Tab", "Tab", "Tab", "Enter", "Space", "Escape", "ArrowDown"])
                        for _ in range(rng.randint(2, 4))]
            else:
                keys = [rng.choice(["Escape", "Escape", "Enter", "Tab"])]
            return "keyboard: " + " ".join(keys), [{"action": "press", "key": k} for k in keys]
        if kind == "scroll":
            remaining = obs["scrollH"] - obs["scrollY"] - obs["vh"]
            dy = remaining + 100 if remaining > 200 and rng.random() < 0.7 else rng.choice([700, -400, 1600])
            return "scroll to the bottom" if dy > 0 else "scroll back up", [{"action": "scroll", "dy": int(dy)}]
        if kind == "resize":
            w = rng.choice(WIDTHS)
            return f"resize to {w}px wide", [{"action": "resize", "width": w, "height": 800}]
        if kind == "throttle":
            mode = rng.choice(["offline", "offline", "slow"])
            target = self._pick([e for e in clickables if e.get("submit") or PRIMARY.search(e["label"])]
                                or clickables, route)
            steps = [{"action": "throttle", "mode": mode}]
            if typables and rng.random() < 0.5:
                el = self._pick(typables, route)
                if el:
                    steps.append(to_step("type", el, text="$EMAIL", submit=True))
            elif target:
                steps.append(to_step("click", target))
            else:
                steps.append({"action": "scroll", "dy": 1600})
            steps += [{"action": "wait", "ms": 700}, {"action": "throttle", "mode": "online"}]
            return f"go {mode} and act anyway", steps
        if kind == "back":
            return "hit back mid-flow", [{"action": "back"}]
        if kind == "reload":
            return "reload at a bad moment", [{"action": "reload"}]
        el = self._pick(clickables, route)
        if el:
            return f"click '{el['label'][:30]}'", [to_step("click", el)]
        return "scroll around", [{"action": "scroll", "dy": 600}]


SYSTEM = """You are "{name}", a chaotic QA tester driving a real web browser. {brief}
Goal: make this web app break: uncaught errors, failed requests, frozen or blank pages, broken layouts, injected script running. Prefer elements and routes nobody has tried yet.
Reply with ONLY one JSON object: {{"thought": "<= 12 words", "actions": [1 to 4 actions]}}
Action forms:
{{"do":"click","id":"e3"}} {{"do":"rage_click","id":"e3"}} {{"do":"dblclick","id":"e3"}} {{"do":"hover","id":"e3"}}
{{"do":"type","id":"e5","text":"$XSS","submit":true}}  (text: your own string or a token: {tokens})
{{"do":"select","id":"e7"}} {{"do":"press","key":"Tab|Enter|Escape|Space|ArrowDown"}} {{"do":"scroll","dy":1500}}
{{"do":"resize","width":375,"height":812}} {{"do":"throttle","mode":"offline|slow|online"}}
{{"do":"back"}} {{"do":"reload"}} {{"do":"goto","url":"<path from ROUTES>"}} {{"do":"wait","ms":500}}
Use only ids from ELEMENTS. [covered] means an overlay is on top: deal with the overlay first."""

ACTION_ALIASES = {"rage": "rage_click", "rageclick": "rage_click", "double_click": "dblclick",
                  "fill": "type", "key": "press", "navigate": "goto", "refresh": "reload"}
ELEMENT_ACTIONS = {"click", "rage_click", "dblclick", "hover", "type", "select", "check"}


class NanoPolicy:
    def __init__(self, persona: dict, state, llm, heuristic: HeuristicPolicy, max_elements: int = 30):
        self.persona, self.state, self.llm, self.h = persona, state, llm, heuristic
        self.max_elements = max_elements
        self.system = SYSTEM.format(name=persona["name"], brief=persona["brief"],
                                    tokens=", ".join(PAYLOADS))

    def _line(self, el: dict, route: str) -> str:
        kind = el["kind"] + (f"[{el['type']}]" if el["kind"] == "input" and el.get("type") else "")
        s = f'{el["id"]} {kind} "{el["label"]}"'
        if el["kind"] == "link" and el.get("href"):
            u = urlparse(el["href"])
            s += f" -> {u.path}{'#' + u.fragment if u.fragment else ''}"
        if el.get("group"):
            s += f" [{el['group']}]"
        if el.get("covered"):
            s += " [covered]"
        if not el.get("inView"):
            s += " (offscreen)"
        n = self.state.touched(route, el_key(el))
        if n:
            s += f" (tried {n}x)"
        return s

    def prompt(self, obs: dict, route: str, done_here: list[str], found_here: set) -> str:
        els = self.h.ranked(obs, route)[: self.max_elements]
        els.sort(key=lambda e: int(e["id"][1:]))
        routes = []
        for u in self.state.unvisited(8):
            p = urlparse(u)
            routes.append(p.path + ("#" + p.fragment if p.fragment else ""))
        lines = [
            f"PAGE {obs['title']!r} | {route} | viewport {obs['vw']}x{obs['vh']} | "
            f"scrolled {obs['scrollY']}/{obs['scrollH']}px" + (" | MODAL OPEN" if obs.get("modal") else ""),
            "HEADINGS: " + "; ".join(obs.get("heads") or []),
            "ELEMENTS:", *[self._line(e, route) for e in els],
            "ROUTES (least explored first): " + ", ".join(routes),
            "DONE HERE: " + ("; ".join(done_here[-6:]) or "nothing yet"),
        ]
        if found_here:
            lines.append("ALREADY BROKEN HERE (find different bugs): " + ", ".join(sorted(found_here)))
        return "\n".join(lines)

    def parse(self, reply: dict, obs: dict) -> tuple[str, list[dict]]:
        by_id = {e["id"]: e for e in obs["elements"]}
        steps = []
        for a in (reply.get("actions") or [])[:4]:
            if not isinstance(a, dict):
                continue
            do = str(a.get("do") or a.get("action") or "").lower().strip()
            do = ACTION_ALIASES.get(do, do)
            if do in ELEMENT_ACTIONS:
                eid = str(a.get("id", "")).strip()
                eid = eid if eid.startswith("e") else f"e{eid}"
                el = by_id.get(eid)
                if not el:
                    continue
                extra = {}
                if do == "type":
                    extra = {"text": str(a.get("text", "")), "submit": bool(a.get("submit"))}
                steps.append(to_step(do, el, **extra))
            elif do == "press":
                steps.append({"action": "press", "key": str(a.get("key") or "Enter")})
            elif do == "scroll":
                steps.append({"action": "scroll", "dy": int(float(a.get("dy", 800) or 800))})
            elif do == "resize":
                steps.append({"action": "resize", "width": int(float(a.get("width", 375) or 375)),
                              "height": int(float(a.get("height", 812) or 812))})
            elif do == "throttle" and a.get("mode") in ("offline", "slow", "online"):
                steps.append({"action": "throttle", "mode": a["mode"]})
            elif do in ("back", "forward", "reload"):
                steps.append({"action": do})
            elif do == "goto" and a.get("url"):
                url = urljoin(obs["url"], str(a["url"]))
                if self.state.normalize(url):
                    steps.append({"action": "goto", "url": url})
            elif do == "wait":
                steps.append({"action": "wait", "ms": int(float(a.get("ms", 400) or 400))})
        return str(reply.get("thought", ""))[:100], steps

    async def plan(self, obs: dict, route: str, done_here: list[str], found_here: set):
        if not self.llm.exhausted:
            reply = await self.llm.chat_json(self.system, self.prompt(obs, route, done_here, found_here))
            if isinstance(reply, dict):
                try:
                    thought, steps = self.parse(reply, obs)
                except (TypeError, ValueError):
                    steps = []
                if steps:
                    return thought, steps, "nano"
        thought, steps = self.h.plan(obs, route)
        return thought, steps, "heuristic"
