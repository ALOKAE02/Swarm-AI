"""Run-wide state shared by every agent: dedupe set, URL frontier, coverage
counters, live event stream and stats. Lets N agents split up the site instead
of all hammering the same button."""
from __future__ import annotations

import random
import re
import time
from collections import Counter, defaultdict
from urllib.parse import urldefrag, urlparse, urlunparse

from contract import append_jsonl, now_iso

SKIP_EXT = re.compile(r"\.(pdf|zip|gz|png|jpe?g|gif|svg|webp|mp4|mp3|wav|dmg|exe|msi|docx?|xlsx?|pptx?|csv)$", re.I)
SKIP_PATH = re.compile(r"log-?out|sign-?out|logoff|/exit\b|unsubscribe|delete-account|/cdn-cgi/", re.I)


class SwarmState:
    def __init__(self, start_url: str, run_id: str, events_path: str | None = None, listener=None):
        self.start_url = start_url
        self.listener = listener                  # callable(dict): live UI / server hook
        self.stopped = False
        u = urlparse(start_url)
        self.origin = (u.scheme, u.netloc)
        self.run_id = run_id
        self.events_path = events_path
        self.t0 = time.time()
        self.seen: set = set()
        self.visits: Counter = Counter()          # normalized url -> visits
        self.pattern_visits: Counter = Counter()  # /product/N -> visits (spreads agents over page TYPES)
        self.frontier: dict[str, str] = {}        # url -> pattern
        self.touches: Counter = Counter()         # (route, element key) -> times acted on
        self.global_touches: Counter = Counter()  # element key -> times acted on, any route
        self.found_on: dict[str, set] = defaultdict(set)
        self.features: dict[str, dict] = {}       # url -> {"inputs": n, "buttons": n}
        self.dead: set[str] = set()               # pages that 404: never send an agent there again
        self.selector_routes: dict[str, set] = defaultdict(set)   # selector -> routes it appears on
        self.findings: list = []
        self.actions = self.failed_actions = 0
        self.plans = Counter()                    # nano / heuristic
        self.add_url(start_url)

    # ---- frontier ------------------------------------------------------
    def normalize(self, url: str) -> str | None:
        try:
            u = urlparse(url)
        except ValueError:
            return None
        if u.scheme not in ("http", "https") or (u.scheme, u.netloc) != self.origin:
            return None
        if SKIP_EXT.search(u.path or "") or SKIP_PATH.search(url):
            return None
        frag = u.fragment if u.fragment.startswith(("/", "!")) else ""   # keep hash-router routes only
        if frag in ("/", "!", "!/"):
            frag = ""                                                    # "/#/" is the same page as "/"
        query = u.query if len(u.query) <= 40 else ""
        return urlunparse((u.scheme, u.netloc, u.path or "/", "", query, frag))

    @staticmethod
    def pattern(url: str) -> str:
        u = urlparse(url)
        return re.sub(r"\d+", "N", (u.path or "/") + ("#" + u.fragment if u.fragment else ""))

    def add_url(self, url: str) -> None:
        n = self.normalize(url)
        if n and n not in self.frontier and len(self.frontier) < 500:
            self.frontier[n] = self.pattern(n)

    def add_links(self, links) -> None:
        for link in links or []:
            self.add_url(link)

    def mark_visit(self, url: str) -> None:
        n = self.normalize(url)
        if n:
            self.add_url(n)
            self.visits[n] += 1
            self.pattern_visits[self.frontier.get(n, self.pattern(n))] += 1

    def note_features(self, url: str, elements: list[dict]) -> None:
        """Remember what each page offers (ignoring site chrome) and which
        elements are chrome: the same selector seen on 3+ routes."""
        n = self.normalize(url)
        if not n:
            return
        r = self.pattern(n)
        for e in elements:
            if e.get("selector"):
                self.selector_routes[e["selector"]].add(r)
        own = [e for e in elements if not self.is_chrome(e.get("selector", ""))]
        self.features[n] = {
            "inputs": sum(e["kind"] in ("input", "textarea", "editable", "select") for e in own),
            "buttons": sum(e["kind"] == "button" for e in own),
        }

    def is_chrome(self, selector: str) -> bool:
        return bool(selector) and len(self.selector_routes.get(selector, ())) >= 3

    def pick_url(self, rng: random.Random, exclude: str | None = None, prefer: str | None = None) -> str | None:
        """Least-explored page TYPE first; personas that need forms or buttons
        get a pull towards pages already known to have them."""
        ex = self.normalize(exclude) if exclude else None
        cands = [u for u in self.frontier if u != ex and u not in self.dead]
        if not cands:
            return None

        def key(u):
            bonus = 1.5 if prefer and self.features.get(u, {}).get(prefer, 0) > 0 else 0.0
            return (self.pattern_visits[self.frontier[u]] - bonus, self.visits[u], rng.random())
        return min(cands, key=key)

    def mark_dead(self, urls) -> None:
        for u in urls:
            n = self.normalize(u)
            if n:
                self.dead.add(n)

    def is_dead(self, url: str) -> bool:
        n = self.normalize(url)
        return bool(n) and n in self.dead

    def unvisited(self, limit: int = 8) -> list[str]:
        items = sorted((u for u in self.frontier if u not in self.dead),
                       key=lambda u: (self.pattern_visits[self.frontier[u]], self.visits[u]))
        return items[:limit]

    # ---- coverage --------------------------------------------------------
    def touch(self, route: str, key: str) -> None:
        self.touches[(route, key)] += 1
        self.global_touches[key] += 1

    def touched(self, route: str, key: str) -> float:
        """Times acted on here, plus a share of times acted on anywhere: shared
        site chrome (nav, footer widgets) stops looking 'new' on every page."""
        return self.touches[(route, key)] + 0.5 * self.global_touches[key]

    # ---- events / stats -------------------------------------------------
    def emit(self, kind: str, **data) -> None:
        ev = {"ts": now_iso(), "t": round(time.time() - self.t0, 2), "run_id": self.run_id, "kind": kind, **data}
        if self.events_path:
            append_jsonl(self.events_path, ev)
        if self.listener:
            try:
                self.listener(ev)
            except Exception:
                pass

    def summary(self, llm_stats: dict | None = None) -> dict:
        by_type, by_sev = Counter(), Counter()
        for f in self.findings:
            by_type[f.bug_type] += 1
            by_sev[f.severity] += 1
        return {
            "run_id": self.run_id, "url": self.start_url, "seconds": round(time.time() - self.t0, 1),
            "actions": self.actions, "failed_actions": self.failed_actions,
            "pages_discovered": len(self.frontier), "pages_visited": len(self.visits),
            "elements_exercised": len(self.touches), "plans": dict(self.plans),
            "findings": len(self.findings), "by_type": dict(by_type), "by_severity": dict(by_sev),
            "llm": llm_stats or {},
        }
