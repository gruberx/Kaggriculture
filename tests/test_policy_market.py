"""Unit tests for kagg.policy.market - see SPEC-policy.md "3. Market
layer" and tasks/plan.md T3.3.

No oracle needed - new decision logic. The plan's literal acceptance
criterion asks for "a shed with more than 10 sellable lots" to prove the
order cap - but only 9 products exist in this game at all (PRODUCTS in
gamelib.constants), so >10 *real* sellable lots isn't reachable. Tested
instead via an explicit smaller `max_orders` override on a full 9-item
shed, which exercises the same capping mechanism without a contrived,
unreachable-in-the-real-game shed.
"""

from kagg.gamelib.constants import CROPS, MARKET_I0, PRODUCTS
from kagg.policy.market import (
    PREMIUM_GOODS,
    buy_wheat_order,
    market_orders,
    sell_orders,
)

_BASE_MARKET_INVENTORY = {p: MARKET_I0 for p in PRODUCTS}


def _full_shed(count: int = 20) -> dict:
    return {p: count for p in PRODUCTS}


def test_sell_orders_respects_a_smaller_max_orders_override():
    orders = sell_orders(_full_shed(), _BASE_MARKET_INVENTORY, max_orders=3)
    assert len(orders) <= 3


def test_sell_orders_never_exceeds_the_default_max_orders():
    orders = sell_orders(_full_shed(), _BASE_MARKET_INVENTORY)
    assert len(orders) <= 10


def test_sell_orders_skips_items_with_zero_stock():
    shed = {p: 0 for p in PRODUCTS}
    shed["WHEAT"] = 5
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY)
    assert orders == [["SELL", "WHEAT", 5]]


def test_sell_orders_reserves_wheat_for_feeding_instead_of_selling_it_all():
    # Real bug found while implementing T6.4: the wheat buy/sell
    # arbitrage (a real, deliberate small income source - see T3.6) sold
    # 100% of shed WHEAT every turn it was profitable, racing against any
    # attempt to PICKUP wheat for feeding a placed animal - a direct
    # episode trace showed the shed's WHEAT flickering 0/10 every single
    # turn, so the farmer could never complete a PICKUP before the
    # arbitrage's own SELL order emptied the shed again, and the placed
    # animal starved and escaped. wheat_reserve keeps enough on hand
    # regardless of how profitable selling it would otherwise be.
    shed = {p: 0 for p in PRODUCTS}
    shed["WHEAT"] = 10
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, wheat_reserve=10)
    assert orders == []


def test_sell_orders_sells_only_the_wheat_above_the_reserve():
    shed = {p: 0 for p in PRODUCTS}
    shed["WHEAT"] = 15
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, wheat_reserve=10)
    assert orders == [["SELL", "WHEAT", 5]]


def test_sell_orders_reserve_never_blocks_other_products():
    shed = {p: 0 for p in PRODUCTS}
    shed["WHEAT"] = 5
    shed["EGG"] = 4
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, wheat_reserve=10)
    assert orders == [["SELL", "EGG", 4]]


def test_sell_orders_never_emits_an_order_for_a_non_product_item():
    # The shed can also hold live animals waiting to be PLACEd - those are
    # never a SELL candidate (README.md: only products are sellable).
    shed = {"GOOSE": 3, "COW": 1}
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY)
    assert orders == []


def test_sell_orders_drip_sells_premium_goods():
    shed = {p: 0 for p in PRODUCTS}
    shed["MELON"] = 50
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, params={"drip_sell_max_per_turn": 5})
    assert orders == [["SELL", "MELON", 5]]


def test_sell_orders_does_not_cap_non_premium_goods():
    shed = {p: 0 for p in PRODUCTS}
    shed["WHEAT"] = 50
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, params={"drip_sell_max_per_turn": 5})
    assert orders == [["SELL", "WHEAT", 50]]


def test_sell_orders_covers_every_named_premium_good():
    assert PREMIUM_GOODS == {"MILK", "WOOL", "MELON", "STRAWBERRY"}


def test_sell_orders_respects_the_margin_parameter():
    # WHEAT's cost basis is its seed cost (10, gamelib.constants.CROPS).
    # At I0, price(WHEAT) == base == 25. A margin of 20 requires price >
    # 30, which 25 doesn't clear.
    shed = {p: 0 for p in PRODUCTS}
    shed["WHEAT"] = 5
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, params={"sell_margin": 20})
    assert orders == []


def test_sell_orders_default_margin_sells_whenever_price_is_positive():
    # Default margin is 0 - an animal product's cost basis is 0 (no
    # direct per-unit input cost), so it sells at any positive price,
    # which PRICE_FLOOR guarantees.
    shed = {p: 0 for p in PRODUCTS}
    shed["EGG"] = 4
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY)
    assert orders == [["SELL", "EGG", 4]]


def test_sell_orders_never_routinely_sells_fertilizer():
    # T8.3e: FERTILIZER exists to be applied via FERTILIZE (a real yield
    # lever - see tasks.py's own FERTILIZE task), not sold off the moment
    # it's collected - selling it the same turn it lands in the shed
    # would starve the new FERTILIZE task of any input to act on.
    shed = {p: 0 for p in PRODUCTS}
    shed["FERTILIZER"] = 4
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY)
    assert orders == []


def test_sell_orders_liquidates_fertilizer_near_season_end():
    # Once there's no time left to ever apply it, unsold FERTILIZER is
    # just as much a total loss as any other stranded shed stock (T8.3d) -
    # liquidate=True overrides the never-routinely-sold rule too.
    shed = {p: 0 for p in PRODUCTS}
    shed["FERTILIZER"] = 4
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, liquidate=True)
    assert orders == [["SELL", "FERTILIZER", 4]]


def test_sell_orders_sells_below_margin_when_liquidating():
    # T8.3d: near season end, holding out for a price recovery that will
    # never arrive is strictly worse than selling now at any positive
    # price (PRICE_FLOOR guarantees > 0) - unsold shed stock scores zero
    # at episode end (confirmed in the real kaggriculture.py engine:
    # reward is final money only, no auto-liquidation). liquidate=True
    # overrides the margin check entirely.
    shed = {p: 0 for p in PRODUCTS}
    shed["WHEAT"] = 5
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, params={"sell_margin": 20}, liquidate=True)
    assert orders == [["SELL", "WHEAT", 5]]


def test_sell_orders_ignores_the_drip_cap_when_liquidating():
    # Same reasoning as above, applied to PREMIUM_GOODS: the drip cap
    # exists to protect *future* price levels, which don't matter once
    # there's no future turn left to sell into.
    shed = {p: 0 for p in PRODUCTS}
    shed["MELON"] = 50
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, params={"drip_sell_max_per_turn": 5}, liquidate=True)
    assert orders == [["SELL", "MELON", 50]]


def test_sell_orders_liquidate_defaults_to_false():
    shed = {p: 0 for p in PRODUCTS}
    shed["MELON"] = 50
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, params={"drip_sell_max_per_turn": 5})
    assert orders == [["SELL", "MELON", 5]]


def test_market_orders_passes_liquidate_through_to_sell_orders():
    shed = {p: 0 for p in PRODUCTS}
    shed["MELON"] = 50
    orders = market_orders(
        shed,
        _BASE_MARKET_INVENTORY,
        market_prices={"WHEAT": 25},
        wheat_on_hand=0,
        params={"drip_sell_max_per_turn": 5, "wheat_restock_threshold": 0},
        liquidate=True,
    )
    assert ["SELL", "MELON", 50] in orders


def test_buy_wheat_order_returns_none_when_stock_is_sufficient():
    assert buy_wheat_order(wheat_on_hand=10, wheat_price=25, params={"wheat_restock_threshold": 5}) is None


def test_buy_wheat_order_returns_none_when_price_is_too_high():
    assert buy_wheat_order(wheat_on_hand=0, wheat_price=1000, params={"wheat_max_buy_price": 40}) is None


def test_buy_wheat_order_restocks_when_low_and_affordable():
    order = buy_wheat_order(wheat_on_hand=1, wheat_price=25, params={"wheat_restock_threshold": 5, "wheat_restock_qty": 10})
    assert order == ["BUY_PRODUCT", "WHEAT", 10]


def test_buy_wheat_order_urgency_override_ignores_price_cap_when_critically_low():
    # T8.25 Part 2: once wheat_on_hand is at or below wheat_urgency_reserve,
    # an escaped animal is worth more than the price ceiling was ever meant
    # to protect against - see kagg.policy.market's own module docstring
    # addendum and the plan's traced seed-900 story (WHEAT price drifting
    # past wheat_max_buy_price for the entire rest of the season).
    order = buy_wheat_order(
        wheat_on_hand=0,
        wheat_price=1000,
        params={"wheat_max_buy_price": 40, "wheat_urgency_reserve": 2, "wheat_restock_threshold": 5, "wheat_restock_qty": 10},
    )
    assert order == ["BUY_PRODUCT", "WHEAT", 10]


def test_buy_wheat_order_urgency_override_is_inactive_above_the_reserve():
    # Still price-gated as normal once wheat_on_hand clears the urgency
    # reserve, even though it's still below the restock threshold.
    order = buy_wheat_order(
        wheat_on_hand=3,
        wheat_price=1000,
        params={"wheat_max_buy_price": 40, "wheat_urgency_reserve": 2, "wheat_restock_threshold": 5},
    )
    assert order is None


def test_buy_wheat_order_urgency_override_defaults_to_disabled():
    # Bit-identical to pre-T8.25 behavior for every existing caller that
    # doesn't pass wheat_urgency_reserve - the price cap alone still
    # blocks the purchase even at wheat_on_hand=0.
    order = buy_wheat_order(
        wheat_on_hand=0, wheat_price=1000, params={"wheat_max_buy_price": 40, "wheat_restock_threshold": 5}
    )
    assert order is None


def test_market_orders_never_emits_buy_product_for_anything_but_wheat():
    # tasks/plan.md T3.3's literal acceptance criterion.
    shed = _full_shed()
    orders = market_orders(
        shed,
        _BASE_MARKET_INVENTORY,
        market_prices={"WHEAT": 25},
        wheat_on_hand=0,
        params={"wheat_restock_threshold": 100},  # force a restock order to appear
    )
    buy_product_orders = [o for o in orders if o[0] == "BUY_PRODUCT"]
    assert all(o[1] == "WHEAT" for o in buy_product_orders)
    assert len(buy_product_orders) == 1


def test_market_orders_passes_the_wheat_reserve_through_to_sell_orders():
    shed = {p: 0 for p in PRODUCTS}
    shed["WHEAT"] = 10
    orders = market_orders(
        shed, _BASE_MARKET_INVENTORY, market_prices={"WHEAT": 25}, wheat_on_hand=10, wheat_reserve=10
    )
    assert [o for o in orders if o[0] == "SELL"] == []


def test_market_orders_total_never_exceeds_max_orders():
    shed = _full_shed()
    orders = market_orders(
        shed,
        _BASE_MARKET_INVENTORY,
        market_prices={"WHEAT": 25},
        wheat_on_hand=0,
        params={"wheat_restock_threshold": 100},
        max_orders=10,
    )
    assert len(orders) <= 10


def test_buy_wheat_order_does_not_buy_when_no_feed_is_needed():
    # T8.3l: the user's own observed defect - the agent was buying and
    # selling 10 WHEAT every single turn before any animal was ever
    # placed or even being pursued. feed_needed=False means there is no
    # animal to feed at all, so restocking has no purpose yet.
    order = buy_wheat_order(
        wheat_on_hand=0, wheat_price=25, params={"wheat_restock_threshold": 5}, feed_needed=False
    )
    assert order is None


def test_buy_wheat_order_still_buys_when_feed_is_needed():
    # Guards the default (feed_needed=True) - every existing caller and
    # test above this one relies on the restock logic firing unchanged.
    order = buy_wheat_order(
        wheat_on_hand=0, wheat_price=25, params={"wheat_restock_threshold": 5, "wheat_restock_qty": 10}
    )
    assert order == ["BUY_PRODUCT", "WHEAT", 10]


def test_market_orders_does_not_ping_pong_wheat():
    # T8.3l: direct regression test for the reported symptom. Traced in a
    # real self-play episode (seed 100): with wheat_reserve=0 (no animal
    # placed yet), buy_wheat_order tops the shed back up to
    # wheat_restock_qty every turn immediately after sell_orders empties
    # it below wheat_restock_threshold - restock and sell-everything
    # fight each other forever, 147 buy/sell pairs in one episode. The
    # fix: market_orders never lets the reserve it sells down to fall
    # below the restock threshold whenever feed is actually needed (a
    # belt-and-braces invariant, not just gating the buy side) - so
    # there's nothing left for a restock to react to.
    shed = {p: 0 for p in PRODUCTS}
    shed["WHEAT"] = 10
    orders = market_orders(
        shed,
        _BASE_MARKET_INVENTORY,
        market_prices={"WHEAT": 25},
        wheat_on_hand=10,
        params={"wheat_restock_threshold": 5, "wheat_restock_qty": 10},
        feed_needed=True,
    )
    assert [o for o in orders if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"] == []
    sell_orders_emitted = [o for o in orders if o[0] == "SELL" and o[1] == "WHEAT"]
    remaining = 10 - (sell_orders_emitted[0][2] if sell_orders_emitted else 0)
    assert remaining >= 5


def test_sell_orders_ignores_the_wheat_reserve_when_liquidating():
    # T8.3l: sell_orders previously subtracted wheat_reserve even under
    # liquidate=True, stranding the feed reserve (~10 WHEAT, worthless
    # unsold at episode end per T8.3d) once an animal had been placed.
    # There is no future feeding to protect it for once liquidation has
    # begun.
    shed = {p: 0 for p in PRODUCTS}
    shed["WHEAT"] = 10
    orders = sell_orders(shed, _BASE_MARKET_INVENTORY, wheat_reserve=10, liquidate=True)
    assert orders == [["SELL", "WHEAT", 10]]


# --- bulk_purchase_plan (T8.45) -----------------------------------------


def test_bulk_purchase_plan_covers_target_plus_rounded_up_buffer():
    from kagg.policy.market import bulk_purchase_plan

    # 24 tiles + 10% = 26.4 -> 27 seeds, nothing on hand.
    plan = bulk_purchase_plan(["MELON"], {}, {"MELON": 80}, 24, 10_000, buffer_fraction=0.10)
    assert plan == {"MELON": 27}


def test_bulk_purchase_plan_subtracts_seeds_already_held():
    from kagg.policy.market import bulk_purchase_plan

    plan = bulk_purchase_plan(["MELON"], {"MELON": 20}, {"MELON": 80}, 24, 10_000, 0.10)
    assert plan == {"MELON": 7}  # 27 - 20


def test_bulk_purchase_plan_buys_nothing_when_holdings_already_cover_it():
    from kagg.policy.market import bulk_purchase_plan

    assert bulk_purchase_plan(["MELON"], {"MELON": 27}, {"MELON": 80}, 24, 10_000, 0.10) == {}
    assert bulk_purchase_plan(["MELON"], {"MELON": 99}, {"MELON": 80}, 24, 10_000, 0.10) == {}


def test_bulk_purchase_plan_ignores_held_units_of_types_outside_the_plan():
    from kagg.policy.market import bulk_purchase_plan

    plan = bulk_purchase_plan(["MELON"], {"WHEAT": 50}, {"MELON": 80}, 10, 10_000, 0.0)
    assert plan == {"MELON": 10}


def test_bulk_purchase_plan_spreads_one_total_across_several_types():
    from kagg.policy.market import bulk_purchase_plan

    plan = bulk_purchase_plan(
        ["MELON", "CARROT"], {}, {"MELON": 80, "CARROT": 20}, 10, 10_000, buffer_fraction=0.0
    )
    assert sum(plan.values()) == 10
    assert plan == {"MELON": 5, "CARROT": 5}


def test_bulk_purchase_plan_water_fills_around_uneven_holdings():
    from kagg.policy.market import bulk_purchase_plan

    # 10 total wanted, 6 CARROT already held -> 4 more, all to MELON first
    # (lowest holdings), ending balanced-ish rather than 5/5 on top.
    plan = bulk_purchase_plan(
        ["MELON", "CARROT"], {"CARROT": 6}, {"MELON": 80, "CARROT": 20}, 10, 10_000, 0.0
    )
    assert plan == {"MELON": 4}


def test_bulk_purchase_plan_is_limited_by_budget():
    from kagg.policy.market import bulk_purchase_plan

    plan = bulk_purchase_plan(["MELON"], {}, {"MELON": 80}, 24, 400, 0.10)
    assert plan == {"MELON": 5}  # floor(400 / 80)


def test_bulk_purchase_plan_skips_an_unaffordable_type_for_an_affordable_one():
    from kagg.policy.market import bulk_purchase_plan

    plan = bulk_purchase_plan(
        ["MELON", "CARROT"], {}, {"MELON": 80, "CARROT": 20}, 10, 70, buffer_fraction=0.0
    )
    assert plan == {"CARROT": 3}  # MELON never affordable; 70 // 20 = 3


def test_bulk_purchase_plan_rounds_down_when_asked_and_buffer_cannot_fill_a_unit():
    from kagg.policy.market import bulk_purchase_plan

    # animals: 3 planned + 10% = 3.3 -> floor 3 (no extra), but 10 + 10% = 11.
    assert bulk_purchase_plan(["COW"], {}, {"COW": 400}, 3, 10_000, 0.10, round_up=False) == {"COW": 3}
    assert bulk_purchase_plan(["COW"], {}, {"COW": 400}, 10, 10_000, 0.10, round_up=False) == {"COW": 11}


def test_bulk_purchase_plan_empty_inputs():
    from kagg.policy.market import bulk_purchase_plan

    assert bulk_purchase_plan([], {}, {}, 5, 100) == {}
    assert bulk_purchase_plan(["MELON"], {}, {"MELON": 80}, 0, 100) == {}
