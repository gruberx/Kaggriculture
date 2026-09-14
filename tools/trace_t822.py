"""T8.22 trace: max_animals_per_type's self-play sweep (2/3/4) was measured
as a decisive, monotonically worsening rejection (28%/24%, 14%/14%,
2%/4% working/holdout - tools/measure_t822.py) rather than a win. This
traces a real seed to confirm *why*, the same T8.3q-style diagnostic used
for every earlier "promised a mechanism the labor budget couldn't execute"
finding: animal tile count over time, feeding/care correctness (fraction
of animal-tiles fed/cared on their final observation, any escapes from
sustained neglect), crop-tile count, and final money - not just the win
rate.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t822_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 900

BASE_FULL_CARE = dict(
    DEFAULT_PARAMS,
    animal_care_aware=True,
    animal_fertilizer_income_aware=True,
    parallel_animal_acquisition=True,
)


def trace(agent_path: str, label: str) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=False)
    env.run([agent_path, "pass"])
    steps = env.steps

    def animal_tiles(farm):
        return [
            t for row in farm["tiles"] for t in row
            if isinstance(t, dict) and "animal" in t
        ]

    def plant_tiles(farm):
        return [
            t for row in farm["tiles"] for t in row
            if isinstance(t, dict) and t.get("kind") == "PLANT"
        ]

    animal_counts = [len(animal_tiles(s[0].observation["farms"][0])) for s in steps]
    final_farm = steps[-1][0].observation["farms"][0]
    final_animals = animal_tiles(final_farm)
    fed_fraction = (
        sum(1 for a in final_animals if a.get("fed_today")) / len(final_animals)
        if final_animals else None
    )
    cared_fraction = (
        sum(1 for a in final_animals if a.get("cared_today")) / len(final_animals)
        if final_animals else None
    )
    max_unfed_seen = max(
        (a.get("consecutive_unfed", 0) for s in steps for a in animal_tiles(s[0].observation["farms"][0])),
        default=0,
    )
    final_plant_count = len(plant_tiles(final_farm))
    print(f"=== {label} (seed {SEED}) ===")
    print(f"  final money: {final_farm['money']}")
    print(
        f"  animal-tile count over time: start={animal_counts[0]} "
        f"mid={animal_counts[len(animal_counts) // 2]} end={animal_counts[-1]} "
        f"peak={max(animal_counts)}"
    )
    print(f"  final animal-tiles: {len(final_animals)}, fed_today fraction={fed_fraction}, "
          f"cared_today fraction={cared_fraction}")
    print(f"  max consecutive_unfed ever observed on any animal tile: {max_unfed_seen}")
    print(f"  final crop (PLANT) tile count: {final_plant_count}")


baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
cap1_agent = tuning.write_candidate_agent(dict(BASE_FULL_CARE, max_animals_per_type=1), WORKDIR)
cap2_agent = tuning.write_candidate_agent(dict(BASE_FULL_CARE, max_animals_per_type=2), WORKDIR)
cap4_agent = tuning.write_candidate_agent(dict(BASE_FULL_CARE, max_animals_per_type=4), WORKDIR)

trace(baseline_agent, "baseline (DEFAULT_PARAMS, max_animals_per_type=1, no full-care flags)")
trace(cap1_agent, "full care, max_animals_per_type=1 (same cap as baseline, isolates the full-care flags)")
trace(cap2_agent, "full care, max_animals_per_type=2")
trace(cap4_agent, "full care, max_animals_per_type=4")
