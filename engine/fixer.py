"""Suggested fixes with Nemotron 3 Ultra.

Two modes:
- With the site's source folder: find the files behind the bug (stack trace
  paths, ids and classes from the DOM, callers of failing functions), ask Ultra
  for exact search-and-replace edits, check every edit against the real files,
  and build a unified diff. One retry if an edit doesn't match.
- Without source: Ultra suggests a CSS/JS/HTML change from the live evidence
  (DOM snippet, stack, repro steps). Confidence is capped, and labelled as such.

apply_patch() writes a validated diff with a backup; revert() restores it.
Everything here is a SUGGESTED patch for a human to review, never auto-merged.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import time
from pathlib import Path

CODE_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue", ".svelte", ".css", ".scss", ".html"}
STYLE_EXT = {".css", ".scss"}
SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".next", ".vite", "coverage", "public", ".swarmqa-backup"}
APP_PATH = re.compile(r"/((?:src|app|pages|components|lib)/[^\s():?#]+?\.(?:jsx?|tsx?|mjs|vue|svelte|css))")
FRAME_FN = re.compile(r"at\s+(?:async\s+)?([A-Za-z_$][\w$]*)\s*\(")
GENERIC = {"Object", "Array", "Promise", "Function", "eval", "new", "async", "anonymous", "fetch", "setTimeout",
           "renderWithHooks", "beginWork", "performUnitOfWork", "workLoopSync", "react_stack_bottom_frame"}

SYSTEM_REPO = """You are a senior front-end engineer fixing a bug that an automated QA swarm found in a live web app.
Make the smallest safe change that removes the bug without changing anything else the user sees.
Reply with ONLY one JSON object:
{"summary": "<one line, imperative>", "explanation": "<2-3 sentences: cause, then fix>", "confidence": <0..1>,
 "edits": [{"file": "<path exactly as given>", "find": "<exact text copied from that file: a few whole lines>", "replace": "<new text>"}],
 "references": [<numbers of any web references that informed the fix>]}
Every "find" must appear exactly once in its file. Do not invent files."""

SYSTEM_NOREPO = """You are a senior front-end engineer. An automated QA swarm broke a live web page. You cannot see the
source code, only the evidence from the browser. Suggest a concrete fix the developer can apply.
Reply with ONLY one JSON object:
{"summary": "<one line, imperative>", "explanation": "<2-3 sentences: likely cause, then fix>", "confidence": <0..0.6>,
 "target": "css|js|html|config", "where": "<which element / component / file to change>", "code": "<the snippet to add or change>",
 "references": [<numbers of any web references that informed the fix>]}"""


# ---------------------------------------------------------------- locating source

def _files(repo: Path) -> dict[str, str]:
    out = {}
    for root, dirs, names in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for n in sorted(names):
            p = Path(root) / n
            if p.suffix.lower() not in CODE_EXT or n.endswith((".config.js", ".config.ts", ".test.js", ".spec.js")):
                continue
            try:
                if p.stat().st_size < 150_000:
                    out[p.relative_to(repo).as_posix()] = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass
    return out


def locate(finding: dict, repo: Path, max_files: int = 4, budget: int = 45_000) -> list[tuple[str, str, str]]:
    """Return [(relpath, text, why)] for the files most likely behind the finding."""
    files = _files(repo)
    score: dict[str, float] = {}
    why: dict[str, list[str]] = {}

    def add(rel, pts, reason):
        score[rel] = score.get(rel, 0) + pts
        why.setdefault(rel, []).append(reason)

    stack = finding.get("stack") or ""
    funcs = []
    for i, line in enumerate(l for l in stack.splitlines() if "node_modules" not in l):
        m = APP_PATH.search(line)
        if not m:
            continue
        rel = next((f for f in files if f == m.group(1) or f.endswith("/" + m.group(1)) or m.group(1).endswith(f)), None)
        if rel:
            add(rel, max(100 - i * 10, 50), "named in the stack trace")
            fm = FRAME_FN.search(line)
            if fm and fm.group(1) not in GENERIC and fm.group(1) not in funcs:
                funcs.append(fm.group(1))
    for fn in funcs[:3]:                     # unhandled promises are fixed in the caller
        call = re.compile(rf"\b{re.escape(fn)}\s*\(")
        define = re.compile(rf"function\s+{re.escape(fn)}\b|\b{re.escape(fn)}\s*=")
        for rel, text in files.items():
            if call.search(text) and not define.search(text):
                add(rel, 45, f"calls {fn}()")

    sel, dom = finding.get("selector") or "", finding.get("dom") or ""
    ids = set(re.findall(r"#([A-Za-z][\w-]*)", sel)) | set(re.findall(r'\bid="([A-Za-z][\w-]*)"', dom))
    # What the agent touched right before it broke (works even with no stack trace).
    touched = [s.get("selector", "") for s in (finding.get("repro") or []) if s.get("selector")][-2:]
    for t in touched:
        for i in re.findall(r"#([A-Za-z][\w-]*)", t.split(" ")[-1]):
            for rel, text in files.items():
                if re.search(rf'\bid\s*=\s*["\']{re.escape(i)}["\']', text):
                    add(rel, 55, f"defines #{i}, which the agent used just before the bug")
    # Property names in the error: "reading 'sku'" -> code that reads .sku
    for prop in re.findall(r"(?:reading|setting) '([A-Za-z_$][\w$]*)'", finding.get("message") or ""):
        for rel, text in files.items():
            if Path(rel).suffix not in STYLE_EXT and re.search(rf"\.{re.escape(prop)}\b", text):
                add(rel, 35, f"reads .{prop}")
    classes = set(re.findall(r"\.([A-Za-z][\w-]*)", sel))
    for attr in re.findall(r'class="([^"]+)"', dom):
        classes.update(c for c in attr.split() if len(c) > 2 and not c.startswith(("is-", "has-")))
    layout = finding.get("bug_type") == "layout_overflow"
    for rel, text in files.items():
        style = Path(rel).suffix in STYLE_EXT
        for i in ids:
            if not style and re.search(rf'\bid\s*=\s*["\']{re.escape(i)}["\']', text):
                add(rel, 60, f"defines #{i}")
        for c in classes:
            if style and layout and re.search(rf"\.{re.escape(c)}(?![\w-])", text):
                add(rel, 70, f"styles .{c}")
            elif not style and re.search(rf'class(?:Name)?=[{{"\'`][^>]*\b{re.escape(c)}\b', text):
                add(rel, 25, f"renders .{c}")
    picked, left = [], budget
    for rel in sorted(score, key=lambda r: (-score[r], r)):
        if len(picked) >= max_files:
            break
        if len(files[rel]) > left and picked:
            continue
        picked.append((rel, files[rel], "; ".join(dict.fromkeys(why[rel]))))
        left -= len(files[rel])
    return picked


# ---------------------------------------------------------------- edits -> diff

class EditError(ValueError):
    pass


def _replace_once(text: str, find: str, replace: str, rel: str) -> str:
    if not find.strip():
        raise EditError(f"empty 'find' for {rel}")
    n = text.count(find)
    if n == 1:
        return text.replace(find, replace, 1)
    if n > 1:
        raise EditError(f"'find' matches {n} places in {rel}; include more surrounding lines")
    want = [l.strip() for l in find.strip("\n").splitlines()]
    lines = text.splitlines(keepends=True)
    stripped = [l.strip() for l in lines]
    hits = [i for i in range(len(lines) - len(want) + 1) if stripped[i:i + len(want)] == want]
    if len(hits) != 1:
        raise EditError(f"'find' text was not found in {rel}")
    i = hits[0]
    start = sum(len(l) for l in lines[:i])
    end = start + sum(len(l) for l in lines[i:i + len(want)])
    if lines[i + len(want) - 1].endswith("\n") and not replace.endswith("\n"):
        replace += "\n"
    return text[:start] + replace + text[end:]


def build_diff(repo: Path, edits: list[dict], allowed: set[str]) -> tuple[str, dict[str, str], int, int]:
    originals, contents = {}, {}
    for e in edits:
        rel = str(e.get("file", "")).replace("\\", "/").lstrip("./")
        if rel not in allowed:
            raise EditError(f"{e.get('file')} was not one of the files you were shown")
        if rel not in contents:
            originals[rel] = contents[rel] = (repo / rel).read_text(encoding="utf-8")
        contents[rel] = _replace_once(contents[rel], str(e.get("find", "")), str(e.get("replace", "")), rel)
    diff, adds, dels = [], 0, 0
    for rel, old in originals.items():
        new = contents[rel]
        if new == old:
            continue
        lines = list(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                          f"a/{rel}", f"b/{rel}", n=3))
        diff.extend(l if l.endswith("\n") else l + "\n" for l in lines)
        adds += sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
        dels += sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    if not diff:
        raise EditError("the edits did not change anything")
    return "".join(diff), {r: contents[r] for r in originals if contents[r] != originals[r]}, adds, dels


# ---------------------------------------------------------------- prompts

def _evidence(f: dict) -> str:
    steps = "\n".join(f"  {i + 1}. {json.dumps(s, ensure_ascii=False)[:160]}"
                      for i, s in enumerate(f.get("repro") or []))
    return "\n".join([
        f"bug_type: {f.get('bug_type')}   severity: {f.get('severity')}",
        f"page: {f.get('page_url') or f.get('url')}   viewport: {f.get('viewport')}   persona: {f.get('persona')}",
        f"message: {f.get('message')}",
        f"stack:\n{(f.get('stack') or '(none)')[:2500]}",
        f"selector: {f.get('selector') or '(none)'}",
        f"dom snippet: {(f.get('dom') or '(none)')[:800]}",
        f"steps that triggered it:\n{steps or '  (none)'}",
    ])


# ---------------------------------------------------------------- main entry

class Fixer:
    def __init__(self, mock: bool | None = None, research=None):
        self.mock = (os.getenv("SWARMQA_MOCK_ULTRA") == "1") if mock is None else mock
        self.llm = None
        self.cache: dict[str, dict] = {}
        self.research = research          # research.Research (Tavily) or None
        self.web = ""                     # reference block for the current request

    def _client(self):
        if self.llm is None:
            from llm import LLM, ULTRA
            self.llm = LLM(model=ULTRA, max_concurrency=2, timeout=240, thinking=True)
        return self.llm

    async def _ask(self, system: str, user: str) -> tuple[dict | None, str]:
        user = user + self.web
        if self.mock:
            from mock_ultra import canned
            return canned(system, user), "mock-ultra (offline)"
        llm = self._client()
        return await llm.chat_json(system, user, max_tokens=8000, temperature=0.2), llm.model

    async def suggest(self, finding: dict, repo: str | None = None, allow_research: bool = True) -> dict:
        key = f"{finding.get('id')}|{repo or ''}"
        if key in self.cache:
            return self.cache[key]
        t0 = time.time()
        patch = {"finding_id": finding.get("id"), "summary": "", "explanation": "", "confidence": 0.0,
                 "target": "", "diff": "", "files": [], "edits": [], "code": "", "where": "",
                 "model": "", "latency_ms": 0, "error": None, "note": "", "sources": [],
                 "research": None, "references": []}
        try:
            self.web = ""
            if self.research is not None and self.research.enabled and allow_research:
                from research import prompt_block
                patch["research"] = await self.research.search(finding)
                self.web = prompt_block(patch["research"])
            if repo and Path(repo).is_dir():
                await self._with_repo(finding, Path(repo), patch)
            else:
                await self._without_repo(finding, patch)
        except Exception as e:
            patch["error"] = f"{type(e).__name__}: {e}"
        patch["latency_ms"] = int((time.time() - t0) * 1000)
        n_src = len((patch.get("research") or {}).get("sources") or [])
        patch["references"] = sorted({int(x) for x in patch.get("references") or []
                                      if str(x).isdigit() and 1 <= int(x) <= n_src})
        if not patch["error"]:
            self.cache[key] = patch
        return patch

    async def _with_repo(self, f: dict, repo: Path, patch: dict) -> None:
        sources = locate(f, repo)
        if not sources:
            patch["note"] = "No files in that folder matched this bug, so this is a page-level suggestion."
            await self._without_repo(f, patch)
            return
        patch["sources"] = [{"file": r, "why": w} for r, _, w in sources]
        files_txt = "\n\n".join(f"=== FILE: {r} ===\n{t}" for r, t, _ in sources)
        user = f"{_evidence(f)}\n\nSource files:\n\n{files_txt}"
        reply, model = await self._ask(SYSTEM_REPO, user)
        patch["model"] = model
        for attempt in range(2):
            if not isinstance(reply, dict):
                patch["error"] = "Ultra returned no usable answer."
                return
            try:
                diff, new, adds, dels = build_diff(repo, reply.get("edits") or [], {r for r, _, _ in sources})
                patch.update(summary=str(reply.get("summary", "")), explanation=str(reply.get("explanation", "")),
                             confidence=float(reply.get("confidence") or 0), target="file", diff=diff,
                             files=sorted(new), edits=reply.get("edits") or [], adds=adds, dels=dels, error=None,
                             references=reply.get("references") or [])
                return
            except EditError as e:
                if attempt == 1:
                    patch["error"] = f"Ultra's edit didn't match the source: {e}"
                    return
                reply, _ = await self._ask(SYSTEM_REPO, user + f"\n\nYour previous edit failed: {e}. "
                                                              f"Copy the 'find' text exactly from the file.")

    async def _without_repo(self, f: dict, patch: dict) -> None:
        reply, model = await self._ask(SYSTEM_NOREPO, _evidence(f))
        patch["model"] = model
        if not isinstance(reply, dict):
            patch["error"] = patch["error"] or "Ultra returned no usable answer."
            return
        patch.update(summary=str(reply.get("summary", "")), explanation=str(reply.get("explanation", "")),
                     confidence=min(0.6, float(reply.get("confidence") or 0)),
                     target=str(reply.get("target", "css")), where=str(reply.get("where", "")),
                     code=str(reply.get("code", "")), references=reply.get("references") or [])


# ---------------------------------------------------------------- apply / revert

def apply_patch(repo: str, patch: dict) -> list[str]:
    root = Path(repo)
    _, new, _, _ = build_diff(root, patch.get("edits") or [], set(patch.get("files") or []) |
                              {str(e.get("file", "")).replace("\\", "/").lstrip("./") for e in patch.get("edits") or []})
    backup = root / ".swarmqa-backup" / time.strftime("%Y%m%d-%H%M%S")
    for rel, text in new.items():
        dest = backup / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(root / rel, dest)
        (root / rel).write_text(text, encoding="utf-8")
    return sorted(new)


def revert(repo: str) -> list[str]:
    root = Path(repo) / ".swarmqa-backup"
    if not root.is_dir():
        return []
    restored: dict[str, Path] = {}
    for snap in sorted(root.iterdir()):       # oldest first: keep the true original
        for f in snap.rglob("*"):
            if f.is_file():
                restored.setdefault(f.relative_to(snap).as_posix(), f)
    for rel, f in restored.items():
        shutil.copy2(f, Path(repo) / rel)
    shutil.rmtree(root)
    return sorted(restored)
