"""T8.28 trace: seed 900, comparing the T8.27 shipped default against
measure_t828.py's accepted winner (or, if nothing beat the shipped point,
against itself for a sanity check) - reports hand count at each day's
hour 1 (post-hire, matching T8.16(d)/T8.27's own trace convention)
alongside the raw pre-clip forecast target for that same day, computed
directly from the day's real own-tile counts the same way `hires_per_
day`'s workload-forecast branch does internally.

The point of printing the raw target, not just the clipped hand count: to
state plainly whether the accepted configuration actually varies hand
count with the farm's real workload, or is still pinned flat at
min_hires_per_day like the T8.27 default is (see kagg.policy.strategy's
own _DEFAULT_WORKLOAD_FORECAST_SCALING_ONLY comment for why that
question needed asking in the first place).

Not part of the committed test suite - a one-off diagnostic run.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.decide import _crop_tile_counts  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402
from kagg.policy.strategy import (  # noqa: E402
    _animal_actions_per_tile_day,
    _crop_actions_per_tile_day,
)

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t828_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 900

T827_SHIPPED = dict(DEFAULT_PARAMS)

# measure_t828.py's coordinate_ascent picked (4, 8, 2.0, 0.0, True) as its
# own internal "best" - but that ranking was contaminated by a self-mirror
# artifact at the search's own starting point (BASE == the checked-in
# baseline exactly, so the very first working-block comparison was a
# guaranteed-tie mirror match, win_rate 0.000 by construction - any real
# parameter change looks "better" than a guaranteed tie by that metric
# alone, regardless of whether it's actually stronger). The held-out gate
# (a real, direct test against the true checked-in baseline, not against
# that degenerate mirror) is what actually decides, and it decisively
# REJECTED this candidate: 7W/43L/0T (14%), Wilson [0.070, 0.262] - a real
# loss, not noise. Traced here anyway (min_hires_per_day=4 was also the
# single highest-win-rate candidate among all 10 tested, working block
# 0.200) to see exactly how raising the floor changes hand count/raw
# target, and why it still loses.
T828_WINNER = dict(DEFAULT_PARAMS, min_hires_per_day=4)


def animal_tile_counts(farm) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in farm["tiles"]:
        for tile in row:
            if isinstance(tile, dict) and "animal" in tile:
                counts[tile["animal"]] = counts.get(tile["animal"], 0) + 1
    return counts


def raw_target(params: dict, animal_counts: dict, crop_counts: dict, days_remaining: int, turns_per_day: int):
    """Bit-identical to hires_per_day's own workload-forecast branch, up
    to but not including the final clip to [min_hires_per_day,
    max_hires_per_day] - see strategy.hires_per_day's own docstring for
    the formula this mirrors."""
    animal_care_aware = params.get("animal_care_aware", False)
    animal_fertilizer_income_aware = params.get("animal_fertilizer_income_aware", False)
    use_fertilizer = params.get("use_fertilizer", False)
    scaling_only = params.get("workload_forecast_scaling_only", True)
    turns_per_task = params.get("turns_per_task_estimate", 2.0)
    buffer_fraction = params.get("hire_buffer_fraction", 0.0)
    animal_turns = sum(
        _animal_actions_per_tile_day(
            a, days_remaining, animal_care_aware, animal_fertilizer_income_aware, scaling_only=scaling_only
        )
        * count
        for a, count in animal_counts.items()
        if count > 0
    )
    crop_turns = sum(
        _crop_actions_per_tile_day(c, days_remaining, use_fertilizer, scaling_only=scaling_only) * count
        for c, count in crop_counts.items()
        if count > 0
    )
    total_turns = (animal_turns + crop_turns) * turns_per_task
    target = math.ceil(total_turns / turns_per_day) - 1
    return math.ceil(target * (1 + buffer_fraction))


def trace(agent_path: str, label: str, params: dict) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=False)
    env.run([agent_path, "pass"])
    steps = env.steps

    min_hires = params.get("min_hires_per_day", 2)
    max_hires = params.get("max_hires_per_day", 8)
    turns_per_day = params.get("turns_per_day", 24)
    season_length_days = params.get("season_length_days", 30)

    rows = []
    for s in steps:
        obs = s[0].observation
        farm = obs["farms"][0]
        day = obs.get("day")
        hour = obs.get("hour")
        if hour == 0:
            days_remaining = max(0, season_length_days - day)
            rt = raw_target(
                params, animal_tile_counts(farm), _crop_tile_counts(farm["tiles"]), days_remaining, turns_per_day
            )
            clipped = min(max(rt, min_hires), max_hires)
            rows.append([day, None, rt, clipped])
        if hour == 1:
            hands = len(farm.get("hands", []))
            if rows and rows[-1][0] == day:
                rows[-1][1] = hands
            else:
                rows.append([day, hands, None, None])

    final_farm = steps[-1][0].observation["farms"][0]
    print(f"=== {label} (seed {SEED}) ===")
    print("  day: hands_at_hour1 (raw_target -> clipped)")
    for day, hands, rt, clipped in rows:
        print(f"    day {day}: {hands} ({rt} -> {clipped})")
    print(f"  final money: {final_farm['money']}")
    print()


t827_agent = tuning.write_candidate_agent(T827_SHIPPED, WORKDIR)
t828_agent = tuning.write_candidate_agent(T828_WINNER, WORKDIR)

trace(t827_agent, "T8.27 shipped default (min_hires_per_day=2)", T827_SHIPPED)
trace(t828_agent, "T8.28 highest-scoring (but held-out-rejected) candidate (min_hires_per_day=4)", T828_WINNER)
