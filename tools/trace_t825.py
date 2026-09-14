"""T8.25 trace: does the WHEAT feed-restock price-ceiling fix actually
prevent the permanent zero-stock drought and the resulting escapes that
tools/trace_t822.py found at every max_animals_per_type cap tried?

Traces, per candidate: WHEAT market price over time, shed WHEAT stock over
time (specifically whether it ever hits 0 and *stays* there for the rest
of the episode - the drought signature, not an ordinary transient dip),
animal-tile fed_today/cared_today fractions and max consecutive_unfed ever
observed (T8.22's own escape diagnostic), and final money.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t825_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 900

# tools/measure_t825b.py found wheat_urgency_reserve=3 alone (cap left
# untouched at 40) bit-identical in practice to raising the cap outright
# (measure_t825.py's cap=1_000_000 combo) - the restock-threshold gating
# (buy_wheat_order only ever fires once wheat_on_hand < 5) means on-hand
# stock is already at or below the urgency reserve by the time a restock
# is even attempted once price has drifted past $40. Simpler, so this is
# the design actually traced/recommended.
FULL_FIX = dict(
    DEFAULT_PARAMS,
    animal_care_aware=True,
    animal_fertilizer_income_aware=True,
    parallel_animal_acquisition=True,
    wheat_urgency_reserve=3,
)


def trace(agent_path: str, label: str) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=False)
    env.run([agent_path, "pass"])
    steps = env.steps

    def animal_tiles(farm):
        return [t for row in farm["tiles"] for t in row if isinstance(t, dict) and "animal" in t]

    wheat_prices = [s[0].observation["market"]["prices"].get("WHEAT", 0) for s in steps]
    shed_wheat = [s[0].observation["private"]["shed"].get("WHEAT", 0) for s in steps]

    # Drought signature: the last index where shed_wheat hits 0 and never
    # recovers above 0 for the rest of the episode, while at least one
    # animal is placed at that point (matches T8.22's own escape window).
    last_zero_start = None
    for i in range(len(shed_wheat) - 1, -1, -1):
        if shed_wheat[i] == 0:
            last_zero_start = i
        else:
            break
    drought_turns = len(shed_wheat) - last_zero_start if last_zero_start is not None else 0

    final_farm = steps[-1][0].observation["farms"][0]
    final_animals = animal_tiles(final_farm)
    fed_fraction = (
        sum(1 for a in final_animals if a.get("fed_today")) / len(final_animals) if final_animals else None
    )
    max_unfed_seen = max(
        (a.get("consecutive_unfed", 0) for s in steps for a in animal_tiles(s[0].observation["farms"][0])),
        default=0,
    )
    first_over_40 = next((i for i, p in enumerate(wheat_prices) if p > 40), None)

    print(f"=== {label} (seed {SEED}) ===")
    print(f"  final money: {final_farm['money']}")
    print(f"  WHEAT price: start={wheat_prices[0]} end={wheat_prices[-1]} first step price>40: {first_over_40}")
    print(f"  shed WHEAT: start={shed_wheat[0]} end={shed_wheat[-1]}")
    print(f"  trailing zero-stock run at episode end: {drought_turns} turns (0 = never permanently empty)")
    print(f"  final animal-tiles: {len(final_animals)}, fed_today fraction={fed_fraction}")
    print(f"  max consecutive_unfed ever observed on any animal tile: {max_unfed_seen}")
    print()


baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
old_cap4_agent = tuning.write_candidate_agent(
    dict(
        DEFAULT_PARAMS, animal_care_aware=True, animal_fertilizer_income_aware=True,
        parallel_animal_acquisition=True, max_animals_per_type=4,
    ),
    WORKDIR,
)
fixed_cap4_agent = tuning.write_candidate_agent(dict(FULL_FIX, max_animals_per_type=4), WORKDIR)

trace(baseline_agent, "plain baseline (DEFAULT_PARAMS)")
trace(old_cap4_agent, "T8.22's old cap=4 (no price fix) - the original drought/escape case")
trace(fixed_cap4_agent, "cap=4 WITH the T8.25 price fix (wheat_urgency_reserve=3, cap unchanged)")
