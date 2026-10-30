"""What one agent actually did during a run, in a form people can read.

agent_story()   -> persona, stats and a timeline (plans with the actions they led to,
                   plus the bugs found), rebuilt from the run's events.jsonl.
explain()       -> a short first-person explanation. Nemotron Nano writes it from the
                   log when a key is set; otherwise a plain summary is assembled from
                   the same facts. Either way it only describes what the log shows.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from personas import PAYLOADS, PERSONAS

PAYLOAD_WORDS = {
    "$XSS": "script-injection probes", "$XSS2": "script-injection probes", "$SQL": "SQL fragments",
    "$LONG": "5,000-character strings", "$EMOJI": "walls of emoji", "$EMPTY": "empty values",
    "$SPACES": "blank spaces", "$NUM": "huge negative numbers", "$ZERO": "zeros", "$NULL": "\"null\"",
    "$UNDEF": "\"undefined\"", "$UNICODE": "mixed-script text", "$PATH": "file paths",
    "$TEMPLATE": "template code", "$DATE": "impossible dates", "$JSON": "prototype-pollution payloads",
    "$EMAIL": "valid email addresses",
}
BUG_WORDS = {
    "console_error": "a crash", "unhandled_promise": "an unhandled promise", "layout_overflow": "a layout overflow",
    "network_error": "a server error", "broken_resource": "a broken file", "blank_screen": "a blank screen",
    "unresponsive": "a frozen page", "xss": "a script injection", "broken_link": "a broken link",
}


INTENT = {
    "Rage-clicker": "My job is to act like a furious, impatient user: hammer the main buttons fast and never wait for anything to load.",
    "Thumb-tapper": "My job is to use the site like someone on a small phone: tap everything, scroll to the bottom and squeeze the screen.",
    "Form-filler": "My job is to feed every field hostile or nonsense input and submit it, to see what the site lets through.",
    "Commuter": "My job is to use the site on a terrible connection: drop or slow the network and keep clicking anyway.",
    "Keyboard user": "My job is to use the site without a mouse: Tab, Enter, Space and Escape only.",
    "Resizer": "My job is to keep resizing the window between phone, tablet and wide screens while using the page.",
    "Explorer": "My job is to reach every page and press every button at least once.",
    "Back-button": "My job is to hit Back, Forward and Reload at the worst possible moments.",
}


def _times(n: int, verb: str) -> str:
    return f"{verb} once" if n == 1 else f"{verb} twice" if n == 2 else f"{verb} {n} times"


def _say(step: dict, fallback: str) -> str:
    """One readable line for an action: names the button/field, not its CSS selector."""
    a, label = step.get("action"), step.get("label") or ""
    lab = f"“{label[:40]}”" if label else "an element"
    text = PAYLOAD_WORDS.get(step.get("text"), f"“{str(step.get('text'))[:30]}”" if step.get("text") else "nothing")
    if a in ("click", "check"):
        return f"clicked {lab}"
    if a == "rage_click":
        return f"rage-clicked {lab}"
    if a == "dblclick":
        return f"double-clicked {lab}"
    if a == "hover":
        return f"hovered over {lab}"
    if a == "type":
        return f"typed {text} into {lab}" + (" and pressed Enter" if step.get("submit") else "")
    if a == "select":
        return f"picked an option in {lab}"
    if a == "press":
        return f"pressed {step.get('key')}"
    if a == "scroll":
        return f"scrolled {'up' if (step.get('dy') or 0) < 0 else 'down'}"
    if a == "resize":
        return f"resized to {step.get('width')}px wide"
    if a == "throttle":
        return {"offline": "went offline", "slow": "slowed the network", "online": "came back online"}.get(step.get("mode"), "changed the network")
    if a == "goto":
        return f"opened {_route(step.get('url', ''))}"
    if a in ("back", "forward", "reload"):
        return f"pressed {a.capitalize()}"
    if a == "wait":
        return "waited"
    return fallback


def _route(u: str) -> str:
    p = urlparse(u or "")
    return (p.path or "/") + ("#" + p.fragment if p.fragment else "")


def _mmss(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


def _persona(name: str) -> dict:
    return next((p for p in PERSONAS if p["name"] == name), {"name": name, "brief": "", "tag": name})


def agent_story(run_dir: Path, agent: int, findings: list[dict], run_started: float) -> dict:
    events = []
    path = run_dir / "events.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("agent") == agent:
                events.append(e)
    start = next((e for e in events if e["kind"] == "agent_start"), {})
    persona = _persona(start.get("persona", ""))
    blocks, cur = [], None
    for e in events:
        if e["kind"] == "plan":
            cur = {"t": e["t"], "thought": e.get("thought", ""), "source": e.get("source", ""), "actions": []}
            blocks.append(cur)
        elif e["kind"] == "action":
            if cur is None or e.get("source") in ("start", "frontier", "recover"):
                label = {"start": "Open the site", "frontier": "Move to a page nobody has tested much",
                         "recover": "Recover after the tab died"}.get(e.get("source"), "")
                cur = {"t": e["t"], "thought": label, "source": e.get("source", ""), "actions": []}
                blocks.append(cur)
            cur["actions"].append({"t": e["t"], "step": e.get("step") or {}, "desc": e.get("desc", ""),
                                   "ok": e.get("ok", True), "page": e.get("page", "")})
    mine = [f for f in findings if f.get("agent") == agent]
    for f in mine:
        try:
            from datetime import datetime
            f_t = datetime.strptime(f["ts"], "%Y-%m-%dT%H:%M:%SZ").timestamp() - run_started
        except Exception:
            f_t = None
        f["_t"] = f_t
    acts = [a for b in blocks for a in b["actions"]]
    steps = [a["step"] for a in acts]
    kinds = Counter(s.get("action") for s in steps)
    typed = Counter(PAYLOAD_WORDS.get(s.get("text"), "") or ("ordinary text" if s.get("text") else "") for s in steps
                    if s.get("action") == "type")
    typed.pop("", None)
    targets = Counter(s.get("label") for s in steps if s.get("label"))
    pages = list(dict.fromkeys(a["page"] for a in acts if a["page"]))
    t_first = acts[0]["t"] if acts else 0
    t_last = acts[-1]["t"] if acts else 0
    stats = {
        "actions": len(acts), "failed": sum(1 for a in acts if not a["ok"]), "pages": pages,
        "seconds": round(t_last - t_first, 1), "kinds": dict(kinds), "typed": dict(typed),
        "top_targets": targets.most_common(4), "plans_nano": sum(1 for b in blocks if b["source"] == "nano"),
        "plans_rules": sum(1 for b in blocks if b["source"] == "heuristic"),
        "viewport": start.get("viewport"),
    }
    for b in blocks:
        b["thought"] = _clean(b["thought"])
        for a in b["actions"]:
            a["say"] = _say(a["step"], a["desc"])
    tag = persona.get("tag", persona["name"])
    return {"agent": agent, "persona": persona["name"], "tag": tag, "intent": INTENT.get(tag, ""),
            "brief": persona.get("brief", ""), "stats": stats, "timeline": blocks,
            "findings": [{"id": f["id"], "bug_type": f["bug_type"], "severity": f.get("severity"),
                          "message": f["message"][:200], "page": _route(f.get("page_url", "")), "t": f.get("_t")}
                         for f in mine],
            "done": any(e["kind"] == "agent_done" for e in events)}


def _clean(thought: str) -> str:
    """Nano's plan notes use payload codes and selectors; make them readable."""
    import re
    t = thought or ""
    for k in sorted(PAYLOADS, key=len, reverse=True):
        t = t.replace(k, PAYLOAD_WORDS.get(k, k))
    t = re.sub(r"#[\w-]+(?:\s*>\s*[\w:()-]+)*", lambda m: "the " + m.group(0).split(">")[0].strip("# ").replace("-", " "), t)
    t = re.sub(r"\be\d+\b", "an element", t)
    t = re.sub(r"\bXSS\b", "a script injection", t, flags=re.I)
    return t[:1].upper() + t[1:] if t else t


def _log_lines(story: dict, limit: int = 70) -> list[str]:
    lines = []
    for b in story["timeline"]:
        lines.append(f"[{_mmss(b['t'])}] PLAN ({'Nano' if b['source'] == 'nano' else 'rules'}): {b['thought']}")
        for a in b["actions"]:
            lines.append(f"    {_say(a['step'], a['desc'][:80])} on {a['page'] or '/'}{'' if a['ok'] else ' (did not work)'}")
    for f in story["findings"]:
        lines.append(f"[{_mmss(f['t'] or 0)}] BUG FOUND: {f['bug_type']} on {f['page']}: {f['message'][:140]}")
    if len(lines) > limit:                     # keep the start, the end and every bug line
        bugs = [l for l in lines if "BUG FOUND" in l]
        rest = [l for l in lines if "BUG FOUND" not in l]
        keep = limit - len(bugs)
        lines = rest[: keep // 2] + ["    ... (more of the same) ..."] + rest[-(keep - keep // 2):] + bugs
    for k in sorted(PAYLOADS, key=len, reverse=True):
        lines = [l.replace(k, PAYLOAD_WORDS.get(k, k)) for l in lines]
    return lines


def plain_summary(story: dict, site: str) -> str:
    s = story["stats"]
    if not s["actions"]:
        return f"I'm the {story['tag']}. I didn't get to act on {site}: the page never became usable for me."
    pages = s["pages"]
    page_txt = (f"the page {pages[0]}" if len(pages) == 1 else
                f"{len(pages)} pages ({', '.join(pages[:4])}{'…' if len(pages) > 4 else ''})")
    k = s["kinds"]
    did = []
    if k.get("rage_click"):
        did.append(_times(k["rage_click"], "rage-clicked"))
    if k.get("click"):
        did.append(_times(k["click"], "clicked"))
    if k.get("type"):
        did.append(_times(k["type"], "typed into fields"))
    if k.get("press"):
        did.append(_times(k["press"], "pressed keys"))
    if k.get("scroll"):
        did.append(_times(k["scroll"], "scrolled"))
    if k.get("resize"):
        did.append(_times(k["resize"], "resized the window"))
    if k.get("throttle"):
        did.append("cut or slowed the network")
    if k.get("back") or k.get("reload"):
        did.append("hit back or reload mid-flow")
    first = f"I'm the {story['tag']}. {INTENT.get(story['tag'], '')}".strip()
    parts = [first, f"Over {_mmss(s['seconds'])} I made {s['actions']} moves across {page_txt}: "
                    f"I {', '.join(did[:-1]) + ' and ' + did[-1] if len(did) > 1 else (did[0] if did else 'looked around')}."]
    if s["top_targets"]:
        parts.append("I spent most of my effort on " + ", ".join(f"“{t}”" for t, _ in s["top_targets"][:3]) + ".")
    if s["typed"]:
        parts.append("Into the forms I fed " + ", ".join(list(s["typed"])[:4]) + ".")
    bugs = story["findings"]
    if bugs:
        def where(b):
            if b["bug_type"] == "broken_link":
                import re
                m = re.search(r"Page not found: (\S+)", b["message"])
                return f"{BUG_WORDS['broken_link']} ({m.group(1) if m else b['page']} doesn't exist)"
            return f"{BUG_WORDS.get(b['bug_type'], b['bug_type'])} on {b['page']}"
        parts.append("That broke things: I caught " + ", ".join(where(b) for b in bugs[:4]) + ".")
    else:
        parts.append("Nothing I tried broke the page, which is a good sign for the parts I covered.")
    if s["failed"]:
        parts.append(f"{s['failed']} of my moves didn't land (the element moved, was covered, or the page was slow).")
    return " ".join(parts)


SYSTEM = """You are "{tag}", one of the AI test agents in Swarm AI. Your persona: {brief}
Below is the exact log of what you did while testing {site}. Explain it to the site's owner, in the first person,
in plain English, in 4 to 6 short sentences: what you set out to do and why (tie it to your persona), the main
things you actually tried (name the buttons, fields and pages from the log), what broke or that nothing broke,
and one concrete thing they should check next. Use only facts from the log; never invent actions or bugs.
Translate technical shorthand into normal words. Reply with ONLY: {{"explanation": "<your text>"}}"""


async def explain(story: dict, site: str, use_llm: bool) -> dict:
    fallback = {"text": plain_summary(story, site), "source": "summary"}
    if not use_llm or not story["stats"]["actions"]:
        return fallback
    try:
        from llm import LLM, NANO
        llm = LLM(model=NANO, max_concurrency=1, timeout=60)
        reply = await llm.chat_json(SYSTEM.format(tag=story["tag"], brief=story["brief"], site=site),
                                    "\n".join(_log_lines(story)), max_tokens=700, temperature=0.4)
        text = (reply or {}).get("explanation", "").strip() if isinstance(reply, dict) else ""
        if len(text) > 40:
            return {"text": text, "source": "nano", "model": NANO}
    except Exception:
        pass
    return fallback
