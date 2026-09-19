"""T8.46: two-step "sell everything, then buy seeds on the real post-sale prices".

`drip_sell_max_per_turn` large = dump premium goods in one order;
`defer_seed_purchase_on_crop_sale=10` = no BUY_SEED in a turn that sells >=10
crop units (the next observation carries the real post-sale prices).
Grid: reference points from T8.45 plus each half and both halves, under the
T8.44 day-plan min=2 config the user is diagnosing and under the shipped
hiring. 50-seed working block, automatic 200-seed holdout for the best point
that clears 0.58. Not part of the committed test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

assert DEFAULT_PARAMS.get("use_fertilizer") is False
WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t846_workdir"
os.makedirs(WORKDIR, exist_ok=True)
blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
LARGE_SEEDS = list(range(900, 1100))
baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)


def evaluate(params, seeds):
    return harness.run_block(tuning.write_candidate_agent(params, WORKDIR), baseline_agent, seeds, jobs=None)


def _even(n):
    return harness.BlockResult(n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0, win_rate_a=0.5,
                               wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=())


def P(**kw):
    return dict(DEFAULT_PARAMS, **kw)


BULK = dict(bulk_seed_purchase=True, bulk_animal_purchase=True, plant_while_animal_pending=True)
DUMP = dict(drip_sell_max_per_turn=1000)
DEFER = dict(defer_seed_purchase_on_crop_sale=10)
DP2 = dict(day_plan_hiring_aware=True, min_hires_per_day=2, max_hires_per_day=12)
DP4 = dict(DP2, min_hires_per_day=4)
GRID = [
    ("baseline (shipped)", P()),
    ("day-plan min=2 + T8.45 bundle (reference)", P(**DP2, **BULK)),
    ("... + dump", P(**DP2, **BULK, **DUMP)),
    ("... + dump + defer  [the two-step]", P(**DP2, **BULK, **DUMP, **DEFER)),
    ("min=4 + bundle + dump + defer", P(**DP4, **BULK, **DUMP, **DEFER)),
    ("shipped hiring: dump only", P(**DUMP)),
    ("shipped hiring: dump + defer (legacy seeds)", P(**DUMP, **DEFER)),
    ("shipped hiring: bulk seeds + dump + defer", P(bulk_seed_purchase=True, **DUMP, **DEFER)),
    ("shipped hiring: full bundle + dump + defer", P(**BULK, **DUMP, **DEFER)),
]
print(f"=== T8.46 grid on {len(WORKING_SEEDS)} working seeds ===")
res = {}
for name, params in GRID:
    b = evaluate(params, WORKING_SEEDS)
    ok = tuning.accept_candidate(b, _even(b.n))
    print(f"  {name}: win_rate={b.win_rate_a:.3f} ({b.wins_a}W/{b.wins_b}L/{b.ties}T) "
          f"interval={b.wilson_interval_a} accept_candidate={ok}", flush=True)
    res[name] = (params, b, ok)
worth = [(n, p, b) for n, (p, b, a) in res.items() if n != GRID[0][0] and (a or b.win_rate_a >= 0.58)]
if not worth:
    print("\nNo candidate meaningfully beats baseline on the working block. Null result.")
else:
    n, p, b = max(worth, key=lambda t: t[2].win_rate_a)
    print(f"\nBest: {n} ({b.win_rate_a:.3f}) -> {len(LARGE_SEEDS)}-seed holdout")
    cb = evaluate(p, LARGE_SEEDS)
    ok = tuning.accept_candidate(cb, _even(cb.n))
    print(f"  confirm: win_rate={cb.win_rate_a:.3f} ({cb.wins_a}W/{cb.wins_b}L/{cb.ties}T) "
          f"interval={cb.wilson_interval_a} accept_candidate={ok}")
    print(f"\nVerdict: {'ACCEPTED' if ok else 'REJECTED on holdout'} - {n}")
