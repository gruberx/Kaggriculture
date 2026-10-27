"""T8.73 follow-up (exploratory, dev-only): day-by-day breakdown of what
occupies each of the 25 NW-quadrant tiles (crop/animal/empty structure/
weed/free) for the same two headline configs as search_t873e_daily_
money.py - COW=2,SHEEP=4,WORKERS=10 and COW=1,SHEEP=4,WORKERS=9.

Tile classification (verified against the real engine,
kaggle_environments/envs/kaggriculture/kaggriculture.py):
- None -> free
- {"kind": "PLANT", "crop": X} -> crop X (only WHEAT/MELON possible here,
  since the candidate's own crop universe is restricted)
- {"kind": "COOP"/"PASTURE", "animal": X} -> animal X
- {"kind": "COOP"/"PASTURE"} without "animal" -> structure built, animal
  not yet placed (a real, if usually short-lived, intermediate state)
- {"kind": "WEED"} -> weed (can appear regardless of the crop
  restriction - weeds aren't planted, they spawn on their own)

Averaged across all 200 episodes (100 seeds x 2 seatings) per config,
same setup as the rest of the T8.73 line.

Not part of the committed test suite.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

import search_t872_opening_start as s1  # noqa: E402

WORKDIR = s1.WORKDIR
EPISODE_STEPS = s1.EPISODE_STEPS
BOARD_HALF = s1.BOARD_HALF
OUT_PATH = os.path.join(WORKDIR, "t873_daily_tiles_results.json")

CONFIGS = [
    {"cows": 2, "sheep": 4, "workers": 10},
    {"cows": 1, "sheep": 4, "workers": 9},
]


def _play_trace(first: str, second: str, seed: int, episode_steps: int):
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": episode_steps, "seed": seed},
        debug=False,
    )
    env.run([first, second])
    return env.steps


def _classify(tile) -> str:
    if tile is None:
        return "FREE"
    if tile == "LOCKED":
        return "LOCKED"
    kind = tile.get("kind")
    if kind == "PLANT":
        return tile["crop"]
    if kind in ("COOP", "PASTURE"):
        if "animal" in tile:
            return tile["animal"]
        return f"{kind}_EMPTY"
    if kind == "WEED":
        return "WEED"
    return kind or "UNKNOWN"


def _tile_counts(tiles) -> Counter:
    c = Counter()
    for y in range(BOARD_HALF):
        for x in range(BOARD_HALF):
            c[_classify(tiles[y][x])] += 1
    return c


def _daily_tile_counts(steps, player_idx: int) -> dict[int, Counter]:
    by_day = {}
    for step in steps:
        obs = step[player_idx].observation
        farm = obs["farms"][player_idx]
        by_day[obs["day"]] = _tile_counts(farm["tiles"])
    return by_day


def _one_seed_star(args):
    candidate_agent, baseline_agent, seed, episode_steps = args
    steps1 = _play_trace(candidate_agent, baseline_agent, seed, episode_steps)
    d1 = _daily_tile_counts(steps1, 0)
    steps2 = _play_trace(baseline_agent, candidate_agent, seed, episode_steps)
    d2 = _daily_tile_counts(steps2, 1)
    return d1, d2


def evaluate_daily_tiles(cows: int, sheep: int, workers: int, seeds: list[int], baseline_agent: str) -> dict:
    params = dict(
        DEFAULT_PARAMS,
        animal_opening_initial={"COW": cows, "SHEEP": sheep},
        min_hires_per_day=workers,
        max_hires_per_day=workers,
    )
    candidate_agent = s1.write_agent(params, restrict_crops=True)
    tasks = [(candidate_agent, baseline_agent, seed, EPISODE_STEPS) for seed in seeds]
    jobs = harness._default_jobs()
    with multiprocessing.Pool(processes=jobs) as pool:
        results = pool.map(_one_seed_star, tasks)
    all_days = [d for pair in results for d in pair]
    n = len(all_days)
    by_day_avg = {}
    for day in range(10):
        totals = Counter()
        count = 0
        for d in all_days:
            if day in d:
                totals += d[day]
                count += 1
        if count:
            by_day_avg[day] = {k: v / count for k, v in totals.items()}
    return {"cows": cows, "sheep": sheep, "workers": workers, "n_episodes": n, "by_day": by_day_avg}


if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds) + list(blocks.holdout_seeds)
    baseline_agent = s1.write_agent(DEFAULT_PARAMS, restrict_crops=False)

    results = []
    t0 = time.time()
    for cfg in CONFIGS:
        t1 = time.time()
        res = evaluate_daily_tiles(cfg["cows"], cfg["sheep"], cfg["workers"], seeds, baseline_agent)
        dt = time.time() - t1
        results.append(res)
        print(f"=== COW={cfg['cows']} SHEEP={cfg['sheep']} WORKERS={cfg['workers']}  [{dt:.1f}s] ===")
        for day in range(10):
            row = res["by_day"].get(day, {})
            parts = ", ".join(f"{k}={v:.2f}" for k, v in sorted(row.items(), key=lambda kv: -kv[1]))
            print(f"  day {day}: {parts}")
        print(flush=True)
    print(f"Total: {time.time() - t0:.1f}s", flush=True)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Full results written to {OUT_PATH}")
