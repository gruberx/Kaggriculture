"""T8.68: what each ranking actually planted, and at what live market
price - the user's own follow-up request after the TOMATO/STRAWBERRY
crossover investigation, to see the real decisions side by side instead
of just the aggregate money/crossover numbers.

Runs NEW (use_cycle_economics_ranking=True) as player 0 and OLD (the
checked-in baseline) as player 1 head-to-head (the same setup as
tools/measure_t868_headtohead.py - real competitive pressure, not
starter/pass), then walks every PLANT action either side ever issues
(farmer + every hand), grouped by (day, crop), with the live market price
of that crop at the moment it was planted.

Not part of the committed test suite - a one-off diagnostic run.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.gamelib.market import price  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t868_plants_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 1
OPPONENT = sys.argv[3] if len(sys.argv) > 3 else None  # None = head-to-head (NEW vs OLD)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_agent = tuning.write_candidate_agent(
    dict(DEFAULT_PARAMS, use_cycle_economics_ranking=True), WORKDIR
)


def plant_events(env, player_index: int, label: str) -> list[tuple]:
    """Every PLANT action `player_index` issued (farmer or any hand),
    as (day, hour, label, crop, price_at_that_moment)."""
    events = []
    for step in env.steps:
        obs = step[player_index].observation
        act = step[player_index].action or {}
        if obs.get("player") != player_index:
            continue  # defensive - observation is always this player's own view
        inv = obs["market"]["inventory"]
        day, hour = obs.get("day"), obs.get("hour")
        actions = [act.get("farmer")] + list(act.get("hands", []))
        for a in actions:
            if a and a[0] == "PLANT":
                crop = a[1]
                events.append((day, hour, label, crop, price(crop, inv.get(crop, 10000))))
    return events


def run_and_collect(opponent: str | None) -> list[tuple]:
    second = opponent if opponent is not None else baseline_agent
    second_label = opponent if opponent is not None else "OLD"
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=False)
    env.run([candidate_agent, second])
    events = plant_events(env, 0, "NEW")
    if opponent is None:
        events += plant_events(env, 1, second_label)
    events.sort(key=lambda e: (e[0], e[1]))
    print(f"=== seed {SEED}, NEW vs {second_label} - final money: NEW={env.steps[-1][0].reward} "
          f"{second_label}={env.steps[-1][1].reward} ===")
    return events


def print_table(events: list[tuple]) -> None:
    # Group consecutive same (day, who, crop) plantings into one row with a count and the
    # (identical, since price only moves between turns, not within the same PLANT batch's
    # read) price - avoids a wall of duplicate single-unit rows.
    grouped: dict[tuple, list] = {}
    order = []
    for day, hour, who, crop, p in events:
        key = (day, who, crop)
        if key not in grouped:
            grouped[key] = [0, p, p]
            order.append(key)
        grouped[key][0] += 1
        grouped[key][1] = min(grouped[key][1], p)
        grouped[key][2] = max(grouped[key][2], p)
    print(f"{'day':>4} | {'who':>4} | {'crop':<10} | {'count':>5} | {'price (min-max)':>16}")
    for (day, who, crop) in order:
        count, lo, hi = grouped[(day, who, crop)]
        price_str = f"{lo}" if lo == hi else f"{lo}-{hi}"
        print(f"{day:4d} | {who:>4} | {crop:<10} | {count:5d} | {price_str:>16}")


if __name__ == "__main__":
    events = run_and_collect(OPPONENT)
    print_table(events)
