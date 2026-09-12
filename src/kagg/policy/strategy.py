"""Strategic-layer scoring: which crops/animals are worth planting right
now, and the land/hiring decisions that go with them - see SPEC-policy.md
"1. Strategic layer" (runs once per day, obs["hour"] == 0).

All numeric decisions are driven by named parameters (a `params: dict`
argument with documented keys and defaults), never a hardcoded constant -
the single most important rule in SPEC-policy.md, since several of these
numbers (hires_per_day in particular) are open, forum-contradicted
questions that only the arena (`tuning`) can settle, not something to
decide here by intuition (see SPEC.md's economic analysis).

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0
from kagg.gamelib.farm import land_price
from kagg.gamelib.growth import (
    forecast_ongoing_schedule,
    forecast_one_time_yield,
    watering_bonus_window,
)
from kagg.gamelib.market import price


def crop_revenue_per_tile_day(crop: str, sell_at_inventory: int) -> float:
    """Expected revenue per tile-day for a crop watered on every day its
    bonus window allows (no fertilizer), evaluated at `sell_at_inventory`
    - the market inventory level its product would actually sell at, not
    base price (SPEC-policy.md: "given current market depth, not by base
    price").

    One-time crops: total yield from watering the entire bonus window,
    divided by the tile-days occupied from planting through harvest
    (`max_yield_day + 1`). Ongoing crops: total yield across the capped
    schedule (SPEC-gamelib.md: finite, capped at `max_yield` scheduled
    productions), divided by the tile-days occupied through the last
    scheduled production.
    """
    cd = CROPS[crop]
    product_price = price(crop, sell_at_inventory)
    if cd["ongoing"]:
        schedule = forecast_ongoing_schedule(crop, planted_day=0)
        total_yield = min(cd["max_yield"], len(schedule))  # 1 unit/tick, capped
        tile_days = schedule[-1] + 1
    else:
        watered_days = set(watering_bonus_window(crop))
        total_yield = forecast_one_time_yield(crop, watered_days)
        tile_days = cd["max_yield_day"] + 1
    return (total_yield * product_price) / tile_days


def animal_revenue_per_tile_day(animal: str, sell_at_inventory: int) -> float:
    """Steady-state revenue per tile-day for a continuously fed animal.

    No tile-days denominator the way crops have one: animals produce
    indefinitely once placed (SPEC.md's economic analysis: "no fixed
    occupancy to divide by") - this is just the per-tick rate
    (1 / interval) at the given product price.
    """
    a = ANIMALS[animal]
    product_price = price(a["product"], sell_at_inventory)
    return product_price / a["interval"]


def rank_portfolio(market_inventory: dict) -> list[str]:
    """All crop and animal names, ranked descending by revenue per
    tile-day at `market_inventory`'s *current* level for each one's own
    product (missing entries fall back to MARKET_I0, i.e. base price).

    This is a first-pass ranking at today's prices - it does not yet
    account for how planting many tiles of the same thing would move the
    price down as your own production lands. That self-impact refinement
    is left to a later policy iteration / tuning experiment, not this
    ranking function - see SPEC.md's economic analysis for why premium
    goods (melon, wool, milk, strawberry) look deceptively good by this
    measure alone until market depth is actually checked.
    """
    scores = {}
    for crop in CROPS:
        inv = market_inventory.get(crop, MARKET_I0)
        scores[crop] = crop_revenue_per_tile_day(crop, inv)
    for animal, a in ANIMALS.items():
        inv = market_inventory.get(a["product"], MARKET_I0)
        scores[animal] = animal_revenue_per_tile_day(animal, inv)
    return sorted(scores, key=scores.__getitem__, reverse=True)


# Starting points for `tuning` to improve on, not values chosen by
# intuition (SPEC-policy.md's central rule) - never raised based on
# reasoning alone, only on a real, held-out-gated arena result.
#
# land_purchase_threshold_money was raised 5000 -> 10000 by T7.4's first
# real Stage 1 sweep (tasks/plan.md): a real, previously unnoticed
# methodological pitfall surfaced along the way - aggregating win rate
# across a panel where 2/3 of the opponents (starter/random) are already
# near a 100% win-rate ceiling dilutes the signal so heavily that a
# candidate which actually *loses* to the checked-in baseline in direct
# self-play (verified: 0.34 win rate head-to-head) can still look like
# an "improvement" on the diluted aggregate (0.78 vs 0.667). Direct
# self-play against the previous-best snapshot, not the blended panel
# score, is what actually found this real change: threshold=10000 beat
# the previous default 50/50 on both the working block and (separately)
# the held-out block, with a 95% Wilson interval of [0.929, 1.0] on
# each. Same sweep also directly confirmed the forum's own contradicted-
# intuition finding for hires_per_day (SPEC-policy.md's hiring note):
# every hires_per_day > 0 value tried lost consistently (0.03-0.17 win
# rate) to hires_per_day=0 in direct self-play, so it stays at 0.
_DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY = 10000
_DEFAULT_HIRES_PER_DAY = 0


def should_buy_land(money: float, n_unlocked_extra: int, params: dict | None = None) -> bool:
    """True if the farm should buy the next quadrant right now.

    `land_purchase_threshold_money` (a named parameter) is how much money
    must be left *after* the purchase - the farm needs
    `land_price(...) + threshold` on hand, not just the price itself, so a
    land purchase never strands the farm without operating cash. Returns
    False once all quadrants are already bought (land_price returns None)
    - there's nothing left to buy, not a threshold failure.
    """
    params = params or {}
    cost = land_price(n_unlocked_extra)
    if cost is None:
        return False
    threshold = params.get(
        "land_purchase_threshold_money", _DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY
    )
    return money >= cost + threshold


def hires_per_day(params: dict | None = None) -> int:
    """How many farm hands to hire at the start of each day.

    Explicitly a tunable parameter, not a fixed policy (SPEC-policy.md):
    the "labor is nearly free, hire many hands" intuition derived from
    `hire_cost`'s Fibonacci curve was directly contradicted by a forum
    measurement ("adding workers has zero marginal value" - SPEC.md's
    economic analysis). The default is deliberately 0 until the arena
    actually measures the real answer.
    """
    params = params or {}
    return params.get("hires_per_day", _DEFAULT_HIRES_PER_DAY)
