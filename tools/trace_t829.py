"""T8.29 trace: seed 900, comparing the checked-in baseline at HEAD (the
labor_units bug: `1 + hires_per_day(params)` called bare, always falling
through to the static fallback) against the current working tree (the
fix: an early, forecast-aware hires_per_day(...) call using the real
tile counts/hour/money/days_remaining) - both run with bit-identical
DEFAULT_PARAMS, matching measure_t829.py's own comparison.

Reports, per day: hand count at hour 1 (post-hire, matching T8.16(d)/
T8.27/T8.28's own trace convention), total planted tile count, total
placed animal count, money, and unlocked quadrant count - to directly
confirm or refute the causal story in kagg.policy.decide's own T8.29
comment: does the fix actually move hand count off the flat-2 floor,
reinvest cash faster, open more quadrants sooner, and/or acquire any
animal, or does it leave the symptom chain unchanged?

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t829_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 900


def trace(agent_path: str, label: str) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=False)
    env.run([agent_path, "pass"])
    steps = env.steps

    rows = []
    for s in steps:
        obs = s[0].observation
        farm = obs["farms"][0]
        day = obs.get("day")
        hour = obs.get("hour")
        if hour == 1:
            hands = len(farm.get("hands", []))
            n_plant = sum(
                1 for row in farm["tiles"] for t in row
                if isinstance(t, dict) and t.get("kind") == "PLANT"
            )
            n_animal = sum(
                1 for row in farm["tiles"] for t in row
                if isinstance(t, dict) and "animal" in t
            )
            n_quadrants = len(farm.get("unlocked_quadrants", []))
            rows.append([day, hands, n_plant, n_animal, farm["money"], n_quadrants])

    final_farm = steps[-1][0].observation["farms"][0]
    print(f"=== {label} (seed {SEED}) ===")
    print("  day: hands  plant_tiles  animal_tiles  money  quadrants")
    for day, hands, n_plant, n_animal, money, n_quadrants in rows:
        print(f"    day {day:>2}: {hands}  {n_plant:>3}  {n_animal}  {money:>7}  {n_quadrants}")
    print(f"  final money: {final_farm['money']}")
    print(f"  final animal tiles: "
          f"{sum(1 for row in final_farm['tiles'] for t in row if isinstance(t, dict) and 'animal' in t)}")
    print()


baseline_agent = tuning.snapshot_agent_from_git_ref("HEAD", WORKDIR, params=DEFAULT_PARAMS)
fixed_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

trace(baseline_agent, "HEAD baseline (labor_units bug: bare hires_per_day(params) call)")
trace(fixed_agent, "T8.29 fix (early, forecast-aware hires_per_day(...) call)")
