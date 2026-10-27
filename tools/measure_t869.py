"""T8.69: investment priority reorder + seed-purchase lookahead deferral,
alone and combined, head-to-head against the checked-in baseline. A
20-seed slice of the working block first (fast signal across several
variants); the winner gets confirmed on the full 50-seed block
separately (tools/measure_t869_confirm.py).

Not part of the committed test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd869")
os.makedirs(W, exist_ok=True)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, W)
GRID = {
    "reorder only": {"investment_priority_reordered": True},
    "lookahead=1": {"seed_purchase_lookahead_aware": True, "seed_purchase_lookahead_turns": 1},
    "lookahead=2": {"seed_purchase_lookahead_aware": True, "seed_purchase_lookahead_turns": 2},
    "lookahead=3": {"seed_purchase_lookahead_aware": True, "seed_purchase_lookahead_turns": 3},
    "lookahead=4": {"seed_purchase_lookahead_aware": True, "seed_purchase_lookahead_turns": 4},
    "reorder + lookahead=2": {
        "investment_priority_reordered": True,
        "seed_purchase_lookahead_aware": True, "seed_purchase_lookahead_turns": 2,
    },
}
candidates = {name: tuning.write_candidate_agent(dict(DEFAULT_PARAMS, **v), W) for name, v in GRID.items()}

if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds)[:20]
    print(f"seeds: {seeds}", flush=True)
    for name in GRID:
        result = harness.run_block(candidates[name], baseline_agent, seeds)
        a_money = sum(r.a_total_money for r in result.paired_results)
        b_money = sum(r.b_total_money for r in result.paired_results)
        print(
            f"{name:24s}: {result.wins_a}W/{result.wins_b}L/{result.ties}T "
            f"win_rate={result.win_rate_a:.2f} money_delta={100*(a_money-b_money)/b_money:+.1f}%",
            flush=True,
        )
