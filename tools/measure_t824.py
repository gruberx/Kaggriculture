"""T8.24: measure whether wheat_self_sufficiency_aware (growing WHEAT
domestically to avoid the buy-side feed-purchase price once real animal
feed demand exists - see kagg.policy.strategy.wheat_feed_credit_per_
tile_day) moves self-play win rate.

Not part of the committed test suite - a one-off measurement run.

Scope note: the plan originally deferred this measurement until T8.22
("lift the single-animal-type cap") landed, on the reasoning that a
single animal's feed demand is too small to matter. T8.22 was measured
and *decisively rejected* (tools/measure_t822.py) - max_animals_per_type
stays 1 in the shipped default, so multi-animal feed demand never
materializes there. This measures the scenario that's actually viable
instead: a single animal (animal_care_aware=True, T8.17's closest lead to
parity, 48%/56%) - real, continuous, whole-season feed demand even
without stacking.

Per T8.3b discipline, two separate comparisons, not confounded together:
1. wheat_self_sufficiency_aware alone against the T8.16(d) baseline - the
   flag with nothing to attach to (animals almost never get bought under
   default economics per T8.18's own null-result finding), predicted to
   be a near no-op.
2. animal_care_aware + wheat_self_sufficiency_aware against animal_care_
   aware alone - isolates the wheat credit's own marginal effect in the
   scenario where it can actually fire (a real animal is being pursued/
   placed most of the episode, per T8.23's own trace).

**Prediction stated up front**: genuinely uncertain, as the plan itself
said - WHEAT's own market is deep (T=400, flattest price-vs-inventory
curve of any product per direct price() trace) so the buy/sell delta a
single tile's small feed diversion produces is real but numerically
modest (tools/test_policy_strategy.py's own cross-check: a few dollars
per tile-day, not tens) - may show as a null result, a real and
informative outcome either way, not assumed to work.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t824_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)


def measure(label, candidate_params, baseline_params):
    print(f"=== {label} ===")
    baseline_agent = tuning.write_candidate_agent(baseline_params, WORKDIR)
    candidate_agent = tuning.write_candidate_agent(candidate_params, WORKDIR)
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


measure(
    "wheat_self_sufficiency_aware alone vs T8.16(d) baseline",
    dict(DEFAULT_PARAMS, wheat_self_sufficiency_aware=True),
    DEFAULT_PARAMS,
)
measure(
    "animal_care_aware + wheat_self_sufficiency_aware vs animal_care_aware alone",
    dict(DEFAULT_PARAMS, animal_care_aware=True, wheat_self_sufficiency_aware=True),
    dict(DEFAULT_PARAMS, animal_care_aware=True),
)
