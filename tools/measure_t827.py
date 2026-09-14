"""T8.27: re-measure workload_forecast_hiring_aware now that
hires_per_day's workload-forecast branch calls the per-tile action
functions with scaling_only=True (excluding routine WATER/FEED/CARE/
COLLECT_FERTILIZER coverage ops from the marginal-hiring forecast, the
same distinction pending_task_count's own _ROUTINE_RECURRING_OPS exclusion
already draws for the reactive path - T8.16(a)).

Same two stages as tools/measure_t826.py, replacing its numbers - the flag
name and code path are unchanged, only the internal per-tile formula the
forecast now uses:

1. **Alone, crop-only farm** vs the T8.16(d) baseline - T8.26 lost this
   stage decisively (10%/0%), traced directly to the routine-ops miscount.
   Does the corrected forecast at least reach parity/no-loss here?

2. **The real payoff test**: combined with T8.25's measured
   `wheat_urgency_reserve=3` fix plus `max_animals_per_type` at 2/3/4 - does
   the corrected forecast improve meaningfully on T8.25-alone (cap=3:
   40%/44%), or even reverse the rejection?

**Prediction stated up front**: the routine-ops miscount was a real,
specific, well-diagnosed cause of T8.26's Stage-1 loss, so Stage 1 should
at least stop losing outright. Genuinely uncertain whether removing it is
*sufficient* - the forecast could still over/under-shoot for a different
reason (e.g. FERTILIZE's ceil(tile_days/3) term, or the -1 farmer's-own-
turn adjustment interacting differently with a now-smaller total). Stage 2
is the real test: if hands are correctly sized and wheat is available
(T8.25) but animals still lose value or escape, that points to FEED-vs-
PLANT task priority or animal self-impact as the next real blocker -
flagged, not built here (see the T8.27 plan).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t827_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)


def measure(label, candidate_params, baseline_params):
    print(f"=== {label} ===", flush=True)
    baseline_agent = tuning.write_candidate_agent(baseline_params, WORKDIR)
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
    print(flush=True)


print("########## STAGE 1: workload_forecast_hiring_aware (scaling_only, T8.27) alone (crop-only) vs T8.16(d) baseline ##########", flush=True)
measure(
    "workload_forecast_hiring_aware=True (T8.27 scaling_only fix) vs plain baseline",
    dict(DEFAULT_PARAMS, workload_forecast_hiring_aware=True),
    DEFAULT_PARAMS,
)

print("########## STAGE 2: T8.25 fix + T8.27 corrected forecast + max_animals_per_type sweep vs plain baseline ##########", flush=True)
for cap in (2, 3, 4):
    FULL_STACK = dict(
        DEFAULT_PARAMS,
        animal_care_aware=True,
        animal_fertilizer_income_aware=True,
        parallel_animal_acquisition=True,
        wheat_urgency_reserve=3,
        workload_forecast_hiring_aware=True,
        max_animals_per_type=cap,
    )
    measure(
        f"max_animals_per_type={cap} (full care + parallel acquisition + wheat_urgency_reserve=3 "
        "+ workload_forecast_hiring_aware [T8.27]) vs plain baseline",
        FULL_STACK,
        DEFAULT_PARAMS,
    )
