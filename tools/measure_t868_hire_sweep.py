"""T8.68: does raising max_hires_per_day (only for the NEW/cycle_economics
candidate, baseline stays at the shipped default 12) close the head-to-
head gap found in tools/measure_t868_headtohead.py? The user's own
hypothesis, traced concretely: the day-plan hiring forecast at day 19
computed a raw target of 18 hands, clipped down to 12 by max_hires_per_
day - by the time the labor backlog cleared enough to plant already-
bought TOMATO seeds, their score had collapsed from 17 to 3.5.

Sweeps max_hires_per_day in [13..20] for the candidate only, head-to-head
against the unchanged baseline (harness.run_paired/run_block, the same
T8.7/T8.8 "direct self-play" pattern tools/measure_t868_headtohead.py
uses) - a reduced 20-seed slice of the working block first (keeps total
runtime bounded across 8 sweep points); the best value can be confirmed
on the full 50-seed block afterward.

Not part of the committed test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd868_hiresweep")
os.makedirs(W, exist_ok=True)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, W)
SWEEP = list(range(13, 21))
candidates = {
    n: tuning.write_candidate_agent(
        dict(DEFAULT_PARAMS, use_cycle_economics_ranking=True, max_hires_per_day=n), W
    )
    for n in SWEEP
}

if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds)[:20]
    print(f"seeds: {seeds}", flush=True)
    for n in SWEEP:
        result = harness.run_block(candidates[n], baseline_agent, seeds)
        a_money = sum(r.a_total_money for r in result.paired_results)
        b_money = sum(r.b_total_money for r in result.paired_results)
        print(
            f"max_hires_per_day={n:2d}: {result.wins_a}W/{result.wins_b}L/{result.ties}T "
            f"win_rate={result.win_rate_a:.2f} money_delta={100*(a_money-b_money)/b_money:+.1f}%",
            flush=True,
        )
