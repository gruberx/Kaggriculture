"""T8.49: carry harvested goods to the shed mid-day and sell them the same turn.

Grid over the drop triggers and `bulk_purchase_counts_harvest_tiles` against the shipped
defaults: arena win rate on the 50 working seeds, plus final money vs the external
`starter`/`pass` opponents on 20 seeds. Not part of the committed test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiprocessing import Pool  # noqa: E402

import harness  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd27")
os.makedirs(W, exist_ok=True)
D = "drop_goods_to_shed"
OV, CA = "drop_goods_overflow_fraction", "drop_goods_cash_min_units"
RT = {"day_plan_remaining_turns_aware": True}
GRID = {"base (current defaults)": {}, "remaining-turns divisor": RT,
        "remaining-turns + min turns left 6": dict(RT, hire_min_turns_left=6),
        "remaining-turns + min turns left 12": dict(RT, hire_min_turns_left=12)}
PATH = {k: tuning.write_candidate_agent(dict(DEFAULT_PARAMS, **v), W) for k, v in GRID.items()}


def job(a):
    n, o, s = a
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": s}, debug=False)
    env.run([PATH[n], o]); return n, o, s, env.steps[-1][0].reward


if __name__ == "__main__":
    seeds = list(range(1, 41))
    with Pool(4) as p:
        res = p.map(job, [(n, o, s) for n in GRID for o in ("starter", "pass") for s in seeds])
    m = {(n, o, s): r for n, o, s, r in res}
    for n in GRID:
        ext = []
        for o in ("starter", "pass"):
            base = sum(m[("base (current defaults)", o, s)] for s in seeds); v = sum(m[(n, o, s)] for s in seeds)
            wins = sum(1 for s in seeds if m[(n, o, s)] > m[("base (current defaults)", o, s)])
            ext.append(f"{o} {v / len(seeds):>7.0f} ({100 * (v - base) / base:+.1f}%, better {wins}/{len(seeds)})")
        print(f"{n:36s} | " + " | ".join(ext), flush=True)
    import harness
    blocks = harness.load_seed_blocks()
    for name, x in (("remaining-turns", "remaining-turns divisor"), ("remaining-turns + min 6", "remaining-turns + min turns left 6"), ("remaining-turns + min 12", "remaining-turns + min turns left 12")):
        b = harness.run_block(PATH[x], PATH["base (current defaults)"], list(blocks.tuning_seeds), jobs=None)
        print(f"arena {name} vs base: {b.wins_a}W/{b.wins_b}L/{b.ties}T win_rate={b.win_rate_a:.2f}", flush=True)
