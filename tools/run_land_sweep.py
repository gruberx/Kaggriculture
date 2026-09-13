"""T8.8's re-sweep of land parameters (tasks/plan.md, /root/.claude/
plans/partitioned-puzzling-blossom.md) - now that labor actually works
(T8.4/T8.6/T8.7), the land-gating defaults accepted in Phase 7/T8.3
(land_purchase_threshold_money=10000, land_buy_max_free_tile_fraction=
0.25) were both fit to a one-unit farm, where land beyond the starting
25-tile quadrant was near-worthless (a single farmer can't productively
work even that much). T8.7 raised hires_per_day 0 -> 1, so this
re-checks whether either value is now stale.

hires_per_day itself is NOT re-opened here - T8.7 already closed that
question decisively (accepted at 1, held-out-gated). This sweep holds it
fixed at the checked-in default and only searches the land-gating
surface.

Direct self-play only against the checked-in T8.7 baseline - never
evaluate_against_panel, per T7.4's own documented pitfall.

Not part of the committed test suite - a real tuning run, re-executed
whenever a future round wants to revisit these two parameters.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_land_sweep_workdir"
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
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    result = harness.run_block(agent_path, _baseline_agent(), WORKING_SEEDS, jobs=None)
    print(
        f"  eval threshold={params['land_purchase_threshold_money']} "
        f"fraction={params['land_buy_max_free_tile_fraction']}: "
        f"win_rate={result.win_rate_a:.3f} interval={result.wilson_interval_a}"
    )
    return result


print("=== T8.8: land_purchase_threshold_money x land_buy_max_free_tile_fraction ===")
print(
    "hires_per_day held fixed at the T8.7-accepted default - not re-opened here. "
    "Both land params suspected stale (fit to a 1-unit farm)."
)

PARAM_GRID = {
    ("land_purchase_threshold_money",): [(2000,), (5000,), (7000,), (10000,), (15000,), (20000,)],
    ("land_buy_max_free_tile_fraction",): [(0.1,), (0.25,), (0.4,), (0.6,), (0.8,), (1.0,)],
}

best_params = tuning.coordinate_ascent(PARAM_GRID, evaluate, dict(DEFAULT_PARAMS))
print(
    "\nWorking-block winner:",
    {k: best_params[k] for k in ("land_purchase_threshold_money", "land_buy_max_free_tile_fraction")},
)

if best_params == dict(DEFAULT_PARAMS):
    print("No change from baseline - coordinate_ascent found nothing better beyond noise.")
    sys.exit(0)

print("\n=== Held-out gate (self-play vs the T8.7 baseline) ===")
candidate_agent = tuning.write_candidate_agent(best_params, WORKDIR)
holdout_block = harness.run_block(candidate_agent, _baseline_agent(), HOLDOUT_SEEDS, jobs=None)
n = holdout_block.n
even_baseline = harness.BlockResult(
    n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
    win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
)
accepted = tuning.accept_candidate(holdout_block, even_baseline)
print(f"held-out self-play: win_rate={holdout_block.win_rate_a:.3f} interval={holdout_block.wilson_interval_a}")
print(f"accept_candidate (vs even-odds at n={n}): {accepted}")

if accepted:
    print("\n=== Non-regression sanity check vs starter/random (reporting only, not the decision) ===")
    panel_result = tuning.evaluate_against_panel(
        candidate_agent, ["starter", "random"], HOLDOUT_SEEDS[:10], WORKDIR, jobs=None
    )
    print(f"vs starter+random (10 holdout seeds): win_rate={panel_result.win_rate_a:.3f}")
