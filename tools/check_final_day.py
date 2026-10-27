"""Final-day audit: what is left unsold at the end (unit inventories, shed stock, ready-but-uncollected tiles).

Usage: python tools/check_final_day.py <seed> [json param overrides]. Not part of the committed test suite.
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning
from kaggle_environments import make
from kagg.policy.params import DEFAULT_PARAMS
from kagg.gamelib.constants import CROPS
seed = int(sys.argv[1])
W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "fd%d" % seed); os.makedirs(W, exist_ok=True)
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
params = dict(DEFAULT_PARAMS)
if len(sys.argv) > 2:
    params.update(json.loads(sys.argv[2]))
env.run([tuning.write_candidate_agent(params, W), "starter"])
st = env.steps
print("seed", seed, "reward", st[-1][0]["reward"], "steps", len(st))
for t in list(range(len(st) - 26, len(st))):
    o = st[t][0].observation
    f = o.farms[0]
    inv = o.get("private", {}).get("inventories") if isinstance(o.get("private"), dict) else None
    carried = {}
    for i in (inv or []):
        for k, v in i.items():
            if v > 0: carried[k] = carried.get(k, 0) + v
    shed = o.get("private", {}).get("shed") if isinstance(o.get("private"), dict) else None
    ready = sum(x.get("yield_units", 0) for row in f["tiles"] for x in row if isinstance(x, dict) and x.get("yield_units", 0) > 0)
    print(t, "day", o["day"], "hour", o.get("hour"), "money", o.farms[0].get("money"), "carried", carried, "shed", shed, "tile_yield", ready, "hands", len(f["hands"]))
