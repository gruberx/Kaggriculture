"""T8.72 (exploratory, dev-only - not a shipping mechanism): brute-force
search over the first-quadrant opening herd composition (COW/SHEEP
counts), with the crop universe restricted to {WHEAT, MELON} (wheat
feed-only, per the user's own framing) - looking for the fastest/most
reliable start that, by day 10, reaches $3500 total money AND has all 25
NW-quadrant tiles occupied. Both conditions are required; missing either
counts as a loss for that seed (the user's own win condition).

Design notes:
- `episode_steps=240` (10 days * 24 turns/day) truncates every episode at
  exactly the end of day 10 - harness.run_paired/run_block already accept
  this directly, no engine change needed.
- Herd composition is swept via the existing `animal_opening_initial`
  param (already a {animal: qty} dict override, unrelated to this task -
  see src/kagg/policy/opening.py `initial_mix`). Worker count is left at
  the shipped adaptive default (`day_plan_hiring_aware` + min/max hires
  per day) - not swept, per the user's explicit "on your judgment, optimal"
  framing; sweeping a 3rd axis would ~7x the grid for a dimension the
  project has already tuned extensively (T8.4-T8.8).
- Crop universe restriction to {WHEAT, MELON}: `kagg.gamelib.constants.
  CROPS` is a single dict object, imported by name (`from kagg.gamelib.
  constants import CROPS`) into every consuming module (decide.py,
  cycle_economics.py, opening.py, strategy.py) - mutating it in place
  (not rebinding) is visible to all of them. Verified no module indexes
  CROPS["CARROT"/"TOMATO"/"STRAWBERRY"] unconditionally (grep, 2026-09-25)
  - every reference is either a comment or an `if x in CROPS`-guarded
  loop, so deleting those 3 keys is safe and requires no source changes
  to any shipped module. Done by injecting one line into the candidate
  agent's own source (same technique tuning.write_candidate_agent uses
  for params), so it happens inside each subprocess worker before any
  decide() call - a parent-process monkeypatch would not reach
  multiprocessing.Pool workers, which re-exec the agent file fresh.

Opponent (per the user's explicit choice): today's shipped baseline
agent (DEFAULT_PARAMS, unrestricted crops) in the other seat.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd872")
os.makedirs(WORKDIR, exist_ok=True)

EPISODE_STEPS = 240  # 10 days * 24 turns/day
TARGET_MONEY = 3500
BOARD_HALF = 5  # NW quadrant: x < 5 and y < 5 on a 10x10 board

_AGENT_MAIN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "src", "kagg", "agent_main.py"
)
_PARAMS_LOAD_LINE = "_PARAMS = load_params()"
_CROP_RESTRICT_SNIPPET = (
    "from kagg.gamelib.constants import CROPS as _T872_CROPS\n"
    "for _t872_c in list(_T872_CROPS):\n"
    "    if _t872_c not in ('WHEAT', 'MELON'):\n"
    "        del _T872_CROPS[_t872_c]\n"
)


def write_agent(params: dict, restrict_crops: bool) -> str:
    with open(_AGENT_MAIN_PATH) as f:
        source = f.read()
    if source.count(_PARAMS_LOAD_LINE) != 1:
        raise RuntimeError("agent_main.py shape changed - update this script")
    unique = uuid.uuid4().hex
    params_path = os.path.join(WORKDIR, f"params_{unique}.json")
    with open(params_path, "w") as f:
        json.dump(params, f)
    replacement = f"_PARAMS = load_params({params_path!r})\n"
    if restrict_crops:
        replacement += _CROP_RESTRICT_SNIPPET
    patched = source.replace(_PARAMS_LOAD_LINE, replacement.rstrip("\n"))
    agent_path = os.path.join(WORKDIR, f"agent_{unique}.py")
    with open(agent_path, "w") as f:
        f.write(patched)
    return agent_path


def nw_tiles_occupied(tiles) -> int:
    return sum(
        1
        for y in range(BOARD_HALF)
        for x in range(BOARD_HALF)
        if tiles[y][x] is not None
    )


def candidate_pass(farm_obs) -> dict:
    money = farm_obs["money"]
    occ = nw_tiles_occupied(farm_obs["tiles"])
    return {"money": money, "occupied": occ, "passed": money >= TARGET_MONEY and occ >= 25}


def evaluate_config(cows: int, sheep: int, seeds: list[int], baseline_agent: str) -> dict:
    params = dict(DEFAULT_PARAMS, animal_opening_initial={"COW": cows, "SHEEP": sheep})
    candidate_agent = write_agent(params, restrict_crops=True)
    block = harness.run_block(
        candidate_agent, baseline_agent, seeds, jobs=None, episode_steps=EPISODE_STEPS
    )
    records = []
    for r in block.paired_results:
        seating1, seating2 = r.episodes
        # seating1: candidate=player0, baseline=player1. seating2: swapped.
        farm1 = seating1[0].observation["farms"][0]
        farm2 = seating2[1].observation["farms"][1]
        records.append(candidate_pass(farm1))
        records.append(candidate_pass(farm2))
    n = len(records)
    passed = sum(1 for x in records if x["passed"])
    avg_money = sum(x["money"] for x in records) / n
    avg_occ = sum(x["occupied"] for x in records) / n
    return {
        "cows": cows,
        "sheep": sheep,
        "n": n,
        "passed": passed,
        "pass_rate": passed / n,
        "avg_money": avg_money,
        "avg_occupied": avg_occ,
    }


if __name__ == "__main__":
    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds) + list(blocks.holdout_seeds)
    baseline_agent = write_agent(DEFAULT_PARAMS, restrict_crops=False)

    cows_range = range(0, 9)   # 0..8
    sheep_range = range(0, 7)  # 0..6

    results = []
    t0 = time.time()
    for cows in cows_range:
        for sheep in sheep_range:
            t1 = time.time()
            res = evaluate_config(cows, sheep, seeds, baseline_agent)
            dt = time.time() - t1
            results.append(res)
            print(
                f"COW={cows:2d} SHEEP={sheep:2d}  pass_rate={res['pass_rate']:.3f} "
                f"({res['passed']}/{res['n']})  avg_money=${res['avg_money']:.0f}  "
                f"avg_occ={res['avg_occupied']:.1f}/25  [{dt:.1f}s]",
                flush=True,
            )
    print(f"\nTotal: {time.time() - t0:.1f}s for {len(results)} configs", flush=True)

    results.sort(key=lambda r: (-r["pass_rate"], -r["avg_money"]))
    print("\n=== Top 15 ===")
    for r in results[:15]:
        print(r)

    out_path = os.path.join(WORKDIR, "results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results written to {out_path}")
