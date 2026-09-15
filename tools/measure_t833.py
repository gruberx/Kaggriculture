"""T8.33 Stage 1: sweep land_purchase_threshold_money downward from the
shipped 15000, alone and then paired with land_buy_max_free_tile_fraction.

User's own observation, confirmed from source this session (see
tasks/todo.md's T8.33 entry and the plan this script implements):
land_purchase_threshold_money=15000 means the farm must hold $16,000 to
buy a $1,000 quadrant, while starting money is only $3,000 and realistic
daily burn (hands + seeds + occasional animals/wheat) is $100-900/day
against mid-season balances of $20k-37k. Land is last in decide.py's
spend tail, so it can never outbid seeds/animals within a turn - the
threshold is acting as a general cash floor, which none of the purpose-
built reserves (seed_cash_reserve, hire_cash_reserve) do since both ship
at 0. T7.4 and T8.8 both swept low thresholds and both times the ascent
moved upward, but neither ever recorded a per-value win rate, and both
ran on code superseded by T8.29's labor fix and T8.31's
always_pursue_one_animal - this is the first sweep of these values with
an isolated, recorded win rate on current code.

Two axes, per SPEC-tuning.md's guidance on correlated knobs:

  Axis A: land_purchase_threshold_money alone, land_buy_max_free_tile_
  fraction left at its shipped 0.1. Tests the reserve in isolation.

  Axis B: the best two Axis A values, each paired with
  land_buy_max_free_tile_fraction in {0.1, 0.2}. Necessary because
  should_buy_land's money gate is a hard AND evaluated *before* the
  occupancy gate (strategy.py:1020-1030) - a loosened reserve can be
  entirely masked by the strict 0.1 fraction gate refusing to buy even
  when cash is plentiful.

Both axes print every candidate's own working-block (50 tuning seeds)
win rate against the checked-in baseline - unlike prior sweeps of this
parameter, this script does not rely on coordinate_ascent's convergence
alone, specifically so every value's win rate ends up recorded in the
log (tasks/todo.md's T8.33 entry complains this was never done before).
The single best combination across both axes is then confirmed once on
the extended 200-seed holdout (range(900, 1100), per the T8.32 addendum's
lesson that n=50 is noisy - 64% at n=50 became 54.5% at n=200 there).

Not part of the committed test suite - a one-off tuning run.

**Prediction stated up front** (T8.3b): directionally plausible but
genuinely uncertain, and explicitly against two prior measured results -
low thresholds lost in both T7.4 and T8.8. The case for retrying is that
both ran under labor regimes two later fixes (T8.29, T8.31) removed, and
that $15k is ~15x the first quadrant's price against a $100-900/day burn
with land already last in the spend queue. Honest risk: the threshold
may be functioning as a useful "don't expand until production is
proven" brake, in which case lowering it loses again here too - that
would be a real, honestly-recorded null result, not a failure to route
around.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t833_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)

# Same disjoint, never-before-used 200-seed range as measure_t832_large_n.py,
# for the single confirmation run - keeps this script's holdout comparable
# with that earlier large-n lesson rather than inventing a new convention.
LARGE_SEEDS = list(range(900, 1100))

_baseline_agent_cache: dict[str, str] = {}


def _baseline_agent() -> str:
    if "path" not in _baseline_agent_cache:
        _baseline_agent_cache["path"] = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
    return _baseline_agent_cache["path"]


def _even_baseline(n: int) -> harness.BlockResult:
    return harness.BlockResult(
        n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
        win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
    )


def evaluate(params: dict, seeds: list[int]) -> harness.BlockResult:
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    return harness.run_block(agent_path, _baseline_agent(), seeds, jobs=None)


results: dict[tuple, harness.BlockResult] = {}

print("=== T8.33 Stage 1, Axis A: land_purchase_threshold_money alone "
      "(land_buy_max_free_tile_fraction left at shipped 0.1) ===")
print("(baseline = checked-in DEFAULT_PARAMS, threshold=15000)")

AXIS_A_VALUES = [0, 1000, 2000, 3000, 5000, 7500, 10000]

for threshold in AXIS_A_VALUES:
    params = dict(DEFAULT_PARAMS, land_purchase_threshold_money=threshold)
    block = evaluate(params, WORKING_SEEDS)
    results[(threshold, DEFAULT_PARAMS["land_buy_max_free_tile_fraction"])] = block
    accepted = tuning.accept_candidate(block, _even_baseline(block.n))
    print(
        f"  threshold={threshold:>6}: win_rate={block.win_rate_a:.3f} "
        f"({block.wins_a}W/{block.wins_b}L/{block.ties}T) "
        f"interval={block.wilson_interval_a} accept_candidate={accepted}",
        flush=True,
    )

axis_a_ranked = sorted(
    ((t, f) for (t, f) in results if f == DEFAULT_PARAMS["land_buy_max_free_tile_fraction"]),
    key=lambda key: results[key].win_rate_a,
    reverse=True,
)
top_two_thresholds = [t for (t, _f) in axis_a_ranked[:2]]
print(f"\nAxis A top two thresholds by working win_rate: {top_two_thresholds}\n")

print("=== T8.33 Stage 1, Axis B: top-two thresholds x "
      "land_buy_max_free_tile_fraction in {0.1, 0.2} ===")

FRACTIONS = [0.1, 0.2]

for threshold in top_two_thresholds:
    for fraction in FRACTIONS:
        key = (threshold, fraction)
        if key in results:
            continue  # already measured in Axis A (fraction=0.1 case)
        params = dict(
            DEFAULT_PARAMS,
            land_purchase_threshold_money=threshold,
            land_buy_max_free_tile_fraction=fraction,
        )
        block = evaluate(params, WORKING_SEEDS)
        results[key] = block
        accepted = tuning.accept_candidate(block, _even_baseline(block.n))
        print(
            f"  threshold={threshold:>6} fraction={fraction}: win_rate={block.win_rate_a:.3f} "
            f"({block.wins_a}W/{block.wins_b}L/{block.ties}T) "
            f"interval={block.wilson_interval_a} accept_candidate={accepted}",
            flush=True,
        )

best_key = max(results, key=lambda key: results[key].win_rate_a)
best_block = results[best_key]
print(f"\nBest combination across both axes: threshold={best_key[0]}, fraction={best_key[1]} "
      f"(working win_rate={best_block.win_rate_a:.3f})")

if best_key == (DEFAULT_PARAMS["land_purchase_threshold_money"], DEFAULT_PARAMS["land_buy_max_free_tile_fraction"]):
    print("No swept combination beat the shipped baseline on the working block. Stopping here - "
          "no confirmation run needed, Stage 1 result is null.")
else:
    print(f"\n=== Confirmation: threshold={best_key[0]}, fraction={best_key[1]} "
          f"on extended {len(LARGE_SEEDS)}-seed holdout ({LARGE_SEEDS[0]}-{LARGE_SEEDS[-1]}) ===")
    best_params = dict(
        DEFAULT_PARAMS,
        land_purchase_threshold_money=best_key[0],
        land_buy_max_free_tile_fraction=best_key[1],
    )
    confirm_block = evaluate(best_params, LARGE_SEEDS)
    n = confirm_block.n
    print(
        f"  confirm: win_rate={confirm_block.win_rate_a:.3f} "
        f"({confirm_block.wins_a}W/{confirm_block.wins_b}L/{confirm_block.ties}T) "
        f"interval={confirm_block.wilson_interval_a}",
        flush=True,
    )
    print(f"  even-odds baseline interval at n={n}: {_even_baseline(n).wilson_interval_a}")
    accepted = tuning.accept_candidate(confirm_block, _even_baseline(n))
    print(f"  accept_candidate (vs even-odds at n={n}): {accepted}", flush=True)
