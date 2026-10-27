"""Market price curve - mirrors kaggriculture.py's _shape()/market_price().

Standard library only (see SPEC.md "Code style" / Official Rules SS2.11) -
this module ships inside the submission bundle.
"""

from __future__ import annotations

import math

from kagg.gamelib.constants import (
    HINGE_GAIN,
    MARKET_PARAMS,
    MAX_SHOP_INSTANCES,
    PRICE_FLOOR,
    SHOPS,
    TOWN_CENTER_PRODUCTS,
)


def shape(func: str, x: float, T: float | None = None) -> float:
    """The `f` in price(inv) = base +/- amp * f(|inv - I0|).

    Mirrors kaggriculture.py's _shape(). `hinge` degenerates to linear if T
    is missing or non-positive (source comment: "Degenerates to linear if T
    is missing or non-positive").
    """
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "log10":
        return math.log10(1.0 + x)
    if func == "hinge":
        if not T or T <= 0:
            return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def price(item: str, inventory: int, params: dict | None = None) -> int:
    """Current per-unit market price for `item` at `inventory` units.

    Mirrors kaggriculture.py's market_price(). Rounds to the nearest int and
    floors at PRICE_FLOOR (SPEC-gamelib.md: a forecast that returns a float
    silently disagrees with the real market near the floor).

    `inventory` is an explicit argument rather than assumed - per README.md
    "Buying inventory from the market", the buy price is quoted at the
    post-buy inventory and the sell price at the pre-sell inventory, so a
    caller must pass the inventory for the side it actually means, not rely
    on this function guessing a direction.

    `params` overrides MARKET_PARAMS entirely when given (matches the real
    interpreter's `market_price(item, inventory, params=None)` signature,
    used when episode configuration supplies `marketParams` overrides) -
    it is not merged with the defaults here.
    """
    p = (params or MARKET_PARAMS)[item]
    base = p["base"]
    I0 = p["I0"]
    T = p["T"]
    if inventory < I0:
        f = p["below_func"]
        amp = p["below_target"] * base / shape(f, T, T)
        computed = base + amp * shape(f, I0 - inventory, T)
    else:
        f = p["above_func"]
        amp = p["above_target"] * base / shape(f, T, T)
        computed = base - amp * shape(f, inventory - I0, T)
    return max(PRICE_FLOOR, int(round(computed)))


def expected_daily_consumption(
    product: str,
    unlocked_shops,
    turns_per_day: int = 24,
    town_center_interval: int = 24,
    shop_interval: int = 4,
) -> float:
    """Units/day of `product` the town removes from the market - T8.3i,
    the user's own observation: this consumption is already reflected
    *reactively* in `price()` once it's happened (kaggriculture.py's
    `_town_consume` mutates the same shared `market["inventory"]` that
    `price()` reads), but nothing in this codebase used it
    *proactively* before this function existed.

    Mirrors kaggriculture.py's `_town_consume`: the town center draws 1
    unit of every product except FERTILIZER every `town_center_interval`
    steps (`turns_per_day / town_center_interval` times/day, so 1/day at
    the real defaults), and each currently unlocked shop that lists
    `product` draws `multiplier` units (2 if that shop has only one
    product - YARN_STORE/PET_CAFE - else 1) every `shop_interval` steps.

    `unlocked_shops` is `obs["town"]["unlocked_shops"]` verbatim - a list
    of shop names, duplicates allowed (shops are drawn with replacement
    and each instance consumes independently, matching the real engine -
    no need to deduplicate here).

    The three interval arguments carry real defaults (turnsPerDay=24,
    townCenterSellInterval=24, townShopSellInterval=4) rather than being
    read from anywhere - like `forecast_animal_schedule`'s own
    `horizon_days=30`, these are episode configuration values not
    exposed in the observation at all, so a real, named default is the
    correct shape here, not a value silently assumed by omission.
    """
    daily = 0.0
    if product in TOWN_CENTER_PRODUCTS:
        daily += turns_per_day / town_center_interval
    for shop in unlocked_shops:
        products = SHOPS.get(shop)
        if products and product in products:
            multiplier = 2 if len(products) == 1 else 1
            daily += multiplier * turns_per_day / shop_interval
    return daily


def expected_consumption_over_horizon(
    product: str,
    unlocked_shops,
    current_day: int,
    days_remaining: int,
    shop_unlock_interval: int = 3,
    max_shop_instances: int = MAX_SHOP_INSTANCES,
    turns_per_day: int = 24,
    town_center_interval: int = 24,
    shop_interval: int = 4,
) -> float:
    """Total expected units of `product` the town removes over the next
    `days_remaining` days - T8.70, the user's own follow-up to T8.69's
    known gap ("shop-driven demand varies by seed and isn't yet priced
    into this ranking at all"): unlike `expected_daily_consumption`
    above, which freezes the rate at *today's* `unlocked_shops` and
    multiplies it flat across the whole horizon, this also prices in
    shops that haven't unlocked yet but will, on the engine's own
    deterministic unlock schedule (kaggriculture.py's shop-unlock draw:
    a new shop every `shop_unlock_interval` days, up to `max_shop_
    instances` total - only the *type* drawn is random, uniformly over
    `SHOPS`, never the *timing*). A not-yet-unlocked shop's expected
    contribution to any one product is therefore its own per-unlock
    consumption weight (`2` if it's a single-product shop like
    YARN_STORE/PET_CAFE, else `1`, summed over every shop type listing
    `product` - the same `multiplier` rule `expected_daily_consumption`
    already uses per-instance) averaged uniformly over `len(SHOPS)`
    possible draws.

    `current_day`/`days_remaining` follow the same convention as every
    other horizon argument in this package (`animal_horizon_profit_
    per_day` etc.): real, current values, not the static `DAYS=30` the
    offline `tile_economics_30d.py` table was built from.
    """
    base_rate = expected_daily_consumption(
        product, unlocked_shops, turns_per_day, town_center_interval, shop_interval
    )
    n_already = len(unlocked_shops)
    weight = sum(
        (2 if len(products) == 1 else 1) for products in SHOPS.values() if product in products
    )
    per_shop_daily_rate = weight * turns_per_day / shop_interval / len(SHOPS)
    total = 0.0
    for offset in range(1, days_remaining + 1):
        day = current_day + offset
        n_unlocked_by_day = min(max_shop_instances, day // shop_unlock_interval)
        n_future = max(0, n_unlocked_by_day - n_already)
        total += base_rate + n_future * per_shop_daily_rate
    return total
