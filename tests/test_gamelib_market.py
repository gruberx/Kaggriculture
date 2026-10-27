"""Tests for kagg.gamelib.market - see SPEC-gamelib.md.

These are the T0.1 spot-checks (tasks/plan.md). The full property-test suite
against the real kaggriculture.py oracle is Phase 1 (T1.1+), not this task.
"""

import pytest
from kaggle_environments.envs.kaggriculture import kaggriculture as real

from kagg.gamelib.constants import MAX_SHOP_INSTANCES, SHOPS, TOWN_CENTER_PRODUCTS
from kagg.gamelib.market import expected_consumption_over_horizon, expected_daily_consumption, price, shape


def test_shops_table_matches_the_real_engine():
    assert SHOPS == real.SHOPS


def test_town_center_products_matches_the_real_engine():
    assert TOWN_CENTER_PRODUCTS == real.TOWN_CENTER_PRODUCTS


def test_max_shop_instances_matches_the_real_engine():
    assert MAX_SHOP_INSTANCES == real.MAX_SHOP_INSTANCES


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


def test_expected_daily_consumption_is_town_center_only_with_no_unlocked_shops():
    # Real defaults: town center draws 1 unit every 24 steps, 24
    # steps/day -> 1.0/day.
    assert expected_daily_consumption("WHEAT", []) == pytest.approx(1.0)


def test_expected_daily_consumption_is_zero_for_fertilizer_with_no_shops():
    # FERTILIZER is excluded from TOWN_CENTER_PRODUCTS and appears in no
    # SHOPS listing.
    assert expected_daily_consumption("FERTILIZER", []) == 0.0


def test_expected_daily_consumption_adds_a_single_product_shops_double_rate():
    # YARN_STORE only sells WOOL, so kaggriculture.py's own
    # `multiplier = 2 if len(products) == 1 else 1` doubles its draw:
    # town center 1.0/day + shop 2 units every 4 steps (6 times/day) = 13.0.
    assert expected_daily_consumption("WOOL", ["YARN_STORE"]) == pytest.approx(1.0 + 2 * 24 / 4)


def test_expected_daily_consumption_a_multi_product_shop_draws_at_the_plain_rate():
    # BAKERY sells both EGG and WHEAT (2 products), so multiplier=1: town
    # center 1.0/day + shop 1 unit every 4 steps (6 times/day) = 7.0.
    assert expected_daily_consumption("EGG", ["BAKERY"]) == pytest.approx(1.0 + 24 / 4)


def test_expected_daily_consumption_ignores_a_shop_that_does_not_sell_the_product():
    assert expected_daily_consumption("MELON", ["YARN_STORE", "BAKERY"]) == pytest.approx(1.0)


def test_expected_daily_consumption_counts_duplicate_shop_instances_independently():
    # Shops are drawn with replacement - two YARN_STORE instances both
    # consume, matching kaggriculture.py's own per-instance loop.
    assert expected_daily_consumption("WOOL", ["YARN_STORE", "YARN_STORE"]) == pytest.approx(1.0 + 2 * (2 * 24 / 4))


def test_expected_consumption_over_horizon_matches_flat_rate_for_a_product_no_shop_sells():
    # MELON appears in no SHOPS listing, so no future unlock can ever add
    # to its rate - the horizon-aware total must collapse to exactly the
    # flat expected_daily_consumption() rate times days_remaining, T8.70's
    # own "0 extra shops means bit-identical to the old flat multiply".
    days_remaining = 10
    flat = expected_daily_consumption("MELON", []) * days_remaining
    assert expected_consumption_over_horizon("MELON", [], current_day=0, days_remaining=days_remaining) == pytest.approx(
        flat
    )


def test_expected_consumption_over_horizon_prices_in_a_future_unlock():
    # WOOL: only YARN_STORE sells it (weight 2, single-product shop).
    # Starting with 0 unlocked shops at current_day=0 over a 3-day
    # horizon: the real engine's own unlock timing (kaggriculture.py's
    # _end_of_day, next_day % shop_unlock_interval == 0) fires the first
    # possible unlock exactly at day 3, not before - so days 1-2 see the
    # plain town-center-only rate (1.0/day) and day 3 sees 1 extra
    # possible shop, weighted 2/8 of len(SHOPS) draws, at 24/4 steps/day:
    # 1.0 + (2/8) * 6 = 2.5.
    total = expected_consumption_over_horizon("WOOL", [], current_day=0, days_remaining=3)
    assert total == pytest.approx(1.0 + 1.0 + 2.5)


def test_expected_consumption_over_horizon_stops_growing_once_shops_are_maxed_out():
    # 8 already-unlocked instances == MAX_SHOP_INSTANCES: no future
    # unlock can ever add more, so the total is exactly the (now
    # elevated) flat rate times days_remaining, same shape as the
    # no-shops case above.
    unlocked = ["YARN_STORE"] * 8
    days_remaining = 5
    flat = expected_daily_consumption("WOOL", unlocked) * days_remaining
    assert expected_consumption_over_horizon(
        "WOOL", unlocked, current_day=0, days_remaining=days_remaining
    ) == pytest.approx(flat)
