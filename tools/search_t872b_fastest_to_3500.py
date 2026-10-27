"""T8.72 follow-up (exploratory, dev-only): among the 22 opening-herd
configs from search_t872_opening_start.py that reach $3500 by day 10 at
least some of the time (pass_rate > 0 in that sweep's results.json), find
which one reaches $3500 in the FEWEST days - the user's refined question
("kto bystree dostigaet $3500 za men'she dnei ili khodov"), replacing the
earlier binary day-10 pass/fail ranking with a speed ranking.

Unlike the first sweep (which only inspected the truncated episode's
final state), this one captures the full per-step trajectory
(env.steps, not just env.steps[-1]) so the day of first crossing $3500
can be read directly off each step's own observation - no bisection or
re-running at different episode_steps needed.

Same setup as the first sweep: crop universe restricted to {WHEAT,
MELON}, opponent = today's shipped baseline agent, both seatings played
(paired), full 100-seed set (tuning + holdout), episode truncated to 240
steps (10 days) since a config that has not reached $3500 within that
window doesn't matter for "fastest" either.

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
TARGET_MONEY = s1.TARGET_MONEY
RESULTS_PATH = os.path.join(WORKDIR, "results.json")
OUT_PATH = os.path.join(WORKDIR, "fastest_results.json")


def _play_trace(first: str, second: str, seed: int, episode_steps: int):
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": episode_steps, "seed": seed},
        debug=False,
    )
    env.run([first, second])
    return env.steps


def _first_day_reaching_3500(steps, player_idx: int):
    """Earliest `day` (as the observation itself reports it) at which
    player_idx's money is >= TARGET_MONEY, or None if never within the
    captured steps."""
    for step in steps:
        obs = step[player_idx].observation
        farm = obs["farms"][player_idx]
        if farm["money"] >= TARGET_MONEY:
            return obs.get("day")
    return None


def _one_seed_star(args):
    candidate_agent, baseline_agent, seed, episode_steps = args
    steps1 = _play_trace(candidate_agent, baseline_agent, seed, episode_steps)
    day1 = _first_day_reaching_3500(steps1, 0)
    steps2 = _play_trace(baseline_agent, candidate_agent, seed, episode_steps)
    day2 = _first_day_reaching_3500(steps2, 1)
    return day1, day2


def evaluate_config_speed(cows: int, sheep: int, seeds: list[int], baseline_agent: str) -> dict:
    params = dict(DEFAULT_PARAMS, animal_opening_initial={"COW": cows, "SHEEP": sheep})
    candidate_agent = s1.write_agent(params, restrict_crops=True)
    tasks = [(candidate_agent, baseline_agent, seed, EPISODE_STEPS) for seed in seeds]
    jobs = harness._default_jobs()
    with multiprocessing.Pool(processes=jobs) as pool:
        results = pool.map(_one_seed_star, tasks)
    days = [d for pair in results for d in pair if d is not None]
    n_total = 2 * len(seeds)
    n_reached = len(days)
    return {
        "cows": cows,
        "sheep": sheep,
        "n_total": n_total,
        "n_reached": n_reached,
        "reach_rate": n_reached / n_total,
        "avg_day": sum(days) / n_reached if days else None,
        "median_day": sorted(days)[len(days) // 2] if days else None,
        "min_day": min(days) if days else None,
        "max_day": max(days) if days else None,
    }


if __name__ == "__main__":
    with open(RESULTS_PATH) as f:
        prior = json.load(f)
    candidates = [(r["cows"], r["sheep"]) for r in prior if r["pass_rate"] > 0]
    print(f"Re-measuring {len(candidates)} candidates for speed-to-$3500", flush=True)

    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds) + list(blocks.holdout_seeds)
    baseline_agent = s1.write_agent(DEFAULT_PARAMS, restrict_crops=False)

    results = []
    t0 = time.time()
    for cows, sheep in candidates:
        t1 = time.time()
        res = evaluate_config_speed(cows, sheep, seeds, baseline_agent)
        dt = time.time() - t1
        results.append(res)
        avg = f"{res['avg_day']:.2f}" if res["avg_day"] is not None else "n/a"
        med = res["median_day"] if res["median_day"] is not None else "n/a"
        print(
            f"COW={cows:2d} SHEEP={sheep:2d}  reach_rate={res['reach_rate']:.3f} "
            f"({res['n_reached']}/{res['n_total']})  avg_day={avg}  median_day={med}  "
            f"min={res['min_day']}  max={res['max_day']}  [{dt:.1f}s]",
            flush=True,
        )
    print(f"\nTotal: {time.time() - t0:.1f}s for {len(results)} configs", flush=True)

    # Rank: higher reach_rate first, then lower avg_day (faster).
    results.sort(key=lambda r: (-r["reach_rate"], r["avg_day"] if r["avg_day"] is not None else 999))
    print("\n=== Ranked by speed ===")
    for r in results:
        print(r)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results written to {OUT_PATH}")
