"""T8.44: day-plan-driven dynamic hiring - a burst-day-aware alternative
to `workload_forecast_hiring_aware`, built from real per-tile-today action
counts (`kagg.policy.tasks.crop_tile_day_actions`/`animal_tile_day_
actions`) plus this turn's already-decided new planting/animal-acquisition,
instead of `_crop_actions_per_tile_day`'s lifetime-averaged rate. Direct
follow-up to T8.43 Stage 3's own mechanical proof that the old forecast's
`ceil(total_turns/24)-1` shape can never exceed 8 from a realistic board
(total_turns > 216 needed, unreachable).

`min_hires_per_day` is swept DOWN to (2, 4, 8) in this grid, not held at
the accepted 8 - the user's own explicit call (2026-09-19): "min_hires_
per_day думаю надо снизить до 2, потому что реальное значение должно
правильно определять наше новое решение, если оно не действует то скорее
надо править это чем заменять таким высоким минимальным порогом" - if the
new day-plan forecast is genuinely accurate, an 8-floor is itself a source
of waste on quiet days (this session's own hand calculation: steady-state
watering needs only ~2-3 workers, not 8). T8.43 Stage 3a's own catastrophic
result from lowering the floor (8%/24%) was measured *against the old,
broken* forecast - not necessarily indicative here.

`use_fertilizer` is left at its shipped `False` in every grid point - the
user's own explicit call: FERTILIZER is more valuable sold (real income,
potentially speeding up land purchase or funding hiring) than applied to
crops this early, a separate tradeoff this task must not quietly reopen.

Not part of the committed test suite - a one-off tuning run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

assert DEFAULT_PARAMS.get("use_fertilizer") is False  # never disturbed by this task

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t844_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
LARGE_SEEDS = list(range(900, 1100))

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)


def evaluate(params: dict, seeds: list[int]) -> harness.BlockResult:
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    return harness.run_block(agent_path, baseline_agent, seeds, jobs=None)


def _even_baseline(n: int) -> harness.BlockResult:
    return harness.BlockResult(
        n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
        win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
    )


def _point(
    min_hires_per_day: int = 2,
    max_hires_per_day: int = 12,
    day_plan_max_new_tiles_per_day: int = 25,
    hire_min_turns_left: int = 0,
    max_hire_orders_per_turn: int = 10,
) -> dict:
    return dict(
        DEFAULT_PARAMS,
        day_plan_hiring_aware=True,
        min_hires_per_day=min_hires_per_day,
        max_hires_per_day=max_hires_per_day,
        day_plan_max_new_tiles_per_day=day_plan_max_new_tiles_per_day,
        hire_min_turns_left=hire_min_turns_left,
        max_hire_orders_per_turn=max_hire_orders_per_turn,
    )


GRID = [
    ("baseline (shipped: workload_forecast, min=8=max)", dict(DEFAULT_PARAMS)),
    ("headline: min=2, max=12, cap=25", _point(min_hires_per_day=2)),
    ("min=4 (otherwise headline)", _point(min_hires_per_day=4)),
    ("min=8 (T8.42-accepted floor, otherwise headline)", _point(min_hires_per_day=8)),
    ("max=16 (otherwise headline)", _point(max_hires_per_day=16)),
    ("cap=8 (smaller new-tile-per-day cap, otherwise headline)", _point(day_plan_max_new_tiles_per_day=8)),
    ("hire_min_turns_left=6 (otherwise headline)", _point(hire_min_turns_left=6)),
    ("max_hire_orders_per_turn=6 (otherwise headline)", _point(max_hire_orders_per_turn=6)),
]

_MEANINGFUL_THRESHOLD = 0.58

print(f"=== T8.44: day-plan hiring grid on {len(WORKING_SEEDS)} working seeds ===")
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
