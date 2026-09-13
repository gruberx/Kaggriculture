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
from kagg.gamelib.market import expected_daily_consumption, price


def _crop_yield_and_tile_days(crop: str) -> tuple[int, int]:
    """(total_yield, tile_days) for one tile of `crop` grown start to
    finish - the two quantities `crop_revenue_per_tile_day` and
    `rank_portfolio` (T8.3f) both need, factored out once so they can't
    drift apart from each other.

    One-time crops: total yield from watering the entire bonus window;
    tile-days occupied from planting through harvest (`max_yield_day +
    1`). Ongoing crops: total yield across the capped schedule (SPEC-
    gamelib.md: finite, capped at `max_yield` scheduled productions);
    tile-days occupied through the last scheduled production.
    """
    cd = CROPS[crop]
    if cd["ongoing"]:
        schedule = forecast_ongoing_schedule(crop, planted_day=0)
        total_yield = min(cd["max_yield"], len(schedule))  # 1 unit/tick, capped
        tile_days = schedule[-1] + 1
    else:
        watered_days = set(watering_bonus_window(crop))
        total_yield = forecast_one_time_yield(crop, watered_days)
        tile_days = cd["max_yield_day"] + 1
    return total_yield, tile_days


def crop_revenue_per_tile_day(
    crop: str,
    sell_at_inventory: int,
    already_committed_units: int = 0,
    expected_consumption: float = 0,
    net_of_seed_cost: bool = False,
) -> float:
    """Expected revenue per tile-day for a crop watered on every day its
    bonus window allows (no fertilizer), evaluated at `sell_at_inventory`
    - the market inventory level its product would actually sell at, not
    base price (SPEC-policy.md: "given current market depth, not by base
    price").

    T8.3f (the user's own observation, matching a real gap this module's
    own `rank_portfolio` docstring used to flag explicitly): self-impact
    aware, not priced at one flat snapshot. `gamelib.market.price` mirrors
    kaggriculture.py's own per-unit lockstep SELL quoting - each unit sold
    pushes market inventory up by exactly 1 before the next unit is
    quoted - so pricing an entire `total_yield`-unit run at the same
    starting snapshot overstates its value, more so for goods whose curve
    reacts steeply to a glut (SPEC.md's PREMIUM_GOODS: MELON/WOOL/MILK/
    STRAWBERRY). Walks `sell_at_inventory + already_committed_units + k`
    for k = 0, 1, ..., total_yield-1 instead of one flat price.

    `already_committed_units` (T8.3f) is `rank_portfolio`'s way of saying
    "this many units of `crop` are already in the pipeline from tiles
    already planted elsewhere on the farm" - **load-bearing**, not
    cosmetic: measured directly (gamelib.market.price at this crop's own
    T-scale) that a *single* tile's own yield barely moves its own price
    at all (e.g. one melon tile's 6-unit run: 250 -> 250, no change - the
    market's elasticity scale T is calibrated to a whole farm's output,
    not one tile's), so without this offset the self-impact walk above is
    a real but practically negligible correction. Committing to *many*
    tiles of the same crop is where the real crash shows up (measured:
    20 melon tiles = 120 units, 250 -> 108 by the last one) - exactly the
    "premium goods react sharper to overproduction" dynamic the user
    described, which only becomes visible at the farm's total footprint,
    not a single new tile's own contribution.

    `expected_consumption` (T8.3i, the user's own follow-up): town/shop
    consumption pulls the *opposite* direction from
    `already_committed_units` - it removes units instead of adding them,
    raising price instead of lowering it - so it's simply subtracted from
    the same starting point before the self-impact walk runs. Previously
    this function only ever *undervalued* a crop by ignoring consumption
    entirely (see the removed paragraph this replaces); this closes that
    gap when a caller supplies a real estimate (`rank_portfolio` computes
    it from `gamelib.market.expected_daily_consumption` and
    `obs["town"]["unlocked_shops"]`) instead of leaving it un-modeled.
    Defaults to 0 (no consumption information), which reproduces T8.3f's
    exact prior behavior for every caller that doesn't pass it.

    Scoped to crops only - `animal_revenue_per_tile_day` (below) is
    unchanged for `already_committed_units` (an animal's lifetime yield
    is intentionally unbounded - see that function's own docstring: "no
    fixed occupancy to divide by" - so there is no natural `total_yield`
    to walk across without picking an arbitrary horizon), but DOES get
    its own `expected_consumption` (T8.3i) since that doesn't need one -
    see its own docstring.

    `net_of_seed_cost` (T8.3k, the user's own observation): time itself
    is a scarce, hard-capped resource in this game (a fixed 30-day
    season), so profitability should be **net profit per day spent**, not
    gross revenue per day spent - before this, the seed's own purchase
    cost (`CROPS[crop]["seed"]`) was never subtracted anywhere in the
    ranking, only used separately as an affordability check
    (`decide()`'s `money >= seed_cost` gate) that has nothing to do with
    whether the purchase is *worth it* relative to another crop. Costs
    nothing to add: seed cost is a one-time, exactly-known charge against
    the same `total_yield`-unit run this function already prices, so it's
    simply subtracted once before dividing by `tile_days` - the same
    "per day of this scarce resource" denominator the user is pointing
    at, now applied to *net*, not gross, proceeds. Defaults to `False`
    (gross revenue, T8.3f/T8.3i's exact prior behavior) for every caller
    that doesn't pass it.
    """
    total_yield, tile_days = _crop_yield_and_tile_days(crop)
    start = sell_at_inventory + already_committed_units - expected_consumption
    total_revenue = sum(price(crop, start + k) for k in range(total_yield))
    if net_of_seed_cost:
        total_revenue -= CROPS[crop]["seed"]
    return total_revenue / tile_days


def animal_revenue_per_tile_day(animal: str, sell_at_inventory: int, expected_consumption: float = 0) -> float:
    """Steady-state revenue per tile-day for a continuously fed animal.

    No tile-days denominator the way crops have one: animals produce
    indefinitely once placed (SPEC.md's economic analysis: "no fixed
    occupancy to divide by") - this is just the per-tick rate
    (1 / interval) at the given product price.

    `expected_consumption` (T8.3i): unlike `crop_revenue_per_tile_day`'s
    `already_committed_units` (which needs a bounded lifetime total this
    function deliberately doesn't have), a consumption estimate over one
    production interval needs no such bound - it's simply subtracted from
    `sell_at_inventory` before pricing, raising the modeled price for a
    product a currently-unlocked shop is actively drawing down (e.g.
    YARN_STORE for WOOL). Defaults to 0, reproducing the exact prior
    behavior for every caller that doesn't pass it.

    No `net_of_seed_cost`-style parameter (T8.3k): unlike a crop's
    one-time seed cost against a bounded `total_yield` run, netting out
    an animal's purchase cost needs an amortization horizon this function
    doesn't have (the same unbounded-lifetime problem that already
    excludes animals from `already_committed_units`), and there's also a
    real *recurring* cost (WHEAT to feed it) this function doesn't model
    at all yet - left as an open, harder problem, not silently ignored;
    see `SPEC.md`'s "Economic analysis" section for the related
    WHEAT-for-feed lead already recorded.
    """
    a = ANIMALS[animal]
    product_price = price(a["product"], sell_at_inventory - expected_consumption)
    return product_price / a["interval"]


def rank_portfolio(
    market_inventory: dict,
    crop_tile_counts: dict | None = None,
    unlocked_shops: list | None = None,
    net_of_seed_cost: bool = False,
) -> list[str]:
    """All crop and animal names, ranked descending by revenue per
    tile-day at `market_inventory`'s *current* level for each one's own
    product (missing entries fall back to MARKET_I0, i.e. base price).

    `crop_tile_counts` (T8.3f, the user's own observation): how many
    tiles of each crop are already planted on the farm, so a *new* tile's
    marginal value is priced starting from where the farm's existing
    commitment to that crop would already have pushed the market, not
    from a pristine snapshot - see `crop_revenue_per_tile_day`'s own
    docstring for why this (not merely walking one tile's own future
    yield) is the part that actually matters: SPEC.md's economic analysis
    warning that premium goods (melon, wool, milk, strawberry) look
    deceptively good until market depth is checked is exactly about a
    farm's *total* footprint in one good, not a single tile's. `None`
    (the default) means "nothing planted yet" - every existing caller
    before T8.3f keeps its old, unadjusted behavior unchanged. Animals
    are unaffected - `crop_tile_counts` only ever names crops.

    `unlocked_shops` (T8.3i, the user's own follow-up question: "is
    elevated shop demand already accounted for, or only as a lagging
    reaction once the price has already moved?"): before this, purely
    the latter - `market_inventory` already reflects any consumption a
    shop has *already* caused (the same shared object `_town_consume`
    mutates), but nothing here looked ahead to what a *currently*
    unlocked shop will keep doing for the rest of the game. `None` (the
    default) means "no information," reproducing the exact prior
    behavior for every caller that doesn't pass it - matches
    `crop_tile_counts`'s own convention.

    `net_of_seed_cost` (T8.3k) is passed straight through to
    `crop_revenue_per_tile_day` - see its own docstring. Animals are
    unaffected (no analogous parameter exists yet on
    `animal_revenue_per_tile_day` - see its own docstring for why).
    """
    crop_tile_counts = crop_tile_counts or {}
    unlocked_shops = unlocked_shops or []
    scores = {}
    for crop in CROPS:
        inv = market_inventory.get(crop, MARKET_I0)
        total_yield, tile_days = _crop_yield_and_tile_days(crop)
        already_committed_units = crop_tile_counts.get(crop, 0) * total_yield
        expected_consumption = expected_daily_consumption(crop, unlocked_shops) * tile_days
        scores[crop] = crop_revenue_per_tile_day(
            crop, inv, already_committed_units, expected_consumption, net_of_seed_cost
        )
    for animal, a in ANIMALS.items():
        inv = market_inventory.get(a["product"], MARKET_I0)
        expected_consumption = expected_daily_consumption(a["product"], unlocked_shops) * a["interval"]
        scores[animal] = animal_revenue_per_tile_day(animal, inv, expected_consumption)
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
