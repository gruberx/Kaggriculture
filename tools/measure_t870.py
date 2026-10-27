"""T8.70: crop_shop_unlock_forecast_aware (M1) and crop_own_future_supply_aware
(M2), alone and combined, head-to-head against the checked-in baseline
(today's shipped DEFAULT_PARAMS, which already has use_cycle_economics_ranking
on). Full working (100-149) and holdout (900-949) blocks for each candidate,
per this project's standing measurement discipline - see tools/measure_t825b.py
for the pattern this mirrors.

Not part of the committed test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd870")
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

GRID = {
    "M1 alone (shop_unlock_forecast_aware)": {"crop_shop_unlock_forecast_aware": True},
    "M2 alone (own_future_supply_aware)": {"crop_own_future_supply_aware": True},
    "M1+M2 combined": {
        "crop_shop_unlock_forecast_aware": True,
        "crop_own_future_supply_aware": True,
    },
}


def measure(label, candidate_params):
    print(f"=== {label} ===", flush=True)
    baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
    candidate_agent = tuning.write_candidate_agent(candidate_params, WORKDIR)
    working = harness.run_block(candidate_agent, baseline_agent, WORKING_SEEDS, jobs=None)
    a_money = sum(r.a_total_money for r in working.paired_results)
    b_money = sum(r.b_total_money for r in working.paired_results)
    print(
        f"  working: {working.wins_a}W/{working.wins_b}L/{working.ties}T "
        f"win_rate={working.win_rate_a:.3f} wilson={working.wilson_interval_a} "
        f"money_delta={100 * (a_money - b_money) / b_money:+.1f}%",
        flush=True,
    )
    holdout = harness.run_block(candidate_agent, baseline_agent, HOLDOUT_SEEDS, jobs=None)
    a_money = sum(r.a_total_money for r in holdout.paired_results)
    b_money = sum(r.b_total_money for r in holdout.paired_results)
    print(
        f"  holdout: {holdout.wins_a}W/{holdout.wins_b}L/{holdout.ties}T "
        f"win_rate={holdout.win_rate_a:.3f} wilson={holdout.wilson_interval_a} "
        f"money_delta={100 * (a_money - b_money) / b_money:+.1f}%",
        flush=True,
    )
    print(flush=True)
    return working, holdout


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for name, overrides in GRID.items():
        if only and only not in name:
            continue
        measure(name, dict(DEFAULT_PARAMS, **overrides))
