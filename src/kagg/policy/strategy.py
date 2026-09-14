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

import math

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0
from kagg.gamelib.farm import land_price
from kagg.gamelib.growth import (
    forecast_animal_schedule,
    forecast_ongoing_schedule,
    forecast_one_time_yield,
    watering_bonus_window,
)
from kagg.gamelib.market import expected_daily_consumption, price


def _crop_yield_and_tile_days(crop: str, days_remaining: int | None = None) -> tuple[int, int]:
    """(total_yield, tile_days) for one tile of `crop` grown start to
    finish - the two quantities `crop_revenue_per_tile_day` and
    `rank_portfolio` (T8.3f) both need, factored out once so they can't
    drift apart from each other.

    One-time crops: total yield from watering the entire bonus window;
    tile-days occupied from planting through harvest (`max_yield_day +
    1`). Ongoing crops: total yield across the capped schedule (SPEC-
    gamelib.md: finite, capped at `max_yield` scheduled productions);
    tile-days occupied through the last scheduled production.

    `days_remaining` (T8.3m, the user's own observation extended from
    T8.3k: time is scarce and hard-capped, and *this* was the piece T8.3k
    didn't reach - `rank_portfolio` had no notion of the current day or
    the remaining season at all, so an option was scored at its full,
    untruncated lifetime revenue right up to the season's last turn).
    `None` (the default) means "unknown/unbounded," reproducing the exact
    prior behavior for every caller that doesn't pass it.

    Deliberately an ongoing-crop correction, not a one-time-crop one:
    a one-time crop's `total_yield` already comes from a fixed watering
    window that either fits before the season ends or doesn't - the
    binary `_crop_has_time_to_mature` filter in `kagg.policy.decide`
    already excludes the ones that can't, so by the time a one-time crop
    reaches this function with a `days_remaining` it can't fit, nothing
    here needs to notice (the caller won't act on it regardless). An
    *ongoing* crop (TOMATO/STRAWBERRY) is different: `_crop_has_time_to_
    mature` only checks the *first* scheduled production, so a crop that
    technically "has time to mature" on day 24 of a 30-day season can
    still be scored at its full 4-production lifetime when only 1 of
    those 4 will actually happen - this truncates the schedule itself,
    not just the tile-days denominator.
    """
    cd = CROPS[crop]
    if cd["ongoing"]:
        schedule = forecast_ongoing_schedule(crop, planted_day=0)
        if days_remaining is not None:
            schedule = [day for day in schedule if day < days_remaining]
        total_yield = min(cd["max_yield"], len(schedule))  # 1 unit/tick, capped
        tile_days = schedule[-1] + 1 if schedule else 1
    else:
        watered_days = set(watering_bonus_window(crop))
        total_yield = forecast_one_time_yield(crop, watered_days)
        tile_days = cd["max_yield_day"] + 1
    if days_remaining is not None:
        # A tile is only ever *occupied* for the days that actually
        # exist - for a one-time crop that already passed the maturity
        # filter this is a no-op (tile_days already <= days_remaining by
        # construction of that filter), so this line only ever bites for
        # the ongoing-crop case above, or for a crop a caller ranks
        # without having applied the maturity filter first (harmless:
        # such a crop is skipped by the caller regardless of its score).
        tile_days = max(1, min(tile_days, days_remaining))
    return total_yield, tile_days


def crop_revenue_per_tile_day(
    crop: str,
    sell_at_inventory: int,
    already_committed_units: int = 0,
    expected_consumption: float = 0,
    net_of_seed_cost: bool = False,
    days_remaining: int | None = None,
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

    `days_remaining` (T8.3m) is passed straight through to
    `_crop_yield_and_tile_days` - see its own docstring. Defaults to
    `None` (no truncation, exact prior behavior for every caller that
    doesn't pass it).
    """
    total_yield, tile_days = _crop_yield_and_tile_days(crop, days_remaining)
    start = sell_at_inventory + already_committed_units - expected_consumption
    total_revenue = sum(price(crop, start + k) for k in range(total_yield))
    if net_of_seed_cost:
        total_revenue -= CROPS[crop]["seed"]
    return total_revenue / tile_days


def wheat_feed_credit_per_tile_day(
    sell_at_inventory: int,
    feed_units_needed: int,
    already_committed_units: int = 0,
    expected_consumption: float = 0,
    days_remaining: int | None = None,
) -> float:
    """T8.24, the user's own follow-up: the marginal value of growing
    WHEAT domestically instead of always buying it
    (`kagg.policy.market.buy_wheat_order`) when real animal-feed demand
    exists - a real, previously unpriced make-vs-buy asymmetry
    `crop_revenue_per_tile_day`'s plain sale-side walk can't see.
    `gamelib.market.price`'s own docstring: BUY is quoted at *post-buy*
    inventory (inventory falls as more is bought, pushing price UP,
    scarcity) while SELL is quoted at *pre-sell* inventory (inventory
    rises as more is sold, pushing price DOWN, glut) - the same market
    curve, walked in opposite directions from the same starting point. A
    WHEAT tile's yield diverted to feed avoids the (higher) buy-side price
    instead of earning the (lower) sell-side price.

    Splits one tile's `total_yield` (`_crop_yield_and_tile_days("WHEAT",
    ...)`) into `feed_units` (diverted to feed, capped at both the tile's
    own yield and `feed_units_needed` - one WHEAT unit covers exactly one
    FEED day, kaggriculture.py's own fixed rate) and the remainder
    `sale_units` (sold normally) - never both credited for the same
    physical unit. Returns the DELTA versus selling the whole yield
    (avoided-buy revenue on `feed_units` minus the sale revenue those
    same units would have earned) - a caller adds this ON TOP of
    `crop_revenue_per_tile_day`'s own WHEAT score (that function's own
    full-yield sale walk already covers `sale_units`' real contribution
    correctly; this only corrects the units that get diverted), never in
    place of it. `expected_consumption`/`already_committed_units` shift
    the sale-side walk's starting point the same way
    `crop_revenue_per_tile_day` already does, for the units that are
    still sold; the buy-avoidance walk always starts from the plain
    `sell_at_inventory` snapshot (today's real purchase price, not
    adjusted by our own crop-side market activity, which doesn't affect
    what a same-turn WHEAT purchase would cost).

    `feed_units_needed=0` (the default, e.g. no animal placed or
    pursued) makes `feed_units=0`, returning exactly `0.0` - a pure
    no-op for every caller that doesn't pass a real feed demand.
    """
    total_yield, tile_days = _crop_yield_and_tile_days("WHEAT", days_remaining)
    feed_units = max(0, min(total_yield, feed_units_needed))
    if feed_units == 0:
        return 0.0
    sale_start = sell_at_inventory + already_committed_units - expected_consumption
    diverted_sale_revenue = sum(price("WHEAT", sale_start + k) for k in range(feed_units))
    feed_avoided_revenue = sum(
        price("WHEAT", sell_at_inventory - k) for k in range(1, feed_units + 1)
    )
    return (feed_avoided_revenue - diverted_sale_revenue) / tile_days


def _animal_full_care_schedule(animal: str, days_remaining: int) -> list[tuple[int, int]]:
    """Exact day-by-day simulation of `CARE`'s `pending_care_bonus`
    mechanic under continuous feeding and care from day 0 through
    `days_remaining`, returning the per-production-day breakdown -
    `[(day, units), ...]`, one entry per day product is actually
    harvested, `day` an absolute day number - the same shape
    `forecast_animal_schedule` returns for the non-care path, except a
    single entry's `units` can be >1 (a banked day paying out in one
    burst) instead of always 1 (T8.21, extracted from the total-only
    `_animal_full_care_units` below so `animal_revenue_per_tile_day` can
    walk real per-unit production days for the `consumption_horizon_
    aware` combination that function's own docstring used to name as a
    deliberate, unclosed gap).

    Mirrors `kaggriculture.py`'s `_daily_refresh_animals` precisely
    (confirmed against the official "Animal Care" docs too): a day both
    fed and cared for banks +1 to `pending_care_bonus` - including
    *before* the animal's first scheduled production, since banking has
    no `first_yield_day` gate the way production does - and a scheduled
    production day (fed) pays out the *entire* bank on top of the base 1
    unit, then resets it to 0, whether or not that day's production was
    the one the bank was originally accrued for. This is genuinely
    path-dependent (SHEEP's `first_yield_day=6` banks 5 days before its
    very first tick, hitting `max_held` in one shot - a real, legal
    mechanic, not a bug), so a day-by-day simulation is used instead of a
    closed-form multiplier that risks getting cases like that silently
    wrong. Assumes harvesting promptly enough that `max_held` is never
    actually binding (a labor-unconstrained ceiling, matching this
    function's own `net_of_cost` framing throughout - see
    `kagg.policy.decide._DEFAULT_ANIMAL_CARE_AWARE` for the measured,
    labor-realistic result).
    """
    a = ANIMALS[animal]
    yield_units = 0
    pending_care_bonus = 0
    schedule: list[tuple[int, int]] = []
    for day in range(days_remaining):
        next_day = day + 1
        days_since_first = next_day - a["first_yield_day"]
        if days_since_first >= 0 and days_since_first % a["interval"] == 0:
            yield_units = min(a["max_held"], yield_units + 1 + pending_care_bonus)
            pending_care_bonus = 0
        pending_care_bonus += 1  # fed and cared every day in this ceiling scenario
        if yield_units > 0:
            schedule.append((next_day, yield_units))
            yield_units = 0
    return schedule


def _animal_full_care_units(animal: str, days_remaining: int) -> int:
    """Total product units produced under continuous care - see
    `_animal_full_care_schedule` (above) for the mechanic itself. Pure
    refactor (T8.21): bit-identical to the prior direct simulation, now
    just the sum of that function's own per-day breakdown.
    """
    return sum(units for _, units in _animal_full_care_schedule(animal, days_remaining))


def animal_revenue_per_tile_day(
    animal: str,
    sell_at_inventory: int,
    expected_consumption: float = 0,
    days_remaining: int | None = None,
    net_of_cost: bool = False,
    feed_price: float = 0,
    fertilizer_income_aware: bool = False,
    fertilizer_sell_at_inventory: int = MARKET_I0,
    care_aware: bool = False,
    consumption_horizon_aware: bool = False,
    consumption_rate: float = 0,
) -> float:
    """Steady-state revenue per tile-day for a continuously fed animal -
    or, when `net_of_cost` is set with a real `days_remaining`, net
    profit per day over the *bounded* remaining season instead (T8.3m).

    No tile-days denominator the way crops have one in the steady-state
    branch: animals produce indefinitely once placed (SPEC.md's economic
    analysis: "no fixed occupancy to divide by") - this is just the
    per-tick rate (1 / interval) at the given product price.

    `expected_consumption` (T8.3i): unlike `crop_revenue_per_tile_day`'s
    `already_committed_units` (which needs a bounded lifetime total this
    function deliberately doesn't have), a consumption estimate over one
    production interval needs no such bound - it's simply subtracted from
    `sell_at_inventory` before pricing, raising the modeled price for a
    product a currently-unlocked shop is actively drawing down (e.g.
    YARN_STORE for WOOL). Defaults to 0, reproducing the exact prior
    behavior for every caller that doesn't pass it.

    `days_remaining`/`net_of_cost`/`feed_price` (T8.3m, the user's own
    observation, previously recorded as an open gap in tasks/todo.md
    under both T8.3k - "animal purchase + recurring feed cost, net of
    season-remaining days" - and T8.3i's animal-product self-impact
    question): `ANIMALS[animal]["cost"]` was never subtracted anywhere in
    the *ranking* before this (only used as a `money >= cost`
    affordability check in `decide()`, unrelated to whether the purchase
    is worth it relative to another option), and the recurring WHEAT feed
    cost wasn't modeled at all. Both need a horizon to net against - the
    same "unbounded lifetime, no natural total to walk" problem that also
    excluded animals from `crop_revenue_per_tile_day`'s
    `already_committed_units` self-impact walk. The remaining season is
    exactly that horizon, and **using it incidentally closes the self-
    impact gap too**: `forecast_animal_schedule(animal, placed_day=0,
    horizon_days=days_remaining)` (the same call
    `kagg.policy.decide._animal_has_time_to_mature` already makes, just
    anchored at day 0 instead of `current_day` - mathematically
    equivalent for counting *how many* productions fit, which is all this
    needs) gives a real, bounded production count to walk the same
    per-unit lockstep pricing `crop_revenue_per_tile_day` already does,
    instead of pricing every future unit at one flat snapshot.
    `feed_price` is charged at 1 WHEAT/day for every day of the horizon
    (FEED consumes exactly 1 WHEAT/day regardless of whether a production
    happens that day) - a real cost, not previously deducted anywhere.
    Both default to off/0 (`net_of_cost=False`, `days_remaining=None`),
    reproducing the exact prior steady-state behavior for every caller
    that doesn't pass them; `net_of_cost=True` with no `days_remaining`
    given also falls back to the steady-state branch (no horizon to net
    against), a graceful default rather than an error.

    `fertilizer_income_aware`/`fertilizer_sell_at_inventory` (T8.3q, the
    user's own observation, confirmed directly in `kaggriculture.py`'s
    `_daily_refresh_animals`): every animal that hasn't escaped sets
    `fertilizer_available = True` at the end of *every single day* it
    survives, **regardless of whether it was fed or cared for that day** -
    a real, always-on revenue stream this function never modeled before
    T8.3q. One FERTILIZER unit per day of `days_remaining` (the same
    horizon the cost/feed terms already use - the animal is assumed
    placed today and alive through season end, same as the rest of this
    function's net-of-cost branch), walked the same per-unit lockstep way
    `crop_revenue_per_tile_day` already does, added to `total_revenue`
    before the cost subtraction. Only applies inside the `net_of_cost`
    branch (an unbounded steady-state rate has no horizon to bound the
    fertilizer walk either) - gated independently of `net_of_cost` itself
    so the two mechanisms can be measured in isolation (T8.3b's own
    lesson): `fertilizer_income_aware=True` with `net_of_cost=False` or
    `days_remaining=None` is a no-op, falling through to the unbounded
    steady-state branch exactly as before. Defaults to `False`
    (`fertilizer_sell_at_inventory` unused when off), reproducing T8.3m's
    exact prior behavior for every caller that doesn't pass it.

    `care_aware` (T8.3q) swaps the plain `forecast_animal_schedule` count
    for `_animal_full_care_units`'s exact day-by-day simulation of
    continuous `CARE`+feeding - see its own docstring for the mechanism
    and the path-dependence that rules out a closed-form shortcut.
    Defaults to `False`, reproducing the exact prior schedule-only count.

    `consumption_horizon_aware`/`consumption_rate` (T8.10, the user's own
    observation): before this, the animal side of `rank_portfolio` only
    ever estimated town/shop consumption over *one production interval*
    (`expected_consumption = rate * a["interval"]`, 1-3 days) - a real,
    asymmetric gap against `crop_revenue_per_tile_day`'s own
    `already_committed_units`/`expected_consumption` handling, which
    already spans the crop's *full* tile-occupancy horizon (T8.3f/T8.3i).
    An animal sells into a shared market the town drains every single day,
    all season - by the time a *later* scheduled unit sells, a real,
    sustained draw has pushed the price up far more than a flat "one
    interval" offset credits. When set (and a real `schedule` is
    available, i.e. `care_aware` is off - see below), each unit is priced
    at its own production day's drained level instead of one shared
    offset: `price(product, sell_at_inventory - consumption_rate * day +
    k)` for the k-th unit produced on absolute day `day`, walking
    `forecast_animal_schedule`'s own list directly rather than just its
    length. `consumption_rate` is a plain units/day rate (unlike
    `expected_consumption`, which callers pre-multiply by whatever horizon
    fits their own model) - `rank_portfolio` computes it once via
    `gamelib.market.expected_daily_consumption` and reuses it here without
    re-deriving a horizon.

    When combined with `care_aware=True` (T8.21; previously a documented
    no-op falling back to the flat `expected_consumption` path, since the
    old total-only `_animal_full_care_units` had no per-unit production
    day to walk consumption against): walks `_animal_full_care_schedule`'s
    real `[(day, units), ...]` breakdown instead - a single day's burst
    (banked units paying out together) is expanded into that many
    consecutive lockstep units, each still priced at its *own* production
    day's consumption-drained level (`sell_at_inventory - consumption_rate
    * day + k`, k the running unit index across the whole horizon, day the
    burst's own day), not a flat one-interval offset. Same real growing
    per-day shop draw the non-`care_aware` branch above already models,
    now also available for the care-aware schedule instead of guessing one
    from the other (T8.3q's own isolation discipline). Defaults to `False`
    (`consumption_rate` unused when off), reproducing the exact prior
    behavior for every caller that doesn't pass it.
    """
    a = ANIMALS[animal]
    if net_of_cost and days_remaining is not None:
        schedule = None
        care_schedule = None
        if care_aware:
            care_schedule = _animal_full_care_schedule(animal, days_remaining)
            units = sum(u for _, u in care_schedule)
        else:
            schedule = forecast_animal_schedule(animal, placed_day=0, horizon_days=days_remaining)
            units = len(schedule)
        if consumption_horizon_aware and care_schedule is not None:
            total_revenue = 0.0
            k = 0
            for day, day_units in care_schedule:
                for _ in range(day_units):
                    total_revenue += price(a["product"], sell_at_inventory - consumption_rate * day + k)
                    k += 1
        elif consumption_horizon_aware and schedule is not None:
            total_revenue = sum(
                price(a["product"], sell_at_inventory - consumption_rate * day + k)
                for k, day in enumerate(schedule)
            )
        else:
            start = sell_at_inventory - expected_consumption
            total_revenue = sum(price(a["product"], start + k) for k in range(units))
        if fertilizer_income_aware:
            total_revenue += sum(
                price("FERTILIZER", fertilizer_sell_at_inventory + k) for k in range(days_remaining)
            )
        total_revenue -= a["cost"]
        total_revenue -= feed_price * days_remaining
        return total_revenue / max(1, days_remaining)
    product_price = price(a["product"], sell_at_inventory - expected_consumption)
    return product_price / a["interval"]


def score_portfolio(
    market_inventory: dict,
    crop_tile_counts: dict | None = None,
    unlocked_shops: list | None = None,
    net_of_seed_cost: bool = False,
    days_remaining: int | None = None,
    rank_season_aware: bool = False,
    animal_net_of_cost: bool = False,
    animal_fertilizer_income_aware: bool = False,
    animal_care_aware: bool = False,
    animal_consumption_horizon_aware: bool = False,
    wheat_self_sufficiency_aware: bool = False,
    wheat_feed_units_needed: int = 0,
) -> dict[str, float]:
    """Every crop and animal name mapped to its own revenue per tile-day
    at `market_inventory`'s *current* level for its own product (missing
    entries fall back to MARKET_I0, i.e. base price) - `rank_portfolio`
    (below) is a thin wrapper sorting this same dict descending; this
    function exists separately (T8.14) so a caller that needs the raw
    scores themselves, not just their rank order - `_top_investment_
    choice`'s own commit-margin check, which compares a candidate
    animal's score directly against the best crop's score - doesn't have
    to recompute them by hand or trust a second, potentially-drifting
    calculation.

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
    `crop_revenue_per_tile_day` - see its own docstring.

    `days_remaining`/`rank_season_aware`/`animal_net_of_cost` (T8.3m):
    `days_remaining` is the one shared fact (days left in the season, if
    planted/placed today) both sides can use; `rank_season_aware` and
    `animal_net_of_cost` independently gate whether the crop side and the
    animal side actually *use* it, so the two mechanisms measure cleanly
    in isolation (T8.3b's own lesson: a bundled test of two mechanisms is
    confounded). Both default to `False`, reproducing the exact prior
    behavior for every caller that doesn't pass them - matches
    `crop_tile_counts`/`unlocked_shops`'s own "`None`/off means no
    information" convention. `feed_price` for the animal side is derived
    here (this module already imports `price`, so there's no need for a
    caller to compute or pass a separate market-prices dict - see
    `agent_main.py`'s own comment on why `obs["market"]["prices"]` is
    unused throughout this package, `price()` recomputes it from
    inventory instead) only when `animal_net_of_cost` is set, since it's
    otherwise unused.

    `animal_fertilizer_income_aware` (T8.3q) is passed straight through to
    `animal_revenue_per_tile_day`, along with the market's current
    FERTILIZER inventory (derived here for the same reason `feed_price`
    is - no separate caller plumbing needed) - see its own docstring for
    the mechanism. Independently gated from `animal_net_of_cost` per
    T8.3b's own lesson, even though it only has an effect when
    `animal_net_of_cost` is also on (no horizon to bound the walk
    otherwise) - this keeps the flag's own meaning ("does the ranking
    know about fertilizer income") separable from whether cost-netting
    happens to be on, for a clean three-way self-play comparison
    (fertilizer alone is a no-op without net-of-cost; net-of-cost alone;
    both together).

    `animal_care_aware` (T8.3q) is passed straight through the same way -
    see `animal_revenue_per_tile_day`'s own docstring and
    `_animal_full_care_units` for the mechanism. Independently gated from
    both `animal_net_of_cost` and `animal_fertilizer_income_aware`, for
    the same reason: T8.3b's isolation lesson applies to every new
    mechanism layered on this ranking, not just the first one.

    `animal_consumption_horizon_aware` (T8.10) is passed straight through
    to `animal_revenue_per_tile_day`, along with a plain units/day
    `consumption_rate` derived here the same way `feed_price`/
    `fertilizer_sell_at_inventory` already are - see that function's own
    docstring for the mechanism. Independently gated from
    `animal_net_of_cost`/`animal_fertilizer_income_aware`/`animal_care_
    aware`, same reason as those three. Defaults to `False`, reproducing
    the exact prior behavior for every caller that doesn't pass it.

    `wheat_self_sufficiency_aware`/`wheat_feed_units_needed` (T8.24, the
    user's own follow-up): adds `wheat_feed_credit_per_tile_day`'s own
    delta to WHEAT's score alone (every other item untouched) - see that
    function's own docstring for the make-vs-buy mechanism. Real feed
    demand (how many remaining days' worth of FEED an existing/pursued
    animal needs) isn't something this function can determine on its own
    (it has no notion of farm state, only market prices) - a caller
    (`decide()`) computes and passes it in, the same "caller supplies the
    number, this function just prices it" convention `expected_
    consumption`/`crop_tile_counts` already use. Both default to
    off/`0`, reproducing the exact prior WHEAT score for every caller
    that doesn't pass them - `wheat_feed_units_needed=0` alone is already
    a no-op regardless of the flag (see `wheat_feed_credit_per_tile_
    day`'s own docstring), the flag is an extra, explicit gate for a
    clean isolated on/off comparison in self-play (T8.3b's own lesson).
    """
    crop_tile_counts = crop_tile_counts or {}
    unlocked_shops = unlocked_shops or []
    crop_days_remaining = days_remaining if rank_season_aware else None
    scores = {}
    for crop in CROPS:
        inv = market_inventory.get(crop, MARKET_I0)
        total_yield, tile_days = _crop_yield_and_tile_days(crop, crop_days_remaining)
        already_committed_units = crop_tile_counts.get(crop, 0) * total_yield
        expected_consumption = expected_daily_consumption(crop, unlocked_shops) * tile_days
        scores[crop] = crop_revenue_per_tile_day(
            crop, inv, already_committed_units, expected_consumption, net_of_seed_cost, crop_days_remaining
        )
        if crop == "WHEAT" and wheat_self_sufficiency_aware:
            scores[crop] += wheat_feed_credit_per_tile_day(
                inv, wheat_feed_units_needed, already_committed_units, expected_consumption,
                crop_days_remaining,
            )
    animal_days_remaining = days_remaining if animal_net_of_cost else None
    feed_price = price("WHEAT", market_inventory.get("WHEAT", MARKET_I0)) if animal_net_of_cost else 0
    fertilizer_sell_at_inventory = market_inventory.get("FERTILIZER", MARKET_I0)
    for animal, a in ANIMALS.items():
        inv = market_inventory.get(a["product"], MARKET_I0)
        consumption_rate = expected_daily_consumption(a["product"], unlocked_shops)
        expected_consumption = consumption_rate * a["interval"]
        scores[animal] = animal_revenue_per_tile_day(
            animal, inv, expected_consumption, animal_days_remaining, animal_net_of_cost, feed_price,
            animal_fertilizer_income_aware, fertilizer_sell_at_inventory, animal_care_aware,
            animal_consumption_horizon_aware, consumption_rate,
        )
    return scores


def rank_portfolio(
    market_inventory: dict,
    crop_tile_counts: dict | None = None,
    unlocked_shops: list | None = None,
    net_of_seed_cost: bool = False,
    days_remaining: int | None = None,
    rank_season_aware: bool = False,
    animal_net_of_cost: bool = False,
    animal_fertilizer_income_aware: bool = False,
    animal_care_aware: bool = False,
    animal_consumption_horizon_aware: bool = False,
    wheat_self_sufficiency_aware: bool = False,
    wheat_feed_units_needed: int = 0,
) -> list[str]:
    """All crop and animal names, ranked descending by revenue per
    tile-day - a thin wrapper sorting `score_portfolio`'s own dict (see
    its docstring for every argument's meaning and measured history).
    Kept as a separate function (rather than inlining the sort at every
    call site) since almost every caller only needs the ranking, not the
    raw numbers.
    """
    scores = score_portfolio(
        market_inventory, crop_tile_counts, unlocked_shops, net_of_seed_cost, days_remaining,
        rank_season_aware, animal_net_of_cost, animal_fertilizer_income_aware, animal_care_aware,
        animal_consumption_horizon_aware, wheat_self_sufficiency_aware, wheat_feed_units_needed,
    )
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
# rate) to hires_per_day=0 in direct self-play - that result was
# overturned by T8.7 below, not merely superseded by a later sweep.
#
# T8.8 re-sweep (once hires_per_day=1 landed): raised again, 10000 ->
# 15000 - a real, held-out-gated result (see
# _DEFAULT_LAND_BUY_MAX_FREE_TILE_FRACTION's own comment for the full
# joint-sweep story; both land params were swept and accepted together).
_DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY = 15000

# T8.7 (tasks/plan.md, Stage B's payoff): T7.4's own hires_per_day=0
# result was invalid, not just stale - Phase 8's planning found it ran
# against code where a hired hand could silently pick up the wheat/
# animal into an inventory decide() never looked at again (starving any
# animal on the farm), and build_task_list proposed at most one new-
# investment task per turn regardless of hand count (extra hands had
# nothing to plant). T8.4 (inventory pinning) and T8.6 (parallel
# planting) fixed both causes; this task re-ran the sweep to find out
# whether hiring pays off once they're gone.
#
# **The prediction stated up front (so a miss would have been
# informative) came true, decisively**: direct self-play against the
# checked-in T8.6 baseline flipped completely - every nonzero
# hires_per_day tried won 96-100% (hires_per_day=1: 50/50, Wilson
# [0.929, 1.0]; 2/3/4/8 also hit the same 100% ceiling; 6 alone dipped to
# 96%, likely noise around an already-saturated result). A joint sweep of
# the suspected-correlated group {hires_per_day, max_plants_per_unit,
# seed_buffer_per_unit} (SPEC-tuning.md: correlated parameters should be
# swept jointly, not independently) found no further improvement beyond
# hires_per_day alone - the geometry-derived defaults for the other two
# (100, 1) already don't bind at this hiring level. **Accepted**:
# hires_per_day 0 -> 1 - a real, held-out-gated win (50/50, Wilson
# [0.929, 1.0]), not merely a working-block artifact. Deliberately the
# most conservative value among several that tied at the measured
# ceiling (1/2/3/4/8 all won 100%) - the least labor cost for the same
# measured benefit, consistent with this project's own preference for
# minimal accepted changes. See `tools/run_hiring_sweep.py` for the full
# sweep and `tasks/todo.md`'s T8.7 entry for the complete story.
_DEFAULT_HIRES_PER_DAY = 1

# T8.16(d) (superseding T8.12's own rejection - see the comment block
# below): dynamic_hiring is ON by default - a real, decisive held-out
# result (49W/1L/0T, 98%, Wilson interval [0.895, 0.996] entirely clear
# of the 50% baseline) accepted it, once T8.16(a)'s counting fix landed
# AND min_hires_per_day was actually swept instead of left at the old
# flat constant's own value. See the acceptance comment below for the
# full traced story.
_DEFAULT_DYNAMIC_HIRING = True
# T8.16(d): swept jointly with dynamic_hiring's other three knobs
# (max_hires_per_day, turns_per_task_estimate, hire_buffer_fraction) via
# tuning.coordinate_ascent - 2 (and 3, tied) decisively beat 1 on the
# working block (0.94 vs 0.62) while every other knob's best value
# stayed at its untouched starting point. This alone - not the buffer,
# not a tighter turns-per-task estimate - is what turned T8.16(a)'s
# "recovered but not decisive" (62%/48%) into a real win: the user's own
# original question ("нужно определиться с необходимым количеством
# рабочих в первый день") named exactly this knob. See
# tools/measure_t816d.py for the full sweep and tools/trace_t816d.py for
# the seed-900 confirmation (8 hands by end of episode vs the old
# default's 1, hand PASS only 101/1438 turns - genuinely working, not
# idling; final money 41365 vs 36172, +14.4% on this one seed).
_DEFAULT_MIN_HIRES_PER_DAY = 2
# The edge this stays comfortably clear of: fib-priced hire #8 costs $21
# (the 8th hire that day), $54 cumulative for the day - negligible next
# to a season's ~$30k of money (see hire_cost's own fib curve), so 8 is a
# real ceiling on wasted labor, not yet a binding cost constraint.
_DEFAULT_MAX_HIRES_PER_DAY = 8
# Derived from a real measurement, not a guess: one traced episode showed
# 405 movement actions across 313 productive farmer actions (~2.3 turns
# spent per unit of real work) - 2.0 is a deliberately conservative
# starting point for a future sweep, not the measured figure itself.
_DEFAULT_TURNS_PER_TASK_ESTIMATE = 2.0
# The user's own explicit request: protect the season's limited starting
# capital from being spent entirely on labor before seeds/animals are
# even affordable. 0 (no reserve) reproduces min_hires_per_day's own
# floor-only behavior for every caller that doesn't set it - the first
# hire costs $1 regardless, so this is not a blanket "never hire while
# poor" rule, only the specific reserve the user named.
_DEFAULT_HIRE_CASH_RESERVE = 0

# T8.16: 0.0 (no buffer) reproduces the pre-T8.16 formula exactly for
# every caller that doesn't set it - see hires_per_day's own docstring.
_DEFAULT_HIRE_BUFFER_FRACTION = 0.0

# T8.26: **measured and decisively rejected** (tools/measure_t826.py: 10%/
# 0% alone on a crop-only farm against the plain T8.16(d) baseline) -
# traced to reproducing T8.12's own original mistake: the ported per-tile
# action functions below count routine WATER/FEED/CARE at their full
# per-day rate, but pending_task_count (the existing reactive path)
# deliberately excludes exactly these ops (T8.16(a)'s own measured fix,
# for the same reason - a tile needs one WATER/FEED per day regardless of
# labor size, so counting it as scaling demand over-hires with no matching
# gain). See kagg.policy.params.DEFAULT_PARAMS's own comment for the full
# measured story. Off by default - the pending_task_count-derived
# (reactive) path stays hires_per_day's default behavior for every caller
# that doesn't set this. Kept available (tested) for a future corrected
# version that excludes routine ops from the forecast - not built here.
_DEFAULT_WORKLOAD_FORECAST_HIRING_AWARE = False
# Matches tools/analyze_unit_economics.py's own SEASON_LENGTH_DAYS - a
# "no days_remaining given -> assume a full season" steady-state fallback,
# the same convention `crop_revenue_per_tile_day`/`animal_revenue_per_
# tile_day` already use elsewhere in this module. decide() passes the
# episode's real days_remaining in practice.
_DEFAULT_WORKLOAD_FORECAST_DAYS_REMAINING = 30

# **dynamic_hiring: originally measured and rejected (T8.12), now
# measured and ACCEPTED (T8.16)**. T8.12's own rejection: 2/50 working,
# 4/50 holdout, 0 ties either block - traced (seed 900) to `len(tasks)`
# counting every queued action including ones that recur regardless of
# labor level (routine watering chief among them), so the formula read a
# large *standing* backlog as a large *marginal* one and over-hired (up
# to 5 hands, 68 idle PASS turns) without a matching gain (final money
# fell, 28439 vs 32958).
#
# T8.16(a) fixed the traced root cause directly: `pending_task_count`
# (decide.py) now excludes `_ROUTINE_RECURRING_OPS` (WATER/FEED) instead
# of counting every queued task. Measured alone (dynamic_hiring=True,
# every other knob at its untouched starting value): 62%/48%, a huge
# recovery from T8.12's 4%/8% but not yet decisive on its own.
#
# T8.16(d) found the actual missing piece via a joint sweep (SPEC-
# tuning.md: correlated parameters together, not independently) over
# {min_hires_per_day, max_hires_per_day, turns_per_task_estimate,
# hire_buffer_fraction}: raising `min_hires_per_day` from 1 to 2 (the
# user's own original ask - a real day-1 floor sized for the season's
# most promising goods, not just a reactive backlog formula) took the
# working-block win rate from 0.62 to 0.94, while every other knob's
# best value stayed at its untouched default (a spare-capacity buffer
# actively hurt at every value tried - 0.02; a tighter turns-per-task
# estimate helped some, 0.72, but far less than the floor change; a
# looser one or a higher max_hires_per_day both hurt). The held-out gate
# then cleared decisively: 49W/1L/0T (98%, Wilson [0.895, 0.996]) against
# the old checked-in baseline. Traced (seed 900, tools/trace_t816d.py):
# candidate ends the episode with 8 hands (vs the old default's 1), hand
# PASS only 101 of 1438 hand action-turns (~7%, genuinely working, not
# idling), final money 41365 vs 36172 (+14.4%). **Shipped default now:
# `dynamic_hiring=True`, `min_hires_per_day=2`** - see
# tools/measure_t816d.py for the full sweep and acceptance run.

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
# 1-unit farm, re-swept once labor works (T8.8).
#
# **T8.8 re-sweep, once hires_per_day=1 (T8.7) landed: real, decisive,
# and the opposite direction the plan's own hypothesis expected.** The
# working assumption going in was "more labor can work more land, so the
# gate should loosen" - measured instead that an even *stricter* gate
# (0.25 -> 0.1) beats 0.25 decisively (working block: 0.90 vs 0.25's own
# 0.36-0.38; held-out: 0.84, Wilson [0.715, 0.917], formally accepted).
# Every looser value tried (0.4, 0.6, 0.8, 1.0 - fully ungated) lost
# outright, 1.0 all the way down to a total 0/50. Traced, not just
# assumed: a second labor unit still doesn't change the underlying
# constraint T8.3 already found - land purchase spends cash that would
# otherwise buy seeds/animals, and a hired hand needs *work* (more
# investment tasks), not more square footage, to be productive; two
# units still can't profitably use even one full 25-tile quadrant, only
# more so once land competes with T8.6's now-larger seed/animal spend
# for the same cash. **Accepted**: 0.25 -> 0.1.
_DEFAULT_LAND_BUY_MAX_FREE_TILE_FRACTION = 0.1
# No evidence yet this second gate is needed once the fraction gate above
# already prevents nearly all land purchases - stays disabled (99 is
# unreachable on any real board).
_DEFAULT_LAND_BUY_MIN_FRONTIER_DISTANCE = 99


def _crop_actions_per_tile_day(crop: str, days_remaining: int, use_fertilizer: bool) -> float:
    """Average farmer-actions/day for one fully-tended tile of `crop` -
    T8.26, ported verbatim from tools/analyze_unit_economics.py (this
    session's own unit-economics analysis, verified directly against
    kaggriculture.py's own handlers) into the shipped bundle, so
    `hires_per_day`'s workload forecast below can use it without a
    tools/-only dependency.

    WATER 1/day for the tile's whole life (anti-weed insurance, not just
    the yield bonus window); HARVEST once for a one-time crop (one call
    empties all banked yield_units and clears the tile) or once per
    scheduled production tick for an ongoing crop (harvested promptly,
    matching `_animal_full_care_units`'s own "labor-unconstrained"
    assumption); FERTILIZE (optional) once every 3 days
    (fertilized_until_day covers today + 2 more); PLANT once at the
    start.
    """
    total_yield, tile_days = _crop_yield_and_tile_days(crop, days_remaining)
    water_actions = tile_days
    harvest_actions = total_yield if CROPS[crop]["ongoing"] else 1
    fertilize_actions = math.ceil(tile_days / 3) if use_fertilizer else 0
    plant_actions = 1
    total_actions = water_actions + harvest_actions + fertilize_actions + plant_actions
    return total_actions / tile_days


def _animal_actions_per_tile_day(
    animal: str, days_remaining: int, care_aware: bool, fertilizer_income_aware: bool
) -> float:
    """Average farmer-actions/day for one fully-tended animal - T8.26,
    ported verbatim from tools/analyze_unit_economics.py (see
    `_crop_actions_per_tile_day`'s own docstring for why it lives here
    now too).

    FEED 1/day (an unfed animal risks escape); CARE (optional) 1/day;
    COLLECT_FERTILIZER (optional) 1/day - fertilizer_available is set
    True at the end of *every* day the animal survives, fed or not
    (`_daily_refresh_animals`); HARVEST once per scheduled production
    tick (`forecast_animal_schedule`'s own count, harvested promptly);
    BUILD_*/PICKUP/PLACE: 3, one-time setup.
    """
    schedule = forecast_animal_schedule(animal, placed_day=0, horizon_days=days_remaining)
    feed_actions = days_remaining
    care_actions = days_remaining if care_aware else 0
    collect_fertilizer_actions = days_remaining if fertilizer_income_aware else 0
    harvest_actions = len(schedule)
    setup_actions = 3
    total_actions = feed_actions + care_actions + collect_fertilizer_actions + harvest_actions + setup_actions
    return total_actions / days_remaining


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


def hires_per_day(
    params: dict | None = None,
    pending_task_count: int | None = None,
    hour: int = 0,
    turns_per_day: int = 24,
    money: float | None = None,
    animal_tile_counts: dict[str, int] | None = None,
    crop_tile_counts: dict[str, int] | None = None,
    days_remaining: int | None = None,
) -> int:
    """How many farm hands to hire right now.

    Explicitly a tunable parameter, not a fixed policy (SPEC-policy.md):
    the "labor is nearly free, hire many hands" intuition derived from
    `hire_cost`'s Fibonacci curve was directly contradicted by an early
    forum measurement ("adding workers has zero marginal value" - SPEC.md's
    economic analysis) and by this project's own first sweep (T7.4). T8.7
    found that result invalid, not just stale - it ran against real bugs
    that starved a hired hand's own throughput - and re-ran the sweep once
    those were fixed (T8.4/T8.6): every nonzero value tried won decisively
    in direct self-play. See `_DEFAULT_HIRES_PER_DAY`'s own comment for
    the full measured story.

    `dynamic_hiring`/`pending_task_count`/`hour`/`turns_per_day`/`money`
    (T8.12, the user's own observation): a flat constant can't reflect how
    much work actually needs doing - the real capacity a labor force needs
    to clear the *current* task backlog before the day resets. When
    `params["dynamic_hiring"]` is set and a real `pending_task_count` is
    given (`decide()` passes `len(tasks)`, the already-built task list -
    no extra board scan needed), the target scales with the backlog:
    `ceil(pending_task_count * turns_per_task_estimate / max(1,
    turns_per_day - hour)) - 1` (the `-1` accounts for the farmer's own
    turn, already one of the labor units working the backlog), clipped to
    `[min_hires_per_day, max_hires_per_day]`. `turns_per_task_estimate`
    (default 2.0) is itself a named, swept parameter, not a guess baked
    into the formula - derived from a real measurement (405 movement
    actions across 313 productive farmer actions in one traced episode,
    ~2.3 turns/task; 2.0 chosen as a deliberately conservative starting
    point for a future sweep, per SPEC-policy.md's own rule against
    unswept intuition constants).

    `min_hires_per_day` (default matches `_DEFAULT_HIRES_PER_DAY`, i.e.
    1) is the user's own explicit concern: the season's limited starting
    capital shouldn't all go to labor before seeds/animals are even
    affordable, so a floor protects it the same way the plain constant
    already did before this task. `hire_cash_reserve` (default 0) makes
    that same concern an explicit, swept, named gate instead of leaving
    it implicit in the floor alone: when `money` is given and falls below
    it, hiring drops to `min_hires_per_day` regardless of backlog size.

    `hire_buffer_fraction` (T8.16, the user's own explicit ask: "небольшой
    запас рабочей силы для компенсации всплеска потребности работы, на
    вскидку 5-10%") scales the raw target up by `(1 + hire_buffer_
    fraction)` (rounded up) *before* clipping to `[min_hires_per_day,
    max_hires_per_day]` - a deliberate margin against the backlog signal
    itself being a noisy, one-turn-snapshot estimate of a fast-changing
    farm. Default `0.0` (no buffer), reproducing the exact pre-T8.16
    formula for every caller that doesn't set it.

    `workload_forecast_hiring_aware`/`animal_tile_counts`/`crop_tile_
    counts` (T8.26, the user's own proposed formula): a *proactive*
    alternative to the `pending_task_count` path above, which sizes the
    target from the currently-*visible* task backlog - a number that only
    grows as the day's turns reveal more work, so it structurally lags a
    day's real, already-known-at-hour-0 workload. When this flag is set
    and both tile-count dicts are given (real per-type tile counts -
    `decide()` passes `placed_animal_type_counts`/`_crop_tile_counts(me[
    "tiles"])`, own tiles only), the target is derived directly from them
    instead: `total_turns = (sum(_animal_actions_per_tile_day(a,
    days_remaining, animal_care_aware, animal_fertilizer_income_aware) *
    animal_tile_counts[a] for each type present) + sum(_crop_actions_per_
    tile_day(c, days_remaining, use_fertilizer) * crop_tile_counts[c] for
    each type present)) * turns_per_task_estimate` - the same task-count-
    to-turn-count conversion the `pending_task_count` path above already
    uses (folding in movement/travel overhead once, not a second additive
    term), buffered by `hire_buffer_fraction` and clipped to `[min_hires_
    per_day, max_hires_per_day]`, same as always.

    Divided by the *full* `turns_per_day`, not `turns_left_today` - this
    is a fixed whole-day forecast computed from tile counts known in full
    at hour 0, not a shrinking backlog, so dividing by the remaining
    turns would keep inflating the target through the day for the exact
    same real work. Computed identically regardless of what hour it's
    called from, so `decide()`'s own hire-emission loop naturally
    front-loads the day's hires into its first turn(s) instead of
    trickling them out as the day's turns tick by.

    `animal_care_aware`/`animal_fertilizer_income_aware`/`use_fertilizer`
    are read from `params` (already-named parameters elsewhere in this
    module) rather than taken as separate arguments here, so this
    forecast automatically matches whatever care/fertilizer mechanisms
    are actually turned on for the episode - a farm not doing CARE
    shouldn't be staffed as if it were.

    Falls back to the `pending_task_count` path (or the plain static
    value) whenever the flag is off, or on but either tile-count dict is
    `None`/`days_remaining` is `None` - bit-identical for every existing
    caller that doesn't pass the new arguments (`days_remaining` alone
    defaults to a full season - see `_DEFAULT_WORKLOAD_FORECAST_DAYS_
    REMAINING` - once both tile-count dicts are actually given, since a
    caller that bothers to pass real tile counts but no `days_remaining`
    still wants *a* real forecast, not a silent fallback).

    Graceful fallback to the plain static value (not an error) whenever
    `dynamic_hiring` is off, or on but `pending_task_count` is `None` (no
    task-list information given) - matches `net_of_cost`'s own "no
    `days_remaining` -> steady state" convention elsewhere in this
    module. `dynamic_hiring` defaults to `False`, reproducing the exact
    prior behavior for every caller that doesn't pass the new arguments.
    """
    params = params or {}
    static = params.get("hires_per_day", _DEFAULT_HIRES_PER_DAY)
    if not params.get("dynamic_hiring", _DEFAULT_DYNAMIC_HIRING):
        return static
    min_hires = params.get("min_hires_per_day", _DEFAULT_MIN_HIRES_PER_DAY)
    max_hires = params.get("max_hires_per_day", _DEFAULT_MAX_HIRES_PER_DAY)
    cash_reserve = params.get("hire_cash_reserve", _DEFAULT_HIRE_CASH_RESERVE)
    if money is not None and money < cash_reserve:
        return min_hires
    turns_per_task = params.get("turns_per_task_estimate", _DEFAULT_TURNS_PER_TASK_ESTIMATE)
    buffer_fraction = params.get("hire_buffer_fraction", _DEFAULT_HIRE_BUFFER_FRACTION)
    workload_forecast_aware = params.get(
        "workload_forecast_hiring_aware", _DEFAULT_WORKLOAD_FORECAST_HIRING_AWARE
    )
    if workload_forecast_aware and animal_tile_counts is not None and crop_tile_counts is not None:
        effective_days_remaining = (
            days_remaining if days_remaining is not None else _DEFAULT_WORKLOAD_FORECAST_DAYS_REMAINING
        )
        animal_care_aware = params.get("animal_care_aware", False)
        animal_fertilizer_income_aware = params.get("animal_fertilizer_income_aware", False)
        use_fertilizer = params.get("use_fertilizer", False)
        animal_turns = sum(
            _animal_actions_per_tile_day(
                a, effective_days_remaining, animal_care_aware, animal_fertilizer_income_aware
            )
            * count
            for a, count in animal_tile_counts.items()
            if count > 0
        )
        crop_turns = sum(
            _crop_actions_per_tile_day(c, effective_days_remaining, use_fertilizer) * count
            for c, count in crop_tile_counts.items()
            if count > 0
        )
        total_turns = (animal_turns + crop_turns) * turns_per_task
        target = math.ceil(total_turns / turns_per_day) - 1
        target = math.ceil(target * (1 + buffer_fraction))
        return min(max(target, min_hires), max_hires)
    if pending_task_count is None:
        return static
    turns_left_today = max(1, turns_per_day - hour)
    needed_unit_turns = pending_task_count * turns_per_task
    target = math.ceil(needed_unit_turns / turns_left_today) - 1
    target = math.ceil(target * (1 + buffer_fraction))
    return min(max(target, min_hires), max_hires)
