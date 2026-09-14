"""T8.32 Stage 1: joint re-sweep of the land-purchase gate and the hiring
floor together, now that both labor (T8.29) and planting genuinely scale
and there's more work to justify labor (T8.31's always_pursue_one_animal).

T8.3/T8.8 tuned land_purchase_threshold_money/land_buy_max_free_tile_
fraction when the farm had only 1-2 labor units and genuinely could not
work even one 25-tile quadrant - tightening the gate won decisively back
then. T8.30 separately re-tested the hiring floor alone post-labor-fix
and it lost decisively - but that test never loosened the land gate at
the same time, so extra hands still had nowhere new to work. Neither
sweep has ever moved both knobs together. The user's own follow-up
hypothesis after seeing T8.30/T8.31's results: land alone can't help
without hands to work it, and hands alone can't help without land to put
them on - a comprehensive re-test needs to move both jointly, exactly as
SPEC-tuning.md prescribes for correlated knobs.

Not part of the committed test suite - a one-off tuning run.

**Prediction stated up front** (T8.3b): plausible win in the joint
region, genuinely uncertain in strength. Real risk: even jointly
loosened, hires_per_day's forecast (strategy.py's workload_forecast_
hiring_aware branch) still only reacts to tiles ALREADY planted, never
to free/potential land - so there may be a cold-start lag (land opens,
but the forecast doesn't ask for more hands until enough of it is
already planted by existing labor to show up in crop_tile_counts) that
limits how much this alone can close the gap to competitors' reported
3-4 quadrants/6-8 hands mid-game. If this measurement is null or mixed,
that motivates T8.32 Stage 2 (a land-aware hiring forecast, not built
here) rather than being a failure to route around.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t832_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

_baseline_agent_cache: dict[str, str] = {}


def _baseline_agent() -> str:
    if "path" not in _baseline_agent_cache:
        _baseline_agent_cache["path"] = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
    return _baseline_agent_cache["path"]


def evaluate(params: dict) -> harness.BlockResult:
    """Pure self-play against the checked-in baseline (T8.31's shipped
    default) - see this module's docstring for why joint, not
    independent, sweeping is the right test here."""
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    result = harness.run_block(agent_path, _baseline_agent(), WORKING_SEEDS, jobs=None)
    print(
        f"  eval threshold={params['land_purchase_threshold_money']} "
        f"fraction={params['land_buy_max_free_tile_fraction']} "
        f"min_hires={params['min_hires_per_day']}: "
        f"win_rate={result.win_rate_a:.3f} interval={result.wilson_interval_a}",
        flush=True,
    )
    return result


print("=== T8.32 Stage 1: joint sweep {land_purchase_threshold_money, "
      "land_buy_max_free_tile_fraction, min_hires_per_day} ===")
print("(baseline = checked-in DEFAULT_PARAMS, i.e. the T8.31 shipped defaults)")

BASE = dict(DEFAULT_PARAMS)

# Curated joint grid (not a full factorial), per SPEC-tuning.md's own
# guidance to check whether correlated knobs want to move together.
PARAM_GRID = {
    ("land_purchase_threshold_money", "land_buy_max_free_tile_fraction", "min_hires_per_day"): [
        (15000, 0.1, 2),   # shipped baseline (bit-identical starting point)
        (10000, 0.2, 2),   # loosen land only (T7.4's pre-T8.8 threshold, T8.3's pre-T8.8 fraction)
        (10000, 0.2, 3),   # loosen land + raise hiring floor together
        (10000, 0.2, 4),   # loosen land + raise hiring floor further
        (8000, 0.3, 4),    # aggressive joint loosening
        (12000, 0.15, 3),  # moderate joint middle ground
        (15000, 0.1, 4),   # hiring floor alone, land untouched - cross-check against T8.30's own result
    ],
}

best_params = tuning.coordinate_ascent(PARAM_GRID, evaluate, BASE)
best_key = (
    best_params["land_purchase_threshold_money"],
    best_params["land_buy_max_free_tile_fraction"],
    best_params["min_hires_per_day"],
)
print("\nWinner:", best_key)
if best_params == BASE:
    print("No joint change beat the shipped starting point beyond noise (working block).")

print("\n=== Held-out gate (self-play vs the checked-in baseline) ===")
candidate_agent = tuning.write_candidate_agent(best_params, WORKDIR)
holdout_block = harness.run_block(candidate_agent, _baseline_agent(), HOLDOUT_SEEDS, jobs=None)
print(
    f"  holdout vs baseline: win_rate={holdout_block.win_rate_a:.3f} "
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
