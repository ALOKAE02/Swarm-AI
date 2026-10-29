"""Run the swarm N times against the bench app and report average catch rate.

    python bench/server.py                      # in another terminal
    python bench/run_bench.py --runs 3 --steps 25 --no-llm
    python bench/run_bench.py --runs 1 --steps 25            # with Nemotron Nano
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(HERE))
from score import score  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8790/")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--agents", type=int, default=4)
    ap.add_argument("--steps", type=int, default=25)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--out-dir", default=str(ENGINE / "bench_out"))
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(exist_ok=True)
    rows = []
    for i in range(1, a.runs + 1):
        f = out / f"findings_{i}.jsonl"
        cmd = [sys.executable, str(ENGINE / "swarm.py"), a.url, "--agents", str(a.agents), "--steps",
               str(a.steps), "--seed", str(i), "--fresh", "--out", str(f), "--events", str(out / f"events_{i}.jsonl"),
               "--summary", str(out / f"summary_{i}.json"), "--shots", str(out / "shots")]
        if a.no_llm:
            cmd.append("--no-llm")
        subprocess.run(cmd, cwd=ENGINE, check=False, stdout=subprocess.DEVNULL)
        with redirect_stdout(io.StringIO()):
            r = score(str(f))
        s = json.loads((out / f"summary_{i}.json").read_text())
        rows.append({**r, "seconds": s["seconds"], "actions": s["actions"]})
        print(f"run {i}: {r['caught']}/{r['total']} planted caught, +{r['extra']} unplanted real, "
              f"{r['noise']} noise, {s['actions']} actions in {s['seconds']}s")
    n = len(rows)
    print(f"\nAverage over {n} runs: {sum(r['caught'] for r in rows) / n:.1f}/{rows[0]['total']} planted caught, "
          f"{sum(r['extra'] for r in rows) / n:.1f} unplanted real, "
          f"{sum(r['noise'] for r in rows) / n:.1f} noise, {sum(r['seconds'] for r in rows) / n:.1f}s per run")


if __name__ == "__main__":
    main()
