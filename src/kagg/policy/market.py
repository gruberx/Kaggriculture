"""Market layer: sell/buy decisions for the shed's contents and wheat
feed-stock - see SPEC-policy.md "3. Market layer" (every turn, capped at
`maxMarketOrdersPerTurn`, default 10).

Only PRODUCTS are sellable (README.md: "every product can be sold via
SELL") - the shed can also hold live animals waiting to be PLACEd on a
structure, but those are never a SELL candidate here. Only WHEAT (and
FERTILIZER, not implemented in this module) can be bought back from the
market at all.

T8.3l correction: an earlier version of this docstring (and
`sell_orders`'s own, below) called the wheat buy/sell round-trip "a real,
deliberate small income source (T3.6)". That was wrong, and the wrongness
had a real, decisive symptom - the user's own observation of the agent
"constantly buying and selling 10 WHEAT". Traced directly in the real
engine (`kaggriculture.py`'s `_process_market`): `BUY_PRODUCT` is quoted
at the *post-buy* inventory specifically "so a buy/sell round-trip
against an unchanged market nets zero" - verified numerically, a solo
10-unit round trip nets exactly $0. There never was an arbitrage to
exploit; `buy_wheat_order` firing with no animal to feed at all was just
churn with no purpose, made *worse* by racing against `sell_orders`'
"sell everything above the reserve" rule (reserve is 0 until an animal is
placed) - 147 buy/sell pairs in one traced episode (seed 100), every
single turn from step 1 to 387. See `wheat_buy_only_when_feed_needed`
below for the fix and its measured (near-zero, honestly reported) real-
game impact.

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

import math

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
_DEFAULT_DRIP_SELL_MAX_PER_TURN = 1000


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
    liquidate_wheat_reserve: bool = True,
    force_sell: dict | None = None,
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
    regardless of price. Real bug found while implementing T6.4: selling
    100% of shed WHEAT every turn the price cleared its margin raced
    against any attempt to PICKUP wheat for feeding a placed animal - a
    direct episode trace showed the shed's WHEAT flickering 0/10 every
    single turn, so the farmer could never complete a PICKUP before the
    routine sell order emptied the shed again, and a placed COW starved
    and escaped. `decide()` sets this to a positive reserve once any
    animal exists on the farm.

    `liquidate_wheat_reserve` (T8.3l): once `liquidate` is set (T8.3d -
    no time left for the reserve to ever be fed with), holding back
    `wheat_reserve` units makes no sense - they'd strand unsold at
    episode end just like any other stock T8.3d already fixed for.
    Defaults to True (ignore the reserve during liquidation); kept
    overridable to isolate it in self-play.

    `force_sell` (T8.51): {item: units} that must go out this turn even
    when the price does not clear the item's margin - the capacity-aware
    override for stock the margin rule would otherwise hold in a shed that
    is about to overflow (see `kagg.policy.decide`). For an item whose price
    clears the margin this changes nothing.

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
        if item == "WHEAT" and not (liquidate and liquidate_wheat_reserve):
            count = max(0, count - wheat_reserve)
        if count <= 0:
            continue
        if not liquidate:
            current_price = price(item, market_inventory.get(item, MARKET_I0))
            if current_price <= _cost_basis(item) + margin:
                forced = min(count, (force_sell or {}).get(item, 0))
                if forced > 0:
                    orders.append(["SELL", item, forced])
                continue
        qty = count if liquidate or item not in PREMIUM_GOODS else min(count, drip_cap)
        if qty > 0:
            orders.append(["SELL", item, qty])
    return orders[:max_orders]


def sale_revenue(orders: list[list], market_inventory: dict) -> int:
    """Money the SELL orders bring in, walking each item's price down one
    unit at a time exactly like the engine's per-unit settlement (a sale at
    price > 1 also raises the market stock by one)."""
    total = 0
    for order in orders:
        if order[0] != "SELL":
            continue
        item, qty = order[1], order[2]
        stock = market_inventory.get(item, MARKET_I0)
        for _ in range(qty):
            p = price(item, stock)
            total += p
            if p > 1:
                stock += 1
    return total


_DEFAULT_WHEAT_RESTOCK_THRESHOLD = 5
_DEFAULT_WHEAT_RESTOCK_QTY = 10
_DEFAULT_WHEAT_MAX_BUY_PRICE = 40
# T8.25 Part 2, off by default (0 - see the "> 0" gate below) until
# measured: 0 means no urgency buffer is configured, i.e. the override
# below never fires and every existing caller keeps the plain price-cap
# behavior it had before this param existed.
_DEFAULT_WHEAT_URGENCY_RESERVE = 3


def buy_wheat_order(
    wheat_on_hand: int, wheat_price: int, params: dict | None = None, feed_needed: bool = True
) -> list | None:
    """A `["BUY_PRODUCT", "WHEAT", n]` order if on-hand wheat is running
    low and the price isn't too expensive to restock at, else `None`.

    Only ever names WHEAT, by construction - there's no branch here that
    could emit any other item (SPEC-policy.md: feed-stock buying is
    specifically about keeping animal feeding from lapsing into the
    two-consecutive-missed-days escape condition, which needs WHEAT).

    `feed_needed` (T8.3l, the user's own observed defect): restocking has
    no purpose at all when there is no animal placed and none being
    pursued - yet this fired unconditionally on shed WHEAT alone, which
    combined with `sell_orders` selling everything above a reserve of 0
    (no animal yet) produced a real, decisive ping-pong: buy 10, sell 10,
    every single turn (147 pairs in one traced episode, seed 100) until
    the price climbed past `wheat_max_buy_price`. `decide()` sets this to
    False whenever no animal is placed and none is the current investment
    choice. Defaults to True so every existing caller keeps restocking
    unconditionally, matching pre-T8.3l behavior.

    T8.25: `wheat_max_buy_price` (below) was found to be a real, previously
    undiscovered bug, not a deliberately-tuned ceiling - a static, never-
    swept $40 cap (no measured-history comment, unlike nearly every other
    tunable in this module) that silently blocks *all* restocking for the
    rest of the episode once WHEAT's market price drifts past it, which it
    structurally does every sufficiently long game (nobody grows WHEAT at
    scale - crop_revenue_per_tile_day never favors it - so there is no
    supply-side counterweight to steady town/shop consumption). Traced
    directly (seed 900): a 4-5 animal farm's shed buffer drains to zero by
    day 20 once price crosses $40 around day 17 - a 10-day feed drought
    matching real escape events exactly. See params.py's own
    wheat_max_buy_price comment for the resweep's measured story.

    `wheat_urgency_reserve` (T8.25 Part 2): when `wheat_on_hand` is at or
    below this reserve (and > 0, i.e. explicitly configured) and
    `feed_needed`, the price cap is ignored entirely for this turn's
    restock - an escaped animal (sunk purchase price + all its future
    revenue) is worth paying above the normal ceiling to avoid, bounded
    only by money itself (the real engine's own BUY_PRODUCT handler
    already rejects an order the farm can't afford - nothing here needs to
    duplicate that check). Defaults to 0 (disabled): every existing caller
    that doesn't pass it keeps the plain price-cap behavior unchanged.
    """
    if not feed_needed:
        return None
    params = params or {}
    threshold = params.get("wheat_restock_threshold", _DEFAULT_WHEAT_RESTOCK_THRESHOLD)
    if wheat_on_hand >= threshold:
        return None
    qty = params.get("wheat_restock_qty", _DEFAULT_WHEAT_RESTOCK_QTY)
    urgency_reserve = params.get("wheat_urgency_reserve", _DEFAULT_WHEAT_URGENCY_RESERVE)
    if urgency_reserve > 0 and wheat_on_hand <= urgency_reserve:
        return ["BUY_PRODUCT", "WHEAT", qty]
    max_price = params.get("wheat_max_buy_price", _DEFAULT_WHEAT_MAX_BUY_PRICE)
    if wheat_price > max_price:
        return None
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
    liquidate_wheat_reserve: bool = True,
    feed_needed: bool = True,
) -> list[list]:
    """This turn's full market-layer order list: sells first, then a
    wheat restock if there's still room under `max_orders` - never more
    than `max_orders` total, matching `maxMarketOrdersPerTurn`.

    `wheat_reserve`, `liquidate`, `use_fertilizer`, and
    `liquidate_wheat_reserve` are passed straight through to
    `sell_orders` - see its own docstring for why they exist.

    `feed_needed` (T8.3l) is passed straight through to `buy_wheat_order`
    - see its own docstring. It also raises the *effective* reserve
    passed to `sell_orders` up to at least `wheat_restock_threshold`
    whenever feed is needed and this isn't a liquidation turn: a
    belt-and-braces invariant, not just a gate on the buy side, so
    `sell_orders` can never again sell WHEAT down to a level that
    `buy_wheat_order` immediately restocks the next turn - the exact
    ping-pong this was built to fix (see this module's own docstring).
    """
    effective_wheat_reserve = wheat_reserve
    if feed_needed and not liquidate:
        threshold = (params or {}).get("wheat_restock_threshold", _DEFAULT_WHEAT_RESTOCK_THRESHOLD)
        effective_wheat_reserve = max(wheat_reserve, threshold)
    orders = sell_orders(
        shed,
        market_inventory,
        params,
        max_orders=max_orders,
        wheat_reserve=effective_wheat_reserve,
        liquidate=liquidate,
        use_fertilizer=use_fertilizer,
        liquidate_wheat_reserve=liquidate_wheat_reserve,
    )
    if len(orders) < max_orders:
        wheat_order = buy_wheat_order(wheat_on_hand, market_prices.get("WHEAT", 0), params, feed_needed=feed_needed)
        if wheat_order is not None:
            orders.append(wheat_order)
    return orders


def bulk_purchase_plan(
    types: list[str],
    held: dict[str, int],
    unit_costs: dict[str, int],
    target_total: int,
    budget: float,
    buffer_fraction: float = 0.0,
    round_up: bool = True,
) -> dict[str, int]:
    """T8.45 (the user's own request): how many units of each of `types`
    to buy *this turn* so that the farm ends up holding enough of them, in
    total, to cover `target_total` planned units (tiles to plant, animals
    to place) plus an optional safety buffer - one shared rule for seeds
    and animals instead of two separate hand-tuned formulas.

    `target_units = target_total * (1 + buffer_fraction)`, rounded up when
    `round_up` (seeds - a 10% margin on 24 tiles must give 27, not 26) or
    down otherwise (animals - a buffer that can't fill a whole unit buys
    nothing extra). What is already on hand (`held`, summed over only the
    given `types` - a seed or animal of some *other* type can't fill this
    plan's need) is subtracted, so a turn that already holds enough buys
    nothing and nothing is ever double-bought across turns.

    The remaining need is spread over `types` by "water-filling": each
    unit goes to the type currently holding the fewest (ties broken by
    `types` order, i.e. rank order for a crop basket), so several crop
    types together add up to the one total instead of each being topped
    up to the full target on its own. `budget` is the money available;
    a type whose unit cost exceeds what's left is skipped and the unit
    goes to the next-lowest affordable type, stopping only when nothing
    is affordable. Returns `{type: qty}` for types with `qty > 0` only,
    in `types` order - one market order per entry, so the T8.5 slot
    arithmetic is unchanged by quantity.
    """
    if not types or target_total <= 0:
        return {}
    raw = target_total * (1 + buffer_fraction)
    target_units = math.ceil(raw - 1e-9) if round_up else math.floor(raw + 1e-9)
    level = {t: held.get(t, 0) for t in types}
    need = max(0, target_units - sum(level.values()))
    plan: dict[str, int] = {}
    remaining_budget = budget
    order = {t: i for i, t in enumerate(types)}
    for _ in range(need):
        affordable = [t for t in types if unit_costs[t] <= remaining_budget]
        if not affordable:
            break
        t = min(affordable, key=lambda x: (level[x], order[x]))
        plan[t] = plan.get(t, 0) + 1
        level[t] += 1
        remaining_budget -= unit_costs[t]
    return {t: plan[t] for t in types if t in plan}
