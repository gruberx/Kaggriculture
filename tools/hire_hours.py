"""When in the day are hands hired? Tally HIRE orders by hour over self-play games (current shipped defaults vs starter).

Usage: python tools/hire_hours.py [n_seeds]. Not part of the committed test suite.
"""
import os, sys
from collections import Counter
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning
from kaggle_environments import make
from kagg.policy.params import DEFAULT_PARAMS
W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "hh"); os.makedirs(W, exist_ok=True)
PATH = tuning.write_candidate_agent(dict(DEFAULT_PARAMS), W)

def job(seed):
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([PATH, "starter"])
    st = env.steps
    by_hour, by_day_late, days_with_late, days_with_hire = Counter(), 0, 0, 0
    per_day = {}
    for t in range(len(st) - 1):
        act = st[t + 1][0].action
        if not act: continue
        n = sum(1 for o in act.get("market", []) if o and o[0] == "HIRE")
        if n:
            o = st[t][0].observation
            by_hour[o["hour"]] += n
            d = per_day.setdefault(o["day"], [0, 0]); d[0] += n
            if o["hour"] > 0: d[1] += n
    return seed, by_hour, per_day

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    with Pool(4) as p:
        res = p.map(job, range(1, n + 1))
    tot, late, days_h, days_l, tot_h = Counter(), 0, 0, 0, 0
    for seed, bh, pd in res:
        tot.update(bh)
        for day, (all_, lt) in pd.items():
            days_h += 1; tot_h += all_; late += lt; days_l += int(lt > 0)
    print("games", n, "hires", tot_h, "hires not at hour 0:", late, f"({100*late/tot_h:.0f}%)")
    print("hire-days", days_h, "of which with any hire after hour 0:", days_l, f"({100*days_l/days_h:.0f}%)")
    print("by hour:", dict(sorted(tot.items())))
