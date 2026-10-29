"""Shared data contract between engine (Kabir), fix-brain (Gagana) and dashboard (Alok).

The engine WRITES Findings. The fix-brain READS Findings and WRITES Patches.
The dashboard READS both. They move as JSON lines (one object per line).

Backward compatible with v1: every original field is unchanged; v2 only ADDS
optional fields (severity, page_url, agent, intent, repro, run_id) and new
bug_type values. Readers should treat unknown bug_types generically.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CORE_TYPES = ("console_error", "unhandled_promise", "layout_overflow")
BUG_TYPES = CORE_TYPES + (
    "network_error",     # first-party request returned 5xx or failed
    "broken_resource",   # first-party image/script/css/font 404
    "blank_screen",      # page went white (app root emptied, no error)
    "unresponsive",      # main thread frozen for seconds, or tab crashed/hung
    "xss",               # hostile input executed as script
)
SEVERITIES = ("high", "medium", "low")

_lock = threading.Lock()
_counter = 0


def next_id() -> str:
    global _counter
    with _lock:
        _counter += 1
        return f"f_{_counter:04d}"


def seed_ids_from(path: str | Path) -> None:
    """Continue numbering after the highest id already in a findings file, so
    ids stay unique when several runs append to the same file."""
    global _counter
    p = Path(path)
    if not p.exists():
        return
    best = 0
    for m in re.finditer(r'"id":\s*"f_(\d+)"', p.read_text(encoding="utf-8", errors="ignore")):
        best = max(best, int(m.group(1)))
    with _lock:
        _counter = max(_counter, best)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Finding:
    url: str                 # the start URL of the run
    persona: str
    viewport: str            # e.g. "375x812"
    actions: list[str]       # human-readable recent actions, e.g. ["rage_click #buy"]
    bug_type: str            # one of BUG_TYPES
    message: str
    stack: str = ""
    dom: str = ""            # outerHTML snippet of the offending element
    selector: str = ""
    screenshot: str = ""     # relative path, e.g. "shots/f_0012.png"
    id: str = field(default_factory=next_id)
    ts: str = field(default_factory=now_iso)
    # ---- v2 additions (all optional) ----
    severity: str = "medium"  # high | medium | low
    page_url: str = ""        # the exact page/route where it broke
    agent: int = -1           # which swarm agent found it
    intent: str = ""          # what the agent was trying to do (Nano's thought)
    repro: list[dict] = field(default_factory=list)  # replayable steps, see repro.py
    run_id: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class Patch:
    finding_id: str
    summary: str
    target: str              # "jsx | css | file"
    diff: str
    explanation: str
    confidence: float

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def append_jsonl(path: str | Path, obj) -> None:
    """Thread-safe append of one JSON line. Accepts dataclasses or dicts."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = obj.to_json() if hasattr(obj, "to_json") else json.dumps(obj, ensure_ascii=False)
    with _lock:
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
