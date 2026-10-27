"""T8.71: crop_pending_supply_aware (single-cycle scoring, priced off the
real currently-known production pipeline - see cycle_economics.
crop_cycle_profit_per_day's own docstring for the full design story),
head-to-head against the checked-in baseline (today's shipped
DEFAULT_PARAMS). Full working (100-149) and holdout (900-949) blocks,
matching this project's standing measurement discipline - see
tools/measure_t870.py for the pattern this mirrors.

Not part of the committed test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd871")
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)


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
    measure("crop_pending_supply_aware", dict(DEFAULT_PARAMS, crop_pending_supply_aware=True))
