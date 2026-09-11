"""Property test for kagg.gamelib.shed.shed_room() - see SPEC-gamelib.md.

Checks shed_room()'s prediction against the real _drop_inventories_to_shed:
if shed_room() says K units of room are available, dropping N items into
that shed should land exactly min(N, K) of them, with the rest discarded.
"""

import random

from kaggle_environments.envs.kaggriculture import kaggriculture as real

from kagg.gamelib.shed import shed_room

_CAPACITY = 100


def _filled_shed(rng: random.Random, total: int) -> dict:
    """A shed dict (as private['shed'] shapes it) holding exactly `total`
    items, spread arbitrarily across a couple of item names."""
    shed = {"WHEAT": 0, "CARROT": 0, "EGG": 0}
    remaining = total
    items = list(shed)
    for item in items[:-1]:
        take = rng.randint(0, remaining)
        shed[item] = take
        remaining -= take
    shed[items[-1]] = remaining
    return shed


def test_shed_room_matches_real_drop_behavior():
    rng = random.Random(42)
    for _ in range(30):
        current_fill = rng.randint(0, _CAPACITY + 10)  # allow already-over-capacity too
        n_to_drop = rng.randint(0, 30)

        private = real._new_private()
        private["shed"] = _filled_shed(rng, current_fill)
        private["inventories"] = [{"MELON": n_to_drop}] if n_to_drop else [{}]

        room_before = shed_room(private["shed"], _CAPACITY)
        shed_before_total = sum(private["shed"].values())

        real._drop_inventories_to_shed(private, _CAPACITY)

        landed = sum(private["shed"].values()) - shed_before_total
        assert landed == min(n_to_drop, room_before), (current_fill, n_to_drop)


def test_shed_room_never_negative_even_when_over_capacity():
    # A shed can end up over capacity from stacking multiple drops in one
    # end-of-day tick (each PICKUP/DROP call clamps individually against
    # the capacity *at that moment*, not against a running total across a
    # whole turn) - shed_room() must still report 0, never a negative
    # number that a caller might misread as "please remove items".
    assert shed_room({"WHEAT": 150}, _CAPACITY) == 0


def test_shed_room_full_capacity_when_empty():
    assert shed_room({}, _CAPACITY) == _CAPACITY
