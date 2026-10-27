"""T8.68 full-episode trace: the user's own follow-up after the 40-seed
measurement's rejection - compare the OLD (rank_portfolio) and NEW
(cycle_economics, use_cycle_economics_ranking=True) agents over a WHOLE
episode, not just day 0: market price trajectories (MELON in particular -
the user's own observation that real Kaggle games crash MELON's price
much harder than this project's starter/pass self-play does) and crop-
tile composition over time.

Not part of the committed test suite - a one-off diagnostic run.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t868_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 1
OPPONENT = sys.argv[3] if len(sys.argv) > 3 else "starter"

CANDIDATE_PARAMS = dict(DEFAULT_PARAMS, use_cycle_economics_ranking=True)


def _crop_tile_counts(tiles):
    counts = {}
    for row in tiles:
        for tile in row:
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                counts[tile["crop"]] = counts.get(tile["crop"], 0) + 1
    return counts


def trace(agent_path: str, label: str) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=False)
    env.run([agent_path, OPPONENT])
    steps = env.steps
    turns_per_day = 24
    print(f"=== {label} (seed {SEED} vs {OPPONENT}) ===")
    print(f"  final money: {steps[-1][0].reward}")
    print("  day | MELON | STRAWBERRY | TOMATO | WHEAT | CARROT | FERTILIZER | tile counts")
    for day in range(0, 30, 3):
        t = min(day * turns_per_day, len(steps) - 1)
        obs = steps[t][0].observation
        inv = obs["market"]["inventory"]
        from kagg.gamelib.market import price

        prices = {p: price(p, inv.get(p, 10000)) for p in ("MELON", "STRAWBERRY", "TOMATO", "WHEAT", "CARROT", "FERTILIZER")}
        counts = _crop_tile_counts(obs["farms"][0]["tiles"])
        print(
            f"  {day:3d} | {prices['MELON']:5d} | {prices['STRAWBERRY']:10d} | {prices['TOMATO']:6d} "
            f"| {prices['WHEAT']:5d} | {prices['CARROT']:6d} | {prices['FERTILIZER']:10d} | {counts}"
        )
    final_obs = steps[-1][0].observation
    print(f"  final tile counts: {_crop_tile_counts(final_obs['farms'][0]['tiles'])}")
    print(f"  final shed: {final_obs['private']['shed']}")


baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_agent = tuning.write_candidate_agent(CANDIDATE_PARAMS, WORKDIR)

trace(baseline_agent, "OLD (rank_portfolio)")
trace(candidate_agent, "NEW (cycle_economics)")
