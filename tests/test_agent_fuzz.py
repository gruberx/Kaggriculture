"""Fault-tolerance fuzzing - see SPEC-agent.md "Fault tolerance" and
tasks/plan.md T2.2.

tests/test_agent_main.py already covers the two trivial cases (`{}`,
`None`). This file targets observations that are *almost* valid - missing
one key, one wrong type, one out-of-range index - specifically chosen to
reach past the policy's early guards and fail deeper in, on whichever
field each mutation actually removes or corrupts.

Split into two groups since T3.5's real policy (kagg.policy.decide)
changed which fields are actually load-bearing, compared to the Phase 0
wheat loop this file was originally written against:

- _MUST_CRASH_CASES: fields decide() genuinely needs (player, farms[player],
  private, market inventory/prices) - still crash and fall back to
  SAFE_DEFAULT_ACTION, same as before T3.5.
- _TOLERATED_CASES: decide() never reads obs["day"] at all (unlike the old
  wheat loop, which computed crop_age from it directly) - these no longer
  crash. The real invariant SPEC-agent.md guarantees is "never raises,
  always a valid action shape," not "always degrades to the safe default
  for anything less than perfectly well-formed" - a policy tolerating
  more malformed input gracefully, by not needing the field at all, is a
  behavior change worth recording accurately, not a regression to force
  back down by weakening the policy.
"""

import copy

from kagg.agent_main import SAFE_DEFAULT_ACTION, agent

# A fully valid baseline where the policy reaches its "buy a seed" branch
# (empty tile, no seeds yet, enough money) - a minimal but real path
# through the code, so mutating one field at a time actually matters.
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
# mutations here exercise the market-sell branch that _BASE_OBS's empty
# farm never reaches.
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


def _is_valid_action_shape(action) -> bool:
    return (
        isinstance(action, dict)
        and set(action) == {"farmer", "hands", "market"}
        and isinstance(action["farmer"], list)
        and isinstance(action["hands"], list)
        and isinstance(action["market"], list)
    )


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


_MUST_CRASH_CASES = {
    "missing_player": _without_key(_BASE_OBS, "player"),
    "missing_farms": _without_key(_BASE_OBS, "farms"),
    "missing_private": _without_key(_BASE_OBS, "private"),
    "missing_market_with_shed_contents": _without_key(_PLANTED_OBS, "market"),
    "player_out_of_range": _mutated(_BASE_OBS, player=5),
    "farms_empty_list": _mutated(_BASE_OBS, farms=[]),
    "farms_is_not_a_list": _mutated(_BASE_OBS, farms="not-a-list"),
}

_TOLERATED_CASES = {
    "day_wrong_type_with_planted_crop": _mutated(_PLANTED_OBS, day="not-a-number"),
    "day_missing_with_planted_crop": _without_key(_PLANTED_OBS, "day"),
}


def test_must_crash_cases_never_raise_and_return_safe_default():
    failures = {}
    for name, obs in _MUST_CRASH_CASES.items():
        try:
            result = agent(obs)
        except Exception as exc:  # pragma: no cover - agent() must not let this happen
            failures[name] = f"raised {type(exc).__name__}: {exc}"
            continue
        if result != SAFE_DEFAULT_ACTION:
            failures[name] = f"returned {result!r} instead of the safe default"
    assert not failures, failures


def test_tolerated_cases_never_raise_and_return_a_valid_action():
    failures = {}
    for name, obs in _TOLERATED_CASES.items():
        try:
            result = agent(obs)
        except Exception as exc:  # pragma: no cover
            failures[name] = f"raised {type(exc).__name__}: {exc}"
            continue
        if not _is_valid_action_shape(result):
            failures[name] = f"returned an invalid action shape: {result!r}"
    assert not failures, failures


def test_farmer_missing_from_farm_dict():
    obs = copy.deepcopy(_BASE_OBS)
    del obs["farms"][0]["farmer"]
    assert agent(obs) == SAFE_DEFAULT_ACTION


def test_farmer_position_malformed():
    obs = copy.deepcopy(_BASE_OBS)
    obs["farms"][0]["farmer"] = 4  # not an [x, y] pair - unpacking must fail
    assert agent(obs) == SAFE_DEFAULT_ACTION


def test_tiles_too_small_for_farmer_position_does_not_raise():
    # Behavior change from before T3.5: the old wheat-loop policy indexed
    # tiles[fy][fx] directly with the farmer's raw position and crashed
    # here. decide()'s build_task_list() only scans rows/columns that
    # actually exist and never indexes tiles by the farmer's position
    # directly, so this no longer needs the except-fallback at all -
    # checked for "doesn't raise, valid shape," not "is exactly the safe
    # default," since a real (if unremarkable) decision comes back now.
    obs = copy.deepcopy(_BASE_OBS)
    obs["farms"][0]["tiles"] = [[None, None], [None, None]]  # farmer sits at (4, 4)
    result = agent(obs)
    assert _is_valid_action_shape(result)


def test_money_missing_from_farm_dict():
    obs = copy.deepcopy(_BASE_OBS)
    del obs["farms"][0]["money"]
    assert agent(obs) == SAFE_DEFAULT_ACTION
