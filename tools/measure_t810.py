"""T8.10 measurement: animal_consumption_horizon_aware, measured alone
against the checked-in baseline - per T8.3b's lesson, a single isolated
mechanism, no bundling with anything else this task didn't touch.

Not part of the committed test suite - a one-off measurement run, like
tools/measure_t83m.py. Direct self-play against the checked-in baseline
(params.DEFAULT_PARAMS with the new flag off) - never starter/random
dilution (SPEC-tuning.md's own T7.4 lesson).

**Prediction stated up front, per this project's own established
discipline (T8.7's pattern)**: a clear, low-risk win. This is a pure
formula correction - each animal-product unit is now priced at its own
production day's drained market level instead of one flat one-interval
offset, exactly mirroring what crop_revenue_per_tile_day already does for
crops (T8.3f/T8.3i). It costs the farmer zero extra actions (no new task,
no new turn spent) - it only changes which investment `_top_investment_
choice` picks, never how many turns are available to execute it. A loss
here would be genuinely surprising and worth understanding, not brushed
off.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t810_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

CANDIDATES = {
    "animal_consumption_horizon_aware": dict(DEFAULT_PARAMS, animal_consumption_horizon_aware=True),
}

for label, params in CANDIDATES.items():
    print(f"=== {label} ===")
    candidate_agent = tuning.write_candidate_agent(params, WORKDIR)
    working_block = harness.run_block(candidate_agent, baseline_agent, WORKING_SEEDS, jobs=None)
    print(
        f"  working: win_rate={working_block.win_rate_a:.3f} "
        f"({working_block.wins_a}W/{working_block.wins_b}L/{working_block.ties}T) "
        f"interval={working_block.wilson_interval_a}"
    )
    holdout_block = harness.run_block(candidate_agent, baseline_agent, HOLDOUT_SEEDS, jobs=None)
    print(
        f"  holdout: win_rate={holdout_block.win_rate_a:.3f} "
        f"({holdout_block.wins_a}W/{holdout_block.wins_b}L/{holdout_block.ties}T) "
        f"interval={holdout_block.wilson_interval_a}"
    )
    n = holdout_block.n
    even_baseline = harness.BlockResult(
        n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
        win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
    )
    accepted = tuning.accept_candidate(holdout_block, even_baseline)
    print(f"  accept_candidate (vs even-odds at n={n}): {accepted}")
    print()
