"""T8.25: measure the WHEAT feed-restock price-ceiling fix.

Not part of the committed test suite - a one-off measurement run.

Root cause (see /root/.claude/plans/jazzy-jumping-lamport.md's Context
section for the full traced story): `wheat_max_buy_price` (kagg.policy.
market._DEFAULT_WHEAT_MAX_BUY_PRICE = 40) is a static, never-swept cap
that silently blocks ALL WHEAT feed restocking once market price drifts
past it - which happens in every sufficiently long game, independent of
animal count, because nobody grows WHEAT at scale (T8.24's own finding).
Traced directly: a 4-5 animal farm (T8.22's own scenario) hits a 10-day
feed drought starting ~day 17, matching T8.22's actual escape events
(turns 504/528/624) exactly.

Three stages, per T8.3b discipline (isolate before combining):

1. **Part 1 alone**: sweep `wheat_max_buy_price` (80, 150, effectively
   unbounded) against the T8.17 "full care" baseline (animal_care_aware +
   animal_fertilizer_income_aware, cap=40 unchanged) - does raising the
   cap alone move that result?
2. **Part 2 on top of the Part 1 winner**: add `wheat_urgency_reserve`
   (an override that ignores the cap entirely once wheat_on_hand is
   critically low) - does it help further, e.g. against a future
   contested-demand price spike even a generously raised cap might not
   anticipate?
3. **The real payoff test**: re-run T8.22's *exact* `max_animals_per_type`
   sweep (2, 3, 4) - which was decisively rejected (28%/24% -> 14%/14% ->
   2%/4%) - with the full price fix from stages 1-2 folded in, against the
   same plain DEFAULT_PARAMS baseline T8.22 used. If the price-ceiling bug
   is really the dominant cause, this sweep should look nothing like its
   original monotonic collapse.

**Prediction stated up front**: Part 1 (raising/removing the cap) should
show a real, positive effect once combined with real feed demand - WHEAT
is cheap in absolute terms ($1500 for a full restock even at $150/unit
against a farm holding $30k+) next to what an escaped animal costs. Part
2's incremental value on top of Part 1 is less certain - genuinely
uncertain whether it matters once Part 1 alone already prevents the
cap from ever binding at the prices this session has observed (<$50 even
after a sustained drought). Stage 3 is the test that actually matters:
does fixing the price unlock T8.22's rejected multi-animal mechanism.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t825_workdir"
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


print("########## STAGE 1: wheat_max_buy_price sweep (full-care baseline) ##########", flush=True)
for cap in (80, 150, 1_000_000):
    measure(
        f"wheat_max_buy_price={cap} vs full-care baseline (cap=40)",
        dict(FULL_CARE, wheat_max_buy_price=cap),
        FULL_CARE,
    )

print("########## STAGE 2: wheat_urgency_reserve on top of Part 1 (cap=1_000_000) ##########", flush=True)
STAGE1_WINNER = dict(FULL_CARE, wheat_max_buy_price=1_000_000)
for reserve in (3,):
    measure(
        f"wheat_urgency_reserve={reserve} vs cap=1_000_000 alone",
        dict(STAGE1_WINNER, wheat_urgency_reserve=reserve),
        STAGE1_WINNER,
    )

print("########## STAGE 3: T8.22's exact max_animals_per_type sweep, price fix folded in ##########", flush=True)
FULL_FIX = dict(
    DEFAULT_PARAMS,
    animal_care_aware=True,
    animal_fertilizer_income_aware=True,
    parallel_animal_acquisition=True,
    wheat_max_buy_price=1_000_000,
    wheat_urgency_reserve=3,
)
for cap in (2, 3, 4):
    measure(
        f"max_animals_per_type={cap} (full care + parallel acquisition + price fix) vs plain baseline",
        dict(FULL_FIX, max_animals_per_type=cap),
        DEFAULT_PARAMS,
    )
