"""T8.26: measure workload_forecast_hiring_aware (the proactive,
tile-count-derived hiring forecast) - the user's own proposed formula,
ported from tools/analyze_unit_economics.py into strategy.py's
hires_per_day().

Two stages, per T8.3b discipline:

1. **Alone, crop-only farm**: sanity check against the T8.16(d) baseline
   (dynamic_hiring's existing reactive path) - no animals in play, so this
   isolates whether the proactive forecast changes anything (for better or
   worse) on its own, before combining with the animal-economics stack.

2. **The real payoff test**: combined with T8.25's measured findings
   (tools/measure_t825.py/measure_t825b.py - `wheat_urgency_reserve=3`
   alone, cap unchanged at 40, found bit-identical to raising the cap
   outright, and closed T8.22's `max_animals_per_type` rejection from
   14%/14% to 40%/44% at cap=3 without reversing it) plus
   `max_animals_per_type` at 3 and 4 - does proactively sizing the labor
   force from real tile counts (instead of reacting to the visible
   backlog one day late) finally close the remaining gap, or reverse it
   into a real win?

**Prediction stated up front**: genuinely uncertain. T8.22's own trace
found hands sitting idle on PLANT while FEED starved on the worst days -
if that was actually a hiring *ramp lag* (the reactive formula only
learns about tomorrow's larger workload from today's backlog, one day
after the tile count that caused it already existed), a forecast that
knows the real tile count at hour 0 should show hand count jumping
immediately at the start of a day instead of ramping through it. If
escapes still happen even with wheat available (T8.25) and hands
proactively sized (this), that's real evidence a third factor (FEED-vs-
PLANT task priority) is still binding - named in the plan, not built here.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t826_workdir"
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


print("########## STAGE 1: workload_forecast_hiring_aware alone (crop-only) vs T8.16(d) baseline ##########", flush=True)
measure(
    "workload_forecast_hiring_aware=True vs plain baseline",
    dict(DEFAULT_PARAMS, workload_forecast_hiring_aware=True),
    DEFAULT_PARAMS,
)

print("########## STAGE 2: T8.25 fix + T8.26 forecast + max_animals_per_type sweep vs plain baseline ##########", flush=True)
for cap in (3, 4):
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
        "+ workload_forecast_hiring_aware) vs plain baseline",
        FULL_STACK,
        DEFAULT_PARAMS,
    )
