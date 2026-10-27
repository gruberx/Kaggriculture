"""T8.64: hire forecast raised in the morning (hire_buffer_fraction / turns_per_task_estimate / horizon), with the
share of hires made after hour 0. Not part of the committed test suite."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiprocessing import Pool  # noqa: E402

import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd64")
os.makedirs(W, exist_ok=True)
GRID = {
    "base": {},
    "full-day + tpt 2.5": {"day_plan_remaining_turns_aware": False, "turns_per_task_estimate": 2.5},
    "full-day + tpt 2.75": {"day_plan_remaining_turns_aware": False, "turns_per_task_estimate": 2.75},
    "full-day + tpt 3.0": {"day_plan_remaining_turns_aware": False, "turns_per_task_estimate": 3.0},
    "full-day + tpt 3.5": {"day_plan_remaining_turns_aware": False, "turns_per_task_estimate": 3.5},
    "full-day+2.5+buf .125": {"day_plan_remaining_turns_aware": False, "turns_per_task_estimate": 2.5, "hire_buffer_fraction": 0.125},
}
PATH = {k: tuning.write_candidate_agent(dict(DEFAULT_PARAMS, **v), W) for k, v in GRID.items()}
BASE = "base"


def job(a):
    n, o, s = a
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": s}, debug=False)
    env.run([PATH[n], o])
    st = env.steps
    late = total = 0
    for t in range(len(st) - 1):
        act = st[t + 1][0].action
        if not act:
            continue
        k = sum(1 for x in act.get("market", []) if x and x[0] == "HIRE")
        total += k
        if st[t][0].observation["hour"] > 0:
            late += k
    return n, o, s, st[-1][0].reward, late, total


if __name__ == "__main__":
    seeds = list(range(1, 41))
    with Pool(4) as p:
        res = p.map(job, [(n, o, s) for n in GRID for o in ("starter", "pass") for s in seeds])
    m = {(n, o, s): r for n, o, s, r, _, _ in res}
    for n in GRID:
        ext = []
        for o in ("starter", "pass"):
            base = sum(m[(BASE, o, s)] for s in seeds); v = sum(m[(n, o, s)] for s in seeds)
            wins = sum(1 for s in seeds if m[(n, o, s)] > m[(BASE, o, s)])
            ext.append(f"{o} {v / len(seeds):>7.0f} ({100 * (v - base) / base:+.1f}%, better {wins}/{len(seeds)})")
        late = sum(l for nn, o, s, r, l, t in res if nn == n); tot = sum(t for nn, o, s, r, l, t in res if nn == n)
        print(f"{n:20s} | " + " | ".join(ext) + f" | hires/game {tot / (2 * len(seeds)):.0f}, after hour 0: {100 * late / tot:.0f}%", flush=True)
