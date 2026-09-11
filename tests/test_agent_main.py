"""Tests for kagg.agent_main - the submission entry point (SPEC-agent.md).

This is T0.2's minimal skeleton check (agent() never raises, returns the
safe default on any failure). The full fault-tolerance fuzz suite -
missing keys, wrong types, a short farms list, an out-of-range player
index - is Phase 2 (T2.2), not this task.
"""

from kagg.agent_main import SAFE_DEFAULT_ACTION, agent


def test_agent_returns_safe_default_for_empty_observation():
    assert agent({}) == SAFE_DEFAULT_ACTION


def test_agent_never_raises_on_non_dict_observation():
    # None isn't a valid observation at all; _decide() will fail on it
    # however it's implemented, and agent()'s try/except must swallow that.
    assert agent(None) == SAFE_DEFAULT_ACTION


def test_safe_default_is_not_mutated_by_repeated_calls():
    # agent() must return a fresh dict each time, not a shared reference to
    # the module-level constant - a caller (or future policy code) mutating
    # its returned action dict must not corrupt every subsequent turn.
    first = agent({})
    first["farmer"].append("MUTATED")
    second = agent({})
    assert second == SAFE_DEFAULT_ACTION
