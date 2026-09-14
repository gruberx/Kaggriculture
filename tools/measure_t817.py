"""T8.17: re-measure whether COW/SHEEP are genuinely profitable, now that
T8.14 (investment-choice hysteresis fix), T8.15 (softer watering-priority
tier), and T8.16(d) (a real, swept day-1 hiring floor - dynamic_hiring=
True, min_hires_per_day=2, now the checked-in default) are all in place.
This is the task that actually answers the session's opening question -
every earlier measurement of these three animal-economics flags
(T8.3q's fertilizer/CARE, this session's own T8.10) was contaminated by
one of those three architectural bugs, unrelated to animal economics
itself.

Not part of the committed test suite - a one-off measurement run.

Per T8.3b discipline: each flag alone first, against the new checked-in
baseline (DEFAULT_PARAMS now carries T8.16(d)'s accepted defaults), then
all three combined - not skipping straight to "all together."

**Predictions stated up front**:
1. animal_consumption_horizon_aware (T8.10) alone: the real open question
   is whether T8.16(d)'s labor floor alone already gives animals enough
   care to stop the score from being a razor-thin, flip-prone lead over
   the best crop - if the hysteresis symptom recurs, investment_commit_
   margin (T8.14, still 0.0 by default) is the documented fix to combine
   with it, tested as a follow-up in that case.
2. animal_fertilizer_income_aware (T8.3q Part 1) alone: predicted to
   have a real shot now that labor genuinely scales - T8.3q's original
   rejection blamed a single farmer being unable to execute FEED+CARE+
   COLLECT_FERTILIZER+HARVEST (~4 actions/day) for one animal, which is
   exactly the labor constraint T8.16(d) relaxes.
3. animal_care_aware (T8.3q Part 2) alone: same prediction as #2, same
   underlying labor-constraint story.
4. All three combined: the actual "full-care COW/SHEEP" scenario
   SPEC.md's own profitability table named as the theoretical ceiling
   ($215/$275 per tile-day) - genuinely uncertain whether real, labor-
   constrained self-play captures much of that ceiling even with the
   architectural blockers gone.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t817_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

CANDIDATES = {
    "animal_consumption_horizon_aware alone": dict(DEFAULT_PARAMS, animal_consumption_horizon_aware=True),
    "animal_fertilizer_income_aware alone": dict(DEFAULT_PARAMS, animal_fertilizer_income_aware=True),
    "animal_care_aware alone": dict(DEFAULT_PARAMS, animal_care_aware=True),
    "all three combined": dict(
        DEFAULT_PARAMS,
        animal_consumption_horizon_aware=True,
        animal_fertilizer_income_aware=True,
        animal_care_aware=True,
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
