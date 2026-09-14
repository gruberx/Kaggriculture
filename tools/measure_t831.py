"""T8.31 Stage A: measure always_pursue_one_animal alone against the
checked-in baseline (the flag defaults False, bit-identical).

Stage 0 (tools/measure_t831_stage0.py, tasks/todo.md) already found
investment_commit_margin cannot be loosened far enough to let an animal
win _top_investment_choice's single top-pick ranking - even margin=-0.5
produced zero behavioral change across 400 self-play games. This
measures the real fix instead: always_pursue_one_animal decouples animal
acquisition from that ranking entirely - when the farm has no animal
anywhere, the single best-scoring animal is pursued in parallel with
whatever crop the normal ranking already picked (see
kagg.policy.decide's own _DEFAULT_ALWAYS_PURSUE_ONE_ANIMAL comment and
the new gating block for the mechanism).

Not part of the committed test suite - a one-off tuning run.

**Prediction stated up front** (T8.3b): genuinely uncertain in
direction, not a predetermined win. This adds real spend (animal cost +
ongoing feed) not currently modeled as "worth it" by the ranking itself
- the whole reason the ranking never picks an animal on its own is that
crops score higher, so forcing an animal purchase anyway could easily
lose on raw money even while it structurally achieves the user's stated
goal (farms that actually run animals, matching the observed top-10
pattern). If this doesn't clear the held-out gate outright, that is
itself informative and should be recorded honestly - a natural follow-up
would be pairing this with T8.17's already-measured animal-awareness
stack (animal_care_aware/animal_fertilizer_income_aware) to see whether
profitability follows once acquisition itself is unblocked, similar to
how T8.16(d)'s labor fix preceded T8.17's animal-awareness re-test.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t831_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

print("=== T8.31 Stage A: always_pursue_one_animal alone vs checked-in baseline ===")

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_params = dict(DEFAULT_PARAMS, always_pursue_one_animal=True)
candidate_agent = tuning.write_candidate_agent(candidate_params, WORKDIR)

working_block = harness.run_block(candidate_agent, baseline_agent, WORKING_SEEDS, jobs=None)
print(
    f"  working: win_rate={working_block.win_rate_a:.3f} "
    f"({working_block.wins_a}W/{working_block.wins_b}L/{working_block.ties}T) "
    f"interval={working_block.wilson_interval_a}",
    flush=True,
)

holdout_block = harness.run_block(candidate_agent, baseline_agent, HOLDOUT_SEEDS, jobs=None)
print(
    f"  holdout: win_rate={holdout_block.win_rate_a:.3f} "
    f"({holdout_block.wins_a}W/{holdout_block.wins_b}L/{holdout_block.ties}T) "
    f"interval={holdout_block.wilson_interval_a}",
    flush=True,
)
n = holdout_block.n
even_baseline = harness.BlockResult(
    n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
    win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
)
accepted = tuning.accept_candidate(holdout_block, even_baseline)
print(f"  accept_candidate (vs even-odds at n={n}): {accepted}", flush=True)
