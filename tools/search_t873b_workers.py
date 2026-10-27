"""T8.73 stage 2 (exploratory, dev-only): follow-up to search_t873_
target5000.py's stage 1 - take the top herd-composition candidates for
the $5000-by-day-10 target and sweep worker count on top of each one.

Worker count is controlled via `min_hires_per_day`/`max_hires_per_day`:
strategy.hires_per_day's dynamic-hiring formula clips its workload-driven
target to `[min_hires_per_day, max_hires_per_day]` every day - setting
both to the same N forces the day-plan to target exactly N new hires/day
(subject to affordability and the existing turn/order caps), giving a
clean, single-knob way to sweep "more or fewer workers" without touching
the adaptive backlog logic itself.

Grid: STAGE1_TOP (10 herd configs, picked by stage 1's own
reach_rate-then-speed ranking) x WORKER_LEVELS (0,1,2,3,4,6,8) = 70 runs,
same $5000/10-day/full-100-seed/trajectory-capture measurement as stage 1
(reusing search_t873_target5000.evaluate_config's params_override hook).

IMPORTANT (carried over from stage 1's own caveat): `reach_rate`/
`total_turns` measure the FIRST time money crosses $5000, not whether it
stays there - the agent keeps spending on development afterward, so
`final_money_avg` at day 10 can end up well below $5000 even for a
100%-reach_rate config. Both numbers are reported; ranking is by speed,
but the final-money column should inform the actual recommendation.

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
OUT_PATH = os.path.join(WORKDIR, "t873_stage2_results.json")

STAGE1_TOP = [
    (0, 4), (0, 5), (1, 4), (2, 4), (1, 5),
    (3, 3), (1, 3), (2, 2), (3, 1), (3, 2),
]
WORKER_LEVELS = [0, 1, 2, 3, 4, 6, 8]


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
