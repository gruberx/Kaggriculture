"""T8.43 Stage 3b: re-sweep the dynamic hiring range - ADDITIVE variant.

Stage 3's first attempt (tools/measure_t843_stage3.py) lowered min_hires_
per_day (2, 4) to re-open the min==max==8 range T8.42 accidentally
collapsed - decisively rejected (8%/24% win rate, both far below the
shipped flat-8 baseline). That grid also showed weight=0.0 and weight=0.1
producing bit-identical W/L records at every seed - not a bug, but a real
finding: the workload forecast's own animal/crop-turn total (with or
without a small free-tile term) computes well below 8 most of the time,
so `min` clips it back up regardless of the weight - the forecast badly
undershoots real workload, confirming T8.34's own original finding on
this same mechanism (mistimed/undersized), not a fluke of this new regime.

This script tests a different, more literal reading of the user's actual
request instead: not "lower the floor" but "hire ABOVE the floor when a
new quadrant just opened with many free tiles" - additive, not reductive.
min_hires_per_day stays at its accepted 8; max_hires_per_day is *raised*
(12, 16) so the forecast has real room to push past 8 specifically when
free_tiles is large, with a real (not token) free_tile_weight (0.3, 1.0 -
the user's own literal formula treats free and occupied tiles equally,
not "small relative to 1.0" as the mechanism's own docstring assumed).

Not part of the committed test suite - a one-off tuning run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t843_stage3b_workdir"
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


def _point(max_hires_per_day: int, free_tile_weight: float) -> dict:
    return dict(
        DEFAULT_PARAMS,
        max_hires_per_day=max_hires_per_day,
        workload_forecast_free_tile_weight=free_tile_weight,
    )


GRID = [
    ("baseline (shipped: min=8=max, weight=0.0)", dict(DEFAULT_PARAMS)),
    ("max=12, weight=0.3", _point(12, 0.3)),
    ("max=16, weight=0.3", _point(16, 0.3)),
    ("max=12, weight=1.0 (the user's own literal formula)", _point(12, 1.0)),
    ("max=16, weight=1.0", _point(16, 1.0)),
]

_MEANINGFUL_THRESHOLD = 0.58

print(f"=== T8.43 Stage 3b: additive dynamic hiring grid on {len(WORKING_SEEDS)} working seeds ===")
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
