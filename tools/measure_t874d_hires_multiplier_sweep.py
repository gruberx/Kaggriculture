"""T8.74 follow-up (exploratory, dev-only): the user wants to know how
today's shipped agent's own final (day-29, whole-season) money responds
to a FIXED worker count (min_hires_per_day == max_hires_per_day == N),
applied for the whole game (unlike quadrant1_hire_target, which only
applies while quadrant 1 is the only unlocked quadrant) - for
N in 7..14, against today's shipped (unmodified, adaptive min=2/max=12)
baseline, full 30-day season, both seed blocks x both seatings (200
episodes per N).

Not part of the committed test suite.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd874_mult_sweep")
os.makedirs(WORKDIR, exist_ok=True)
OUT_PATH = os.path.join(WORKDIR, "results.json")

WORKER_LEVELS = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8]

if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds) + list(blocks.holdout_seeds)
    baseline_dir = os.path.join(WORKDIR, "baseline")
    os.makedirs(baseline_dir, exist_ok=True)
    baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, baseline_dir)

    results = []
    t0 = time.time()
    for n in WORKER_LEVELS:
        t1 = time.time()
        cand_dir = os.path.join(WORKDIR, f"m{n}")
        os.makedirs(cand_dir, exist_ok=True)
        cand_params = dict(DEFAULT_PARAMS, hires_multiplier=n)
        cand_agent = tuning.write_candidate_agent(cand_params, cand_dir)

        block = harness.run_block(cand_agent, baseline_agent, seeds)
        # a_total_money is summed across both seatings of a seed (SPEC-harness.md
        # requirement 1) - halve it back to a per-episode average final money.
        final_moneys = [pr.a_total_money / 2 for pr in block.paired_results]
        avg_final = sum(final_moneys) / len(final_moneys)
        min_final = min(final_moneys)
        max_final = max(final_moneys)
        dt = time.time() - t1
        results.append({
            "multiplier": n,
            "win_rate_a": block.win_rate_a,
            "wins_a": block.wins_a,
            "wins_b": block.wins_b,
            "ties": block.ties,
            "n": block.n,
            "avg_final_money": avg_final,
            "min_final_money": min_final,
            "max_final_money": max_final,
        })
        print(
            f"MULT={n:.1f}  win_rate={block.win_rate_a:.3f} ({block.wins_a}W/{block.wins_b}L/{block.ties}T)  "
            f"final_money(min/avg/max)=${min_final:.0f}/${avg_final:.0f}/${max_final:.0f}  [{dt:.1f}s]",
            flush=True,
        )
    print(f"\nTotal: {time.time() - t0:.1f}s", flush=True)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Full results written to {OUT_PATH}")
