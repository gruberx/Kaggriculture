"""T8.32 addendum: retest Stage 1's promising-but-unaccepted candidate at
a much larger sample size.

T8.32 Stage 1 (tools/measure_t832.py) found that the joint combination
(land_purchase_threshold_money=10000, land_buy_max_free_tile_fraction=
0.2, min_hires_per_day=4) scored a real 64% held-out win rate (32W/18L/
0T out of the standard 50-seed block) against the checked-in baseline -
the strongest result this project has measured for either knob - but
tuning.accept_candidate returned False: the held-out Wilson interval
[0.501, 0.759] still overlapped the even-odds baseline's own interval
[0.366, 0.634] at n=50.

harness.run_block takes an arbitrary caller-supplied seed list,
decoupled from load_seed_blocks() - no code change is needed to use a
larger sample. Computed directly from wilson_interval's own formula
(holding the point estimates at 64%/50%), n=190 is where the interval
separation needed to clear accept_candidate first appears - the binding
constraint is the baseline's own upper bound shrinking down past the
candidate's lower bound, not simply the candidate's own lower bound
clearing 0.5.

This script does NOT edit params/seed_blocks.json (that would silently
change what every future measure_t8*.py script and every entry in
data/arena/accepted_runs.jsonl means by "held-out", breaking
comparability with this project's entire measurement history). Instead
it builds its own explicit, disjoint, never-before-used seed range
range(900, 1100) - the original 50 holdout seeds 900-949 plus 150
freshly-unused ones 950-1099 - and passes it directly to run_block, the
same zero-friction path every prior one-off measure_t8*.py script uses.

Not part of the committed test suite - a one-off tuning run.

**Prediction stated up front** (T8.3b): genuinely uncertain - this is
honestly testing whether the original 64%/50 was real signal or a
favorable draw, not confirming a foregone conclusion. If the true win
rate is actually closer to 55-60%, no practically-sized sample would
separate it from a 50% baseline whose own point estimate might also
shift on a larger draw.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t832_large_n_workdir"
os.makedirs(WORKDIR, exist_ok=True)

# Disjoint from both canonical blocks (tuning_seeds 100-149, holdout_seeds
# 900-949) except for the original holdout range itself, which this
# extends rather than replaces.
LARGE_SEEDS = list(range(900, 1100))

STAGE1_CANDIDATE = dict(
    DEFAULT_PARAMS,
    land_purchase_threshold_money=10000,
    land_buy_max_free_tile_fraction=0.2,
    min_hires_per_day=4,
)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_agent = tuning.write_candidate_agent(STAGE1_CANDIDATE, WORKDIR)

print(f"=== T8.32 addendum: large-n retest on {len(LARGE_SEEDS)} seeds ({LARGE_SEEDS[0]}-{LARGE_SEEDS[-1]}) ===")
block = harness.run_block(candidate_agent, baseline_agent, LARGE_SEEDS, jobs=None)
print(
    f"  large_n: win_rate={block.win_rate_a:.3f} "
    f"({block.wins_a}W/{block.wins_b}L/{block.ties}T) "
    f"interval={block.wilson_interval_a}",
    flush=True,
)

n = block.n
even_baseline = harness.BlockResult(
    n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
    win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
)
print(f"  even-odds baseline interval at n={n}: {even_baseline.wilson_interval_a}")
accepted = tuning.accept_candidate(block, even_baseline)
print(f"  accept_candidate (vs even-odds at n={n}): {accepted}", flush=True)
