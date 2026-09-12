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

# T8.3 (tasks/plan.md): the user's own observed defect - a quadrant
# sometimes bought while plenty of free tiles remained, because the old
# should_buy_land looked at money alone. The fraction gate's mechanism
# shipped at 1.0 (a no-op, ungated) but was swept and accepted in the
# same task, not left unswept: every tested value (0.6, 0.4, 0.25, 0.1)
# beat the ungated default 50/50 in direct self-play on the working
# block, confirmed 50/50 again on the held-out block for 0.25 - traced
# directly, not just trusted: with the gate on, BUY_LAND stops firing
# almost entirely and final money rises ~34-35%, confirming a single
# farmer cannot productively work even one 25-tile quadrant, so land
# beyond it is currently pure waste. Explicitly provisional - fit to a
# 1-unit farm, must be re-swept once labor works (T8.8).
_DEFAULT_LAND_BUY_MAX_FREE_TILE_FRACTION = 0.25
# No evidence yet this second gate is needed once the fraction gate above
# already prevents nearly all land purchases - stays disabled (99 is
# unreachable on any real board).
_DEFAULT_LAND_BUY_MIN_FRONTIER_DISTANCE = 99


def should_buy_land(
    money: float,
    n_unlocked_extra: int,
    params: dict | None = None,
    free_tiles: int | None = None,
    unlocked_tiles: int | None = None,
    nearest_free_shed_distance: int | None = None,
) -> bool:
    """True if the farm should buy the next quadrant right now.

    `land_purchase_threshold_money` (a named parameter) is how much money
    must be left *after* the purchase - the farm needs
    `land_price(...) + threshold` on hand, not just the price itself, so a
    land purchase never strands the farm without operating cash. Returns
    False once all quadrants are already bought (land_price returns None)
    - there's nothing left to buy, not a threshold failure.

    `free_tiles`/`unlocked_tiles`/`nearest_free_shed_distance` (T8.3) gate
    the purchase on actual occupancy, not just cash - the direct fix for a
    real, user-observed defect (land bought while most of the farm was
    still empty). `None`/falsy `unlocked_tiles` (the caller has no
    occupancy info) skips both gates entirely, reproducing the pre-T8.3
    money-only behavior - decide() always supplies real occupancy in
    practice, so this is a graceful default, not the intended real-play
    path. Two independent, OR'd gates once occupancy is given:

    - `land_buy_max_free_tile_fraction`: buy once the free-tile fraction
      of what we already own drops to or below this - "we're running out
      of land."
    - `land_buy_min_frontier_distance`: buy anyway once our own nearest
      free tile is at least this far from the shed - "the land we'd get
      is closer than the land we have left." Matters because of T8.1's
      finding: a newly unlocked quadrant always contributes a tile at
      shed-distance 1 (one of its corners touches the shed), so a farm
      whose remaining free tiles are all farther out than that is
      genuinely better served by expanding than by using up the far
      corners of what it already has.

    `land_buy_min_frontier_distance` still defaults to a no-op (99 - see
    `_DEFAULT_LAND_BUY_MIN_FRONTIER_DISTANCE`), unswept so far.
    `land_buy_max_free_tile_fraction` defaults to 0.25, not the
    mechanism's original 1.0 no-op - see that constant's own comment for
    the real, decisive self-play result it was accepted on. Pass
    `land_buy_max_free_tile_fraction=1.0` explicitly to get the fully
    ungated, pre-T8.3 money-only decision back.
    """
    params = params or {}
    cost = land_price(n_unlocked_extra)
    if cost is None:
        return False
    threshold = params.get(
        "land_purchase_threshold_money", _DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY
    )
    if money < cost + threshold:
        return False
    if not unlocked_tiles:
        return True
    max_free_fraction = params.get(
        "land_buy_max_free_tile_fraction", _DEFAULT_LAND_BUY_MAX_FREE_TILE_FRACTION
    )
    if (free_tiles or 0) / unlocked_tiles <= max_free_fraction:
        return True
    min_frontier = params.get(
        "land_buy_min_frontier_distance", _DEFAULT_LAND_BUY_MIN_FRONTIER_DISTANCE
    )
    return nearest_free_shed_distance is not None and nearest_free_shed_distance >= min_frontier


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
