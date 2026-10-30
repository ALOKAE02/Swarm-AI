"""SwarmQA web app: paste a URL, watch the swarm live, get fixes.

    python server.py                  # opens http://localhost:8800
    python server.py --port 9000 --no-browser
    SWARMQA_MOCK_ULTRA=1 python server.py    # try the fix flow offline (labelled "mock")

Standard library only (plus the engine's own deps). Runs one swarm at a time.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
UI = HERE / "ui"
RUNS = HERE / "runs"
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HERE / ".env")

import fixer as fixer_mod  # noqa: E402
from research import Research  # noqa: E402
from swarm import run_swarm  # noqa: E402

# Public demo mode (--public): safe to expose through a tunnel. Only the listed
# targets can be attacked, fixes only read and write the demo source folders,
# runs are capped, and folder paths never reach the browser.
PUBLIC = False
TARGETS: list[dict] = []           # [{"label", "url", "repo"}]
QUOTA = {"runs_per_hour": 12, "fixes_per_hour": 40, "agents": 6, "minutes": 2.0}


def same_target(a: str, b: str) -> bool:
    def n(u):
        p = urlparse(u if "://" in u else "http://" + u)
        h = (p.hostname or "").replace("127.0.0.1", "localhost")
        return h, p.port, (p.path or "/").rstrip("/") or "/"
    return n(a) == n(b)


def target_for(url: str) -> dict | None:
    return next((t for t in TARGETS if same_target(t["url"], url)), None)


class Rate:
    def __init__(self):
        self.events: dict[str, list[float]] = {}

    def allow(self, kind: str, limit: int) -> bool:
        now = time.time()
        q = [t for t in self.events.get(kind, []) if now - t < 3600]
        if len(q) >= limit:
            self.events[kind] = q
            return False
        q.append(now)
        self.events[kind] = q
        return True


RATE = Rate()


class Run:
    def __init__(self, url: str, opts: dict):
        self.id = uuid.uuid4().hex[:6]
        self.url, self.opts = url, opts
        self.repo = (opts.get("repo") or "").strip() or None
        self.status = "running"
        self.started = time.time()
        self.ended: float | None = None
        self.dir = RUNS / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []          # replayed to late joiners (no frames)
        self.frames: dict[int, dict] = {}     # latest frame per agent
        self.findings: list[dict] = []
        self.patches: dict[str, dict] = {}
        self.summary: dict = {}
        self.subs: set[queue.Queue] = set()
        self.lock = threading.Lock()
        self.state_ref: list = []

    def meta(self, public_view: bool = True) -> dict:
        opts = dict(self.opts)
        repo = self.repo
        if PUBLIC and public_view:
            opts["repo"] = "demo source" if opts.get("repo") else ""
            repo = "demo source" if repo else None
        return {"id": self.id, "url": self.url, "status": self.status, "started": self.started,
                "ended": self.ended, "opts": opts, "repo": repo, "findings": len(self.findings),
                "summary": self.summary}

    def publish(self, ev: dict) -> None:
        kind = ev.get("kind")
        if kind == "finding" and "finding" not in ev:
            return                            # the short engine event; the full one comes from on_finding
        with self.lock:
            if kind == "frame":
                self.frames[ev["agent"]] = ev
            else:
                self.events.append(ev)
                if len(self.events) > 4000:
                    self.events = self.events[-3000:]
            for q in list(self.subs):
                if kind == "frame" and q.qsize() > 120:
                    continue                  # slow viewer: drop frames, never events
                try:
                    q.put_nowait(ev)
                except queue.Full:
                    pass

    def on_finding(self, f) -> None:
        d = asdict(f)
        d["shot_url"] = f"/runs/{self.id}/shots/{Path(f.screenshot).name}" if f.screenshot else ""
        self.findings.append(d)
        self.publish({"kind": "finding", "finding": d, "t": round(time.time() - self.started, 2)})

    def thread_main(self) -> None:
        o = self.opts
        try:
            asyncio.run(run_swarm(
                self.url, agents=int(o.get("agents", 6)), headed=False, use_llm=o.get("planner") == "nano",
                max_steps=100_000, findings_path=str(self.dir / "findings.jsonl"), shots_dir=str(self.dir / "shots"),
                on_finding=self.on_finding, minutes=float(o.get("minutes", 2)),
                events_path=str(self.dir / "events.jsonl"), summary_path=str(self.dir / "summary.json"),
                show_ui=True, human=True, listener=self.publish, on_frame=self.publish,
                state_ref=self.state_ref, run_id=self.id, llm_calls=int(o.get("llm_calls", 400))))
            self.status = "stopped" if self.status == "stopping" else "done"
        except Exception as e:
            self.status = "error"
            self.publish({"kind": "run_error", "error": f"{type(e).__name__}: {e}"})
        self.ended = time.time()
        try:
            self.summary = json.loads((self.dir / "summary.json").read_text())
        except Exception:
            self.summary = {}
        self.publish({"kind": "run_finished", "status": self.status, "summary": self.summary})


class App:
    def __init__(self):
        self.runs: dict[str, Run] = {}
        self.research = Research(RUNS)
        self.fixer = fixer_mod.Fixer(research=self.research)
        self.loop = asyncio.new_event_loop()   # fixes and replays run here
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self._load_history()

    def _load_history(self) -> None:
        if not RUNS.is_dir():
            return
        for d in sorted(RUNS.iterdir(), key=lambda p: p.stat().st_mtime)[-20:]:
            meta = d / "meta.json"
            if not meta.exists():
                continue
            try:
                m = json.loads(meta.read_text())
                r = Run.__new__(Run)
                r.__dict__.update(id=m["id"], url=m["url"], opts=m.get("opts", {}), repo=m.get("repo"),
                                  status=m.get("status", "done"), started=m["started"], ended=m.get("ended"),
                                  dir=d, events=[], frames={}, patches={}, summary=m.get("summary", {}),
                                  subs=set(), lock=threading.Lock(), state_ref=[], findings=[])
                try:
                    r.patches = json.loads((d / "patches.json").read_text(encoding="utf-8"))
                except Exception:
                    pass
                fpath = d / "findings.jsonl"
                if fpath.exists():
                    for line in fpath.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            f = json.loads(line)
                            f["shot_url"] = f"/runs/{r.id}/shots/{Path(f['screenshot']).name}" if f.get("screenshot") else ""
                            r.findings.append(f)
                self.runs[r.id] = r
            except Exception:
                pass

    def active(self) -> Run | None:
        return next((r for r in self.runs.values() if r.status in ("running", "stopping")), None)

    def start(self, body: dict) -> tuple[int, dict]:
        url = (body.get("url") or "").strip()
        if url and "://" not in url:
            url = "http://" + url
        if urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
            return 400, {"error": "Enter a full web address, like http://localhost:5174"}
        if self.active():
            return 409, {"error": "A swarm is already running. Stop it first, or wait for it to finish."}
        target = None
        if PUBLIC:
            target = target_for(url)
            if not target:
                return 403, {"error": "This public demo only runs on the demo sites listed below. "
                                      "Run SwarmQA on your own computer to test any site."}
            url = target["url"]
            if not RATE.allow("run", QUOTA["runs_per_hour"]):
                return 429, {"error": "The demo has hit its hourly limit of swarms. Try again in a little while."}
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=6).close()
        except urllib.error.HTTPError:
            pass                                    # it answered; 401/404 pages are still testable
        except Exception as e:
            reason = getattr(e, "reason", e)
            return 400, {"error": f"Couldn't reach {url} ({reason}). Is it running, and reachable from this computer?"}
        repo = (body.get("repo") or "").strip()
        if PUBLIC:
            repo = target.get("repo") or ""
            if repo:
                fixer_mod.revert(repo)          # every visitor starts from the original, buggy shop
        if repo and not Path(repo).is_dir():
            return 400, {"error": f"Source folder not found: {repo}"}
        max_agents, max_min = (QUOTA["agents"], QUOTA["minutes"]) if PUBLIC else (8, 10.0)
        opts = {"agents": max(1, min(max_agents, int(body.get("agents", 6)))),
                "minutes": max(0.5, min(max_min, float(body.get("minutes", 2)))),
                "planner": "nano" if body.get("planner", "nano") == "nano" and os.getenv("NEBIUS_API_KEY") else "offline",
                "repo": repo}
        run = Run(url, opts)
        self.runs[run.id] = run
        threading.Thread(target=self._run_and_save, args=(run,), daemon=True).start()
        return 200, run.meta()

    def _run_and_save(self, run: Run) -> None:
        (run.dir / "meta.json").write_text(json.dumps(run.meta(public_view=False)))
        run.thread_main()
        (run.dir / "meta.json").write_text(json.dumps(run.meta(public_view=False)))

    def call(self, coro, timeout=300):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=timeout)


APP: App | None = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ---- helpers
    def _json(self, code: int, obj) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            return self._json(404, {"error": "not found"})
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            ctype = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}") if n else {}
        except json.JSONDecodeError:
            return {}

    def _run(self, rid: str) -> Run | None:
        return APP.runs.get(rid)

    @staticmethod
    def _patch_view(patch: dict) -> dict:
        """What the browser sees: in public mode, no folder paths."""
        if not PUBLIC:
            return patch
        v = dict(patch)
        if v.get("repo"):
            v["repo"] = "demo source"
        return v

    def _md(self, text: str, filename: str | None) -> None:
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _base(self) -> str:
        proto = self.headers.get("X-Forwarded-Proto") or "http"
        return f"{proto}://{self.headers.get('Host') or 'localhost:8800'}"

    def _finding(self, run: Run, fid: str) -> dict | None:
        return next((f for f in run.findings if f["id"] == fid), None)

    # ---- routes
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        parts = [p for p in path.split("/") if p]
        if path in ("/", "/index.html", "/swarm") or (parts and parts[0] in ("run", "swarm")):
            return self._file(UI / "index.html")
        if parts[:1] == ["ui"]:
            return self._file((UI / "/".join(parts[1:])).resolve()) if ".." not in parts else self._json(400, {})
        if parts[:1] == ["runs"] and len(parts) == 4 and parts[2] == "shots" and ".." not in parts:
            return self._file(RUNS / parts[1] / "shots" / parts[3])
        if path == "/api/status":
            return self._json(200, {"nebius_key": bool(os.getenv("NEBIUS_API_KEY")), "mock_ultra": APP.fixer.mock,
                                    "nano": os.getenv("NANO_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"),
                                    "ultra": os.getenv("ULTRA_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b"),
                                    "active": APP.active().id if APP.active() else None,
                                    "tavily": APP.research.status(), "public": PUBLIC,
                                    "targets": [{"label": t["label"], "url": t["url"], "source": bool(t.get("repo"))}
                                                for t in TARGETS] if PUBLIC else [],
                                    "limits": QUOTA if PUBLIC else None})
        if path == "/api/runs":
            runs = sorted(APP.runs.values(), key=lambda r: -r.started)
            return self._json(200, [r.meta() for r in runs[:20]])
        if len(parts) == 3 and parts[:2] == ["api", "runs"]:
            run = self._run(parts[2])
            if not run:
                return self._json(404, {"error": "run not found"})
            return self._json(200, {**run.meta(), "findings_list": run.findings,
                                    "patches": {k: self._patch_view(v) for k, v in run.patches.items()}})
        if len(parts) == 5 and parts[:2] == ["api", "runs"] and parts[3] == "agents" and parts[4].isdigit():
            run = self._run(parts[2])
            if not run:
                return self._json(404, {"error": "run not found"})
            from story import agent_story
            return self._json(200, agent_story(run.dir, int(parts[4]), [dict(f) for f in run.findings], run.started))
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "report.md":
            run = self._run(parts[2])
            if not run:
                return self._json(404, {"error": "run not found"})
            import report
            q = dict(p.split("=", 1) for p in urlparse(self.path).query.split("&") if "=" in p)
            if q.get("finding"):
                f = self._finding(run, q["finding"])
                if not f:
                    return self._json(404, {"error": "finding not found"})
                return self._md(report.finding_md(f, run.patches.get(f["id"]), self._base()), None)
            host = (urlparse(run.url).hostname or "site").replace(".", "-")
            return self._md(report.run_md(run, self._base()), f"swarmqa-{host}-{run.id}.md")
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "stream":
            return self._stream(parts[2])
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        body = self._body()
        if path == "/api/runs":
            code, obj = APP.start(body)
            return self._json(code, obj)
        if path == "/api/revert":
            run = self._run(str(body.get("run") or ""))
            repo = run.repo if run and run.repo else ("" if PUBLIC else (body.get("repo") or ""))
            if PUBLIC and repo and not any(t.get("repo") == repo for t in TARGETS):
                repo = ""
            return self._json(200, {"restored": fixer_mod.revert(repo) if repo else []})
        if len(parts) >= 4 and parts[:2] == ["api", "runs"]:
            run = self._run(parts[2])
            if not run:
                return self._json(404, {"error": "run not found"})
            if len(parts) == 6 and parts[3] == "agents" and parts[4].isdigit() and parts[5] == "explain":
                from story import agent_story, explain
                n = int(parts[4])
                cache = run.dir / f"explain_{n}.json"
                story = agent_story(run.dir, n, [dict(f) for f in run.findings], run.started)
                if cache.exists() and story["done"] and not body.get("refresh"):
                    try:
                        return self._json(200, json.loads(cache.read_text(encoding="utf-8")))
                    except Exception:
                        pass
                use_llm = bool(os.getenv("NEBIUS_API_KEY"))
                out = APP.call(explain(story, run.url, use_llm), timeout=90)
                out["actions"] = story["stats"]["actions"]
                if story["done"]:
                    cache.write_text(json.dumps(out), encoding="utf-8")
                return self._json(200, out)
            if parts[3] == "stop":
                if run.status == "running":
                    run.status = "stopping"
                    for st in run.state_ref:
                        st.stopped = True
                return self._json(200, run.meta())
            if len(parts) == 6 and parts[3] == "findings":
                f = self._finding(run, parts[4])
                if not f:
                    return self._json(404, {"error": "finding not found"})
                action = parts[5]
                if PUBLIC:
                    repo = run.repo or None             # never a folder from the request
                else:
                    repo = (body.get("repo") if body.get("repo") else run.repo) or None
                if action == "fix":
                    if PUBLIC and not RATE.allow("fix", QUOTA["fixes_per_hour"]):
                        return self._json(429, {"error": "The demo has hit its hourly limit of fixes. Try again soon."})
                    patch = APP.call(APP.fixer.suggest(f, repo, allow_research=body.get("research", True) is not False),
                                     timeout=420)
                    patch["repo"] = repo
                    run.patches[f["id"]] = patch
                    try:
                        (run.dir / "patches.json").write_text(json.dumps(run.patches), encoding="utf-8")
                    except OSError:
                        pass
                    view = self._patch_view(patch)
                    run.publish({"kind": "patch", "patch": view})
                    return self._json(200, view)
                if action == "apply":
                    if PUBLIC and repo and not any(t.get("repo") == repo for t in TARGETS):
                        return self._json(403, {"error": "Applying fixes is limited to the demo source in this demo."})
                    patch = run.patches.get(f["id"])
                    if not patch or not patch.get("diff") or not repo:
                        return self._json(400, {"error": "Nothing to apply: this fix has no code diff."})
                    try:
                        files = fixer_mod.apply_patch(repo, patch)
                    except Exception as e:
                        return self._json(400, {"error": f"Couldn't apply: {e}"})
                    patch["applied"] = True
                    return self._json(200, {"files": files})
                if action == "minimize":
                    from repro import minimize, reproduces
                    try:
                        if not APP.call(reproduces(f, tries=2), timeout=240):
                            return self._json(200, {"steps": f.get("repro"), "error": "It didn't break on replay, so the steps can't be shortened."})
                        steps = APP.call(minimize(f), timeout=600)
                    except Exception as e:
                        return self._json(500, {"error": f"Couldn't shorten: {e}"})
                    f["repro"] = steps
                    return self._json(200, {"steps": steps})
                if action == "replay":
                    from repro import reproduces
                    try:
                        hit = APP.call(reproduces(f, tries=2), timeout=240)
                    except Exception as e:
                        return self._json(500, {"error": f"Replay failed: {e}"})
                    return self._json(200, {"reproduced": hit})
        return self._json(404, {"error": "not found"})

    def _stream(self, rid: str) -> None:
        run = self._run(rid)
        if not run:
            return self._json(404, {"error": "run not found"})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q: queue.Queue = queue.Queue(maxsize=2000)
        with run.lock:
            backlog = [{"kind": "hello", "run": run.meta()}] + list(run.events)
            backlog += [{"kind": "finding", "finding": f, "replay": True} for f in run.findings
                        if not any(e.get("kind") == "finding" and e.get("finding", {}).get("id") == f["id"]
                                   for e in run.events)]
            backlog += list(run.frames.values())
            run.subs.add(q)
        try:
            for ev in backlog:
                self._send(ev)
            if run.status not in ("running", "stopping") and not any(e.get("kind") == "run_finished" for e in run.events):
                self._send({"kind": "run_finished", "status": run.status, "summary": run.summary})
            while True:
                try:
                    ev = q.get(timeout=15)
                    self._send(ev)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            run.subs.discard(q)

    def _send(self, ev: dict) -> None:
        self.wfile.write(b"data: " + json.dumps(ev, ensure_ascii=False).encode() + b"\n\n")
        self.wfile.flush()


def main() -> None:
    global APP
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="SwarmQA web app")
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--open", action="store_true", help="also open the app in a new browser tab")
    ap.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)   # kept for old commands
    ap.add_argument("--public", action="store_true",
                    help="public demo mode: only --target sites, source locked to their folders, runs capped")
    ap.add_argument("--target", action="append", default=[], metavar="URL[=SOURCE_FOLDER]",
                    help="a site the public demo may attack, optionally with its source folder (repeatable)")
    a = ap.parse_args()
    RUNS.mkdir(exist_ok=True)
    global PUBLIC
    PUBLIC = a.public
    if PUBLIC:
        specs = a.target or ["http://localhost:5174/=" + os.getenv("SWARMQA_DEMO_REPO", ""), "http://localhost:8790/"]
        for spec in specs:
            url, _, repo = spec.partition("=")
            repo = repo.strip().strip('"')
            if repo and not Path(repo).is_dir():
                sys.exit(f"--target source folder not found: {repo}")
            label = {"5174": "Aangan demo shop", "8790": "Bug benchmark"}.get(str(urlparse(url).port), urlparse(url).netloc)
            TARGETS.append({"label": label, "url": url if url.endswith("/") else url + "/", "repo": repo or None})
    APP = App()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.daemon_threads = True
    url = f"http://localhost:{a.port}"
    key = "Nemotron key found" if os.getenv("NEBIUS_API_KEY") else "no NEBIUS_API_KEY: offline planner only"
    print(f"SwarmQA is running at {url}  ({key}{', mock Ultra' if APP.fixer.mock else ''})")
    print("Open that address in your browser (or refresh the tab you already have). Ctrl+C to stop.")
    tv = APP.research.status()
    print(f"Tavily research: {'on, ' + str(tv['used_this_month']) + ' of ' + str(tv['cap']) + ' credits used this month' if tv['enabled'] else 'off (no TAVILY_API_KEY)'}")
    if PUBLIC:
        print("PUBLIC DEMO MODE. Allowed targets:")
        for t in TARGETS:
            print(f"  {t['label']}: {t['url']}" + ("  (with source, fixes can be applied)" if t.get("repo") else ""))
    if a.open and not a.no_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
