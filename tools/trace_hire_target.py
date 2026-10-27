"""Trace the day-plan hire target by hour (inputs of strategy.hires_per_day) in one self-play game.

Usage: python tools/trace_hire_target.py <seed> [first_day] [last_day]. Not part of the committed test suite.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kaggle_environments import make
import kagg.policy.strategy as strat
import kagg.policy.decide as dec
import kagg.agent_main as am

LOG = []
orig = strat.hires_per_day
def wrapped(params=None, **kw):
    r = orig(params, **kw)
    LOG.append(dict(hour=kw.get("hour"), target=r, maint=kw.get("maintenance_actions_today"),
                    new_tiles=kw.get("planned_new_crop_tiles"), new_animals=kw.get("planned_new_animals"),
                    free=kw.get("free_tiles")))
    return r
dec.hires_per_day = wrapped
seed = int(sys.argv[1]); d0 = int(sys.argv[2]) if len(sys.argv) > 2 else 8; d1 = int(sys.argv[3]) if len(sys.argv) > 3 else 8
HIRES = {}
def agent(obs):
    LOG.clear()
    out = am.agent(obs)
    n = sum(1 for o in out.get("market", []) if o and o[0] == "HIRE")
    hd = None
    try:
        hd = obs["farms"][obs["player"]]["hires_today"] if "player" in obs else obs["farms"][0].get("hires_today")
    except Exception:
        pass
    if d0 <= obs.get("day", -1) <= d1 and (n or obs["hour"] == 0):
        l = LOG[-1] if LOG else {}
        print(f"d{obs['day']:>2} h{obs['hour']:>2} units {1+len(obs['farms'][0]['hands']):>2} hires_now {n} target {l.get('target')} maint {l.get('maint')} new_tiles {l.get('new_tiles')} new_animals {l.get('new_animals')} free {l.get('free')}")
    return out
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
env.run([agent, "starter"])
