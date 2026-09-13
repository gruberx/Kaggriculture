"""T8.14 follow-up: investment_commit_margin measured ALONE
(measure_t814.py) was a complete no-op against today's baseline (100%
ties at every margin tried, working and holdout) - expected, not a
rejection: under the shipped default (animal_consumption_horizon_aware=
False), animal scores never come remotely close to a crop's, so the
margin check never has anything to gate. Its actual purpose only shows up
combined with a mechanism that brings animal/crop scores close together -
exactly animal_consumption_horizon_aware (T8.10), the flag whose own
rejection this margin was built to fix.

This previews T8.17's own step 1 (re-test animal_consumption_horizon_aware
now that T8.14 exists) ahead of T8.15/T8.16 landing, since T8.10's
rejection was purely about investment-choice hysteresis - unrelated to
labor/watering-priority, so this specific combination doesn't need to
wait for the rest of the chain.

**Prediction stated up front**: if T8.14 actually fixes T8.10's traced
failure mode, animal_consumption_horizon_aware + investment_commit_margin
together should measure much closer to T8.10's own original prediction
("a clear, zero-risk win") than T8.10 alone did (1/50 working, 0/50
holdout) - a real test of whether the fix works, not just a hoped-for
number.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t814_combined_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

CANDIDATES = {
    "consumption_horizon_aware alone (T8.10 retried, no margin)": dict(
        DEFAULT_PARAMS, animal_consumption_horizon_aware=True
    ),
    "consumption_horizon_aware + margin=0.05": dict(
        DEFAULT_PARAMS, animal_consumption_horizon_aware=True, investment_commit_margin=0.05
    ),
    "consumption_horizon_aware + margin=0.10": dict(
        DEFAULT_PARAMS, animal_consumption_horizon_aware=True, investment_commit_margin=0.10
    ),
    "consumption_horizon_aware + margin=0.20": dict(
        DEFAULT_PARAMS, animal_consumption_horizon_aware=True, investment_commit_margin=0.20
    ),
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
