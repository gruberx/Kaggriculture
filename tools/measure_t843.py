"""T8.43 Stage 1: measure `defer_one_time_harvest_to_max_yield` - see
tasks/todo.md's T8.43 entry (folded in from
`/root/.claude/plans/jazzy-jumping-lamport.md`) for the full reasoning.

A real, previously-undiscovered ranking/task-layer inconsistency, not a
calibration question: strategy._crop_yield_and_tile_days already scores a
one-time crop assuming its full watering_bonus_window gets watered before
harvest (growth.forecast_one_time_yield), but tasks._is_actually_
harvestable has always proposed HARVEST the instant a crop is legally
harvestable, forfeiting that assumed bonus yield entirely for WHEAT/CARROT
(whose bonus windows start at/after first_yield_day - zero bonus days ever
realized). This script measures the fix in isolation, on top of T8.42's
now-shipped defaults (min_hires_per_day=8, land_purchase_threshold_
money=0).

Not part of the committed test suite - a one-off tuning run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t843_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
LARGE_SEEDS = list(range(900, 1100))

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)


def _even_baseline(n: int) -> harness.BlockResult:
    return harness.BlockResult(
        n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
        win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
    )


def evaluate(params: dict, seeds: list[int]) -> harness.BlockResult:
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    return harness.run_block(agent_path, baseline_agent, seeds, jobs=None)


CANDIDATE = dict(DEFAULT_PARAMS, defer_one_time_harvest_to_max_yield=True)

# Same "don't trust n=50 alone" threshold this project has used since
# T8.32's own noise-trap lesson.
_MEANINGFUL_THRESHOLD = 0.58

print(f"=== T8.43 Stage 1: defer_one_time_harvest_to_max_yield on {len(WORKING_SEEDS)} working seeds ===")
block = evaluate(CANDIDATE, WORKING_SEEDS)
accepted = tuning.accept_candidate(block, _even_baseline(block.n))
print(
    f"  candidate: win_rate={block.win_rate_a:.3f} "
    f"({block.wins_a}W/{block.wins_b}L/{block.ties}T) "
    f"interval={block.wilson_interval_a} accept_candidate={accepted}",
    flush=True,
)

if not (accepted or block.win_rate_a >= _MEANINGFUL_THRESHOLD):
    print("\nDoes not meaningfully beat baseline on the working block. Stopping here - null result.")
else:
    print(f"\n=== Confirmation on extended {len(LARGE_SEEDS)}-seed holdout ({LARGE_SEEDS[0]}-{LARGE_SEEDS[-1]}) ===")
    confirm_block = evaluate(CANDIDATE, LARGE_SEEDS)
    n = confirm_block.n
    stage_accepted = tuning.accept_candidate(confirm_block, _even_baseline(n))
    print(
        f"  confirm: win_rate={confirm_block.win_rate_a:.3f} "
        f"({confirm_block.wins_a}W/{confirm_block.wins_b}L/{confirm_block.ties}T) "
        f"interval={confirm_block.wilson_interval_a} accept_candidate={stage_accepted}",
        flush=True,
    )
    print(f"\nVerdict: {'ACCEPTED' if stage_accepted else 'REJECTED on holdout'}")
