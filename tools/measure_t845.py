"""T8.45: bulk seed/animal purchase (+ plant_while_animal_pending).

The user's own request after a per-hour day-0 trace: only 21 of 24 planned
tiles were planted despite 33 idle unit-turns - the seed purchase
(`labor_units * seed_buffer_per_unit`, ~5 at a time) ran dry late in the day,
and a bought-but-unplaced animal blocked all planting in the morning.

Grid: each mechanism alone and combined, under the shipped hiring (min=8=max)
and under the T8.44 day-plan hiring (which needs more seeds than the old
trickle could supply). 50-seed working block, automatic 200-seed holdout for
the best candidate that clears 0.58 / accept_candidate. `use_fertilizer` stays
at its shipped False. Not part of the committed test suite.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

assert DEFAULT_PARAMS.get("use_fertilizer") is False

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t845_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
LARGE_SEEDS = list(range(900, 1100))
baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)


def evaluate(params, seeds):
    return harness.run_block(tuning.write_candidate_agent(params, WORKDIR), baseline_agent, seeds, jobs=None)


def _even_baseline(n):
    return harness.BlockResult(
        n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0, win_rate_a=0.5,
        wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
    )


def P(**kw):
    return dict(DEFAULT_PARAMS, **kw)


DAY_PLAN = dict(day_plan_hiring_aware=True, min_hires_per_day=2, max_hires_per_day=12)
GRID = [
    ("baseline (shipped)", P()),
    ("seeds only", P(bulk_seed_purchase=True)),
    ("seeds, no buffer", P(bulk_seed_purchase=True, bulk_seed_buffer_fraction=0.0)),
    ("seeds + animals", P(bulk_seed_purchase=True, bulk_animal_purchase=True)),
    ("seeds + plant_while_animal_pending", P(bulk_seed_purchase=True, plant_while_animal_pending=True)),
    ("seeds + animals + plant_while_pending",
     P(bulk_seed_purchase=True, bulk_animal_purchase=True, plant_while_animal_pending=True)),
    ("plant_while_pending alone", P(plant_while_animal_pending=True)),
    ("day-plan min=2, all three on",
     P(bulk_seed_purchase=True, bulk_animal_purchase=True, plant_while_animal_pending=True, **DAY_PLAN)),
    ("day-plan min=4, all three on",
     P(bulk_seed_purchase=True, bulk_animal_purchase=True, plant_while_animal_pending=True,
       **dict(DAY_PLAN, min_hires_per_day=4))),
]

print(f"=== T8.45: bulk purchase grid on {len(WORKING_SEEDS)} working seeds ===")
results = {}
for name, params in GRID:
    block = evaluate(params, WORKING_SEEDS)
    accepted = tuning.accept_candidate(block, _even_baseline(block.n))
    print(f"  {name}: win_rate={block.win_rate_a:.3f} ({block.wins_a}W/{block.wins_b}L/{block.ties}T) "
          f"interval={block.wilson_interval_a} accept_candidate={accepted}", flush=True)
    results[name] = (params, block, accepted)

worth = [(n, p, b) for n, (p, b, a) in results.items() if n != GRID[0][0] and (a or b.win_rate_a >= 0.58)]
if not worth:
    print("\nNo candidate meaningfully beats baseline on the working block. Null result.")
else:
    name, params, block = max(worth, key=lambda t: t[2].win_rate_a)
    print(f"\nBest working-block candidate: {name} ({block.win_rate_a:.3f}) -> {len(LARGE_SEEDS)}-seed holdout")
    cb = evaluate(params, LARGE_SEEDS)
    ok = tuning.accept_candidate(cb, _even_baseline(cb.n))
    print(f"  confirm: win_rate={cb.win_rate_a:.3f} ({cb.wins_a}W/{cb.wins_b}L/{cb.ties}T) "
          f"interval={cb.wilson_interval_a} accept_candidate={ok}")
    print(f"\nVerdict: {'ACCEPTED' if ok else 'REJECTED on holdout'} - {name}")
