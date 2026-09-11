"""Market price curve - mirrors kaggriculture.py's _shape()/market_price().

Standard library only (see SPEC.md "Code style" / Official Rules SS2.11) -
this module ships inside the submission bundle.
"""

from __future__ import annotations

import math

from kagg.gamelib.constants import HINGE_GAIN, MARKET_PARAMS, PRICE_FLOOR


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
