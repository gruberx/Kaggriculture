"""T8.22: measure whether lifting the single-animal-type cap
(`max_animals_per_type`, T8.22) is actually worth it once the farm's labor
force genuinely supports a second animal (T8.16(d)'s day-1 hiring floor),
under the "full care" animal-economics scenario the unit-economics
analysis (tools/analyze_unit_economics.py) found most competitive.

Not part of the committed test suite - a one-off measurement run.

Per T8.3b discipline: sweep the cap (2, 3, 4) against the T8.16(d)
baseline, with animal_care_aware/animal_fertilizer_income_aware on (T8.17's
"full care" combination, the closest lead to parity so far) and
parallel_animal_acquisition=True (T8.18, built for exactly this multi-
animal scenario). NOT combined with T8.21's new consumption_horizon_aware
walk - that combination was measured and rejected on its own merits
(tools/measure_t821.py), so stacking it here would confound the two
questions.

**Predictions stated up front**: genuinely uncertain. A second COW/SHEEP
doubles the fully-cared animal's own steady-state revenue at the cost of
roughly doubling its FEED/CARE/COLLECT_FERTILIZER/HARVEST labor demand -
whether the farm's real hired labor (min_hires_per_day=2 by default) can
actually execute that without starving crop tiles is exactly the T8.3q-
style failure mode to watch for in the trace step below, not something to
assume from the unit-economics analysis's own labor-unconstrained ceiling.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t822_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

BASE_FULL_CARE = dict(
    DEFAULT_PARAMS,
    animal_care_aware=True,
    animal_fertilizer_income_aware=True,
    parallel_animal_acquisition=True,
)

CANDIDATES = {
    f"max_animals_per_type={cap} (full care + parallel acquisition)": dict(
        BASE_FULL_CARE, max_animals_per_type=cap,
    )
    for cap in (2, 3, 4)
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
