"""T8.3q Part 2 measurement: animal_care_aware, isolated from
animal_fertilizer_income_aware (T8.3q Part 1, rejected separately). Direct
self-play against the checked-in baseline (which already has
animal_net_of_cost=True).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t83q_care_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_params = dict(DEFAULT_PARAMS, animal_care_aware=True)
candidate_agent = tuning.write_candidate_agent(candidate_params, WORKDIR)

print("=== animal_care_aware alone ===")
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
