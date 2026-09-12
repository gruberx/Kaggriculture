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


def test_buy_wheat_order_returns_none_when_stock_is_sufficient():
    assert buy_wheat_order(wheat_on_hand=10, wheat_price=25, params={"wheat_restock_threshold": 5}) is None


def test_buy_wheat_order_returns_none_when_price_is_too_high():
    assert buy_wheat_order(wheat_on_hand=0, wheat_price=1000, params={"wheat_max_buy_price": 40}) is None


def test_buy_wheat_order_restocks_when_low_and_affordable():
    order = buy_wheat_order(wheat_on_hand=1, wheat_price=25, params={"wheat_restock_threshold": 5, "wheat_restock_qty": 10})
    assert order == ["BUY_PRODUCT", "WHEAT", 10]


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
