"""T8.74: full-episode (720-step, untruncated), both-seed-block head-to-head
- candidate = the fixed quadrant-1 opening (COW=2/SHEEP=4 herd,
quadrant1_hire_target=10, quadrant1_crop_lock="MELON") found by this
session's own T8.72/73 truncated/crop-restricted brute-force search - vs
today's shipped baseline. This is the first real test of whole-game money
and the quadrant-1-to-quadrant-2 handoff; T8.72/73's own numbers never
exercised either. Not part of the committed test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd874")
W_BASELINE = W + "_baseline"
os.makedirs(W, exist_ok=True)
os.makedirs(W_BASELINE, exist_ok=True)

CANDIDATE_PARAMS = dict(
    DEFAULT_PARAMS,
    animal_opening_initial={"COW": 2, "SHEEP": 4},
    quadrant1_hire_target=10,
    quadrant1_crop_lock="MELON",
)

if __name__ == "__main__":
    candidate_agent = tuning.write_candidate_agent(CANDIDATE_PARAMS, W)
    baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, W_BASELINE)

    blocks = harness.load_seed_blocks()
    for name, seeds in (("tuning", blocks.tuning_seeds), ("holdout", blocks.holdout_seeds)):
        result = harness.run_block(candidate_agent, baseline_agent, list(seeds))
        lo, hi = result.wilson_interval_a
        print(
            f"{name}: win_rate_a={result.win_rate_a:.3f} ({result.wins_a}W/{result.wins_b}L/{result.ties}T, "
            f"n={result.n}) wilson95%=({lo:.3f},{hi:.3f})",
            flush=True,
        )
