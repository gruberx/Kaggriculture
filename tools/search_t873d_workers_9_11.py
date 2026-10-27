"""T8.73 stage 4 (exploratory, dev-only): fills the gap the user noticed -
stages 2/3 jumped straight from WORKERS=8 to WORKERS=10 to WORKERS=12,
skipping 9 and 11, right around the newly-found optimum (WORKERS=10
clearly beat 8 for several configs; 12 was already past the peak for
most). Same 10 herd configs, same $5000/10-day/full-100-seed measurement.

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
OUT_PATH = os.path.join(WORKDIR, "t873_stage4_results.json")

STAGE1_TOP = [
    (0, 4), (0, 5), (1, 4), (2, 4), (1, 5),
    (3, 3), (1, 3), (2, 2), (3, 1), (3, 2),
]
WORKER_LEVELS = [9, 11]


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
