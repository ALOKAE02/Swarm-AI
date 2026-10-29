"""The three bug detectors: console errors, uncaught exceptions / unhandled
promise rejections, and horizontal layout overflow.

Usage (per page):
    det = Detectors(page, seen)       # `seen` is a shared set -> run-wide dedupe
    await det.install()               # BEFORE page.goto()
    ...do an action...
    bugs = await det.drain()          # list[RawBug]
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from playwright.async_api import Page

# JS helper reused by detectors and the agent's element lister.
SELECTOR_JS = """
function __sqaSelector(el) {
  if (!(el instanceof Element)) return '';
  if (el.id) return '#' + CSS.escape(el.id);
  const tid = el.getAttribute('data-testid');
  if (tid) return '[data-testid="' + tid + '"]';
  const parts = [];
  while (el && el.nodeType === 1 && el !== document.documentElement) {
    let part = el.tagName.toLowerCase();
    if (el.id) { parts.unshift('#' + CSS.escape(el.id)); break; }
    const sib = el.parentElement ? Array.from(el.parentElement.children).filter(c => c.tagName === el.tagName) : [];
    if (sib.length > 1) part += ':nth-of-type(' + (sib.indexOf(el) + 1) + ')';
    parts.unshift(part);
    el = el.parentElement;
  }
  return parts.join(' > ');
}
"""

# Runs in every page before app code: bridges window errors + unhandled
# rejections to Python via an exposed binding (more reliable than guessing which
# Playwright event fires for rejections).
INIT_SCRIPT = """
(() => {
  const report = (kind, message, stack) => {
    try { window.__swarmqa_report(kind, String(message || ''), String(stack || '')); } catch (e) {}
  };
  window.addEventListener('error', (e) => {
    report('pageerror', e.message, e.error && e.error.stack);
  });
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason;
    report('unhandled_promise', (r && r.message) || r, r && r.stack);
  });
})();
"""

OVERFLOW_JS = "() => {" + SELECTOR_JS + """
  const vw = document.documentElement.clientWidth;
  const sw = document.documentElement.scrollWidth;
  if (sw <= vw + 1) return null;
  let worst = null, worstRight = vw;
  for (const el of document.body.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right > worstRight + 1) { worst = el; worstRight = r.right; }
  }
  return {
    viewport: vw, scrollWidth: sw,
    selector: worst ? __sqaSelector(worst) : '',
    dom: worst ? worst.outerHTML.slice(0, 600) : '',
  };
}
"""


_PREFIX_RE = re.compile(r"^(uncaught\s*(\(in promise\))?\s*)?((type|reference|range|syntax)?error:\s*)?", re.I)


def _normalize(msg: str) -> str:
    """'Uncaught TypeError: x' and 'x' are the same bug."""
    return _PREFIX_RE.sub("", msg.strip())[:200].lower()


@dataclass
class RawBug:
    bug_type: str      # console_error | unhandled_promise | layout_overflow
    message: str
    stack: str = ""
    selector: str = ""
    dom: str = ""


class Detectors:
    def __init__(self, page: Page, seen: set[tuple[str, str]]):
        self.page = page
        self.seen = seen                       # shared across agents -> dedupe
        self._queue: list[RawBug] = []

    async def install(self) -> None:
        await self.page.expose_binding("__swarmqa_report", self._on_js_report)
        await self.page.add_init_script(INIT_SCRIPT)
        self.page.on("console", self._on_console)
        self.page.on("pageerror", self._on_pageerror)

    # --- event handlers -------------------------------------------------
    def _on_console(self, msg) -> None:
        if msg.type == "error":
            text = msg.text
            # Skip noisy resource-404s unless they're the only signal; they are
            # still console errors, so keep them but mark clearly.
            self._queue.append(RawBug("console_error", text))

    def _on_pageerror(self, exc) -> None:
        self._queue.append(RawBug(
            "console_error",
            getattr(exc, "message", str(exc)),
            stack=getattr(exc, "stack", "") or "",
        ))

    async def _on_js_report(self, _source, kind: str, message: str, stack: str) -> None:
        bug_type = "unhandled_promise" if kind == "unhandled_promise" else "console_error"
        self._queue.append(RawBug(bug_type, message, stack=stack))

    # --- polled -----------------------------------------------------------
    async def _check_overflow(self) -> None:
        try:
            res = await self.page.evaluate(OVERFLOW_JS)
        except Exception:
            return
        if res:
            msg = (f"Horizontal overflow: content is {res['scrollWidth']}px wide "
                   f"in a {res['viewport']}px viewport")
            self._queue.append(RawBug("layout_overflow", msg,
                                      selector=res.get("selector", ""),
                                      dom=res.get("dom", "")))

    async def drain(self, settle: float = 0.25) -> list[RawBug]:
        """Wait briefly for async errors, run the overflow check, return NEW bugs."""
        await asyncio.sleep(settle)
        await self._check_overflow()
        out: list[RawBug] = []
        queue, self._queue = self._queue, []
        # Specific detectors first, so a duplicate console echo never wins the label.
        queue.sort(key=lambda b: b.bug_type == "console_error")
        for bug in queue:
            if bug.bug_type == "layout_overflow":
                key = ("layout_overflow", bug.selector)      # same element = same bug at any width
            else:
                key = ("js", _normalize(bug.message))        # pageerror + console echo = one bug
            if key in self.seen:
                continue
            self.seen.add(key)
            out.append(bug)
        return out
