"""T8.72 follow-up #2 (exploratory, dev-only): within the "day 7" tier
found by search_t872b_fastest_to_3500.py, rank by the exact TURN
(hour-of-day, 0-23) the $3500 crossing happens on, not just the day -
the user's refined question. Reuses the same per-step trajectory capture,
just reads `obs["hour"]` alongside `obs["day"]` at the crossing step and
reports min/avg/max of both the hour-within-day and the total turn count
since game start (day * turns_per_day + hour).

Restricted to the 7 configs that reached day 7 with 100% reliability in
the prior sweep, plus the one at 98.5% (COW=2, SHEEP=3) for completeness.

Not part of the committed test suite.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

import search_t872_opening_start as s1  # noqa: E402
import search_t872b_fastest_to_3500 as s2  # noqa: E402

WORKDIR = s1.WORKDIR
EPISODE_STEPS = s1.EPISODE_STEPS
TARGET_MONEY = s1.TARGET_MONEY
TURNS_PER_DAY = 24
OUT_PATH = os.path.join(WORKDIR, "turns_in_day7_results.json")

DAY7_TIER = [(1, 2), (0, 3), (4, 2), (2, 4), (3, 3), (1, 5), (3, 2), (2, 3)]


def _first_crossing_day_hour(steps, player_idx: int):
    for step in steps:
        obs = step[player_idx].observation
        farm = obs["farms"][player_idx]
        if farm["money"] >= TARGET_MONEY:
            return obs.get("day"), obs.get("hour")
    return None, None


def _one_seed_star(args):
    candidate_agent, baseline_agent, seed, episode_steps = args
    steps1 = s2._play_trace(candidate_agent, baseline_agent, seed, episode_steps)
    day1, hour1 = _first_crossing_day_hour(steps1, 0)
    steps2 = s2._play_trace(baseline_agent, candidate_agent, seed, episode_steps)
    day2, hour2 = _first_crossing_day_hour(steps2, 1)
    return (day1, hour1), (day2, hour2)


def evaluate_config_turns(cows: int, sheep: int, seeds: list[int], baseline_agent: str) -> dict:
    params = dict(DEFAULT_PARAMS, animal_opening_initial={"COW": cows, "SHEEP": sheep})
    candidate_agent = s1.write_agent(params, restrict_crops=True)
    tasks = [(candidate_agent, baseline_agent, seed, EPISODE_STEPS) for seed in seeds]
    jobs = harness._default_jobs()
    with multiprocessing.Pool(processes=jobs) as pool:
        results = pool.map(_one_seed_star, tasks)
    pairs = [p for pair in results for p in pair if p[0] is not None]
    n_total = 2 * len(seeds)
    n_reached = len(pairs)
    hours = [h for _, h in pairs]
    turns = [d * TURNS_PER_DAY + h for d, h in pairs]
    days = [d for d, _ in pairs]

    def stats(xs):
        return {"min": min(xs), "avg": sum(xs) / len(xs), "max": max(xs)} if xs else None

    return {
        "cows": cows,
        "sheep": sheep,
        "n_total": n_total,
        "n_reached": n_reached,
        "reach_rate": n_reached / n_total,
        "day": stats(days),
        "hour_of_day": stats(hours),
        "total_turns": stats(turns),
    }


if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds) + list(blocks.holdout_seeds)
    baseline_agent = s1.write_agent(DEFAULT_PARAMS, restrict_crops=False)

    results = []
    t0 = time.time()
    for cows, sheep in DAY7_TIER:
        t1 = time.time()
        res = evaluate_config_turns(cows, sheep, seeds, baseline_agent)
        dt = time.time() - t1
        results.append(res)
        tt = res["total_turns"]
        hh = res["hour_of_day"]
        print(
            f"COW={cows:2d} SHEEP={sheep:2d}  reach_rate={res['reach_rate']:.3f}  "
            f"hour_of_day(min/avg/max)={hh['min']}/{hh['avg']:.2f}/{hh['max']}  "
            f"total_turns(min/avg/max)={tt['min']}/{tt['avg']:.2f}/{tt['max']}  [{dt:.1f}s]",
            flush=True,
        )
    print(f"\nTotal: {time.time() - t0:.1f}s for {len(results)} configs", flush=True)

    results.sort(key=lambda r: r["total_turns"]["avg"])
    print("\n=== Ranked by avg total turns ===")
    for r in results:
        print(r)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results written to {OUT_PATH}")
