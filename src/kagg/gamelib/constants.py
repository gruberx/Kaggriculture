"""Game rule constants, copied verbatim from the real environment.

Mirrors kaggle_environments/envs/kaggriculture/kaggriculture.py. These are
game rules, not implementation details - the environment does not expose
them as an importable, dependency-free module we could rely on at
submission time, so gamelib owns its own copy (see SPEC-gamelib.md
"Scope"). Keep this file a byte-for-byte match of the source values; a
divergence here is a silent, hard-to-notice bug everywhere gamelib is used.
"""

CROPS = {
    "WHEAT": {"seed": 10, "first_yield_day": 2, "max_yield_day": 4, "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT": {"seed": 20, "first_yield_day": 2, "max_yield_day": 3, "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO": {"seed": 50, "first_yield_day": 8, "max_yield_day": 8, "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first_yield_day": 10, "max_yield_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON": {"seed": 80, "first_yield_day": 10, "max_yield_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}

ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP", "first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW": {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}

PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]

# Pricing model, see kagg.gamelib.market.price():
#     price(inv) = base + sign * amp * f(|inv - I0|)
#     sign = +1 below I0 (scarcity), -1 above I0 (glut)
#     amp  = target * base / f(T)
#     f    in {linear, sq, sqrt, log, log10, hinge}
# Floored at PRICE_FLOOR.
MARKET_I0 = 10000
PRICE_FLOOR = 1

MARKET_PARAMS = {
    "WHEAT": {"base": 25, "I0": MARKET_I0, "T": 400, "below_func": "sqrt", "below_target": 0.80, "above_func": "log", "above_target": 0.20},
    "CARROT": {"base": 35, "I0": MARKET_I0, "T": 450, "below_func": "hinge", "below_target": 1.00, "above_func": "sqrt", "above_target": 0.70},
    "TOMATO": {"base": 60, "I0": MARKET_I0, "T": 200, "below_func": "hinge", "below_target": 0.40, "above_func": "sqrt", "above_target": 0.60},
    "STRAWBERRY": {"base": 120, "I0": MARKET_I0, "T": 100, "below_func": "sqrt", "below_target": 0.70, "above_func": "linear", "above_target": 1.60},
    "MELON": {"base": 250, "I0": MARKET_I0, "T": 300, "below_func": "log", "below_target": 0.20, "above_func": "sq", "above_target": 3.60},
    "EGG": {"base": 50, "I0": MARKET_I0, "T": 332, "below_func": "hinge", "below_target": 0.40, "above_func": "log", "above_target": 0.20},
    "MILK": {"base": 160, "I0": MARKET_I0, "T": 122, "below_func": "sqrt", "below_target": 0.60, "above_func": "linear", "above_target": 1.60},
    "WOOL": {"base": 200, "I0": MARKET_I0, "T": 105, "below_func": "log", "below_target": 0.20, "above_func": "sq", "above_target": 3.20},
    "FERTILIZER": {"base": 100, "I0": MARKET_I0, "T": 200, "below_func": "linear", "below_target": 0.40, "above_func": "linear", "above_target": 0.40},
}

# "hinge" spikes once x passes T. Below the knee it is linear in x/T; above
# it a quadratic term takes over. f(T) == 1 by construction, which keeps
# `target` meaning the same thing it does for every other shape.
HINGE_GAIN = 8.0

# Town shops: each unlocked instance consumes specific products from the
# market over time (kaggriculture.py's _town_consume), raising their
# price - a real demand signal, distinct from PRODUCTS' base scarcity
# math. A shop with only one product (YARN_STORE, PET_CAFE) consumes it
# at double the per-instance rate of a multi-product shop - mirrors
# _town_consume's `multiplier = 2 if len(products) == 1 else 1`.
SHOPS = {
    "BAKERY": ["EGG", "WHEAT"],
    "PIZZA_SHOP": ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT": ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE": ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE": ["CARROT"],
    "SMOOTHIE_SHOP": ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}

# Every PRODUCT except FERTILIZER is drawn down by the town center itself,
# shops or not - mirrors kaggriculture.py's TOWN_CENTER_PRODUCTS.
TOWN_CENTER_PRODUCTS = [p for p in PRODUCTS if p != "FERTILIZER"]

# Shops are drawn with replacement (the same shop can unlock more than
# once, each instance consuming independently) - this caps total unlocked
# instance count, not variety.
MAX_SHOP_INSTANCES = 8

# n-th hire of the day -> cost = FARM_HAND_COST_MULT * fib(n), resetting
# each day. Configurable via episode configuration's `farmHandCostMult`,
# but this is the default multiplier.
FARM_HAND_COST_MULT = 1

# NW is always unlocked; players unlock the rest in this order.
LAND_ORDER = ["NE", "SW", "SE"]
LAND_PRICES = [1000, 2000, 4000]
