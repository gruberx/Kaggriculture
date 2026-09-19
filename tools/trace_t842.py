"""T8.42 trace: why (min_hires_per_day=8, land_purchase_threshold_money=0)
decisively beat the shipped baseline (96% n=50, 89.5% n=200 holdout,
tools/measure_t842.py) - confirming the real mechanism, not just trusting
the aggregate number (T8.33's own "no result without a trace" discipline).

Checks, per the plan (`/root/.claude/plans/jazzy-jumping-lamport.md`):
  1. Hand count trajectory actually matches the min_hires_per_day=8 floor
     from day 0 (not a reactive/mistimed signal like T8.34's rejected
     workload_forecast_free_tile_weight).
  2. Quadrant-unlock day, and whether the newly-opened land actually gets
     planted promptly (not left idle - the exact T8.33 failure mode for
     a low land threshold with unchanged labor).
  3. Whether BUY_LAND is ever silently truncated out of a hires-heavy
     turn's order queue (_MAX_MARKET_ORDERS=10, hires+sells+tail
     concatenated then truncated) - a real, once-per-day-at-most risk
     named in the plan, checked directly rather than assumed away.
  4. Final tile/animal/quadrant counts vs. T8.40's real top-player
     medians - is this candidate actually closing the real gap, not
     winning by an unrelated margin.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import top_replay_stats as trs  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t842_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)

_SEASON_LENGTH_DAYS = 30
CANDIDATE_PARAMS = dict(DEFAULT_PARAMS, min_hires_per_day=8, land_purchase_threshold_money=0)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_agent = tuning.write_candidate_agent(CANDIDATE_PARAMS, WORKDIR)


def trace_seed(seed: int) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([candidate_agent, baseline_agent])
    steps = env.steps

    print(f"=== seed {seed} (candidate=team0, baseline=team1) ===")

    # 1. Hand count trajectory, days 0-12.
    hand_traj = [trs.hands_for_day(steps, d, 0)["hands_max"] for d in range(12)]
    print(f"  candidate hands_max day0-11: {hand_traj}")

    # 2. Quadrant-unlock day + land occupancy for both teams.
    for team, label in ((0, "candidate"), (1, "baseline")):
        unlocks = trs.quadrant_unlock_days(steps, team)
        print(f"  {label} quadrant_unlock_days: {unlocks}")
    for day in (0, 3, 6, 9, 12, 15, 20, 25, 29):
        tc = trs.board_for_day(steps, day, 0)
        print(
            f"    day {day} [candidate]: quads={tc['n_quadrants']} plants={tc['plants_total']} "
            f"animals={tc['animals_total']} empty={tc['empty']} weeds={tc['weeds']}"
        )

    # 3. _MAX_MARKET_ORDERS truncation check: did BUY_LAND ever appear in
    # should_buy_land-eligible state but not actually fire that turn
    # because HIRE orders crowded out the tail? Approximate directly from
    # the real action log: count turns where 8 HIRE orders were queued
    # simultaneously, and check the very next BUY_LAND turn's delay.
    hires_per_turn = []
    buy_land_turns = []
    for t in range(1, len(steps)):
        action = steps[t][0]["action"]
        if not action:
            continue
        orders = action.get("market", [])
        n_hires = sum(1 for o in orders if o and o[0] == "HIRE")
        if n_hires:
            hires_per_turn.append((t, n_hires))
        if any(o and o[0] == "BUY_LAND" for o in orders):
            buy_land_turns.append(t)
    max_simultaneous_hires = max((n for _, n in hires_per_turn), default=0)
    print(f"  max simultaneous HIRE orders in one turn: {max_simultaneous_hires}")
    print(f"  BUY_LAND fired on turns: {buy_land_turns}")

    # 4. Final counts vs. real top-player medians (T8.40: hands~10 by
    # day 9, animals~15 by day 29, 2nd quadrant by day ~6-9).
    final = steps[-1]
    tc_final = trs.board_for_day(steps, 29, 0)
    tb_final = trs.board_for_day(steps, 29, 1)
    print(
        f"  final money: candidate={final[0].reward:.0f} baseline={final[1].reward:.0f} | "
        f"day29 quads: candidate={tc_final['n_quadrants']} baseline={tb_final['n_quadrants']} | "
        f"day29 animals: candidate={tc_final['animals_total']} baseline={tb_final['animals_total']}"
    )
    print()


for seed in (100, 101, 900):
    trace_seed(seed)
