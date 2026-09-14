"""T8.16(d): joint coordinate_ascent sweep over {min_hires_per_day,
max_hires_per_day, turns_per_task_estimate, hire_buffer_fraction} with
dynamic_hiring=True - T8.16(a)'s counting fix is unconditional (already
landed in decide.py, not behind a flag), so every trial here already
benefits from it. This follows directly from T8.16(a)'s own measurement
(62% working / 48% holdout - a huge recovery from T8.12's 4%/8%
rejection, but not yet decisive) and the plan's own T8.16(c)/(d)
reasoning: none of these four parameters have ever actually been swept
jointly - they were only ever turned on at their geometry-derived
starting values.

Not part of the committed test suite - a one-off tuning run
(SPEC-tuning.md: sweep correlated parameters jointly, not independently).

**Prediction stated up front**: uncertain, genuinely. Two plausible
outcomes, both informative: (1) some point in this joint grid clears the
held-out gate outright, confirming dynamic_hiring just needed real tuning
rather than its geometry-derived defaults; or (2) nothing in this grid
clears it, which would suggest the earlier T8.15+T8.16(a) combined result
(58%/42% - worse than either alone) reflects a real interaction cost
between the two mechanisms, not just untuned knobs, and dynamic_hiring
should stay rejected pending a different fix.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t816d_workdir"
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
    """Pure self-play against the checked-in baseline (dynamic_hiring
    off) - see this module's docstring for why this, not
    evaluate_against_panel, is the search/decision signal."""
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    result = harness.run_block(agent_path, _baseline_agent(), WORKING_SEEDS, jobs=None)
    print(
        f"  eval min={params['min_hires_per_day']} max={params['max_hires_per_day']} "
        f"turns_est={params['turns_per_task_estimate']} buffer={params['hire_buffer_fraction']}: "
        f"win_rate={result.win_rate_a:.3f} interval={result.wilson_interval_a}"
    )
    return result


print("=== T8.16(d): joint sweep {min_hires_per_day, max_hires_per_day, turns_per_task_estimate, hire_buffer_fraction} ===")
print("(dynamic_hiring=True throughout; T8.16(a)'s counting fix is unconditional and already in decide.py)")

BASE = dict(DEFAULT_PARAMS, dynamic_hiring=True)

# A curated, small joint grid (not a full factorial - too expensive):
# the untouched starting point, then one-at-a-time neighbors in each
# direction, per SPEC-tuning.md's own guidance to check whether the
# knobs want to move together rather than search exhaustively.
PARAM_GRID = {
    ("min_hires_per_day", "max_hires_per_day", "turns_per_task_estimate", "hire_buffer_fraction"): [
        (1, 8, 2.0, 0.0),  # T8.16(a)'s own measured starting point
        (1, 8, 2.0, 0.1),  # a modest spare-capacity buffer
        (1, 8, 2.0, 0.2),  # a larger buffer (the user's own upper suggestion, "5-10%" -> doubled to probe)
        (1, 8, 1.5, 0.0),  # tighter turns-per-task estimate -> more hires from the same backlog
        (1, 8, 3.0, 0.0),  # looser estimate -> fewer hires
        (2, 8, 2.0, 0.0),  # a real day-1 floor above the historical default
        (3, 8, 2.0, 0.0),  # a higher day-1 floor still
        (1, 12, 2.0, 0.0),  # a higher ceiling, in case 8 is binding
        (2, 8, 2.0, 0.1),  # floor + buffer combined
    ],
}

best_params = tuning.coordinate_ascent(PARAM_GRID, evaluate, BASE)
print(
    "\nWinner:",
    {k: best_params[k] for k in ("min_hires_per_day", "max_hires_per_day", "turns_per_task_estimate", "hire_buffer_fraction")},
)
if best_params == BASE:
    print("No joint change beat the starting point beyond noise (working block).")

print("\n=== Held-out gate (self-play vs the checked-in baseline, dynamic_hiring off) ===")
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
