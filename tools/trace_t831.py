"""T8.31 trace: seed 900, comparing the checked-in baseline
(always_pursue_one_animal=False, the default) against the candidate
(always_pursue_one_animal=True) - both run with otherwise bit-identical
DEFAULT_PARAMS, matching measure_t831.py's own comparison.

Reports, per day: hand count at hour 1 (matching this project's own
established trace convention), total planted tile count, total placed
animal count, money, and unlocked quadrant count - to directly confirm
whether an animal is actually acquired now (not just structurally
possible) and what it costs/produces relative to the baseline's zero-
animal trajectory.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t831_trace_workdir"
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
    final_animal_tiles = [
        t for row in final_farm["tiles"] for t in row if isinstance(t, dict) and "animal" in t
    ]
    print(f"  final animal tiles: {len(final_animal_tiles)} "
          f"({[t['animal'] for t in final_animal_tiles]})")
    print()


baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_params = dict(DEFAULT_PARAMS, always_pursue_one_animal=True)
candidate_agent = tuning.write_candidate_agent(candidate_params, WORKDIR)

trace(baseline_agent, "baseline (always_pursue_one_animal=False)")
trace(candidate_agent, "T8.31 candidate (always_pursue_one_animal=True)")
