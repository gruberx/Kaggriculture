"""T8.73 stage 3 (exploratory, dev-only): extends stage 2's worker-count
sweep (search_t873b_workers.py) beyond WORKERS=8 - every top config there
kept improving up to the grid's own ceiling (8), so the user asked to
push further. Same 10 herd configs, same $5000/10-day/full-100-seed
measurement, WORKER_LEVELS = [10, 12, 16] only (8 and below already
measured in stage 2 - t873_stage2_results.json).

Verified before launching that WORKERS=16 is actually reachable: the
hiring loop in decide.py (`max_hire_orders_per_turn`, default 10) caps
orders per TURN, not per day - `hires_today` accumulates across a day's
24 turns toward `target_hires`, so a target above 10 just spreads the
hiring over 2 turns instead of blocking it.

Not part of the committed test suite.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

import search_t872_opening_start as s1  # noqa: E402
import search_t873_target5000 as s4  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = s1.WORKDIR
OUT_PATH = os.path.join(WORKDIR, "t873_stage3_results.json")

STAGE1_TOP = [
    (0, 4), (0, 5), (1, 4), (2, 4), (1, 5),
    (3, 3), (1, 3), (2, 2), (3, 1), (3, 2),
]
WORKER_LEVELS = [10, 12, 16]


if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds) + list(blocks.holdout_seeds)
    baseline_agent = s1.write_agent(DEFAULT_PARAMS, restrict_crops=False)

    results = []
    t0 = time.time()
    for cows, sheep in STAGE1_TOP:
        for n in WORKER_LEVELS:
            t1 = time.time()
            res = s4.evaluate_config(
                cows, sheep, seeds, baseline_agent,
                params_override={"min_hires_per_day": n, "max_hires_per_day": n},
            )
            res["workers"] = n
            dt = time.time() - t1
            results.append(res)
            tt = res["total_turns"]
            tt_str = f"{tt['min']}/{tt['avg']:.1f}/{tt['max']}" if tt else "n/a"
            print(
                f"COW={cows:2d} SHEEP={sheep:2d} WORKERS={n:2d}  reach_rate={res['reach_rate']:.3f} "
                f"({res['n_reached']}/{res['n_total']})  total_turns(min/avg/max)={tt_str}  "
                f"final_money_avg=${res['final_money_avg']:.0f}  occ_avg={res['final_occ_avg']:.1f}/25  [{dt:.1f}s]",
                flush=True,
            )
    print(f"\nTotal: {time.time() - t0:.1f}s for {len(results)} runs", flush=True)

    results.sort(
        key=lambda r: (
            -r["reach_rate"],
            r["total_turns"]["avg"] if r["total_turns"] else 9999,
        )
    )
    print("\n=== Top 20 by reach_rate then speed ===")
    for r in results[:20]:
        print(r)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results written to {OUT_PATH}")
