"""T8.21: measure whether closing the `care_aware`/`consumption_horizon_
aware` no-op gap (strategy.py's new `_animal_full_care_schedule`, walked
lockstep by `animal_revenue_per_tile_day` when both flags are set) moves
the near-parity T8.17 result (`animal_care_aware` alone: 48%/56%) toward
a real win - or just narrows variance around the same ~50% mean.

Not part of the committed test suite - a one-off measurement run.

Per T8.3b discipline: each flag alone first, against the checked-in
T8.16(d) baseline (DEFAULT_PARAMS), then combinations - not skipping
straight to "all together."

**Predictions stated up front**:
1. animal_consumption_horizon_aware alone: unrelated to this change (the
   non-care_aware branch's code path is untouched) - expected to
   reproduce T8.17's own 0/50, 0/50 exactly, a sanity check that the
   refactor didn't leak into the untouched branch.
2. animal_care_aware + animal_consumption_horizon_aware together: this is
   the actual new behavior - predicted to help specifically in games
   where a relevant shop opens (the unit-economics analysis script's own
   "expected end-game" scenario showed COW/SHEEP beating even contested
   MELON by a wide margin there), genuinely uncertain whether it clears
   the held-out gate or just narrows the variance around T8.17's ~50%
   mean for animal_care_aware alone.
3. All three (+animal_fertilizer_income_aware), re-running T8.17's own
   three-flag combination on the new code: the "full care" scenario the
   unit-economics analysis found most competitive.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t821_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

CANDIDATES = {
    "animal_consumption_horizon_aware alone (sanity check, unrelated to T8.21)": dict(
        DEFAULT_PARAMS, animal_consumption_horizon_aware=True,
    ),
    "animal_care_aware + animal_consumption_horizon_aware (T8.21's new combination)": dict(
        DEFAULT_PARAMS, animal_care_aware=True, animal_consumption_horizon_aware=True,
    ),
    "all three (+ animal_fertilizer_income_aware)": dict(
        DEFAULT_PARAMS,
        animal_care_aware=True,
        animal_consumption_horizon_aware=True,
        animal_fertilizer_income_aware=True,
    ),
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
