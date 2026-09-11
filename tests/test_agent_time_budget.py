"""Time-budget guard - see SPEC-agent.md "Time budget" and tasks/plan.md T2.1.

Exception handling (agent() never raises) is already covered by
tests/test_agent_main.py and is unchanged by this - the time-budget guard
is a separate failure mode: a computation that *succeeds* but takes too
long to trust, which SPEC-agent.md's own words call "a circuit breaker for
pathological cases, not a budget to spend routinely."
"""

from kagg import agent_main
from kagg.policy.wheat_loop import wheat_loop_action

_OBS = {
    "player": 0,
    "day": 0,
    "hour": 0,
    "farms": [
        {
            "money": 3000,
            "tiles": [[None] * 10 for _ in range(10)],
            "farmer": [4, 4],
            "hands": [],
            "unlocked_quadrants": ["NW"],
            "hires_today": 0,
        }
    ],
    "private": {"shed": {}, "seeds": {}, "inventories": [{}]},
    "market": {"inventory": {"WHEAT": 10000}, "prices": {"WHEAT": 25}},
    "town": {"unlocked_shops": []},
}


def test_fast_decisions_pass_through_unaffected(monkeypatch):
    monkeypatch.setattr(agent_main, "_last_good_action", agent_main._safe_default())
    assert agent_main.agent(_OBS) == wheat_loop_action(_OBS)


def test_fast_decision_updates_the_cache(monkeypatch):
    monkeypatch.setattr(agent_main, "_last_good_action", agent_main._safe_default())
    agent_main.agent(_OBS)
    assert agent_main._last_good_action == wheat_loop_action(_OBS)


def test_slow_decision_falls_back_to_the_cached_action(monkeypatch):
    known_good = {"farmer": ["PLANT", "WHEAT"], "hands": [], "market": []}
    monkeypatch.setattr(agent_main, "_last_good_action", known_good)
    monkeypatch.setattr(agent_main, "_TURN_TIME_CEILING_SECONDS", 0.01)

    def _slow_decide(obs):
        import time

        time.sleep(0.05)  # comfortably past the monkeypatched 10ms ceiling
        return {"farmer": ["HARVEST"], "hands": [], "market": []}  # a distinguishable "late" action

    monkeypatch.setattr(agent_main, "_decide", _slow_decide)

    result = agent_main.agent(_OBS)

    assert result == known_good  # not the slow decision
    assert agent_main._last_good_action == known_good  # cache not overwritten by the discarded result


def test_exception_still_returns_safe_default_not_the_cache():
    # The pre-existing fault-tolerance behavior (T0.2) must be unaffected
    # by this task: an exception is a different failure mode from "too
    # slow" and still gets the plain safe default, not a stale cached
    # decision that might no longer make sense for the current turn.
    result = agent_main.agent(None)
    assert result == agent_main.SAFE_DEFAULT_ACTION
