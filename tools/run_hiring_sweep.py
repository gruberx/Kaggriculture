"""T8.7's re-run of the hiring-count sweep (tasks/plan.md, /root/.claude/
plans/partitioned-puzzling-blossom.md) - the payoff of Stage B (T8.4-T8.6).

T7.4's original sweep (Phase 7) found every hires_per_day > 0 lost
consistently (0.03-0.17 win rate), and that result was accepted as the
shipped default. Phase 8's own planning found that result invalid, not
just stale: it ran against code where (a) decide() modeled only
inventories[0], so a hired hand could silently pick up the wheat/animal
into an inventory decide() never looked at again, starving any animal on
the farm; and (b) build_task_list proposed at most one new-investment
task per turn regardless of hand count, so extra hands had nothing to
plant. T8.4 (inventory pinning) and T8.6 (parallel planting) fix both
causes - this script is the real test of whether hiring pays off once
they're gone.

**State the prediction up front, per this project's own established
discipline (T8.3q's own script), so a miss is genuinely informative**:
with both causes fixed, hiring is predicted to win clearly. If
hires_per_day=0 still wins, the bottleneck is not labor - the next
investigation is market depth (are we crashing the price of our own
higher-throughput output?), not more units.

Direct self-play ONLY (harness.run_block against the checked-in
baseline) - never evaluate_against_panel. T7.4's own real, documented
methodological pitfall: blending win rate across starter/random (both
near a 100% ceiling against any reasonable policy) with self-play
dilutes the signal so heavily that a candidate which actually *loses* to
the baseline head-to-head can still look like an improvement on the
blended aggregate.

Not part of the committed test suite - a real tuning run, re-executed
whenever a future round wants to revisit hires_per_day/max_plants_per_
unit/seed_buffer_per_unit, not on every test pass.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_hiring_sweep_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

HIRES_CANDIDATES = [0, 1, 2, 3, 4, 6, 8]

_baseline_agent_cache: dict[str, str] = {}


def _baseline_agent() -> str:
    if "path" not in _baseline_agent_cache:
        _baseline_agent_cache["path"] = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
    return _baseline_agent_cache["path"]


def evaluate(params: dict) -> harness.BlockResult:
    """Pure self-play against the checked-in T8.6 baseline - see this
    module's own docstring for why this, not evaluate_against_panel, is
    the search/decision signal."""
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    result = harness.run_block(agent_path, _baseline_agent(), WORKING_SEEDS, jobs=None)
    print(
        f"  eval hires_per_day={params['hires_per_day']} max_plants_per_unit={params['max_plants_per_unit']} "
        f"seed_buffer_per_unit={params['seed_buffer_per_unit']}: "
        f"win_rate={result.win_rate_a:.3f} interval={result.wilson_interval_a}"
    )
    return result


print("=== Stage 1: hires_per_day alone (direct self-play vs the T8.6 baseline) ===")
print(
    "Prediction: with T8.4 (inventory pinning) + T8.6 (parallel planting) landed, hiring should "
    "win clearly. If hires_per_day=0 still wins, the bottleneck is not labor - see this script's "
    "own docstring."
)
best_hires_result = None
best_hires_value = 0
baseline_result = evaluate(DEFAULT_PARAMS)
best_hires_result = baseline_result
for hires in HIRES_CANDIDATES:
    if hires == 0:
        continue  # already have the baseline-vs-itself point above
    trial_params = dict(DEFAULT_PARAMS, hires_per_day=hires)
    trial_result = evaluate(trial_params)
    if tuning.accept_candidate(trial_result, best_hires_result):
        best_hires_result = trial_result
        best_hires_value = hires

print(f"\nStage 1 winner: hires_per_day={best_hires_value} (win_rate={best_hires_result.win_rate_a:.3f})")

if best_hires_value == 0:
    print(
        "\nhires_per_day=0 still wins - the single most informative negative result this plan "
        "names. Not proceeding to Stage 2 (nothing to jointly tune around a hires_per_day that "
        "doesn't pay off)."
    )
    sys.exit(0)

print("\n=== Stage 2: joint sweep {hires_per_day, max_plants_per_unit, seed_buffer_per_unit} ===")
print("(SPEC-tuning.md: suspected-correlated parameters swept jointly, not independently)")

# A curated, small set of joint candidates around Stage 1's winner - not
# a full factorial grid (too expensive), but enough to check whether the
# other two knobs want to move together with hires_per_day.
PARAM_GRID = {
    ("hires_per_day", "max_plants_per_unit", "seed_buffer_per_unit"): [
        (best_hires_value, 100, 1),  # Stage 1's winner, unmodified geometry defaults
        (best_hires_value, 100, 2),
        (best_hires_value, 100, 3),
        (best_hires_value, 8, 1),  # a tight watering-capacity cap, forcing plant_budget to bind
        (best_hires_value, 16, 1),
        (max(0, best_hires_value - 1), 100, 1),  # neighbors of Stage 1's winner, in case Stage 1's
        (min(8, best_hires_value + 1), 100, 1),  # single-param result doesn't hold jointly
    ],
}

initial = dict(DEFAULT_PARAMS, hires_per_day=best_hires_value)
best_params = tuning.coordinate_ascent(PARAM_GRID, evaluate, initial)
print(
    "\nStage 2 winner:",
    {k: best_params[k] for k in ("hires_per_day", "max_plants_per_unit", "seed_buffer_per_unit")},
)

if best_params == dict(initial):
    print("No joint change beat Stage 1's own winner beyond noise.")

print("\n=== Held-out gate (self-play vs the T8.6 baseline) ===")
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
