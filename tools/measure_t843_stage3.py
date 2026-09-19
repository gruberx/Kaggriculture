"""T8.43 Stage 3: re-sweep the dynamic hiring range under T8.42's real
conditions - see tasks/todo.md's T8.43 entry (folded in from
`/root/.claude/plans/jazzy-jumping-lamport.md`) for the full reasoning.

**A real structural finding, not assumed going in**: T8.42 raised
min_hires_per_day 2 -> 8 but never touched max_hires_per_day (already
shipped at 8) - so today's shipped params have min_hires_per_day ==
max_hires_per_day == 8. strategy.hires_per_day's own clip,
`min(max(target, min_hires), max_hires)`, collapses to exactly 8 no
matter what the forecast computes - dynamic_hiring=True is currently
inert in practice, a flat 8 every single day regardless of workload.
This is exactly the user's own complaint (over-hired day 0, under-hired
once a new quadrant opens) - not a new problem, but a different, sharper
diagnosis than "re-test workload_forecast_free_tile_weight" alone: the
weight cannot matter at all while min==max clips every value to the same
number first. This script re-opens the range (lowering min_hires_per_day,
informed by T8.40's own real day-0 hand counts - see T8.42's entry) and
only then re-sweeps workload_forecast_free_tile_weight, since testing the
weight alone (unscoped, matching min==max) would just repeat a no-op.

T8.32/T8.34 both measured workload_forecast_free_tile_weight under the
old land_purchase_threshold_money=15000 regime and found it either
marginal (T8.32, 64% then 54.5% at n=200) or actively mistimed (T8.34,
reactive path). Neither ran under T8.42's now-shipped land/labor regime,
and neither ran with the min/max range actually open.

Not part of the committed test suite - a one-off tuning run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t843_stage3_workdir"
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


def _point(min_hires_per_day: int, free_tile_weight: float) -> dict:
    return dict(
        DEFAULT_PARAMS,
        min_hires_per_day=min_hires_per_day,
        workload_forecast_free_tile_weight=free_tile_weight,
    )


GRID = [
    ("baseline (shipped: min=8=max, weight=0.0 - currently inert)", dict(DEFAULT_PARAMS)),
    ("min=2, weight=0.0 (re-open the range alone)", _point(2, 0.0)),
    ("min=4, weight=0.0 (re-open the range alone)", _point(4, 0.0)),
    ("min=2, weight=0.1", _point(2, 0.1)),
    ("min=4, weight=0.1", _point(4, 0.1)),
]

_MEANINGFUL_THRESHOLD = 0.58

print(f"=== T8.43 Stage 3: dynamic hiring range grid on {len(WORKING_SEEDS)} working seeds ===")
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
