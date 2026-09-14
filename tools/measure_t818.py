"""T8.18 measurement: parallel_animal_acquisition - verified directly
against kaggriculture.py that PICKUP has no structural prerequisite, so
BUILD_* and PICKUP can fire the same turn instead of the shipped serial
if/elif chain (BUILD -> PICKUP -> PLACE, up to 3 sequential turns even
when 2+ labor units are free). This only matters once a second labor
unit actually exists (Stage B's hires_per_day/dynamic_hiring) - at the
historical hires_per_day=0 default there's only ever one unit anyway, so
this is measured against a baseline with a real second hand present.

Not part of the committed test suite - a one-off measurement run.

**Prediction stated up front**: a real, if modest, improvement whenever
hires_per_day/dynamic_hiring gives a second unit spare capacity right as
an animal acquisition is in flight - compresses the pipeline from up to
3 sequential turns to 2. Expected to be a small effect on overall win
rate (animal acquisition is a rare, one-time event per episode, not a
recurring cost), so this is checked at a real, generous alpha
(accept_candidate's Wilson-interval gate) rather than assumed - a null
result here is plausible and would just mean the effect is too small
relative to noise to matter on its own, not that the mechanism is wrong.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t818_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

# A real second hand present (hires_per_day=2) so the parallelization has
# something to bite on - at hires_per_day=0/1 there's rarely a free
# second unit at the exact moment BUILD_*/PICKUP are both actionable.
BASE = dict(DEFAULT_PARAMS, hires_per_day=2)

baseline_agent = tuning.write_candidate_agent(BASE, WORKDIR)

CANDIDATES = {
    "parallel_animal_acquisition (hires_per_day=2 base)": dict(BASE, parallel_animal_acquisition=True),
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
