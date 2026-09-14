"""T8.31 Stage 0: cheap sanity check before building anything new - sweep
investment_commit_margin into *negative* territory, against the checked-
in baseline (margin=0.0). T8.14 only ever tried positive margins
(tightening the animal-acquisition gate further, to fix a razor-thin-lead
contamination). Never tested whether loosening it (letting an animal win
while trailing the best crop score) helps animals actually get acquired.

Not part of the committed test suite - a one-off measurement run.

**Prediction stated up front** (T8.3b): unlikely to be sufficient on its
own, but cheap to check before building the real fix (T8.31 Stage 1's
always_pursue_one_animal mechanism). Direct computation this session
(score_portfolio at day 0, fresh market) found MELON scoring ~119/tile-
day vs COW's ~23 - beating MELON needs roughly a -80% margin, an
economically extreme value that likely just forces bad investments
whenever MELON (or another strong crop) is available. Closer competitors
(WHEAT ~19.4, CARROT ~21.25, TOMATO ~16.17) are much nearer to COW's
~23, so a moderate negative margin could matter only once MELON/
STRAWBERRY are absent from the ranking or heavily self-impacted (self-
impact is scoped per-crop, not farm-wide, so this is rare in practice -
see T8.31's own todo.md entry for the full self-impact-sweep evidence).
Record the result honestly either way: if a moderate negative margin
surprises us by helping, that changes Stage 1's scope; if the only
margins that flip the ranking are economically extreme (and lose), that
confirms Stage 1's new-mechanism approach is the right next step, not a
detour.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t831_stage0_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

CANDIDATES = {
    "margin=-0.1": dict(DEFAULT_PARAMS, investment_commit_margin=-0.1),
    "margin=-0.2": dict(DEFAULT_PARAMS, investment_commit_margin=-0.2),
    "margin=-0.3": dict(DEFAULT_PARAMS, investment_commit_margin=-0.3),
    "margin=-0.5": dict(DEFAULT_PARAMS, investment_commit_margin=-0.5),
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
