"""End-to-end check for the Phase 0 walking skeleton - tasks/plan.md T0.3.

Runs a real 720-turn episode through kaggle_environments and asserts our
agent (a single wheat loop) beats the "pass" baseline. Deliberately an
integration test, not a fast unit test - proving the whole pipeline works
end to end (file loading, sys.path, observation/action shapes) is Phase
0's actual acceptance criterion, not something a mock can stand in for.
"""

import os

from kaggle_environments import make

AGENT_MAIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "kagg", "agent_main.py"
)


def test_wheat_loop_beats_pass_over_a_full_season():
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": 1},
        debug=False,
    )
    env.run([AGENT_MAIN_PATH, "pass"])

    final = env.steps[-1]
    our_result, opponent_result = final[0], final[1]

    assert our_result.status == "DONE"  # no crash, no DeadlineExceeded
    assert our_result.reward > 3000  # starting money; PASS alone never grows it
    assert opponent_result.reward == 3000  # sanity: "pass" never touches its own money
