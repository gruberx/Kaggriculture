"""T8.73 follow-up (exploratory, dev-only): the user wants a day-by-day
average money table for the two headline configs found in stage 3/4 -
COW=2,SHEEP=4,WORKERS=10 (best overall money, $7395 final) and
COW=1,SHEEP=4,WORKERS=9 (best speed+reliability combo, always exactly
day 7/169 turns). Captures end-of-day money (the observation at hour=23,
i.e. the last turn of each day) for days 0-9, averaged across all 200
episodes (100 seeds x 2 seatings) per config - same setup as the rest of
the T8.73 line (crop universe restricted to WHEAT/MELON, opponent =
shipped baseline, episode truncated to 240 steps).

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
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

import search_t872_opening_start as s1  # noqa: E402

WORKDIR = s1.WORKDIR
EPISODE_STEPS = s1.EPISODE_STEPS
OUT_PATH = os.path.join(WORKDIR, "t873_daily_money_results.json")

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


def _daily_money(steps, player_idx: int) -> dict[int, float]:
    by_day = {}
    for step in steps:
        obs = step[player_idx].observation
        by_day[obs["day"]] = obs["farms"][player_idx]["money"]
    return by_day


def _one_seed_star(args):
    candidate_agent, baseline_agent, seed, episode_steps = args
    steps1 = _play_trace(candidate_agent, baseline_agent, seed, episode_steps)
    d1 = _daily_money(steps1, 0)
    steps2 = _play_trace(baseline_agent, candidate_agent, seed, episode_steps)
    d2 = _daily_money(steps2, 1)
    return d1, d2


def evaluate_daily(cows: int, sheep: int, workers: int, seeds: list[int], baseline_agent: str) -> dict:
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
    by_day_stats = {}
    for day in range(10):
        vals = [d.get(day) for d in all_days if day in d]
        if vals:
            by_day_stats[day] = {
                "min": min(vals),
                "avg": sum(vals) / len(vals),
                "max": max(vals),
                "n": len(vals),
            }
    return {"cows": cows, "sheep": sheep, "workers": workers, "n_episodes": n, "by_day": by_day_stats}


if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds) + list(blocks.holdout_seeds)
    baseline_agent = s1.write_agent(DEFAULT_PARAMS, restrict_crops=False)

    results = []
    t0 = time.time()
    for cfg in CONFIGS:
        t1 = time.time()
        res = evaluate_daily(cfg["cows"], cfg["sheep"], cfg["workers"], seeds, baseline_agent)
        dt = time.time() - t1
        results.append(res)
        print(f"=== COW={cfg['cows']} SHEEP={cfg['sheep']} WORKERS={cfg['workers']}  [{dt:.1f}s] ===")
        for day in range(10):
            st = res["by_day"].get(day)
            if st:
                print(f"  day {day}: min=${st['min']:.0f}  avg=${st['avg']:.0f}  max=${st['max']:.0f}  (n={st['n']})")
        print(flush=True)
    print(f"Total: {time.time() - t0:.1f}s", flush=True)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Full results written to {OUT_PATH}")
