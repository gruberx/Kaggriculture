"""T8.43 Stage 2: measure `always_pursue_animal_target_count` - see
tasks/todo.md's T8.43 entry (folded in from
`/root/.claude/plans/jazzy-jumping-lamport.md`) for the full reasoning.

A real, previously-undiscovered mechanism gap, not a ranking-strength
question: always_pursue_one_animal's own gate was a one-shot trigger -
"not placed_animal_type_counts" permanently disables itself the instant
*any* animal exists anywhere, of any type - which is the actual reason
max_animals_per_type has never once bound in any measurement this project
has run (T8.41 traced animals_total stuck at exactly 1 regardless of the
cap's value). This script measures the generalized mechanism (target_count
> 1, diversifying across animal types once earlier ones hit their own
max_animals_per_type cap) on top of T8.42's now-shipped defaults.

Not part of the committed test suite - a one-off tuning run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t843_stage2_workdir"
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


def _point(target_count: int, max_animals_per_type: int = 1) -> dict:
    return dict(
        DEFAULT_PARAMS,
        always_pursue_animal_target_count=target_count,
        max_animals_per_type=max_animals_per_type,
    )


GRID = [
    ("baseline (shipped: target_count=1)", dict(DEFAULT_PARAMS)),
    ("target_count=2, cap=1 (diversify to 2 types)", _point(2, 1)),
    ("target_count=3, cap=1 (diversify to 3 types)", _point(3, 1)),
    ("target_count=2, cap=2 (up to 2 of the same type)", _point(2, 2)),
]

_MEANINGFUL_THRESHOLD = 0.58

print(f"=== T8.43 Stage 2: always_pursue_animal_target_count grid on {len(WORKING_SEEDS)} working seeds ===")
results: dict[str, tuple[dict, harness.BlockResult, bool]] = {}
for name, params in GRID:
    block = evaluate(params, WORKING_SEEDS)
    accepted = tuning.accept_candidate(block, _even_baseline(block.n))
    print(
        f"  {name}: win_rate={block.win_rate_a:.3f} "
        f"({block.wins_a}W/{block.wins_b}L/{block.ties}T) "
        f"interval={block.wilson_interval_a} accept_candidate={accepted}",
        flush=True,
    )
    results[name] = (params, block, accepted)

worth_confirming = [
    (name, params, block) for name, (params, block, accepted) in results.items()
    if name != GRID[0][0] and (accepted or block.win_rate_a >= _MEANINGFUL_THRESHOLD)
]

if not worth_confirming:
    print("\nNo candidate meaningfully beats baseline on the working block. Stopping here - null result.")
else:
    best_name, best_params, best_block = max(worth_confirming, key=lambda t: t[2].win_rate_a)
    print(f"\nBest working-block candidate worth confirming: {best_name} (win_rate={best_block.win_rate_a:.3f})")
    print(f"\n=== Confirmation: {best_name} on extended {len(LARGE_SEEDS)}-seed holdout "
          f"({LARGE_SEEDS[0]}-{LARGE_SEEDS[-1]}) ===")
    confirm_block = evaluate(best_params, LARGE_SEEDS)
    n = confirm_block.n
    stage_accepted = tuning.accept_candidate(confirm_block, _even_baseline(n))
    print(
        f"  confirm: win_rate={confirm_block.win_rate_a:.3f} "
        f"({confirm_block.wins_a}W/{confirm_block.wins_b}L/{confirm_block.ties}T) "
        f"interval={confirm_block.wilson_interval_a} accept_candidate={stage_accepted}",
        flush=True,
    )
    print(f"\nVerdict: {'ACCEPTED' if stage_accepted else 'REJECTED on holdout'} - {best_name}")
