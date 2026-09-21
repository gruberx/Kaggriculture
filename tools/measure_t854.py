"""T8.54: no PLANT on the last turn of the day (it can never be watered -> weed at midnight).

Flag on (shipped candidate) vs off: final money vs the external `starter`/`pass` opponents on
40 seeds, plus arena win rate on the working seeds. Not part of the committed test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiprocessing import Pool  # noqa: E402

import harness  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd28")
os.makedirs(W, exist_ok=True)
GRID = {"off": {"no_plant_on_last_turn": False}, "on": {"no_plant_on_last_turn": True}}
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
            base = sum(m[("off", o, s)] for s in seeds); v = sum(m[(n, o, s)] for s in seeds)
            wins = sum(1 for s in seeds if m[(n, o, s)] > m[("off", o, s)])
            ext.append(f"{o} {v / len(seeds):>7.0f} ({100 * (v - base) / base:+.1f}%, better {wins}/{len(seeds)})")
        print(f"{n:5s} | " + " | ".join(ext), flush=True)
    blocks = harness.load_seed_blocks()
    b = harness.run_block(PATH["on"], PATH["off"], list(blocks.tuning_seeds), jobs=None)
    print(f"arena on vs off: {b.wins_a}W/{b.wins_b}L/{b.ties}T win_rate={b.win_rate_a:.2f}", flush=True)
