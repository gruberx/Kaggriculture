"""T8.39 trace: seed 100 (day 28) and seed 105 (day 29) - T8.35/T8.37's
own known-escape seeds/days for the shipped baseline - plus seed 900,
with feed_pickup_unpinned=True vs. the shipped baseline (False), played
as a real paired match against 'pass'.

Answers what tools/measure_t839.py's win rate alone can't:

  1. Does a hand ever actually PICKUP/FEED under the flag - not just
     theoretically eligible, but really assigned a turn.
  2. Did the T6.4/T8.4 livelock recur - PICKUP-of-WHEAT count per day
     should stay <= 1 per feeding episode, same as the pinned baseline.
  3. Did the animal that escaped under the baseline survive instead once
     a free hand could feed it - reusing daily_dashboard.classify_
     animal_transition directly (T8.38's own reuse discipline), not a
     second implementation of "did it escape".

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_dashboard  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t839_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)


def trace_paired(agent_path: str, label: str, opponent: str, seed: int, focus_day: int | None) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([agent_path, opponent])
    steps = env.steps

    print(f"=== seed {seed}: {label} vs {opponent} ===")
    escapes = []
    pickup_count_by_day: dict[int, int] = {}
    for t in range(1, len(steps)):
        prev_obs0 = steps[t - 1][0].observation
        cur_obs0 = steps[t][0].observation
        day = cur_obs0.get("day")
        prev_farm, cur_farm = prev_obs0["farms"][0], cur_obs0["farms"][0]

        for y, row in enumerate(prev_farm["tiles"]):
            for x, prev_tile in enumerate(row):
                cause = daily_dashboard.classify_animal_transition(prev_tile, cur_farm["tiles"][y][x])
                if cause == "escaped":
                    escapes.append((day, x, y, prev_tile.get("animal")))

        action = steps[t][0].action
        farmer_action = action.get("farmer") if action else None
        hand_actions = action.get("hands", []) if action else []
        if farmer_action and farmer_action[0] == "PICKUP" and farmer_action[1] == "WHEAT":
            pickup_count_by_day[day] = pickup_count_by_day.get(day, 0) + 1
        for h in hand_actions:
            if h and h[0] == "PICKUP" and h[1] == "WHEAT":
                pickup_count_by_day[day] = pickup_count_by_day.get(day, 0) + 1

        if focus_day is not None and day != focus_day:
            continue
        if farmer_action and farmer_action[0] not in ("PASS", "NORTH", "SOUTH", "EAST", "WEST"):
            print(f"    day {day} farmer: {farmer_action}  pos={tuple(cur_farm['farmer'])}")
        for i, h in enumerate(hand_actions):
            if h and h[0] not in ("PASS", "NORTH", "SOUTH", "EAST", "WEST"):
                hand_pos = tuple(cur_farm["hands"][i]) if i < len(cur_farm.get("hands", [])) else None
                inv = (
                    cur_obs0["private"]["inventories"][i + 1]
                    if i + 1 < len(cur_obs0["private"]["inventories"])
                    else {}
                )
                print(f"    day {day} hand[{i}]: {h}  pos={hand_pos}  wheat_held={inv.get('WHEAT', 0)}")

    max_daily_pickups = max(pickup_count_by_day.values(), default=0)
    print(f"  max wheat PICKUPs in a single day: {max_daily_pickups} (livelock guard: should be <= 1)")
    print(f"  animal escapes: {escapes if escapes else 'none'}")
    final = steps[-1]
    print(f"  final money: our={final[0].reward}  opponent={final[1].reward}")
    print()


baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_agent = tuning.write_candidate_agent(dict(DEFAULT_PARAMS, feed_pickup_unpinned=True), WORKDIR)

for seed, focus_day in ((100, 28), (105, 29), (900, None)):
    trace_paired(baseline_agent, "baseline (feed_pickup_unpinned=False)", "pass", seed, focus_day)
    trace_paired(candidate_agent, "candidate (feed_pickup_unpinned=True)", "pass", seed, focus_day)
