"""T8.12 measurement: dynamic_hiring, measured alone against the
checked-in baseline (hires_per_day=1, dynamic_hiring off) - per T8.3b's
lesson, a single isolated mechanism.

Not part of the committed test suite - a one-off measurement run, like
tools/measure_t810.py / tools/measure_t811.py.

**Prediction stated up front, per this project's own established
discipline**: this task's own plan named the dependency explicitly -
"a win if T8.11 has already freed labor, close to zero otherwise." T8.11
(water_bonus_window_aware) was measured and REJECTED (7/50 working,
3/50 holdout - see measure_t811.py's own docstring), so the labor supply
this mechanism would scale into is still saturated by the same
out-of-bonus-window watering T8.11 tried and failed to free. Predicted:
close to zero effect, possibly a small net loss - extra hired hands with
nothing more productive to do than join the already-oversubscribed
ROUTINE_CARE watering queue (fib hire cost is real, if small). Not
expected to be a clean win the way T8.7's original hires_per_day 0->1
sweep was, since that sweep ran *after* T8.4/T8.6 genuinely fixed the
bottleneck it was measuring against - this one does not have an
equivalent fix landed underneath it yet.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t812_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

CANDIDATES = {
    "dynamic_hiring": dict(DEFAULT_PARAMS, dynamic_hiring=True),
}

for label, params in CANDIDATES.items():
    print(f"=== {label} ===")
    candidate_agent = tuning.write_candidate_agent(params, WORKDIR)
    working_block = harness.run_block(candidate_agent, baseline_agent, WORKING_SEEDS, jobs=None)
    print(
        f"  working: win_rate={working_block.win_rate_a:.3f} "
        f"({working_block.wins_a}W/{working_block.wins_b}L/{working_block.ties}T) "
        f"interval={working_block.wilson_interval_a}"
    )
    holdout_block = harness.run_block(candidate_agent, baseline_agent, HOLDOUT_SEEDS, jobs=None)
    print(
        f"  holdout: win_rate={holdout_block.win_rate_a:.3f} "
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
    print()
