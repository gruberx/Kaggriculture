"""T8.58: does the agent harvest one-time crops before that day's watering (losing the last bonus)?

For every HARVEST in a self-play episode (current shipped defaults vs `starter`): the yield taken against the
yield attainable with the plan's daily watering (1 + the bonus-window ages up to the harvest age, capped at
`max_yield`), and whether the tile had been watered that day. Ongoing crops and animals: units per harvest.
Usage: python tools/check_harvest_before_water.py <seed> [json param overrides]. Not part of the committed test suite.
"""
import os, sys, json
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning
from kaggle_environments import make
from kagg.policy.params import DEFAULT_PARAMS
from kagg.gamelib.constants import CROPS, ANIMALS
from kagg.gamelib.growth import watering_bonus_window
seed = int(sys.argv[1])
W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wha%d" % seed); os.makedirs(W, exist_ok=True)
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
params = dict(DEFAULT_PARAMS)
if len(sys.argv) > 2:
    params.update(json.loads(sys.argv[2]))  # e.g. '{"harvest_water_first": true}'
env.run([tuning.write_candidate_agent(params, W), "starter"])
st = env.steps
S = defaultdict(lambda: defaultdict(int))
for t in range(len(st) - 1):
    obs = st[t][0].observation; act = st[t + 1][0].action
    if not act: continue
    farm = obs.farms[0]; tiles = farm["tiles"]
    units = [tuple(farm["farmer"])] + [tuple(h) for h in farm["hands"]]
    ops = [act.get("farmer", ["PASS"])] + list(act.get("hands", []))
    watered_now = set(); done = set()
    for pos, op in zip(units, ops):
        if not op: continue
        x, y = pos; tile = tiles[y][x]
        if op[0] == "WATER": watered_now.add(pos)
        if op[0] != "HARVEST" or not isinstance(tile, dict) or pos in done: continue
        if tile.get("kind") == "PLANT":
            crop = tile["crop"]; cd = CROPS[crop]; day = obs["day"]; age = day - tile["planted_day"]; y_at = tile["yield_units"]
            if y_at <= 0: continue
            done.add(pos)
            s = S[crop]; s["n"] += 1; s["units"] += y_at
            if cd["ongoing"]:
                s[f"y{y_at}"] += 1; s[f"a{age}"] += 1
            else:
                watered = tile["watered_today"] or pos in watered_now
                win = watering_bonus_window(crop)
                last = (not watered) and age in win and y_at < cd["max_yield"]
                s["last_day_lost"] += int(last)
                # attainable with the daily watering the plan assumes: 1 + ages in window that are <= harvest age
                attain = min(cd["max_yield"], 1 + sum(1 for a in win if a <= age))
                s["attainable"] += attain; s["got"] += y_at
        elif "animal" in tile:
            a = tile["animal"]; y_at = tile["yield_units"]
            if y_at > 0:
                done.add(pos); s = S[a]; s["n"] += 1; s["units"] += y_at; s[f"y{y_at}"] += 1
print(f"seed {seed} final {st[-1][0]['reward']:.0f}")
for k, s in S.items():
    if k in ("WHEAT", "CARROT", "MELON"):
        print(f"  {k}: {s['n']} harvests, got {s['got']} of attainable {s['attainable']} ({100*s['got']/s['attainable']:.0f}%); last-day (harvest before water) lost {s['last_day_lost']} units in {s['last_day_lost']} harvests")
    else:
        ys = {kk[1:]: v for kk, v in s.items() if kk.startswith("y")}
        ages = {kk[1:]: v for kk, v in s.items() if kk.startswith("a")}
        print(f"  {k}: {s['n']} harvests, avg units {s['units']/s['n']:.2f}; by units {dict(sorted(ys.items(), key=lambda kv:int(kv[0])))}" + (f"; by age {dict(sorted(ages.items(), key=lambda kv:int(kv[0])))}" if ages else ""))
