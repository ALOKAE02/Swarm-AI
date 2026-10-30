# Swarm AI engine

A swarm of chaotic browser agents attacks a live web UI. **Nemotron Nano on Nebius Token Factory** plans each agent's next moves; detectors catch what breaks; every bug comes with a screenshot and a replayable repro.

## Quick start

```bash
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env          # add NEBIUS_API_KEY (and ULTRA_MODEL if needed)
python hello.py               # lists live Nemotron model ids, pings Nano + Ultra

python swarm.py http://localhost:5174 --agents 6                                # Nano-driven swarm
python swarm.py http://localhost:5174 --agents 6 --headed --tile --minutes 1.5  # hero shot (see below)
python swarm.py http://localhost:5174 --minutes 3                               # time budget instead of step budget
python swarm.py http://localhost:5174 --no-llm                                  # heuristic planner, zero API calls
python swarm.py --stub                                                          # 3 fake findings, no browser
```

Only point the swarm at apps you own or have permission to test: agents submit forms and type hostile input.

## The web app

```bash
python server.py                 # then open http://localhost:8800 (add --open to have it open a tab for you)
python research.py               # optional: check the Tavily key (1 credit)
```

`/` is the landing page, `/swarm` is the app. Everything happens in that one tab: paste any URL (or pick the demo shop or the benchmark), choose agents, duration and planner, and start. You get:

- **Live agents**: one tile per agent, streamed from its browser (CDP screencast), with what it is doing and why
- **Bugs as they happen**: plain-language cards with severity; open one for the screenshot, the steps that break it, the raw error and stack
- **Click any agent** to see what it did: its job, a first-person explanation (written by Nemotron Nano from the agent's own log, or a plain summary without a key), the bugs it found, and every plan and move on a timeline
- **Replay** the steps in a fresh browser, and **Shorten the steps** to the minimum that still breaks it
- **Suggest a fix** with Nemotron 3 Ultra. Give it the site's source folder and Ultra reads the files behind the bug (found from the stack, the element the agent touched, and the error), then writes search-and-replace edits that are checked against the real files and shown as a diff. **Apply** writes it with a backup, **Replay to verify** proves the bug is gone, **Undo** restores everything. Without source, you get a page-level CSS/JS suggestion with capped confidence.

No key yet? `SWARMQA_MOCK_ULTRA=1 python server.py` runs the whole flow with an offline stand-in (labelled "mock"). Every patch is a suggestion for a human to review.

Each bug also has **Copy as GitHub issue** (screenshot link, steps, error, suggested diff and sources, as Markdown), and finished runs have **Download report** for the whole run.

## How Nemotron, Token Factory and Tavily are used

| Step | Model / service | What it does |
|---|---|---|
| Every agent move | **Nemotron Nano** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`) on Nebius Token Factory | Reads a compact page summary (elements as short ids, least-explored pages, what was tried, what already broke) and plans the next 1–4 actions as JSON. One call drives several moves. A coverage-guided rule planner takes over instantly if Nano is slow or returns junk. |
| Explaining an agent | **Nemotron Nano** | Turns the agent's own log into a first-person account of what it tried and found. |
| Before each fix | **Tavily** search | Searches MDN, framework docs, Stack Overflow and GitHub for the exact error (framework detected from the stack and host). Basic depth, 1 credit, cached on disk, monthly cap. |
| Writing the fix | **Nemotron 3 Ultra** (`nvidia/Nemotron-3-Ultra-550b-a55b`) on Nebius Token Factory, reasoning on | Reads the evidence, the source files behind the bug and the Tavily sources, and returns exact search-and-replace edits that are checked against the real files and turned into a diff. It cites which sources it used. |

Real costs from our runs: an 8-agent, 3-minute swarm on a live site made 63 Nano calls for about **$0.005**; a busier run made 207 calls for about **$0.014**. Ultra is only called when someone asks for a fix.

## Tavily research

Add `TAVILY_API_KEY=tvly-...` to `.env`. Then `python research.py` runs one real search (1 credit) and prints the sources, which checks the key.
Credits are protected: basic search only, every query is cached in `runs/tavily_cache.json`, and Swarm AI stops searching at `TAVILY_MONTHLY_CAP` (default 1000 of the free 1,500 a month). The fix panel shows how many have been used this month.

## Public demo (share a link safely)

```bash
python server.py --public --target "http://localhost:5174/=C:\path\to\victim-app" --target http://localhost:8790/
cloudflared tunnel --url http://localhost:8800      # prints a public https://….trycloudflare.com link
```

In public mode visitors can only attack the listed sites; fixes read and write only those sites' source folders (paths never reach the browser); each new run restores the demo shop's original, buggy source; runs are capped at 6 agents and 2 minutes, 12 swarms and 40 fixes an hour. Never expose the app without `--public`: it would let anyone point the swarm at any site on your API keys and read folders on your computer.

## Hero-shot mode

`--headed --tile` opens one window per agent in a grid, and the agents behave like people:

- the mouse travels on curved, eased paths timed by distance (with the occasional overshoot), clicks land off-centre with a real press, rage-clicks come in at about 10 a second with hand tremor
- text is typed key by key with natural rhythm; long junk is pasted, as a person would
- scrolling comes in eased wheel bursts, with short pauses to look before the next move

Each window shows the agent's cursor with a name tag (like multiplayer cursors), a thin ring on each press, a keycap when a keyboard agent presses Tab or Esc, and when a bug is caught, a notification card plus an outline on the element that broke. Use `--minutes` for recordings so every window runs to the end together, `--fast` to keep the windows but skip the human motion, and `--no-ui` to hide the overlay.

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
| `broken_link` | a page the site links to returns 404 (agents then stop visiting it) | medium |

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
