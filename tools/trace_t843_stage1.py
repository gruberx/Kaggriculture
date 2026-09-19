"""T8.43 Stage 1 trace: why defer_one_time_harvest_to_max_yield decisively
lost (40% win rate, 20W/30L/0T, n=50 - tools/measure_t843.py) instead of
winning as predicted.

Hypothesis checked directly, not assumed: WHEAT cycles extremely fast
(first_yield_day=2, max_yield_day=4) - harvesting the instant it's legal
and replanting immediately lets one tile cycle through *multiple* harvests
in the time a single deferred-to-max_yield harvest takes. The extra yield
per harvest (waiting for the bonus window) may be worth far less than the
throughput lost by holding the tile occupied for 2 extra days each cycle -
an opportunity-cost effect the plan's own yield-per-harvest framing didn't
account for. Checks PLANT/HARVEST counts and per-crop tile-day
"occupancy" for both teams to confirm or refute this before writing off
the whole idea.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import top_replay_stats as trs  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t843_stage1_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)

CANDIDATE_PARAMS = dict(DEFAULT_PARAMS, defer_one_time_harvest_to_max_yield=True)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_agent = tuning.write_candidate_agent(CANDIDATE_PARAMS, WORKDIR)


def trace_seed(seed: int) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([candidate_agent, baseline_agent])
    steps = env.steps

    print(f"=== seed {seed} (candidate=team0 defer-on, baseline=team1 defer-off) ===")

    for team, label in ((0, "candidate"), (1, "baseline")):
        total_harvest = 0
        total_plant = 0
        for day in range(30):
            ac = trs.action_counts(steps, day, team)
            total_harvest += ac["farmer"].get("HARVEST", 0) + ac["hands"].get("HARVEST", 0)
            total_plant += ac["farmer"].get("PLANT", 0) + ac["hands"].get("PLANT", 0)
        final_board = trs.board_for_day(steps, 29, team)
        final_money = trs.money_for_day(steps, 29, team)
        print(
            f"  {label}: total_HARVEST={total_harvest} total_PLANT={total_plant} "
            f"final_plants={final_board['plants']} final_money={final_money}"
        )

    for day in (0, 2, 4, 6, 10, 15, 20, 25, 29):
        c = trs.board_for_day(steps, day, 0)
        b = trs.board_for_day(steps, day, 1)
        print(f"  day {day}: candidate plants={c['plants']} weeds={c['weeds']} | baseline plants={b['plants']} weeds={b['weeds']}")


for seed in (900, 901, 902):
    trace_seed(seed)
