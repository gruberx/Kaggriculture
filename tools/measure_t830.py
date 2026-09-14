"""T8.30: re-sweep the hiring-floor knobs now that labor_units genuinely
scales with hires_per_day's real forecast (T8.29 fixed the bare
hires_per_day(params) call at labor_units's own call site - see
kagg.policy.decide's T8.29 comment).

T8.28's own sweep of these same knobs (min_hires_per_day/max_hires_per_
day/turns_per_task_estimate/hire_buffer_fraction) ran *before* T8.29's
fix - every candidate that raised the floor above 2 or tightened
turns_per_task_estimate lost, because labor_units was hardcoded at 2
regardless of what hires_per_day actually forecast: raising the floor
just bought idle hands with no extra planting capacity to put them to
work on. That finding needs re-testing, not re-trusting, now that
labor_units tracks the real forecast.

Not part of the committed test suite - a one-off tuning run
(SPEC-tuning.md: sweep correlated parameters jointly, not independently).

**Prediction stated up front** (T8.3b): genuinely uncertain, not a
predetermined win. T8.29's fix raises labor_units correctly, but
min_hires_per_day itself still comes from the *same* forecast formula
(workload_forecast_scaling_only's own clip-to-floor behavior, per
T8.28's docstring) - so whether *more actual hands* helps depends on
whether hiring cost (fib-scaled, still cheap - fib hire #8 costs $21) is
worth it once the farm can truly use the labor. Real risk this still
doesn't move: T8.29's own seed-900 trace already showed hand count
pinned at the floor because the forecast itself never clears it for a
single-quadrant farm - if so, that confirms the bottleneck is elsewhere
(e.g. land/quadrant count, not the hiring formula), and should be
recorded honestly rather than forced by picking a noise-level "winner."
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t830_workdir"
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
    """Pure self-play against the checked-in baseline (the T8.29 shipped
    default, i.e. plain DEFAULT_PARAMS - nothing to toggle for the fix
    itself, it's now the shipped labor_units call site)."""
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    result = harness.run_block(agent_path, _baseline_agent(), WORKING_SEEDS, jobs=None)
    print(
        f"  eval min={params['min_hires_per_day']} max={params['max_hires_per_day']} "
        f"turns_est={params['turns_per_task_estimate']} buffer={params['hire_buffer_fraction']}: "
        f"win_rate={result.win_rate_a:.3f} interval={result.wilson_interval_a}"
    )
    return result


print("=== T8.30: joint re-sweep {min_hires_per_day, max_hires_per_day, "
      "turns_per_task_estimate, hire_buffer_fraction} now that labor_units "
      "genuinely scales (T8.29) ===")
print("(baseline = checked-in DEFAULT_PARAMS, i.e. the T8.29 shipped fix)")

BASE = dict(DEFAULT_PARAMS)

# Curated joint grid (not a full factorial), per SPEC-tuning.md's own
# guidance to check whether correlated knobs want to move together.
PARAM_GRID = {
    ("min_hires_per_day", "max_hires_per_day", "turns_per_task_estimate", "hire_buffer_fraction"): [
        (2, 8, 2.0, 0.0),  # the shipped starting point (bit-identical to BASE)
        # Floors above the current 2 - T8.28 found 3/4 lost pre-fix; now
        # genuinely worth re-testing since extra hands have real planting
        # capacity to use.
        (3, 8, 2.0, 0.0),
        (4, 8, 2.0, 0.0),
        (5, 8, 2.0, 0.0),
        (6, 8, 2.0, 0.0),
        # Tighter turns-per-task estimate - T8.28 also found these lost
        # pre-fix, same reasoning.
        (2, 8, 1.5, 0.0),
        (2, 8, 1.0, 0.0),
        # One buffer probe.
        (2, 8, 2.0, 0.1),
    ],
}

best_params = tuning.coordinate_ascent(PARAM_GRID, evaluate, BASE)
best_key = (
    best_params["min_hires_per_day"], best_params["max_hires_per_day"],
    best_params["turns_per_task_estimate"], best_params["hire_buffer_fraction"],
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
