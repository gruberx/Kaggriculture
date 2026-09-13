"""T8.16(a) measurement: dynamic_hiring re-tested now that pending_task_
count excludes routine WATER/FEED (T8.12's own traced root cause) -
before the joint buffer/floor sweep (T8.16(b)/(d)), to see how much the
counting fix alone recovers.

Not part of the committed test suite - a one-off measurement run.

**Prediction stated up front**: a real improvement over T8.12's original
2/50 working, 4/50 holdout rejection, but not necessarily a clean win yet -
the counting fix addresses over-hiring, but nothing here yet gives hired
hands more *useful* work to do (that was T8.11/T8.15's job, and T8.15 is
being measured separately). A partial recovery here would still be
informative and consistent with the plan's own dependency chain.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t816a_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

CANDIDATES = {
    "dynamic_hiring (counting fix only, no buffer/floor changes)": dict(DEFAULT_PARAMS, dynamic_hiring=True),
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
