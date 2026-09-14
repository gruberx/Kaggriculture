"""T8.19 measurement: portfolio_basket_size - the user's own observation
that committing every new tile to the single top-ranked product invites
a double price-crash risk (our own volume plus a plausible independent
opponent bet on the same good).

Not part of the committed test suite - a one-off measurement run.

**Prediction stated up front**: genuinely uncertain. A real
diversification benefit (lower variance, less exposure to a single
crash) trades against giving up some of the single best option's raw
edge - spreading tiles into a worse-ranked option has a real, calculable
cost per tile, not just a hedge benefit. Measured on top of T8.16(d)'s
new accepted baseline (dynamic_hiring=True, min_hires_per_day=2), since
that's now the checked-in default this candidate is compared against.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t819_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

CANDIDATES = {
    "portfolio_basket_size=2": dict(DEFAULT_PARAMS, portfolio_basket_size=2),
    "portfolio_basket_size=3": dict(DEFAULT_PARAMS, portfolio_basket_size=3),
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
