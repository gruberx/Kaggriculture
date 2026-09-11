"""Fault-tolerance fuzzing - see SPEC-agent.md "Fault tolerance" and
tasks/plan.md T2.2.

tests/test_agent_main.py already covers the two trivial cases (`{}`,
`None`). This file targets observations that are *almost* valid - missing
one key, one wrong type, one out-of-range index - specifically chosen to
reach past wheat_loop_action's early guards and fail deeper in, on
whichever field each mutation actually removes or corrupts. Every case
must come back as SAFE_DEFAULT_ACTION, never a raised exception.
"""

import copy

from kagg.agent_main import SAFE_DEFAULT_ACTION, agent

# A fully valid baseline where wheat_loop_action reaches its "buy a seed"
# branch (empty tile, no seeds yet, enough money) - a minimal but real
# path through the code, so mutating one field at a time actually matters.
_BASE_OBS = {
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

# A second baseline with a planted, growing crop and shed produce - so
# mutations here exercise the day-arithmetic and market-sell branches that
# _BASE_OBS's empty farm never reaches.
_PLANTED_OBS = copy.deepcopy(_BASE_OBS)
_PLANTED_OBS["day"] = 3
_PLANTED_OBS["farms"][0]["tiles"][4][4] = {
    "kind": "PLANT",
    "crop": "WHEAT",
    "planted_day": 1,
    "watered_today": False,
    "consecutive_unwatered": 0,
    "yield_units": 1,
    "max_lifespan_step": 120,
    "fertilized_until_day": -1,
}
_PLANTED_OBS["private"]["shed"]["WHEAT"] = 5


def _sanity_check_baselines_are_actually_valid():
    """Not a test - a guard against this file's own fuzz cases being
    meaningless because the "valid" baselines were never valid to begin
    with. Both must produce a real decision, not the safe default, or the
    fuzz tests below would be trivially passing for the wrong reason."""
    assert agent(_BASE_OBS) != SAFE_DEFAULT_ACTION
    assert agent(_PLANTED_OBS) != SAFE_DEFAULT_ACTION


_sanity_check_baselines_are_actually_valid()


def _without_key(obs: dict, key: str) -> dict:
    mutated = copy.deepcopy(obs)
    del mutated[key]
    return mutated


def _mutated(obs: dict, **overrides) -> dict:
    mutated = copy.deepcopy(obs)
    mutated.update(overrides)
    return mutated


_FUZZ_CASES = {
    "missing_player": _without_key(_BASE_OBS, "player"),
    "missing_farms": _without_key(_BASE_OBS, "farms"),
    "missing_private": _without_key(_BASE_OBS, "private"),
    "missing_market_with_shed_contents": _without_key(_PLANTED_OBS, "market"),
    "player_out_of_range": _mutated(_BASE_OBS, player=5),
    "farms_empty_list": _mutated(_BASE_OBS, farms=[]),
    "farms_is_not_a_list": _mutated(_BASE_OBS, farms="not-a-list"),
    "day_wrong_type_with_planted_crop": _mutated(_PLANTED_OBS, day="not-a-number"),
    "day_missing_with_planted_crop": _without_key(_PLANTED_OBS, "day"),
}


def test_fuzzed_observations_never_raise_and_return_safe_default():
    failures = {}
    for name, obs in _FUZZ_CASES.items():
        try:
            result = agent(obs)
        except Exception as exc:  # pragma: no cover - agent() must not let this happen
            failures[name] = f"raised {type(exc).__name__}: {exc}"
            continue
        if result != SAFE_DEFAULT_ACTION:
            failures[name] = f"returned {result!r} instead of the safe default"
    assert not failures, failures


def test_farmer_missing_from_farm_dict():
    obs = copy.deepcopy(_BASE_OBS)
    del obs["farms"][0]["farmer"]
    assert agent(obs) == SAFE_DEFAULT_ACTION


def test_farmer_position_malformed():
    obs = copy.deepcopy(_BASE_OBS)
    obs["farms"][0]["farmer"] = 4  # not an [x, y] pair - unpacking must fail
    assert agent(obs) == SAFE_DEFAULT_ACTION


def test_tiles_too_small_for_farmer_position():
    obs = copy.deepcopy(_BASE_OBS)
    obs["farms"][0]["tiles"] = [[None, None], [None, None]]  # farmer sits at (4, 4)
    assert agent(obs) == SAFE_DEFAULT_ACTION


def test_money_missing_from_farm_dict():
    obs = copy.deepcopy(_BASE_OBS)
    del obs["farms"][0]["money"]
    assert agent(obs) == SAFE_DEFAULT_ACTION
