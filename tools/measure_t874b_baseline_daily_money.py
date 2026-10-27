"""T8.74 follow-up (exploratory, dev-only): day-by-day average money table
for today's shipped baseline agent alone (self-play, no opening changes),
over the FULL 30-day season - not the 10-day truncation T8.72/73 used.
Requested as a reference point to compare against the COW=2/SHEEP=4/
WORKERS=10 candidate's own day-by-day trace (measure_t874.py /
diag_t874.py), after that candidate's full-episode measurement came back
a decisive loss.

Self-play (baseline vs baseline) across both seed blocks (100 seeds) x 2
seatings = 200 samples/day, so day-to-day timing noise (e.g. when a
quadrant purchase happens to land) averages out the same way it did for
every other T8.72/73/74 table.

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
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd874_baseline_daily")
os.makedirs(WORKDIR, exist_ok=True)
OUT_PATH = os.path.join(WORKDIR, "results.json")
EPISODE_STEPS = 720
N_DAYS = 30


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
    agent_a, agent_b, seed, episode_steps = args
    steps = _play_trace(agent_a, agent_b, seed, episode_steps)
    d1 = _daily_money(steps, 0)
    d2 = _daily_money(steps, 1)
    return d1, d2


if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds) + list(blocks.holdout_seeds)
    baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

    t0 = time.time()
    tasks = [(baseline_agent, baseline_agent, seed, EPISODE_STEPS) for seed in seeds]
    jobs = harness._default_jobs()
    with multiprocessing.Pool(processes=jobs) as pool:
        results = pool.map(_one_seed_star, tasks)
    all_days = [d for pair in results for d in pair]
    n = len(all_days)

    by_day_stats = {}
    for day in range(N_DAYS):
        vals = [d.get(day) for d in all_days if day in d]
        if vals:
            by_day_stats[day] = {
                "min": min(vals), "avg": sum(vals) / len(vals), "max": max(vals), "n": len(vals),
            }

    print(f"n_episodes={n}  [{time.time() - t0:.1f}s]")
    for day in range(N_DAYS):
        st = by_day_stats.get(day)
        if st:
            print(f"  day {day:2d}: min=${st['min']:.0f}  avg=${st['avg']:.0f}  max=${st['max']:.0f}  (n={st['n']})")

    with open(OUT_PATH, "w") as f:
        json.dump(by_day_stats, f, indent=2)
    print(f"Full results written to {OUT_PATH}")
