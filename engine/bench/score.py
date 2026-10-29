"""Score a findings.jsonl against the bench app's 12 planted bugs.

    python bench/score.py findings.jsonl

Prints which planted bugs were caught, which were missed, and every finding
that matched no planted bug (noise / false positives).
"""
from __future__ import annotations

import json
import sys

# (id, description, matcher)
PLANTED = [
    ("B1", "rage-click Add to cart -> null.sku race", lambda f: "reading 'sku'" in f["message"]),
    ("B2", "quick view, close, Escape -> leaked keydown listener", lambda f: "reading 'remove'" in f["message"]),
    ("B3", "pricing table overflows on phones", lambda f: f["bug_type"] == "layout_overflow" and "pricing" in (f.get("selector", "") + f.get("dom", ""))),
    ("B4", "signup fetch chain has no error handling", lambda f: f["bug_type"] in ("unhandled_promise", "console_error") and any(s in f["message"] for s in ("toUpperCase", "Internal S", "Failed to fetch"))),
    ("B5", "server 500 on hostile signup email", lambda f: f["bug_type"] == "network_error" and "/api/subscribe" in f["message"] and "500" in f["message"]),
    ("B6", "newsletter (shadow DOM) Join with empty email", lambda f: "setting 'textContent'" in f["message"]),
    ("B7", "search renders input with innerHTML (XSS)", lambda f: f["bug_type"] == "xss"),
    ("B8", "profile route renders a blank white screen", lambda f: f["bug_type"] == "blank_screen"),
    ("B9", "Generate report freezes the tab for 8s", lambda f: f["bug_type"] == "unresponsive"),
    ("B10", "feed page 3 returns truncated JSON", lambda f: "end of JSON input" in f["message"] or "/api/feed" in f["message"]),
    ("B11", "dark mode toggle logs a theme error", lambda f: "Theme 'dark'" in f["message"]),
    ("B12", "About page team photo 404s", lambda f: f["bug_type"] == "broken_resource" and "team.png" in f["message"]),
]


# Real bugs in the bench app that were NOT planted on purpose (found by the swarm).
# Reported separately so they never inflate the planted catch rate.
UNPLANTED = [
    ("X1", "search echoes long unbroken input -> page overflows", lambda f: f["bug_type"] == "layout_overflow" and "#results" in f.get("selector", "")),
    ("X2", "newsletter Join button overflows 320px phones", lambda f: f["bug_type"] == "layout_overflow" and "sqa-newsletter" in f.get("selector", "")),
]


def score(path: str) -> dict:
    findings = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    caught: dict[str, list[str]] = {}
    extra: dict[str, list[str]] = {}
    noise = []
    for f in findings:
        hits = [pid for pid, _, m in PLANTED if m(f)]
        for pid in hits:
            caught.setdefault(pid, []).append(f["id"])
        xs = [] if hits else [xid for xid, _, m in UNPLANTED if m(f)]
        for xid in xs:
            extra.setdefault(xid, []).append(f["id"])
        if not hits and not xs:
            noise.append(f)
    print(f"\n{len(caught)}/{len(PLANTED)} planted bugs caught, {len(extra)} real unplanted bugs, "
          f"{len(findings)} findings, {len(noise)} noise\n")
    for pid, desc, _ in PLANTED:
        mark = "CAUGHT" if pid in caught else "missed"
        print(f"  {pid:<4} {mark:<7} {desc}")
    for xid, desc, _ in UNPLANTED:
        if xid in extra:
            print(f"  {xid:<4} {'BONUS':<7} {desc}")
    if noise:
        print("\nNoise / unmatched findings:")
        for f in noise:
            print(f"  {f['id']} {f['bug_type']}: {f['message'][:100]}")
    return {"caught": len(caught), "total": len(PLANTED), "extra": len(extra),
            "findings": len(findings), "noise": len(noise)}


if __name__ == "__main__":
    score(sys.argv[1] if len(sys.argv) > 1 else "findings.jsonl")
