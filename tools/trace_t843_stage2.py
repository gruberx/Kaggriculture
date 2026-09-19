"""T8.43 Stage 2 trace: confirms the generalized always_pursue_animal_
target_count mechanism actually diversifies animal types in real episodes
(not just unit-test fixtures) - see tools/measure_t843_stage2.py for the
aggregate win-rate result this checks the mechanism behind.

Checks, per the plan (`/root/.claude/plans/jazzy-jumping-lamport.md`):
  1. animals_total and per-type animal tile counts over the season -
     real diversification (distinct types), not just a higher total of
     one type.
  2. When each animal was placed (day), to see whether the pursuit is
     front-loaded or dragged out.
  3. Final money vs. the shipped baseline, same seeds.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import top_replay_stats as trs  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t843_stage2_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)

TARGET_COUNT = int(sys.argv[2]) if len(sys.argv) > 2 else 2
CAP = int(sys.argv[3]) if len(sys.argv) > 3 else 1
CANDIDATE_PARAMS = dict(
    DEFAULT_PARAMS, always_pursue_animal_target_count=TARGET_COUNT, max_animals_per_type=CAP
)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_agent = tuning.write_candidate_agent(CANDIDATE_PARAMS, WORKDIR)


def trace_seed(seed: int) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([candidate_agent, baseline_agent])
    steps = env.steps

    print(f"=== seed {seed} (candidate=team0 target_count={TARGET_COUNT} cap={CAP}, baseline=team1) ===")
    for team, label in ((0, "candidate"), (1, "baseline")):
        for day in (0, 3, 6, 9, 12, 15, 20, 25, 29):
            board = trs.board_for_day(steps, day, team)
            if board["animals_total"] > 0 or day in (0, 29):
                print(f"    {label} day {day}: animals={board['animals']} animals_total={board['animals_total']}")
        final_money = trs.money_for_day(steps, 29, team)
        print(f"  {label} final_money: {final_money}")


for seed in (900, 901, 902, 903, 904):
    trace_seed(seed)
