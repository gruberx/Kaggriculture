"""Tests for kagg.gamelib.market - see SPEC-gamelib.md.

These are the T0.1 spot-checks (tasks/plan.md). The full property-test suite
against the real kaggriculture.py oracle is Phase 1 (T1.1+), not this task.
"""

from kagg.gamelib.market import price, shape


def test_price_at_i0_returns_base():
    # At the shared starting inventory I0, price must equal the resource's
    # base price exactly - this is the anchor point the whole curve is
    # built around (SPEC-gamelib.md's price-function table: WHEAT base=25).
    assert price("WHEAT", 10000) == 25


def test_price_returns_int_not_float():
    # A float here would silently disagree with the real market by
    # sub-cent amounts near the floor - SPEC-gamelib.md flags this
    # explicitly as a subtlety to get right.
    result = price("WHEAT", 0)
    assert isinstance(result, int)


def test_price_floors_at_one_under_extreme_glut():
    # Extreme oversupply must clamp to PRICE_FLOOR, never go to zero or
    # negative.
    assert price("MELON", 10_000_000) == 1


def test_shape_hinge_degenerates_to_linear_without_t():
    # Per kaggriculture.py's _shape: hinge degenerates to linear if T is
    # missing or non-positive.
    assert shape("hinge", 5.0, None) == 5.0


def test_shape_hinge_equals_one_at_t():
    # By construction, f(T) == 1 for hinge (keeps `target` meaning the same
    # thing it does for every other shape) - SPEC-gamelib.md.
    assert shape("hinge", 100.0, 100.0) == 1.0
