"""T8.11 measurement: water_bonus_window_aware, measured alone against
the checked-in baseline - per T8.3b's lesson, a single isolated
mechanism.

Not part of the committed test suite - a one-off measurement run, like
tools/measure_t810.py.

**Prediction stated up front, per this project's own established
discipline**: a real, informative win, but not risk-free - a strictly
weaker prediction than T8.10's own ("clear, zero-risk win") was, and
that one was measured to lose (see tools/measure_t810.py's own
docstring). This is exactly the class of change T8.3e's FERTILIZE
rejection warns about: demoting a task's priority can starve it if the
lower tier never gets reached either. The mitigating factor T8.3e's
FERTILIZE didn't have: this doesn't add a *new* consumer of scarce
MAINTENANCE-tier turns, it *frees up* ROUTINE_CARE-tier turns that were
being spent on genuinely useless watering (zero yield, verified directly
against the real handler) - so the risk is narrower (does PLANT actually
absorb the freed turns, not does a new task starve an old one), but real
enough to check WEED counts explicitly, not just trust the win rate.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t811_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

CANDIDATES = {
    "water_bonus_window_aware": dict(DEFAULT_PARAMS, water_bonus_window_aware=True),
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
