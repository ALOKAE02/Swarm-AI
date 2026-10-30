"""Tavily web research for fixes.

Before Nemotron 3 Ultra writes a fix, SwarmQA searches the web with Tavily for
documentation, known issues and answers that match the bug (MDN, framework docs,
Stack Overflow, GitHub issues), and hands the best snippets to Ultra. The fix
panel shows which sources were read and which ones Ultra says it used.

Credits are protected: basic search only (1 credit), every query is cached on
disk, and a monthly cap (TAVILY_MONTHLY_CAP, default 1000) stops searching
before the free 1,500 run out.

    python research.py            # self-test: one real search (1 credit), prints the sources
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
TAVILY_URL = os.getenv("TAVILY_URL", "https://api.tavily.com/search")

DEV_DOMAINS = [
    "developer.mozilla.org", "stackoverflow.com", "github.com", "web.dev", "react.dev", "legacy.reactjs.org",
    "nextjs.org", "vuejs.org", "angular.dev", "svelte.dev", "vitejs.dev", "vite.dev", "firebase.google.com",
    "css-tricks.com", "javascript.info", "nodejs.org", "typescriptlang.org", "owasp.org", "cheatsheetseries.owasp.org",
    "tailwindcss.com", "dev.to", "smashingmagazine.com", "w3.org", "docs.netlify.com", "vercel.com",
]
GENERIC_JS = re.compile(r"(Cannot read properties of|Cannot set properties of|is not a function|is not defined|"
                        r"is not valid JSON|Unexpected token|Unexpected end of JSON|Maximum call stack|"
                        r"Failed to fetch|NetworkError|Load failed|is not iterable|Assignment to constant)", re.I)


def detect_stack(f: dict) -> str:
    """Best guess at the framework / platform, used to aim the search."""
    blob = " ".join(str(f.get(k) or "") for k in ("stack", "dom", "page_url", "url", "message")).lower()
    host = urlparse(f.get("url") or f.get("page_url") or "").hostname or ""
    parts = []
    if "/_next/" in blob or "next.js" in blob:
        parts.append("Next.js")
    elif "react" in blob or ".jsx" in blob or ".tsx" in blob or "data-reactroot" in blob:
        parts.append("React")
    elif "vue" in blob:
        parts.append("Vue")
    elif "angular" in blob or "ng-version" in blob:
        parts.append("Angular")
    elif "svelte" in blob:
        parts.append("Svelte")
    if host.endswith((".web.app", ".firebaseapp.com")):
        parts.append("Firebase Hosting")
    elif host.endswith(".vercel.app"):
        parts.append("Vercel")
    elif host.endswith(".netlify.app"):
        parts.append("Netlify")
    return " ".join(parts)


def query_for(f: dict) -> str:
    t = f.get("bug_type", "")
    stack = detect_stack(f)
    msg = re.sub(r"^Uncaught\s+(\(in promise\)\s*)?", "", str(f.get("message") or "")).strip()
    msg = re.sub(r"https?://\S+", "", msg)
    last = next((s for s in reversed(f.get("repro") or []) if s.get("action") in ("click", "rage_click", "type")), {})
    if t == "unhandled_promise" and GENERIC_JS.search(msg):
        core = msg.split("\n")[0][:120]
        where = " after submitting a form" if last.get("action") in ("click", "type") else ""
        q = f'{stack} unhandled promise rejection "{core}"{where}, catch the error and show a message instead of a stuck loading state'
    elif t in ("console_error", "unhandled_promise") and GENERIC_JS.search(msg):
        core = msg.split("\n")[0][:140]
        extra = " after clicking a button repeatedly" if last.get("action") == "rage_click" else ""
        q = f'{stack} "{core}"{extra} fix'
    elif t == "unhandled_promise":
        q = f"{stack} unhandled promise rejection when a fetch fails in a form submit handler, show an error instead of a stuck loading state"
    elif t == "console_error":
        q = f"{stack} JavaScript error {msg[:120]} fix"
    elif t == "layout_overflow":
        q = (f"{stack} CSS page wider than the screen on mobile, horizontal scroll caused by fixed width or "
             f"white-space nowrap, fix with max-width min-width 0 overflow-wrap")
    elif t == "broken_link":
        if "Firebase" in stack:
            q = "Firebase Hosting single page app route returns 404 Page Not Found on refresh or direct link, firebase.json rewrites"
        else:
            q = f"{stack} link returns 404 page not found, single page app route works when clicked but not on direct load, server fallback to index.html"
    elif t == "xss":
        q = f"{stack} prevent XSS when rendering user input with innerHTML, render as text instead"
    elif t == "blank_screen":
        q = f"{stack} page renders blank white screen with no error, missing empty or logged-out state handling"
    elif t == "unresponsive":
        q = "JavaScript long task blocks the main thread for seconds after a click, page freezes, move work off the main thread"
    elif t == "network_error":
        q = f"{stack} handle HTTP 500 server error from fetch in the UI, validate input before sending"
    elif t == "broken_resource":
        q = f"{stack} image or script returns 404 in production, wrong asset path"
    else:
        q = f"{stack} {msg[:160]} fix"
    return re.sub(r"\s+", " ", q).strip()[:380]


class Research:
    def __init__(self, store: Path | None = None):
        self.key = os.getenv("TAVILY_API_KEY", "").strip()
        self.cap = int(os.getenv("TAVILY_MONTHLY_CAP", "1000"))
        self.store = store or (HERE / "runs")
        self.store.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.store / "tavily_cache.json"
        self.usage_path = self.store / "tavily_usage.json"
        self.lock = threading.Lock()
        self.cache = self._load(self.cache_path, {})
        self.usage = self._load(self.usage_path, {})

    @staticmethod
    def _load(p: Path, default):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _save(self) -> None:
        try:
            self.cache_path.write_text(json.dumps(self.cache), encoding="utf-8")
            self.usage_path.write_text(json.dumps(self.usage), encoding="utf-8")
        except OSError:
            pass

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def used_this_month(self) -> int:
        return int(self.usage.get(time.strftime("%Y-%m"), 0))

    def status(self) -> dict:
        return {"enabled": self.enabled, "used_this_month": self.used_this_month(), "cap": self.cap}

    def _post(self, query: str) -> dict:
        body = {"query": query, "search_depth": "basic", "max_results": 6, "chunks_per_source": 2,
                "include_domains": DEV_DOMAINS, "include_usage": True}
        req = urllib.request.Request(TAVILY_URL, data=json.dumps(body).encode(), method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))

    def search_sync(self, finding: dict) -> dict:
        q = query_for(finding)
        out = {"query": q, "sources": [], "cached": False, "credits": 0, "error": None, "provider": "Tavily"}
        if not self.enabled:
            out["error"] = "No TAVILY_API_KEY set"
            return out
        with self.lock:
            hit = self.cache.get(q)
        if hit and time.time() - hit.get("ts", 0) < 30 * 86400:
            out.update(sources=dedupe(hit["sources"]), cached=True)
            return out
        if self.used_this_month() >= self.cap:
            out["error"] = f"Monthly Tavily cap reached ({self.cap} credits); fixing without web research."
            return out
        try:
            data = self._post(q)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode()).get("detail", {})
                detail = detail.get("error", "") if isinstance(detail, dict) else str(detail)
            except Exception:
                pass
            out["error"] = f"Tavily HTTP {e.code}{': ' + detail if detail else ''}"
            return out
        except Exception as e:
            out["error"] = f"Tavily unreachable: {getattr(e, 'reason', e)}"
            return out
        credits = int((data.get("usage") or {}).get("credits", 1) or 1)
        sources = []
        for r in (data.get("results") or [])[:8]:
            url = r.get("url") or ""
            if not url.startswith("http"):
                continue
            snippet = re.sub(r"\s+", " ", str(r.get("content") or "")).strip()[:700]
            sources.append({"n": len(sources) + 1, "title": str(r.get("title") or url)[:140], "url": url,
                            "domain": (urlparse(url).hostname or "").removeprefix("www."),
                            "snippet": snippet, "score": round(float(r.get("score") or 0), 3)})
        sources = dedupe(sources)[:5]
        with self.lock:
            month = time.strftime("%Y-%m")
            self.usage[month] = self.used_this_month() + credits
            self.cache[q] = {"ts": time.time(), "sources": sources}
            self._save()
        out.update(sources=sources, credits=credits)
        return out

    async def search(self, finding: dict) -> dict:
        return await asyncio.to_thread(self.search_sync, finding)


def dedupe(sources: list[dict]) -> list[dict]:
    """Tavily can return the same page several times (one per matching chunk): keep it once,
    merging the snippets, and renumber."""
    out, seen = [], {}
    for s in sources:
        key = s["url"].split("#")[0].split("?")[0].rstrip("/").lower()   # ?answertab= etc. is the same page
        if key in seen:
            first = seen[key]
            if s.get("snippet") and s["snippet"] not in first["snippet"] and len(first["snippet"]) < 900:
                first["snippet"] = (first["snippet"] + " … " + s["snippet"])[:900]
            continue
        s = dict(s)
        seen[key] = s
        out.append(s)
    for i, s in enumerate(out, 1):
        s["n"] = i
    return out


def prompt_block(research: dict | None) -> str:
    if not research or not research.get("sources"):
        return ""
    lines = ["", "Reference material found on the web with Tavily (it may or may not apply; the evidence above wins):"]
    for s in research["sources"]:
        lines.append(f"[{s['n']}] {s['title']} ({s['domain']})\n    {s['snippet']}")
    lines.append('If a reference informed your fix, list its numbers in "references", e.g. "references": [1, 3].')
    return "\n".join(lines)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    r = Research()
    if not r.enabled:
        raise SystemExit("TAVILY_API_KEY is not set in .env")
    sample = {"bug_type": "console_error", "message": "Uncaught TypeError: Cannot read properties of undefined (reading 'sku')",
              "stack": "at onBuy (http://localhost:5174/src/components/ProductPanel.jsx:14:22)",
              "url": "http://localhost:5174/", "repro": [{"action": "rage_click"}]}
    res = r.search_sync(sample)
    print("query:", res["query"])
    if res["error"]:
        raise SystemExit("ERROR: " + res["error"])
    print(f"{len(res['sources'])} sources ({'cached, 0 credits' if res['cached'] else str(res['credits']) + ' credit'}):")
    for s in res["sources"]:
        print(f"  [{s['n']}] {s['domain']}: {s['title']}")
    print(f"Tavily credits used this month by SwarmQA: {r.used_this_month()} of cap {r.cap}")
