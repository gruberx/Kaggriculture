"""T8.23: verify (not assume) that crop+animal coexistence emerges
naturally from plant_while_pursuing_animal (T8.9, on by default) once an
animal is genuinely worth pursuing - the user's own diversification
hypothesis ("melon + milk won't crash one market as hard as melon alone").

Scoped to the single-animal case only: T8.22's max_animals_per_type>1 was
measured and decisively rejected (tools/measure_t822.py) - the "repeated
same-type stacking starves crop planting via stuck_animal" risk T8.23's
own plan section named as its fallback-fix trigger cannot arise in the
shipped default (max_animals_per_type stays 1), so this traces the
scenario that's actually viable: animal_care_aware=True (T8.17's closest
lead to parity, 48%/56%), everything else default.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.gamelib.constants import ANIMALS  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t823_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 900

CANDIDATE_PARAMS = dict(DEFAULT_PARAMS, animal_care_aware=True)


def crop_tile_counts(farm) -> dict:
    counts: dict[str, int] = {}
    for row in farm["tiles"]:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "PLANT" and "crop" in t:
                counts[t["crop"]] = counts.get(t["crop"], 0) + 1
    return counts


def has_animal(farm) -> bool:
    return any(
        isinstance(t, dict) and "animal" in t for row in farm["tiles"] for t in row
    )


def trace(agent_path: str, label: str) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=False)
    env.run([agent_path, "pass"])
    steps = env.steps

    # Only count farmer-hour turns (hour == 0 decisions happen once/day, but
    # PLANT tasks can be assigned to hands on any turn) - approximate "was an
    # animal being pursued/held this turn" as "farm has an animal tile OR the
    # farmer/any hand's action targets BUY_ANIMAL/PLACE/BUILD_COOP/
    # BUILD_PASTURE/FEED/CARE this turn".
    animal_pursuit_turns = 0
    plant_during_pursuit = 0
    plant_during_animal_free = 0
    animal_actions = {"BUY_ANIMAL", "PLACE", "BUILD_COOP", "BUILD_PASTURE", "FEED", "CARE"}
    for s in steps:
        farm = s[0].observation["farms"][0]
        action = s[0].action or {}
        all_actions = [action.get("farmer")] + list(action.get("hands", []))
        is_pursuit_turn = has_animal(farm) or any(
            a and a[0] in animal_actions for a in all_actions if a
        )
        planted_this_turn = any(a and a[0] == "PLANT" for a in all_actions if a)
        if is_pursuit_turn:
            animal_pursuit_turns += 1
            if planted_this_turn:
                plant_during_pursuit += 1
        elif planted_this_turn:
            plant_during_animal_free += 1

    final_farm = steps[-1][0].observation["farms"][0]
    final_market = steps[-1][0].observation["market"]["inventory"]
    print(f"=== {label} (seed {SEED}) ===")
    print(f"  final money: {final_farm['money']}")
    print(f"  final crop-tile diversity: {crop_tile_counts(final_farm)}")
    print(f"  final animal tiles: {sum(1 for row in final_farm['tiles'] for t in row if isinstance(t, dict) and 'animal' in t)}")
    print(f"  animal-pursuit-or-held turns: {animal_pursuit_turns} / {len(steps)}")
    print(f"    of which a PLANT also happened this turn: {plant_during_pursuit}")
    print(f"  animal-free turns with a PLANT: {plant_during_animal_free}")
    print(f"  final MELON market inventory: {final_market.get('MELON')}, MILK: {final_market.get('MILK')}")


baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_agent = tuning.write_candidate_agent(CANDIDATE_PARAMS, WORKDIR)

trace(baseline_agent, "baseline (DEFAULT_PARAMS, animal_care_aware=False)")
trace(candidate_agent, "candidate (animal_care_aware=True)")
