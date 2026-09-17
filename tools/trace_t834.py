"""T8.34 trace: seed 100, workload_forecast_free_tile_weight=2 vs. the
checked-in baseline (weight=0), played as a real paired match.

Written to pin down *why* every weight in the calibrated Stage 1 sweep
(tools/measure_t834.py) lost decisively even though the floor-breaking
mechanism itself worked exactly as predicted (max hand count did climb
with weight). Found: free_tiles peaks on day 0, before a single tile is
planted - exactly when there's no real backlog to justify extra hands -
so the forecast fires a one-time day-0 hiring burst (Fibonacci-priced)
that reverts to the floor again by day 1 once tiles get planted and
free_tiles shrinks. That single day's overspend leaves a persistently
thinner cash cushion for the rest of the season; in this seed, that lag
caused the weight=2 farm's planted-tile count to fall just short of
land_buy_max_free_tile_fraction's occupancy gate at the one moment late
in the season when the baseline crossed it, so it never opened its 2nd
quadrant at all - see tasks/todo.md's T8.34 entry for the full traced
numbers and interpretation.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t834_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 100


def trace_paired(first: str, first_label: str, second: str, second_label: str, seed: int) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([first, second])
    steps = env.steps

    print(f"=== seed {seed}: player0={first_label}  player1={second_label} ===")
    print("  day: [p0]hands plant animal money quad  | [p1]hands plant animal money quad")
    for s in steps:
        obs = s[0].observation
        if obs.get("hour") != 1:
            continue
        day = obs.get("day")
        cells = []
        for i in (0, 1):
            farm = obs["farms"][i]
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
            cells.append(f"{hands} {n_plant:>3} {n_animal} {farm['money']:>8.0f} {n_quadrants}")
        print(f"    day {day:>2}: {cells[0]}   |   {cells[1]}")

    final = steps[-1]
    print(f"  final money: p0={final[0].reward}  p1={final[1].reward}")
    print()


baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
weight2_agent = tuning.write_candidate_agent(
    dict(DEFAULT_PARAMS, workload_forecast_free_tile_weight=2), WORKDIR
)

trace_paired(weight2_agent, "weight=2", baseline_agent, "baseline (weight=0)", SEED)
