"""Shared data contract between engine (Kabir), fix-brain (Gagana) and dashboard (Alok).

The engine WRITES Findings. The fix-brain READS Findings and WRITES Patches.
The dashboard READS both. They move as JSON lines (one object per line).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

BUG_TYPES = ("console_error", "unhandled_promise", "layout_overflow")

_lock = threading.Lock()
_counter = 0


def next_id() -> str:
    global _counter
    with _lock:
        _counter += 1
        return f"f_{_counter:04d}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Finding:
    url: str
    persona: str
    viewport: str            # e.g. "375x812"
    actions: list[str]       # e.g. ["click #buy", "click #buy"]
    bug_type: str            # one of BUG_TYPES
    message: str
    stack: str = ""
    dom: str = ""            # outerHTML snippet of the offending element
    selector: str = ""
    screenshot: str = ""     # relative path, e.g. "shots/f_0012.png"
    id: str = field(default_factory=next_id)
    ts: str = field(default_factory=now_iso)

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


def append_jsonl(path: str | Path, obj: Finding | Patch) -> None:
    """Thread-safe append of one JSON line. Creates parent dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with p.open("a", encoding="utf-8") as f:
            f.write(obj.to_json() + "\n")
