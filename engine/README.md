# SwarmQA engine

A swarm of chaotic browser agents attacks a live web UI. **Nemotron Nano on Nebius Token Factory** plans each agent's next moves; detectors catch what breaks; every bug comes with a screenshot and a replayable repro.

## Quick start

```bash
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env          # add NEBIUS_API_KEY (and ULTRA_MODEL if needed)
python hello.py               # lists live Nemotron model ids, pings Nano + Ultra

python swarm.py http://localhost:5173 --agents 6                   # Nano-driven swarm
python swarm.py http://localhost:5173 --agents 8 --headed --tile   # hero shot: tiled windows, cursors, bug alarms
python swarm.py http://localhost:5173 --minutes 3                  # time budget instead of step budget
python swarm.py http://localhost:5173 --no-llm                     # heuristic planner, zero API calls
python swarm.py --stub                                             # 3 fake findings, no browser
```

Only point the swarm at apps you own or have permission to test: agents submit forms and type hostile input.

## How it works

1. **Observe**: one snapshot per plan collects every interactive element, including inside web components (shadow DOM), ranks them, and gives each a short id (`e1`, `e2`, …).
2. **Plan**: Nemotron Nano receives a compact page summary (elements, least-explored routes, what was tried, what already broke) and returns 1–4 actions as JSON. If Nano is slow, out of budget or returns junk, a coverage-guided heuristic takes over instantly.
3. **Act**: click, rage-click, type hostile payloads, fill and submit whole forms, mash Escape at dialogs, go offline mid-request, resize, back, reload.
4. **Detect** after every action, run-wide deduped, with third-party and benign noise filtered:

| bug_type | catches | severity |
|---|---|---|
| `console_error` | uncaught exceptions (high), `console.error` logs (medium) | high / medium |
| `unhandled_promise` | rejected promises nobody caught | high |
| `layout_overflow` | horizontal scroll on the page, with the **root-cause element** | medium |
| `network_error` | first-party 5xx / failed requests | high |
| `broken_resource` | first-party image/script/css 404 | low |
| `blank_screen` | page went white with no error | high |
| `unresponsive` | main thread frozen 2.5s+, tab hung or crashed | high |
| `xss` | hostile input executed as script | high |

5. **Explore**: agents share a URL frontier and split the site by page *type*; personas that need forms or buttons are pulled to pages that have them; site chrome (nav/footer) is discounted so agents work on each page's own controls.

## Outputs

- `findings.jsonl`: one Finding per bug (contract below)
- `events.jsonl`: live activity stream: `run_start`, `agent_start`, `plan` (with Nano's `thought`), `action`, `finding`, `agent_done`, `run_done`
- `run_summary.json`: coverage, findings by type/severity, Nano calls / tokens / estimated cost
- `shots/f_XXXX.png`: screenshot at the moment of each bug

## Contract changes (v2, backward compatible)

Every v1 field is unchanged. New optional fields on each Finding:

| field | meaning |
|---|---|
| `severity` | `high` / `medium` / `low` |
| `page_url` | exact page/route where it broke (`url` is still the start URL) |
| `agent` | which agent found it |
| `intent` | what the agent was trying (Nano's thought), e.g. "double-submit the payment form" |
| `repro` | replayable steps: `[{"action":"set_viewport",...},{"action":"goto","url":...},{"action":"rage_click","selector":"#buy"}, ...]` |
| `run_id` | run identifier; ids now keep counting across runs that append to the same file |

`bug_type` can now be any value in the table above. **Alok**: render unknown types with a generic card and use `severity` for colour. To restrict the run to the original three: `--detectors core`.

## Repro, minimize, verify a fix

```bash
python repro.py f_0007              # replay in a fresh browser: REPRODUCED / NOT reproduced
python repro.py f_0007 --headed     # watch it
python repro.py f_0007 --minimize   # shortest step list that still breaks
python repro.py --all               # verify every finding
```

**Gagana**: after applying Ultra's patch, `await repro.reproduces(finding)` returning `False` means the bug is gone. That's the "show the fix works" moment for the video.

## Benchmark

`bench/` is a deliberately tricky SPA with 12 planted bugs (race conditions, a leaked listener, shadow-DOM crash, XSS, freeze, silent blank screen, server 500, truncated JSON) plus realistic noise (ad-script errors, ResizeObserver warnings, a cookie banner, intentional scroll areas).

```bash
python bench/server.py                                 # terminal 1
python bench/run_bench.py --runs 3 --steps 25 --no-llm # terminal 2
```

Same budget (4 agents × 25 actions), no LLM:

| | planted bugs caught | noise findings / run |
|---|---|---|
| v1 engine (5 runs) | 2.0 / 12 | 6.2 |
| v2 engine (8 runs) | 9.4 / 12 | 0 |
| v2, 60 actions/agent (3 runs) | 11.3 / 12 | 0 |

## Other flags

`--storage-state auth.json` (from `python login.py URL`) tests behind a login · `--llm-calls 400` hard cap on Nano calls · `--slowmo 150` slows actions for video · `--include-third-party` · `--page-budget 10` · `--seed 1` · `--fresh` clears old findings/events.
