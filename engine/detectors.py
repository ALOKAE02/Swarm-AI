"""Bug detectors.

Core three (the contract): console errors / uncaught exceptions, unhandled
promise rejections, horizontal layout overflow. Plus: first-party 5xx and
failed requests, broken first-party resources, blank white screens, frozen or
crashed tabs, and executed XSS payloads.

Noise control is what makes this usable on real, complex sites:
- third-party scripts' errors (ads, analytics, widgets) are dropped,
- known-benign messages (ResizeObserver loop, sanitized "Script error.", dev
  tooling chatter, favicon 404) are dropped,
- console "Failed to load resource" lines are replaced by the network
  detector, which knows the URL, method and status,
- intentional scroll containers and fixed/off-canvas elements don't count as
  overflow, and the reported culprit is the ROOT element causing it,
- blank screens are re-checked before reporting so loading states don't count,
- every finding is deduped run-wide across all agents.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from contract import BUG_TYPES
from observe import SELECTOR_JS

INIT_SCRIPT = r"""
(() => {
  if (window.__sqaInit) return;
  window.__sqaInit = true;
  const report = (kind, message, stack, file) => {
    try { window.__swarmqa_report(kind, String(message || ''), String(stack || ''), String(file || '')); } catch (e) {}
  };
  window.addEventListener('error', (e) => {
    if (e.target && e.target !== window) return;            // resource errors: network detector
    report('error', e.message, e.error && e.error.stack, e.filename);
  });
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason;
    report('unhandled_promise', (r && r.message) || r, r && r.stack, '');
  });
  try {
    new PerformanceObserver((list) => {
      for (const en of list.getEntries())
        if (en.duration > 2500) (window.__sqaLong = window.__sqaLong || []).push(Math.round(en.duration));
    }).observe({type: 'longtask', buffered: true});
  } catch (e) {}
})();
"""

PROBE_JS = "() => {" + SELECTOR_JS + r"""
  const out = {url: location.href, longtasks: (window.__sqaLong || []).splice(0)};
  const html = document.documentElement, body = document.body;
  if (!body) return out;
  const vw = html.clientWidth;
  const sw = Math.max(html.scrollWidth, body.scrollWidth);
  const clips = (el) => { const o = getComputedStyle(el).overflowX; return o === 'hidden' || o === 'clip'; };
  const viewportClips = clips(html) || (getComputedStyle(html).overflowX === 'visible' && clips(body));
  if (sw > vw + 1 && !viewportClips) {
    let best = null, bestRight = vw + 1, visited = 0;
    const walk = (el, parentOver) => {
      const kids = el.shadowRoot ? [...el.children, ...el.shadowRoot.children] : el.children;
      for (const c of kids) {
        if (++visited > 8000) return;
        if (c.hasAttribute('data-sqa-ui') || ['STYLE', 'SCRIPT', 'TEMPLATE'].includes(c.tagName)) continue;
        const st = getComputedStyle(c);
        if (st.display === 'none') continue;
        const r = c.getBoundingClientRect();
        const right = r.right + scrollX;
        const over = r.width > 0 && right > vw + 1 && st.position !== 'fixed';
        if (over && !parentOver && right > bestRight) { best = c; bestRight = right; }
        if (st.overflowX === 'visible') walk(c, parentOver || over);
      }
    };
    walk(body, false);
    out.overflow = {vw, sw, width: Math.round(bestRight),
                    selector: best ? __sqaSel(best) : '', dom: best ? best.outerHTML.slice(0, 600) : ''};
  }
  const t = (body.innerText || '').trim();
  out.textLen = t.length;
  if (t.length < 400) {
    const fixed = new Map();
    const inFixed = (el) => {
      for (let e = el; e && e !== body; e = e.parentElement) {
        if (fixed.has(e)) return fixed.get(e);
        const p = getComputedStyle(e).position;
        if (p === 'fixed' || p === 'sticky') { fixed.set(e, true); return true; }
      }
      return false;
    };
    let vis = 0;
    const tw = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = tw.nextNode())) {
      const s = node.textContent.trim();
      const p = node.parentElement;
      if (!s || !p || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(p.tagName)) continue;
      if (p.checkVisibility && !p.checkVisibility()) continue;
      if (!inFixed(p)) vis += s.length;
    }
    out.visibleText = vis;
    out.media = body.querySelectorAll('img,svg,canvas,video,iframe,object').length;
  }
  return out;
}
"""

IGNORE = re.compile("|".join([
    r"ResizeObserver loop", r"^\s*(Uncaught\s+)?Script error\.?\s*$", r"favicon",
    r"Download the React DevTools", r"chrome-extension://", r"moz-extension://",
    r"ERR_BLOCKED_BY_CLIENT", r"\[vite\]", r"\[HMR\]", r"\[webpack-dev-server\]",
    r"Failed to load resource", r"net::ERR_INTERNET_DISCONNECTED", r"sqa-x",
]), re.I)

SEVERITY = {
    "unhandled_promise": "high", "network_error": "high", "blank_screen": "high",
    "unresponsive": "high", "xss": "high", "layout_overflow": "medium",
    "console_error": "medium", "broken_resource": "low", "broken_link": "medium",
}
PRIORITY = {"xss": 0, "unhandled_promise": 1, "unresponsive": 2, "blank_screen": 3,
            "network_error": 4, "console_error": 5, "layout_overflow": 6, "broken_link": 6, "broken_resource": 7}

_PREFIX = re.compile(r"^(uncaught\s*(\(in promise\))?\s*)?((\w*error|domexception)\s*:\s*)?", re.I)
_URL = re.compile(r"https?://[^\s'\")]+")


def normalize(msg: str) -> str:
    m = _PREFIX.sub("", msg.strip())
    m = _URL.sub(lambda u: urlparse(u.group(0)).path or "/", m)
    m = re.sub(r"\d+", "N", m)
    return m[:200].lower()


def route(url: str) -> str:
    u = urlparse(url or "")
    return (u.path or "/") + ("#" + u.fragment if u.fragment else "")


def bug_key(bug_type: str, message: str, selector: str = "", page_url: str = "", dom: str = "") -> tuple:
    if bug_type == "layout_overflow":   # same KIND of element = same bug: sibling cards, any page, any state
        if not selector:
            return ("layout", route(page_url))
        return ("layout", re.sub(r":nth-of-type\(\d+\)", "", selector), element_signature(dom))
    if bug_type in ("blank_screen", "unresponsive", "xss"):
        return (bug_type, route(page_url))
    if bug_type == "broken_link":
        m = re.search(r"Page not found: (\S+)", message)
        return ("broken_link", m.group(1) if m else normalize(message))
    if bug_type in ("network_error", "broken_resource"):
        return (bug_type, normalize(message))
    return ("js", normalize(message))   # console_error + unhandled_promise share a key space


def element_signature(dom: str) -> str:
    """'<button class="product-card is-selected" ...>' -> 'button.product-card' (state classes dropped)."""
    m = re.match(r"\s*<([\w-]+)([^>]*)>", dom or "")
    if not m:
        return ""
    cm = re.search(r'class="([^"]*)"', m.group(2))
    classes = [c for c in (cm.group(1).split() if cm else [])
               if not re.match(r"(is|has)-|active$|selected$|open$|focus", c)]
    return ".".join([m.group(1).lower()] + sorted(classes))


def site_base(host: str) -> str:
    """Registrable-ish domain: app.acme.com and api.acme.com are both first-party."""
    if not host or host == "localhost" or re.fullmatch(r"[\d.]+|\[.*\]", host):
        return host
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac", "edu"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


@dataclass
class RawBug:
    bug_type: str
    message: str
    stack: str = ""
    selector: str = ""
    dom: str = ""
    severity: str = "medium"
    page_url: str = ""
    fatal: bool = False      # page is dead/hung: agent must recover


class Detectors:
    def __init__(self, target_url: str, seen: set, enabled=BUG_TYPES, include_third_party: bool = False):
        self.base = site_base(urlparse(target_url).hostname or "")
        self.seen = seen
        self.enabled = set(enabled)
        self.include_third_party = include_third_party
        self.page = None
        self._queue: list[RawBug] = []
        self._offline_until = 0.0
        self._last_js = 0.0
        self._dead_doc = False                # a crash blanked this document; only a real load revives it
        self.dead_urls: set[str] = set()      # first-party pages that answered 404/410
        self.had_content = False

    # ---- wiring --------------------------------------------------------
    async def install(self, ctx) -> None:
        await ctx.expose_binding("__swarmqa_report", self._on_js_report)
        await ctx.add_init_script(INIT_SCRIPT)

    def attach(self, page) -> None:
        self.page = page
        self.had_content = False
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_requestfailed)
        page.on("dialog", self._on_dialog)
        page.on("domcontentloaded", lambda *_: setattr(self, "_dead_doc", False))
        page.on("crash", lambda *_: self._push("unresponsive", "Tab crashed (renderer process died)",
                                               severity="high", fatal=True))

    def set_offline(self, offline: bool) -> None:
        self._offline_until = float("inf") if offline else time.time() + 3.0

    # ---- helpers -------------------------------------------------------
    def first_party(self, url: str) -> bool:
        if self.include_third_party or not url:
            return True
        host = urlparse(url).hostname or ""
        if not host:
            return True
        return host == self.base or host.endswith("." + self.base)

    def _stack_first_party(self, stack: str) -> bool:
        m = _URL.search(stack or "")
        return self.first_party(m.group(0)) if m else True

    def _page_url(self) -> str:
        try:
            return self.page.url if self.page else ""
        except Exception:
            return ""

    def _push(self, bug_type, message, stack="", selector="", dom="", severity=None, fatal=False):
        if bug_type == "unhandled_promise" or (bug_type == "console_error" and severity == "high"):
            self._last_js = time.time()       # a crash explains a white page: don't double-report it
        self._queue.append(RawBug(bug_type, message, stack, selector, dom,
                                  severity or SEVERITY.get(bug_type, "medium"), self._page_url(), fatal))

    # ---- event handlers ------------------------------------------------
    def _on_console(self, msg) -> None:
        if msg.type != "error":
            return
        text = msg.text
        loc = msg.location or {}
        if IGNORE.search(text) or not self.first_party(loc.get("url", "")):
            return
        where = f"at {loc.get('url')}:{(loc.get('lineNumber') or 0) + 1}" if loc.get("url") else ""
        self._push("console_error", text, stack=where, severity="medium")

    def _on_pageerror(self, err) -> None:
        msg = getattr(err, "message", None) or str(err)
        stack = getattr(err, "stack", "") or ""
        name = getattr(err, "name", "") or ""
        if IGNORE.search(msg) or not self._stack_first_party(stack):
            return
        if "in promise" in name.lower():       # Chromium tags rejections "Uncaught (in promise) X"
            self._push("unhandled_promise", msg, stack=stack or name)
        else:
            self._push("console_error", msg, stack=stack, severity="high")

    async def _on_js_report(self, _source, kind: str, message: str, stack: str, file: str) -> None:
        if IGNORE.search(message) or not self.first_party(file) or not self._stack_first_party(stack):
            return
        if kind == "unhandled_promise":
            self._push("unhandled_promise", message, stack=stack)
        else:
            self._push("console_error", message, stack=stack, severity="high")

    def _on_response(self, resp) -> None:
        try:
            url, status = resp.url, resp.status
            if status < 400 or not self.first_party(url):
                return
            req = resp.request
            path = urlparse(url).path or "/"
            if req.resource_type == "document" and status in (404, 410):
                self.dead_urls.add(url.split("#")[0])
                ref = (req.headers or {}).get("referer", "")
                came = f", linked from {urlparse(ref).path or '/'}" if ref and self.first_party(ref) else ""
                self._push("broken_link", f"Page not found: {path} returns {status}{came}")
            elif status >= 500:
                self._push("network_error", f"{req.method} {path} -> {status} (server error)")
            elif status == 404 and req.resource_type in ("image", "script", "stylesheet", "font", "media"):
                if "favicon" not in path and "sqa-" not in path:
                    self._push("broken_resource", f"{req.resource_type} {path} -> 404 Not Found")
        except Exception:
            pass

    def _on_requestfailed(self, req) -> None:
        if time.time() < self._offline_until:
            return
        try:
            failure = req.failure or ""
            if any(s in failure for s in ("ERR_ABORTED", "BLOCKED", "ERR_INTERNET_DISCONNECTED", "cancel")):
                return
            if req.resource_type in ("fetch", "xhr", "document", "script") and self.first_party(req.url):
                self._push("network_error", f"{req.method} {urlparse(req.url).path or '/'} failed: {failure}",
                           severity="medium")
        except Exception:
            pass

    def _on_dialog(self, dialog) -> None:
        if "sqa-xss" in (dialog.message or ""):
            self._push("xss", f"Injected script executed: user input reached the DOM as HTML "
                              f"and fired {dialog.type}('{dialog.message}')")
        action = dialog.accept() if dialog.type == "beforeunload" else dialog.dismiss()
        asyncio.ensure_future(action)

    # ---- polled checks ---------------------------------------------------
    async def _probe(self, timeout: float = 4.0):
        """Returns the probe dict, {} if the page navigated mid-probe, None if hung."""
        try:
            return await asyncio.wait_for(self.page.evaluate(PROBE_JS), timeout)
        except asyncio.TimeoutError:
            return None
        except Exception:
            return {}

    async def _wait_responsive(self, limit: float = 20.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < limit:
            try:
                await asyncio.wait_for(self.page.evaluate("1"), 2.0)
                return True
            except asyncio.TimeoutError:
                continue
            except Exception:
                return True
        return False

    async def drain(self, settle: float = 0.3) -> list[RawBug]:
        """Wait for async errors, run polled checks, return NEW (deduped) bugs."""
        await asyncio.sleep(settle)
        probe = await self._probe()
        if probe is None:                      # main thread blocked right now
            if await self._wait_responsive():
                probe = await self._probe() or {}
            else:
                self._push("unresponsive", "Page hung: main thread never recovered (20s+)",
                           severity="high", fatal=True)
                probe = {}
        self._process_probe(probe)
        blankish = probe.get("visibleText", 99) < 3 and probe.get("media", 1) == 0
        if blankish and time.time() - self._last_js <= 3:
            self._dead_doc = True             # the crash took the page down with it
        if (blankish and self.had_content and not self._dead_doc
                and str(probe.get("url", "")).startswith("http")):
            await asyncio.sleep(1.2)           # give loading states a chance
            again = await self._probe() or {}
            if again.get("visibleText", 99) < 3 and again.get("media", 1) == 0:
                self._push("blank_screen", "Page rendered blank: no visible content, and no error was "
                                           "thrown (likely an unhandled empty/logged-out/loading state)")
        if probe.get("textLen", 0) >= 50:
            self.had_content = True
        return self._filter()

    def _process_probe(self, probe: dict) -> None:
        for ms in probe.get("longtasks") or []:
            self._push("unresponsive", f"Main thread blocked for {ms / 1000:.1f}s: the page froze and "
                                       f"ignored input")
        ov = probe.get("overflow")
        if ov:
            self._push("layout_overflow",
                       f"Horizontal overflow: content is {ov['sw']}px wide in a {ov['vw']}px viewport"
                       + (f"; root cause {ov['selector']} extends to {ov['width']}px" if ov["selector"] else ""),
                       selector=ov.get("selector", ""), dom=ov.get("dom", ""))

    def _filter(self) -> list[RawBug]:
        queue, self._queue = self._queue, []
        queue.sort(key=lambda b: PRIORITY.get(b.bug_type, 9))
        out = []
        for bug in queue:
            if bug.bug_type not in self.enabled and not bug.fatal:
                continue
            key = bug_key(bug.bug_type, bug.message, bug.selector, bug.page_url, bug.dom)
            if key in self.seen:
                if bug.fatal:   # still need the agent to recover, just don't re-report
                    out.append(RawBug(**{**bug.__dict__, "bug_type": "_recover"}))
                continue
            self.seen.add(key)
            out.append(bug)
        return out
