"""Market layer: sell/buy decisions for the shed's contents and wheat
feed-stock - see SPEC-policy.md "3. Market layer" (every turn, capped at
`maxMarketOrdersPerTurn`, default 10).

Only PRODUCTS are sellable (README.md: "every product can be sold via
SELL") - the shed can also hold live animals waiting to be PLACEd on a
structure, but those are never a SELL candidate here. Only WHEAT (and
FERTILIZER, not implemented in this module) can be bought back from the
market at all.

FERTILIZER (T8.3e) is technically a PRODUCT (sellable in principle - it's
in the PRODUCTS list) but is excluded from the *routine* sell loop below:
it exists to be applied via kagg.policy.tasks's FERTILIZE task (a real
yield-doubling lever), not liquidated for cash the moment it's collected -
selling it on sight would starve that task of any input to act on.
`liquidate` (T8.3d) still sells it once there is no more time left to
ever apply it - see `sell_orders`'s own docstring.

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

from kagg.gamelib.constants import CROPS, MARKET_I0, PRODUCTS
from kagg.gamelib.market import price

# Goods whose market depth is thin enough that dumping a large shed stock
# in one turn craters the price well past what a staged sale would fetch
# (SPEC.md's economic analysis: milk/wool/melon/strawberry all use an
# `above_target` > 1, meaning a modest glut already drives them toward the
# $1 floor) - named explicitly in SPEC-policy.md's task description.
PREMIUM_GOODS = frozenset({"MILK", "WOOL", "MELON", "STRAWBERRY"})

# T8.3e: never routinely sold - see this module's own docstring above.
_NEVER_ROUTINELY_SOLD = frozenset({"FERTILIZER"})

_DEFAULT_SELL_MARGIN = 0
_DEFAULT_DRIP_SELL_MAX_PER_TURN = 5


def _cost_basis(item: str) -> int:
    """Approximate cost basis for one unit of `item`: a crop's own seed
    cost, or 0 for an animal product (no direct per-unit input cost - the
    animal purchase and its feed are sunk costs, already paid regardless
    of whether this specific unit of product gets sold).

    Acknowledged simplification, not solved here: once a crop is already
    harvested, its seed cost is sunk either way - refusing to sell below
    it doesn't recoup anything, it just risks the item being discarded
    for free if the shed overflows before any price recovery. This margin
    is a starting, tunable heuristic (SPEC-policy.md: policy encodes "the
    shape of the strategy, not the specific numbers"), not a claim that
    holding harvested goods below cost is provably optimal. The default
    margin of 0 already means "sell whenever price clears zero," i.e.
    whenever price > 0 - which PRICE_FLOOR (gamelib.market) guarantees
    for any item with a market at all.
    """
    if item in CROPS:
        return CROPS[item]["seed"]
    return 0


def sell_orders(
    shed: dict,
    market_inventory: dict,
    params: dict | None = None,
    max_orders: int = 10,
    wheat_reserve: int = 0,
    liquidate: bool = False,
    use_fertilizer: bool = True,
) -> list[list]:
    """Sell orders for this turn, one per sellable item with stock and a
    price that clears its margin, capped at `max_orders` (kept as an
    explicit parameter matching `maxMarketOrdersPerTurn` rather than a
    bare literal, so a different configuration can't silently violate it
    - though with only 9 PRODUCTS in this game, one order per item never
    reaches the default of 10 on its own).

    Premium goods (PREMIUM_GOODS) are drip-sold: capped at
    `drip_sell_max_per_turn` units per turn even if more are sitting in
    the shed, rather than dumped in one order (README.md "Selling
    inventory to the market": a single large SELL order walks the price
    down unit-by-unit within that same turn).

    `wheat_reserve` keeps that many WHEAT units off the sell list
    regardless of price. Real bug found while implementing T6.4: the
    wheat buy/sell arbitrage (a real, deliberate small income source -
    T3.6) sold 100% of shed WHEAT every turn it was profitable, which
    raced against any attempt to PICKUP wheat for feeding a placed
    animal - a direct episode trace showed the shed's WHEAT flickering
    0/10 every single turn, so the farmer could never complete a PICKUP
    before the arbitrage's own SELL order emptied the shed again, and a
    placed COW starved and escaped. `decide()` sets this to a positive
    reserve once any animal exists on the farm - the arbitrage still
    runs on whatever's left above the reserve.

    `liquidate` (T8.3d, the user's own observed defect): both the margin
    check and the premium-goods drip cap exist to protect *future*
    turns - refusing a below-cost sale in case the price recovers later,
    or spreading a big sale out so it doesn't crater tomorrow's price.
    Neither protection makes sense once there is no future turn left to
    sell into: confirmed directly in the real kaggriculture.py engine
    that the episode's reward is final money only, with no
    auto-liquidation of leftover shed stock - anything still unsold at
    the last step scores exactly zero, which is strictly worse than
    selling it at any positive price (PRICE_FLOOR guarantees > 0).
    `decide()` sets this once the season is within its configured
    liquidation window of ending. Also overrides `_NEVER_ROUTINELY_SOLD`
    (T8.3e) - see this module's own docstring for why FERTILIZER is
    normally excluded here at all.

    `use_fertilizer` (T8.3e) mirrors kagg.policy.tasks's own param of the
    same name: when the FERTILIZE task is disabled there, excluding
    FERTILIZER from routine selling here would just strand it as dead
    weight until `liquidate` finally sells it - so this same flag also
    controls the `_NEVER_ROUTINELY_SOLD` exclusion, keeping the two
    modules' behavior consistent for a clean on/off self-play comparison.
    """
    params = params or {}
    margin = params.get("sell_margin", _DEFAULT_SELL_MARGIN)
    drip_cap = params.get("drip_sell_max_per_turn", _DEFAULT_DRIP_SELL_MAX_PER_TURN)

    orders = []
    for item in PRODUCTS:
        if len(orders) >= max_orders:
            break
        if item in _NEVER_ROUTINELY_SOLD and use_fertilizer and not liquidate:
            continue
        count = shed.get(item, 0)
        if item == "WHEAT":
            count = max(0, count - wheat_reserve)
        if count <= 0:
            continue
        if not liquidate:
            current_price = price(item, market_inventory.get(item, MARKET_I0))
            if current_price <= _cost_basis(item) + margin:
                continue
        qty = count if liquidate or item not in PREMIUM_GOODS else min(count, drip_cap)
        if qty > 0:
            orders.append(["SELL", item, qty])
    return orders[:max_orders]


_DEFAULT_WHEAT_RESTOCK_THRESHOLD = 5
_DEFAULT_WHEAT_RESTOCK_QTY = 10
_DEFAULT_WHEAT_MAX_BUY_PRICE = 40


def buy_wheat_order(wheat_on_hand: int, wheat_price: int, params: dict | None = None) -> list | None:
    """A `["BUY_PRODUCT", "WHEAT", n]` order if on-hand wheat is running
    low and the price isn't too expensive to restock at, else `None`.

    Only ever names WHEAT, by construction - there's no branch here that
    could emit any other item (SPEC-policy.md: feed-stock buying is
    specifically about keeping animal feeding from lapsing into the
    two-consecutive-missed-days escape condition, which needs WHEAT).
    """
    params = params or {}
    threshold = params.get("wheat_restock_threshold", _DEFAULT_WHEAT_RESTOCK_THRESHOLD)
    if wheat_on_hand >= threshold:
        return None
    max_price = params.get("wheat_max_buy_price", _DEFAULT_WHEAT_MAX_BUY_PRICE)
    if wheat_price > max_price:
        return None
    qty = params.get("wheat_restock_qty", _DEFAULT_WHEAT_RESTOCK_QTY)
    return ["BUY_PRODUCT", "WHEAT", qty]


def market_orders(
    shed: dict,
    market_inventory: dict,
    market_prices: dict,
    wheat_on_hand: int,
    params: dict | None = None,
    max_orders: int = 10,
    wheat_reserve: int = 0,
    liquidate: bool = False,
    use_fertilizer: bool = True,
) -> list[list]:
    """This turn's full market-layer order list: sells first, then a
    wheat restock if there's still room under `max_orders` - never more
    than `max_orders` total, matching `maxMarketOrdersPerTurn`.

    `wheat_reserve`, `liquidate`, and `use_fertilizer` are passed straight
    through to `sell_orders` - see its own docstring for why they exist.
    """
    orders = sell_orders(
        shed,
        market_inventory,
        params,
        max_orders=max_orders,
        wheat_reserve=wheat_reserve,
        liquidate=liquidate,
        use_fertilizer=use_fertilizer,
    )
    if len(orders) < max_orders:
        wheat_order = buy_wheat_order(wheat_on_hand, market_prices.get("WHEAT", 0), params)
        if wheat_order is not None:
            orders.append(wheat_order)
    return orders
