"""T8.28: re-sweep the hiring knobs under the forecast path T8.27 actually
shipped, plus re-test the total-work variant at its own knobs.

A read-only computation (not this script) found the shipped forecast's
raw pre-clip target (workload_forecast_scaling_only=True) is 0 at every
realistic farm size - it is *always* clipped up to min_hires_per_day=2.
T8.27's accepted default is, in practice, flat 2 hands/day; the tile-
count scaling term never actually engages. See
kagg.policy.strategy._DEFAULT_WORKLOAD_FORECAST_SCALING_ONLY's own
comment for the numbers and the full traced story.

Two things follow, neither ever measured:
(1) min_hires_per_day/max_hires_per_day/turns_per_task_estimate/
    hire_buffer_fraction were jointly swept by T8.16(d) against the
    *reactive* pending_task_count path. That formula is gone from the
    default branch now - min_hires_per_day is structurally the only
    live term at scaling_only=True, and it has never been swept in a
    regime where it's the sole binding value.
(2) The total-work variant (scaling_only=False, which genuinely scales -
    raw target 2 at 25 tiles + 1 cow, 5 at 50 tiles + 3 cows) was
    measured by T8.26 at turns_per_task_estimate=2.0/min=2/max=8 -
    values fitted to the unrelated reactive path, not to itself. Its
    10%/0% rejection is a rejection of that specific combination.

Not part of the committed test suite - a one-off tuning run
(SPEC-tuning.md: sweep correlated parameters jointly, not independently).

**Predictions stated up front**: min_hires_per_day is again the dominant
knob (it was in T8.16(d), and here it is structurally the *only* live
term at scaling_only=True - raising it is mechanically identical to
raising a flat hires_per_day constant). Genuinely uncertain whether a
floor above 2 wins (T8.16(d)'s own finding under the old formula was
that 2 beat 1 and 3+ didn't help further, but that was under a formula
that *could* rise above the floor on its own - this one can't). Genuinely
uncertain whether the total-work variant, given its own turns_per_task_
estimate, can beat flat hiring - that is the real open question this
task exists to answer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t828_workdir"
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
    """Pure self-play against the checked-in baseline (the T8.27 shipped
    default) - see this module's docstring for why this, not
    evaluate_against_panel, is the search/decision signal."""
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    result = harness.run_block(agent_path, _baseline_agent(), WORKING_SEEDS, jobs=None)
    print(
        f"  eval min={params['min_hires_per_day']} max={params['max_hires_per_day']} "
        f"turns_est={params['turns_per_task_estimate']} buffer={params['hire_buffer_fraction']} "
        f"scaling_only={params['workload_forecast_scaling_only']}: "
        f"win_rate={result.win_rate_a:.3f} interval={result.wilson_interval_a}"
    )
    return result


print("=== T8.28: joint sweep {min_hires_per_day, max_hires_per_day, turns_per_task_estimate, "
      "hire_buffer_fraction, workload_forecast_scaling_only} ===")
print("(baseline = checked-in DEFAULT_PARAMS, i.e. the T8.27 shipped forecast)")

BASE = dict(DEFAULT_PARAMS)

# Curated joint grid (not a full factorial - too expensive), per SPEC-
# tuning.md's own guidance to check whether correlated knobs want to move
# together rather than search exhaustively.
PARAM_GRID = {
    ("min_hires_per_day", "max_hires_per_day", "turns_per_task_estimate", "hire_buffer_fraction",
     "workload_forecast_scaling_only"): [
        (2, 8, 2.0, 0.0, True),  # the shipped starting point (bit-identical to BASE)
        # Floors, now that the floor is the only binding term at scaling_only=True:
        (1, 8, 2.0, 0.0, True),
        (3, 8, 2.0, 0.0, True),
        (4, 8, 2.0, 0.0, True),
        # Tighter turns-per-task estimate, to see if the scaling term can
        # clear the floor at all under this variant:
        (2, 8, 1.0, 0.0, True),
        (2, 8, 0.5, 0.0, True),
        # The total-work variant (T8.26's original formula), at its own knobs:
        (2, 8, 2.0, 0.0, False),
        (2, 8, 1.0, 0.0, False),
        (1, 8, 2.0, 0.0, False),
        (2, 12, 2.0, 0.0, False),
        # One buffer probe under the new (shipped) path:
        (2, 8, 2.0, 0.1, True),
    ],
}

best_params = tuning.coordinate_ascent(PARAM_GRID, evaluate, BASE)
best_key = (
    best_params["min_hires_per_day"], best_params["max_hires_per_day"],
    best_params["turns_per_task_estimate"], best_params["hire_buffer_fraction"],
    best_params["workload_forecast_scaling_only"],
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
