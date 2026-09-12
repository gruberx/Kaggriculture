"""T7.4's Stage 1 sweep runner: the hiring-count question (SPEC-tuning.md's
"First sweep priority"), plus land_purchase_threshold_money, swept jointly
per SPEC-policy.md's hiring-interaction note.

Not part of the committed test suite - a real tuning run, re-executed
(with an updated grid centered on whatever the current checked-in
params/policy.json is) whenever a future tuning round wants to revisit
this parameter pair, not on every test run.

Real methodological finding from this script's first real run, load-
bearing for how `evaluate` is written below - not an abstract caveat:
`tuning.evaluate_against_panel()` blends win rate across every opponent
in the panel into one aggregate number. That's fine when every panel
member is comparably matched, but starter/random are both near a 100%
win-rate ceiling against basically any reasonable policy - blending
them with self-play against the previous-best snapshot dilutes the
self-play signal so heavily that a first real run of this script
accepted a candidate (more hires_per_day) whose blended score looked
better (0.78 vs baseline's 0.667) while it *actually lost* to the
baseline in direct self-play (0.34 win rate, verified by re-running
that one comparison in isolation). The real, load-bearing signal is
self-play against the previous-best snapshot alone - `evaluate` below
uses exactly that (plain harness.run_block, not evaluate_against_panel)
for the search and the accept/reject decision. evaluate_against_panel
is still used once at the end, purely as a non-regression sanity report
against starter/random - never as part of the decision.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_tuning_workdir"
os.makedirs(WORKDIR, exist_ok=True)

TUNING_SEEDS = list(range(100, 150))  # the full 50-seed working block
HOLDOUT_SEEDS = list(range(900, 950))  # the full 50-seed held-out block

PARAM_GRID = {
    ("hires_per_day",): [(0,), (1,), (2,), (3,), (4,)],
    ("land_purchase_threshold_money",): [(1000,), (2000,), (3000,), (5000,), (7000,), (10000,)],
}

_baseline_agent_cache: dict[str, str] = {}


def _baseline_agent() -> str:
    if "path" not in _baseline_agent_cache:
        _baseline_agent_cache["path"] = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
    return _baseline_agent_cache["path"]


def evaluate(params: dict) -> harness.BlockResult:
    """Pure self-play against the checked-in baseline - see this
    module's own docstring for why this, not evaluate_against_panel, is
    the search/decision signal.

    A real second bug was found and fixed here, not anticipated in
    advance: an earlier revision special-cased "comparing the baseline
    against itself" with a hand-typed `wilson_interval_a=(0.0, 0.0)`
    instead of the real `harness.wilson_interval(0, n)` (which is *not*
    degenerate - e.g. (0, 0.071) at n=50, per the Wilson score formula's
    own continuity correction). That artificially zero-width interval
    made literally any other candidate's interval look "clearly better"
    (never overlapping a single-point interval at exactly 0), which
    silently let coordinate_ascent walk hires_per_day up to a spuriously
    "best" value of 3 on a real run of this script - correctly caught
    and rejected at the held-out gate below (hires_per_day > 0
    consistently loses in direct self-play, confirmed separately), so no
    bad change reached params/policy.json, but the sweep itself wasted
    real compute chasing a false signal. No special case is needed at
    all: letting the baseline play itself for real (it always ties
    exactly, so win_rate_a is 0.0 either way) computes the correct,
    non-degenerate interval automatically.
    """
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    result = harness.run_block(agent_path, _baseline_agent(), TUNING_SEEDS, jobs=None)
    print(
        f"  eval hires={params['hires_per_day']} land={params['land_purchase_threshold_money']}: "
        f"win_rate={result.win_rate_a:.3f} interval={result.wilson_interval_a}"
    )
    return result


print("=== Stage 1 sweep: hires_per_day, then land_purchase_threshold_money (self-play vs baseline) ===")
best_params = tuning.coordinate_ascent(PARAM_GRID, evaluate, dict(DEFAULT_PARAMS))
print("best params found:", {k: best_params[k] for k in ("hires_per_day", "land_purchase_threshold_money")})

if best_params == dict(DEFAULT_PARAMS):
    print("No change from baseline - coordinate_ascent found nothing better beyond noise.")
    sys.exit(0)

print("\n=== Held-out gate (self-play vs baseline) ===")
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
    print("\n=== Non-regression sanity check vs starter/random (reporting only) ===")
    panel_result = tuning.evaluate_against_panel(
        candidate_agent, ["starter", "random"], HOLDOUT_SEEDS[:10], WORKDIR, jobs=None
    )
    print(f"vs starter+random (10 holdout seeds): win_rate={panel_result.win_rate_a:.3f}")
