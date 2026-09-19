"""T8.42: a real-data-calibrated joint (min_hires_per_day,
land_purchase_threshold_money) resweep - see tasks/todo.md's T8.42 entry
(folded in from `/root/.claude/plans/jazzy-jumping-lamport.md`) for the
full reasoning.

T8.40's already-saved real-leaderboard extract (`data/top_replay_records/`)
shows top players buy their 2nd quadrant leaving essentially zero cash
reserve (several team-seasons as low as $1-$88 right after the purchase)
and hire far more aggressively from day 0 than anything tested before
(hands_max median 4 on day 0, 6 by day 2, 8 by day 6, 10 by day 9) - both
far more extreme than any prior sweep in this project.

T8.32 already found a joint (min_hires_per_day=4, land_purchase_threshold_
money=10000, land_buy_max_free_tile_fraction=0.2) scoring 64% at n=50 but
regressing to 54.5% (accept_candidate=False) at n=200 - "a real,
promising, well-evidenced direction... worth a wider grid search or a
larger held-out sample." T8.33 (land alone) and T8.34 (labor alone, via a
reactive signal T8.34 itself found mistimed) were both decisively
rejected. This script pushes both axes further, calibrated to the real
numbers, and - per T8.32's own explicit "n=50 noise" lesson - treats any
working-block result that meaningfully beats baseline (not only a strict
accept_candidate pass) as requiring an n=200 confirmation before any
conclusion is drawn.

**Prediction stated up front** (T8.3b): if this project's land+labor
co-optimization hypothesis is real, pushing both levers further toward
the real-data-calibrated extreme should clear the working block more
decisively than T8.32's own 64%-then-54.5% shape - not just repeat it. A
similarly marginal result here would be a second, independent data point
confirming the effect is real but too weak to accept, not a fluke.

Not part of the committed test suite - a one-off tuning run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t842_workdir"
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


def _point(min_hires_per_day: int, land_purchase_threshold_money: int) -> dict:
    return dict(
        DEFAULT_PARAMS,
        min_hires_per_day=min_hires_per_day,
        land_purchase_threshold_money=land_purchase_threshold_money,
    )


GRID = [
    ("baseline (shipped: 2, 15000)", dict(DEFAULT_PARAMS)),
    ("(4, 10000) - T8.32's own point, re-confirmed", _point(4, 10000)),
    ("(6, 2000)", _point(6, 2000)),
    ("(8, 0) - saturates max_hires_per_day, near-zero reserve", _point(8, 0)),
]

# A working-block win rate at or above this (well short of T8.32's own
# 64%, but clearly not noise-flat either) is treated as "meaningfully
# beats baseline" and triggers an immediate n=200 confirmation, per the
# plan's own anti-noise-trap discipline - not gated behind a strict
# accept_candidate pass at n=50 alone.
_MEANINGFUL_THRESHOLD = 0.58

print(f"=== T8.42: diagonal grid on {len(WORKING_SEEDS)} working seeds ===")
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
