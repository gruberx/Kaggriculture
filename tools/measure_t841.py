"""T8.41 Stage A: the untested cell - more labor + more animals, with
both farmer-only scaling gaps already closed (animal_pickup_unpinned,
prioritize_animal_setup, plus T8.39's own feed_pickup_unpinned) - see
tasks/todo.md's T8.40 entry for the real-data motivation (top players
end the season with ~4.3x our money, driven by hands growing to 10 and
animals to 15 while we stay flat at 2/1 all season) and this task's own
plan (`/root/.claude/plans/jazzy-jumping-lamport.md`, folded into
tasks/todo.md on completion) for the full reasoning behind testing this
specific cell.

Every prior attempt to raise labor or animals in this project was tested
on the wrong cell (tasks/todo.md T8.22/T8.25/T8.27/T8.28/T8.32/T8.34/
T8.37/T8.39): hiring increases were always measured with at most 1
animal on the farm (extra hands had no animal work to do); animal-cap
increases were always measured at min_hires_per_day=2 flat (confirmed
directly against strategy.hires_per_day() - the shipped forecast's raw
pre-clip target is 0 at every realistic farm size, so it always clips to
min_hires_per_day). Several of those tasks explicitly named "once
max_animals_per_type is revisited with real labor" as their own
reopening condition and never ran that measurement. This script runs it,
with the two T8.41 Stage 0 flags on for every non-baseline candidate (a
farmer-only pin/priority-starvation bottleneck would confound a "more
labor + more animals" result if left in place - the user's own
reasoning during planning).

A small diagonal grid, not a full cross-product - "labor alone" and
"animals alone" were each already answered in isolation by the tasks
named above. Each non-baseline candidate = (min_hires_per_day,
max_animals_per_type) + feed_pickup_unpinned=True +
animal_pickup_unpinned=True + prioritize_animal_setup=True, informed by
T8.40's real medians (hands up to 10, animals up to 15 by top players).

**Prediction stated up front** (T8.3b): the baseline row (literally
DEFAULT_PARAMS evaluated against itself) should land near 50% - a
sanity check on the harness, not a real result. Among the real
candidates, expect win rate to first rise with more labor/animals (idle
capacity genuinely gets used once the scaling gaps are closed) and then
plateau or fall as either travel overhead or feed/watering saturation
starts to dominate - not a monotonically-best-is-largest result, which
would itself be suspicious and demand a trace before trusting it (T8.33's
own lesson).

Not part of the committed test suite - a one-off tuning run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t841_workdir"
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


def _bundle(min_hires_per_day: int, max_animals_per_type: int) -> dict:
    return dict(
        DEFAULT_PARAMS,
        min_hires_per_day=min_hires_per_day,
        max_animals_per_type=max_animals_per_type,
        feed_pickup_unpinned=True,
        animal_pickup_unpinned=True,
        prioritize_animal_setup=True,
    )


GRID = [
    ("baseline (shipped: 2, 1, no bundle - harness sanity check)", dict(DEFAULT_PARAMS)),
    ("(4, 2) + unpin + priority", _bundle(4, 2)),
    ("(6, 3) + unpin + priority", _bundle(6, 3)),
    ("(8, 4) + unpin + priority", _bundle(8, 4)),
]

print(f"=== T8.41 Stage A: diagonal grid on {len(WORKING_SEEDS)} working seeds ===")
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

accepted_candidates = [
    (name, params, block) for name, (params, block, accepted) in results.items()
    if accepted and name != GRID[0][0]
]

if not accepted_candidates:
    print("\nNo candidate clears accept_candidate on the working block. Stopping here - null result.")
else:
    best_name, best_params, best_block = max(accepted_candidates, key=lambda t: t[2].win_rate_a)
    print(f"\nBest working-block candidate: {best_name} (win_rate={best_block.win_rate_a:.3f})")
    print(f"\n=== Confirmation: {best_name} on extended {len(LARGE_SEEDS)}-seed holdout "
          f"({LARGE_SEEDS[0]}-{LARGE_SEEDS[-1]}) ===")
    confirm_block = evaluate(best_params, LARGE_SEEDS)
    n = confirm_block.n
    stage_a_accepted = tuning.accept_candidate(confirm_block, _even_baseline(n))
    print(
        f"  confirm: win_rate={confirm_block.win_rate_a:.3f} "
        f"({confirm_block.wins_a}W/{confirm_block.wins_b}L/{confirm_block.ties}T) "
        f"interval={confirm_block.wilson_interval_a} accept_candidate={stage_a_accepted}",
        flush=True,
    )
    print(f"\nStage A verdict: {'ACCEPTED' if stage_a_accepted else 'REJECTED on holdout'} - {best_name}")
