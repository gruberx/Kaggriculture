"""T8.66: drop goods into the shed at once when a unit is near it. Not part of the committed test suite."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiprocessing import Pool  # noqa: E402

import harness  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd66")
os.makedirs(W, exist_ok=True)
GRID = {
    "base (off)": {},
    "d=0 days<11": {"drop_near_shed_distance": 0, "drop_near_shed_max_day": 11},
    "d=0 days<11 +fertilizer": {"drop_near_shed_distance": 0, "drop_near_shed_max_day": 11, "drop_near_shed_fertilizer": True},
    "d=0 days<8 +fertilizer": {"drop_near_shed_distance": 0, "drop_near_shed_max_day": 8, "drop_near_shed_fertilizer": True},
}
PATH = {k: tuning.write_candidate_agent(dict(DEFAULT_PARAMS, **v), W) for k, v in GRID.items()}
BASE = "base (off)"


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
            base = sum(m[(BASE, o, s)] for s in seeds); v = sum(m[(n, o, s)] for s in seeds)
            wins = sum(1 for s in seeds if m[(n, o, s)] > m[(BASE, o, s)])
            ext.append(f"{o} {v / len(seeds):>7.0f} ({100 * (v - base) / base:+.1f}%, better {wins}/{len(seeds)})")
        print(f"{n:30s} | " + " | ".join(ext), flush=True)
