"""T8.25 follow-up: Stage 1 of measure_t825.py found that raising
wheat_max_buy_price unconditionally is a real, small, but consistent net
loss for the single-animal scenario (traced directly: price does cross
$40 in these seeds, ~48-53, and the raised cap just buys the same
already-surviving buffer back at a worse price - no escape was ever at
risk there to begin with, so there's no benefit, only the extra cost,
~$200-300/episode). Stage 3 found the *payoff* scenario (multi-animal,
cap=3/4) improves substantially with the full fix (cap=1_000_000 +
urgency_reserve=3 combined) but still nets an overall loss.

This isolates the more surgical alternative design: leave
wheat_max_buy_price at its unmodified default (40, never wasting money on
a non-critical restock at an elevated price) and rely ONLY on
wheat_urgency_reserve's override (fires only when wheat_on_hand is
critically low, i.e. exactly the real escape-risk window) - does this
avoid Stage 1's downside while still capturing most of Stage 3's upside?

**Prediction stated up front**: genuinely uncertain - the single-animal
case should now be a near no-op (or a small win, since the override is
this scenario's *only* chance to survive if price ever gets high enough
that the animal's buffer would otherwise run out, which the original
trace found happens right at the edge, day 29). The multi-animal case
is the real question: does an emergency-only override recover most of
Stage 3's gain (cap=3 went from 14%/14% to 40%/44% with the full fix)
without needing the general cap raised at all.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t825b_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

FULL_CARE = dict(DEFAULT_PARAMS, animal_care_aware=True, animal_fertilizer_income_aware=True)


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


print("########## urgency_reserve ALONE (cap stays 40), single-animal ##########", flush=True)
measure(
    "wheat_urgency_reserve=3, cap=40 unchanged vs full-care baseline",
    dict(FULL_CARE, wheat_urgency_reserve=3),
    FULL_CARE,
)

print("########## urgency_reserve ALONE (cap stays 40), max_animals_per_type=3 vs plain baseline ##########", flush=True)
URGENCY_ONLY_FIX = dict(
    DEFAULT_PARAMS,
    animal_care_aware=True,
    animal_fertilizer_income_aware=True,
    parallel_animal_acquisition=True,
    wheat_urgency_reserve=3,
    max_animals_per_type=3,
)
measure(
    "max_animals_per_type=3 (full care + parallel acquisition + urgency_reserve=3 only) vs plain baseline",
    URGENCY_ONLY_FIX,
    DEFAULT_PARAMS,
)
