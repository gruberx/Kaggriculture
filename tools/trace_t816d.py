"""T8.16(d) trace: confirm the accepted candidate (dynamic_hiring=True,
min_hires_per_day=2, everything else default) actually puts hired hands
to productive work rather than idling - the same seed-900 diagnostic
T8.12's own rejection traced (hand count over time, PASS count, final
money), now for the mechanism that decisively cleared the held-out gate
(49W/1L/0T, 98% - see tools/measure_t816d.py's own log).

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t816d_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 900

CANDIDATE_PARAMS = dict(DEFAULT_PARAMS, dynamic_hiring=True, min_hires_per_day=2)


def trace(agent_path: str, label: str) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=False)
    env.run([agent_path, "pass"])
    steps = env.steps
    final_farm = steps[-1][0].observation["farms"][0]
    money = final_farm["money"]
    hand_counts = [len(s[0].observation["farms"][0].get("hands", [])) for s in steps]
    farmer_pass = sum(1 for s in steps if s[0].action and s[0].action.get("farmer") == ["PASS"])
    hand_pass = sum(
        1
        for s in steps
        if s[0].action
        for h in s[0].action.get("hands", [])
        if h == ["PASS"]
    )
    hand_actions_total = sum(len(s[0].action.get("hands", [])) for s in steps if s[0].action)
    print(f"=== {label} (seed {SEED}) ===")
    print(f"  final money: {money}")
    print(f"  hand count over time: start={hand_counts[0]} mid={hand_counts[len(hand_counts) // 2]} end={hand_counts[-1]}")
    print(f"  farmer PASS turns: {farmer_pass}")
    print(f"  hand PASS turns: {hand_pass} / hand action-turns total: {hand_actions_total}")


baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_agent = tuning.write_candidate_agent(CANDIDATE_PARAMS, WORKDIR)

trace(baseline_agent, "baseline (dynamic_hiring=False, hires_per_day=1)")
trace(candidate_agent, "candidate (dynamic_hiring=True, min_hires_per_day=2)")
