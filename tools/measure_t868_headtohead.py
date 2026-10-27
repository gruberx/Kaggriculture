"""T8.68 head-to-head: the user's own follow-up after the starter/pass
measurement (-3.5%/-3.2%) - starter only ever grows CARROT and pass does
nothing, so neither ever competes for MELON/STRAWBERRY market share the
way a real Kaggle opponent does (confirmed directly: the trace showed
STRAWBERRY's price RISING all game against starter, not crashing). This
instead pits the candidate (use_cycle_economics_ranking=True) directly
against the checked-in baseline (today's shipped rank_portfolio) -
harness.run_paired/run_block, the same "direct self-play against the
checked-in baseline" pattern T8.7/T8.8 used - so BOTH sides aggressively
plant premium crops and genuinely compete for the same market, a much
closer proxy for real competitive price pressure.

Not part of the committed test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd868_h2h")
os.makedirs(W, exist_ok=True)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, W)
candidate_agent = tuning.write_candidate_agent(
    dict(DEFAULT_PARAMS, use_cycle_economics_ranking=True), W
)

if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    print(f"working block ({len(blocks.tuning_seeds)} seeds)...", flush=True)
    result = harness.run_block(candidate_agent, baseline_agent, list(blocks.tuning_seeds))
    print(
        f"candidate (cycle_economics) vs baseline (rank_portfolio): "
        f"{result.wins_a}W/{result.wins_b}L/{result.ties}T out of {result.n}, "
        f"win_rate={result.win_rate_a:.2f}, Wilson={result.wilson_interval_a}",
        flush=True,
    )
    a_money = sum(r.a_total_money for r in result.paired_results)
    b_money = sum(r.b_total_money for r in result.paired_results)
    print(f"total money: candidate={a_money:.0f} baseline={b_money:.0f} ({100*(a_money-b_money)/b_money:+.1f}%)")
