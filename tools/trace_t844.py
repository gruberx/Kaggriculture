"""T8.44 trace: why day_plan_hiring_aware at min_hires_per_day=2 (30% win
rate, 15W/35L/0T, n=50 - tools/measure_t844.py) and min_hires_per_day=8
(18%, 9W/41L/0T) both decisively lost, while min=4 won the working block
(66%) but collapsed to 49% on the 200-seed holdout (REJECTED - noise, not
a real effect).

Per the user's own explicit framing (2026-09-19): "если оно не действует
то скорее надо править это чем заменять таким высоким минимальным
порогом" - if a low min_hires_per_day loses, that's reason to diagnose and
fix the day-plan forecast itself, not retreat to a high floor. Checks the
specific risk the plan itself named: the labor_units -> plant_qty/seed_
target throttle spiral (PLANT/BUY_SEED counts collapsing turn over turn
because an undersized early forecast starves its own labor_units input),
by tracking hand counts and PLANT/HIRE/BUY_SEED counts day by day for
both min=2 and the shipped baseline, on the same seeds.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import top_replay_stats as trs  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t844_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)

MIN2_PARAMS = dict(
    DEFAULT_PARAMS, day_plan_hiring_aware=True, min_hires_per_day=2, max_hires_per_day=12,
)
MIN8_PARAMS = dict(
    DEFAULT_PARAMS, day_plan_hiring_aware=True, min_hires_per_day=8, max_hires_per_day=12,
)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
min2_agent = tuning.write_candidate_agent(MIN2_PARAMS, WORKDIR)
min8_agent = tuning.write_candidate_agent(MIN8_PARAMS, WORKDIR)


def trace_seed(candidate_agent, candidate_label: str, seed: int) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([candidate_agent, baseline_agent])
    steps = env.steps

    print(f"=== seed {seed} (candidate=team0 {candidate_label}, baseline=team1 shipped) ===")
    for team, label in ((0, candidate_label), (1, "baseline")):
        print(f"  {label}:")
        for day in (0, 1, 2, 3, 5, 8, 12, 18, 25, 29):
            if day * trs.TURNS_PER_DAY >= len(steps):
                break
            h = trs.hands_for_day(steps, day, team)
            money = trs.money_for_day(steps, day, team)
            ac = trs.action_counts(steps, day, team)
            n_plant = ac["farmer"].get("PLANT", 0) + ac["hands"].get("PLANT", 0)
            n_hire = ac["market"].get("HIRE", {}).get("count", 0)
            n_buy_seed = ac["market"].get("BUY_SEED", {}).get("count", 0)
            board = trs.board_for_day(steps, day, team)
            print(
                f"    day {day:2d}: hands_mid={h['hands_at_mid_day']} hires_today={h['hires_today']} "
                f"PLANT={n_plant} HIRE_orders={n_hire} BUY_SEED_orders={n_buy_seed} "
                f"plants_on_board={board['plants_total']} money_close={money.get('close')} "
                f"hands_pass%={ac['hands_pass_fraction']:.2f}"
            )


for seed in (900, 901, 902):
    trace_seed(min2_agent, "min=2", seed)
print()
for seed in (900, 901, 902):
    trace_seed(min8_agent, "min=8", seed)
