"""T8.48: hold BUY_SEED while >= N HARVEST / WATER tasks (which outrank PLANT) are queued.

Grid over `seed_purchase_max_pending_harvest` / `_water` (None = off) against the shipped
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

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd7")
os.makedirs(W, exist_ok=True)
H, WT = "seed_purchase_max_pending_harvest", "seed_purchase_max_pending_water"
GRID = {"shipped": {}, "H<4": {H: 4}, "H<8": {H: 8}, "W<4": {WT: 4}, "W<8": {WT: 8}, "W<12": {WT: 12},
        "H<4+W<8": {H: 4, WT: 8}, "H<8+W<8": {H: 8, WT: 8}, "H<8+W<12": {H: 8, WT: 12}}
PATH = {k: tuning.write_candidate_agent(dict(DEFAULT_PARAMS, **v), W) for k, v in GRID.items()}


def job(a):
    n, o, s = a
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": s}, debug=False)
    env.run([PATH[n], o]); return n, o, s, env.steps[-1][0].reward


if __name__ == "__main__":
    seeds = list(range(1, 21))
    with Pool(4) as p:
        res = p.map(job, [(n, o, s) for n in GRID for o in ("starter", "pass") for s in seeds])
    m = {(n, o, s): r for n, o, s, r in res}
    blocks = harness.load_seed_blocks()
    for n in GRID:
        ext = []
        for o in ("starter", "pass"):
            base = sum(m[("shipped", o, s)] for s in seeds); v = sum(m[(n, o, s)] for s in seeds)
            ext.append(f"{o} {v / len(seeds):>7.0f} ({100 * (v - base) / base:+.1f}%)")
        if n == "shipped":
            print(f"{n:10s} | " + " | ".join(ext), flush=True); continue
        b = harness.run_block(PATH[n], PATH["shipped"], list(blocks.tuning_seeds), jobs=None)
        print(f"{n:10s} | " + " | ".join(ext) + f" | arena vs shipped {b.wins_a}W/{b.wins_b}L win_rate={b.win_rate_a:.2f}", flush=True)
