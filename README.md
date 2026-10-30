# SwarmQA

**Break your website before your users do.** Paste a URL and a swarm of AI users attacks the live site: rage-clicking, typing hostile input, dropping the network, squeezing the screen, hitting Back at the worst moment. Every bug comes back with a screenshot, the exact steps to reproduce it, and a suggested fix written by **NVIDIA Nemotron 3 Ultra on Nebius Token Factory**, grounded in docs found by **Tavily**.

Built for the Nebius × NVIDIA Global AI Hackathon, Best Apps & Agents track. MIT licensed.

## What it does

1. **Paste a URL.** Choose 4, 6 or 8 agents and how long they get.
2. **Watch the swarm live.** Each agent has a personality (rage-clicker, phone user, form-filler, commuter on a dead connection, keyboard-only user, window-resizer) and its own browser, streamed into the page. Click any agent to hear, in its own words, what it tried and what it found.
3. **Get bugs with evidence.** Crashes, unhandled promises, layout overflow, server errors, broken links, blank screens, frozen tabs and script injection. Each one has a screenshot, replayable steps (with a "shorten the steps" button), the raw error, and "Copy as GitHub issue".
4. **Get a fix.** Tavily searches MDN, framework docs, Stack Overflow and GitHub for the error; Nemotron 3 Ultra reads the evidence, the sources and (if you point it at the project folder) the code, and writes a diff. Apply it, then **Replay to verify** the bug is gone.

## How Nemotron, Token Factory and Tavily are used

| Step | Model / service | Role |
|---|---|---|
| Every agent move | **Nemotron Nano** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`) on Nebius Token Factory | Plans each agent's next 1–4 actions as JSON from a compact page summary. Cheap and fast: an 8-agent, 3-minute swarm on a live site made 63 calls for about $0.005. |
| Agent explanations | **Nemotron Nano** | Turns an agent's log into a plain first-person account. |
| Before each fix | **Tavily** search | Finds docs and known issues for the exact error (1 credit, cached). |
| Writing the fix | **Nemotron 3 Ultra** (`nvidia/Nemotron-3-Ultra-550b-a55b`) on Nebius Token Factory, reasoning on | Returns exact edits, validated against the real files and shown as a diff, citing the sources it used. Called only on a bug. |

## Run it

```bash
cd engine
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env        # add NEBIUS_API_KEY and TAVILY_API_KEY
python server.py            # open http://localhost:8800
```

Demo target with three planted bugs (rage-click crash, mobile overflow, unhandled promise):

```bash
cd victim-app && npm install && npm run dev     # http://localhost:5174
```

In the app choose **Aangan demo shop**, add the `victim-app` folder as the source, and start the swarm.

Full details (detectors, benchmark, CLI, hero-shot mode, public demo mode): [engine/README.md](engine/README.md). Planted bugs: [victim-app/BUGS.md](victim-app/BUGS.md).

## Results

On a benchmark site with 12 planted bugs and realistic noise (ad-script errors, cookie banner, intentional scroll areas), 4 agents × 25 actions catch about 9 of 12 with zero false alarms, up from 2 of 12 with about 6 false alarms in our first version. With 60 actions per agent, 11.3 of 12. On a real production site it found a broken `/enquire-now` link.

Fixes are **suggested patches** for a human to review, never auto-merged. Only point SwarmQA at sites you own or have permission to test: its agents really submit forms.

## Team

Alok (dashboard, video, submission), Kabir Anand (swarm engine and web app), Gagana (fix-brain and demo app).
