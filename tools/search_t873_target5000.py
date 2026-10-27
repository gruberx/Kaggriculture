"""T8.73 (exploratory, dev-only): follow-up to T8.72 - the user raised the
bar from $3500 to $5000 and dropped the "full quadrant occupied" hard
requirement (now a secondary tie-breaker, "more is better but not
required"). Stage 1: full herd-composition grid (same COW x SHEEP grid as
search_t872_opening_start.py), default (shipped) worker-hiring policy,
looking for which composition reaches $5000 earliest within the first 10
days. Captures the full per-step trajectory (like search_t872b) so the
exact (day, hour) of first crossing is read directly, plus the final-day
money/occupied-tile count for reference.

Same setup otherwise: crop universe restricted to {WHEAT, MELON}, opponent
= today's shipped baseline agent, both seatings played (paired), full
100-seed set (tuning + holdout), episode truncated to 240 steps (10 days).

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
TARGET_MONEY = 5000
TURNS_PER_DAY = 24
OUT_PATH = os.path.join(WORKDIR, "t873_stage1_results.json")


def _play_trace(first: str, second: str, seed: int, episode_steps: int):
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": episode_steps, "seed": seed},
        debug=False,
    )
    env.run([first, second])
    return env.steps


def _crossing_and_final(steps, player_idx: int):
    day = hour = None
    for step in steps:
        obs = step[player_idx].observation
        farm = obs["farms"][player_idx]
        if day is None and farm["money"] >= TARGET_MONEY:
            day, hour = obs.get("day"), obs.get("hour")
    final_obs = steps[-1][player_idx].observation
    final_farm = final_obs["farms"][player_idx]
    final_money = final_farm["money"]
    final_occ = s1.nw_tiles_occupied(final_farm["tiles"])
    return day, hour, final_money, final_occ


def _one_seed_star(args):
    candidate_agent, baseline_agent, seed, episode_steps = args
    steps1 = _play_trace(candidate_agent, baseline_agent, seed, episode_steps)
    r1 = _crossing_and_final(steps1, 0)
    steps2 = _play_trace(baseline_agent, candidate_agent, seed, episode_steps)
    r2 = _crossing_and_final(steps2, 1)
    return r1, r2


def evaluate_config(cows: int, sheep: int, seeds: list[int], baseline_agent: str, params_override: dict | None = None) -> dict:
    params = dict(DEFAULT_PARAMS, animal_opening_initial={"COW": cows, "SHEEP": sheep})
    if params_override:
        params.update(params_override)
    candidate_agent = s1.write_agent(params, restrict_crops=True)
    tasks = [(candidate_agent, baseline_agent, seed, EPISODE_STEPS) for seed in seeds]
    jobs = harness._default_jobs()
    with multiprocessing.Pool(processes=jobs) as pool:
        results = pool.map(_one_seed_star, tasks)
    records = [r for pair in results for r in pair]
    n_total = len(records)
    reached = [r for r in records if r[0] is not None]
    n_reached = len(reached)
    days = [d for d, h, m, o in reached]
    turns = [d * TURNS_PER_DAY + h for d, h, m, o in reached]
    final_money = [m for d, h, m, o in records]
    final_occ = [o for d, h, m, o in records]

    def stats(xs):
        return {"min": min(xs), "avg": sum(xs) / len(xs), "max": max(xs)} if xs else None

    return {
        "cows": cows,
        "sheep": sheep,
        "n_total": n_total,
        "n_reached": n_reached,
        "reach_rate": n_reached / n_total,
        "day": stats(days),
        "total_turns": stats(turns),
        "final_money_avg": sum(final_money) / n_total,
        "final_occ_avg": sum(final_occ) / n_total,
    }


if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds) + list(blocks.holdout_seeds)
    baseline_agent = s1.write_agent(DEFAULT_PARAMS, restrict_crops=False)

    cows_range = range(0, 9)
    sheep_range = range(0, 7)

    results = []
    t0 = time.time()
    for cows in cows_range:
        for sheep in sheep_range:
            t1 = time.time()
            res = evaluate_config(cows, sheep, seeds, baseline_agent)
            dt = time.time() - t1
            results.append(res)
            tt = res["total_turns"]
            tt_str = f"{tt['min']}/{tt['avg']:.1f}/{tt['max']}" if tt else "n/a"
            print(
                f"COW={cows:2d} SHEEP={sheep:2d}  reach_rate={res['reach_rate']:.3f} "
                f"({res['n_reached']}/{res['n_total']})  total_turns(min/avg/max)={tt_str}  "
                f"final_money_avg=${res['final_money_avg']:.0f}  occ_avg={res['final_occ_avg']:.1f}/25  [{dt:.1f}s]",
                flush=True,
            )
    print(f"\nTotal: {time.time() - t0:.1f}s for {len(results)} configs", flush=True)

    results.sort(
        key=lambda r: (
            -r["reach_rate"],
            r["total_turns"]["avg"] if r["total_turns"] else 9999,
        )
    )
    print("\n=== Top 15 by reach_rate then speed ===")
    for r in results[:15]:
        print(r)

    with open(OUT_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results written to {OUT_PATH}")
