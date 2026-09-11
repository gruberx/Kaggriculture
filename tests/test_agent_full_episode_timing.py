"""Full-episode timing test - see SPEC-agent.md "Time budget" and
tasks/plan.md T2.3.

Runs a real 720-turn episode and checks our agent's own per-turn
durations, exactly as kaggle_environments measures them for its own
DeadlineExceeded check (kaggle_environments/agent.py: Agent.act() records
`duration = perf_counter() - start` around the whole `self.agent(*args)`
call, stored per-step in `env.logs[step][agent_index]["duration"]").

Budgets: p100 under the 400ms hard ceiling (SPEC-agent.md), and cumulative
overage well under the 60s pool - target <10s total, leaving margin for
slower Kaggle hardware than this dev machine.

Expected to be re-run, not rewritten, once Phase 3 replaces the wheat-loop
policy - the actual numbers will change, but the budgets themselves don't.
"""

import os

from kaggle_environments import make

AGENT_MAIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "kagg", "agent_main.py"
)

_EPISODE_STEPS = 720
_HARD_CEILING_SECONDS = 0.400
_TARGET_CUMULATIVE_OVERAGE_SECONDS = 10.0
_ACT_TIMEOUT_SECONDS = 1.0  # kaggriculture.json's actTimeout


def test_full_episode_stays_within_the_time_budget():
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": _EPISODE_STEPS, "seed": 1},
        debug=False,
    )
    env.run([AGENT_MAIN_PATH, "pass"])

    our_durations = [
        step_logs[0]["duration"]
        for step_logs in env.logs
        if step_logs and "duration" in step_logs[0]
    ]

    # kaggle_environments itself leaves the first two env.logs entries
    # empty (verified directly: env.steps[1]'s action is already a real,
    # agent-computed decision - BUY_SEED, not the default - even though
    # env.logs[1] is []) - an internal bookkeeping quirk of the harness,
    # not something our own code causes or can fix. Tolerate a small,
    # fixed gap rather than either hardcoding that exact quirk count or
    # silently accepting a test that's measuring far less than the full
    # episode because something actually broke.
    assert len(our_durations) >= _EPISODE_STEPS - 5, len(our_durations)

    p100 = max(our_durations)
    assert p100 < _HARD_CEILING_SECONDS, f"slowest turn took {p100:.4f}s"

    cumulative_overage = sum(max(0.0, d - _ACT_TIMEOUT_SECONDS) for d in our_durations)
    assert cumulative_overage < _TARGET_CUMULATIVE_OVERAGE_SECONDS, (
        f"cumulative overage {cumulative_overage:.4f}s"
    )
