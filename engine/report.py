"""Markdown bug reports: one finding as a GitHub issue, or a whole run."""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse

TITLES = {
    "console_error": "Crash", "unhandled_promise": "Unhandled promise", "layout_overflow": "Layout overflow",
    "network_error": "Server error", "broken_resource": "Broken file", "blank_screen": "Blank screen",
    "unresponsive": "Page froze", "xss": "Script injection", "broken_link": "Broken link",
}
PAYLOAD = {
    "$XSS": "a script-injection probe", "$XSS2": "a script-injection probe", "$SQL": "an SQL fragment",
    "$LONG": "5,000 characters", "$EMOJI": "a wall of emoji", "$EMPTY": "nothing", "$SPACES": "only spaces",
    "$NUM": "a huge negative number", "$ZERO": "0", "$NULL": '"null"', "$UNDEF": '"undefined"',
    "$UNICODE": "mixed-script text", "$PATH": "a file path", "$TEMPLATE": "template code", "$DATE": "an impossible date",
    "$JSON": "a __proto__ payload", "$EMAIL": "an email address",
}
KEYS = {"Escape": "Esc", " ": "Space", "ArrowDown": "Down arrow", "ArrowUp": "Up arrow"}


def route(u: str) -> str:
    p = urlparse(u or "")
    return (p.path or "/") + ("#" + p.fragment if p.fragment else "")


def step_text(s: dict) -> str:
    a = s.get("action")
    label = f"**{s['label'][:60]}**" if s.get("label") else "the element"
    text = PAYLOAD.get(s.get("text"), f'"{str(s.get("text"))[:40]}"' if s.get("text") else "nothing")
    return {
        "click": f"Click {label}", "check": f"Click {label}", "dblclick": f"Double-click {label}",
        "rage_click": f"Click {label} {s.get('times', 6)} times, fast", "hover": f"Hover over {label}",
        "type": f"Type {text} into {label}" + (", then press Enter" if s.get("submit") else ""),
        "select": f"Pick an option in {label}", "press": f"Press {KEYS.get(s.get('key'), s.get('key'))}",
        "scroll": f"Scroll {'up' if (s.get('dy') or 0) < 0 else 'down'} {abs(int(s.get('dy') or 0))}px",
        "resize": f"Resize the window to {s.get('width')}px wide",
        "set_viewport": f"Use a {s.get('width')} × {s.get('height')} screen",
        "throttle": {"offline": "Go offline", "slow": "Slow the network to a crawl",
                     "online": "Come back online"}.get(s.get("mode"), "Change the network"),
        "goto": f"Open `{route(s.get('url', ''))}`", "back": "Press Back", "forward": "Press Forward",
        "reload": "Reload the page", "wait": "Wait a moment",
    }.get(a, str(a))


def plain(f: dict) -> str:
    m = re.sub(r"^Uncaught\s+", "", str(f.get("message") or ""))
    t = f.get("bug_type")
    if t == "layout_overflow":
        x = re.search(r"(\d+)px wide in a (\d+)px", m)
        if x:
            return f"The page is {x.group(1)}px wide on a {x.group(2)}px screen, so it scrolls sideways."
    if t == "unhandled_promise":
        return f"A request failed and nothing handled it: {m}"
    if t == "blank_screen":
        return "The page went white and no error was thrown."
    if t == "xss":
        return "Text typed into the page ran as a script."
    if t == "broken_link":
        x = re.search(r"Page not found: (\S+) returns (\d+)", m)
        if x:
            return f"The site links to `{x.group(1)}`, but that page doesn't exist ({x.group(2)})."
    return m


def finding_md(f: dict, patch: dict | None, base: str, heading: str = "##") -> str:
    sev = (f.get("severity") or "").upper()
    title = TITLES.get(f.get("bug_type"), f.get("bug_type"))
    out = [f"{heading} [{sev}] {title}: {plain(f)[:110]}", ""]
    out.append(f"**Page:** `{route(f.get('page_url') or f.get('url'))}` on {urlparse(f.get('url') or '').netloc}  ")
    out.append(f"**Screen:** {str(f.get('viewport', '')).replace('x', ' × ')}  ")
    out.append(f"**Found by:** the {f.get('persona', 'Swarm AI')} agent  ")
    out.append(f"**Finding:** `{f.get('id')}`, {f.get('ts', '')}")
    out.append("")
    if f.get("shot_url"):
        out += [f"![Screenshot when it broke]({base}{f['shot_url']})", ""]
    steps = [s for s in (f.get("repro") or [])]
    if steps:
        out.append(f"{heading}# Steps to reproduce")
        out += [f"{i}. {step_text(s)}" for i, s in enumerate(steps, 1)]
        out.append("")
    out.append(f"{heading}# What happened")
    out += ["```", str(f.get("message") or "")]
    stack = "\n".join(str(f.get("stack") or "").splitlines()[:12])
    if stack and stack not in str(f.get("message")):
        out.append(stack)
    out += ["```", ""]
    if patch and patch.get("summary"):
        conf = round((patch.get("confidence") or 0) * 100)
        model = "offline stand-in for Ultra" if "mock" in str(patch.get("model")) else "Nemotron 3 Ultra"
        out.append(f"{heading}# Suggested fix ({model}, {conf}% confident)")
        out += [f"**{patch['summary']}**", "", patch.get("explanation", ""), ""]
        if patch.get("diff"):
            out += ["```diff", patch["diff"].rstrip(), "```", ""]
        elif patch.get("code"):
            out += [f"Where: {patch.get('where') or 'see above'}", "", "```", patch["code"].rstrip(), "```", ""]
        srcs = ((patch.get("research") or {}).get("sources") or [])
        if srcs:
            used = set(patch.get("references") or [])
            out.append("References found with Tavily:")
            out += [f"- [{s['title']}]({s['url']}){' (used for this fix)' if s['n'] in used else ''}" for s in srcs]
            out.append("")
    out.append("_Reported by Swarm AI. Suggested patches are for review, not auto-merged._")
    return "\n".join(out)


def run_md(run, base: str) -> str:
    s = run.summary or {}
    when = time.strftime("%d %b %Y, %H:%M", time.localtime(run.started))
    out = [f"# Swarm AI report: {run.url}", "",
           f"{when}. {s.get('findings', len(run.findings))} bugs from {run.opts.get('agents')} agents in "
           f"{int(s.get('seconds', 0)) // 60}:{int(s.get('seconds', 0)) % 60:02d}, "
           f"{s.get('actions', '?')} actions across {s.get('pages_visited', '?')} "
           f"{'page' if s.get('pages_visited') == 1 else 'pages'}.", ""]
    llm = s.get("llm") or {}
    if llm:
        out += [f"Agents planned with {llm.get('model')} ({llm.get('calls')} calls, about ${llm.get('est_cost_usd', 0):.4f}).", ""]
    order = {"high": 0, "medium": 1, "low": 2}
    if not run.findings:
        out.append("No bugs found in the parts of the site the agents reached.")
    for f in sorted(run.findings, key=lambda x: order.get(x.get("severity"), 3)):
        out += [finding_md(f, run.patches.get(f["id"]), base), "", "---", ""]
    return "\n".join(out)
