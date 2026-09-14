"""T8.29: measure the labor_units bug fix.

`labor_units = 1 + hires_per_day(params)` at decide.py's own line used to
be a bare call with no runtime arguments - `hour`/`pending_task_count`/
`animal_tile_counts`/`crop_tile_counts`/`days_remaining`/`money` all
omitted. Every real path inside hires_per_day (reactive pending_task_
count, proactive workload-forecast) needs at least one of those; with
none given, both fell straight through to the static fallback (default
1), so labor_units was hardcoded at 2 every turn of every game -
completely decoupled from dynamic_hiring (shipped default True since
T8.16(d)) and from the farm's real workload. See kagg.policy.decide's
own T8.29 comment (right above the fix) for the full causal story, and
tasks/todo.md's T8.29 entry for the live-trace evidence that motivated
this task (hand count pinned at 2 for all 30 days, cash stuck near the
$500-1000 floor, a single quadrant most of the game, zero animals ever
acquired).

This is a pure code fix, not a new named/swept parameter (unlike every
prior measure_t8*.py script) - there is nothing to toggle in DEFAULT_
PARAMS to reproduce the old behavior. The comparison is therefore the
current working tree (the fix, via tuning.write_candidate_agent, which
uses the live editable-installed kagg package) against the exact
checked-in baseline at HEAD (tuning.snapshot_agent_from_git_ref("HEAD",
...), a real git-archive snapshot of src/kagg as last committed - the
pre-fix code) - both run with bit-identical DEFAULT_PARAMS.

Not part of the committed test suite - a one-off tuning run.

**Prediction stated up front** (T8.3b): real gain is plausible and is
the whole point of this task - if the theory is right, previously-
throttled cash finally gets reinvested (bigger seed batches, more
simultaneous planting, earlier land purchases once tiles fill faster).
Genuinely uncertain in magnitude, and there's a real risk the fix alone
isn't enough - min_hires_per_day staying at 2 means the newly-unlocked
capacity might still be sized for a 2-hand farm; if so, that's the
natural T8.30 follow-up (re-sweep the hiring floor now that real
capacity exists for it to bind on), not chased here.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t829_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

print("=== T8.29: labor_units bug fix (current working tree) vs checked-in baseline (HEAD) ===")
print("Both run with bit-identical DEFAULT_PARAMS - only the labor_units call site differs.")

baseline_agent = tuning.snapshot_agent_from_git_ref("HEAD", WORKDIR, params=DEFAULT_PARAMS)
candidate_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

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
