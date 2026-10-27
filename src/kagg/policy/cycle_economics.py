"""T8.68: cycle-economics ranking - a drop-in replacement for
`kagg.policy.strategy.score_portfolio`/`rank_portfolio`, built on the
saved "profit per day per cycle" analysis (T8.57, `tools/
tile_economics_30d.py` -> `tasks/data/tile_economics.json`, explicitly
kept as "the basis of the formula that picks the next product for a free
tile" - see that task's own tasks/todo.md entry).

The user's own request, in three parts: (1) an animal's horizon is the
real days remaining until the season ends, not `tile_economics_30d.py`'s
own hardcoded `DAYS = 30`; (2) a crop's horizon is the same real days
remaining, and if that isn't enough for even one full plant->harvest
cycle, or ends mid-cycle, the score reflects the partial yield actually
reachable instead of excluding the crop outright; (3) prices are always
the live market price, never the tile_economics table's static base
price. A follow-up added a fourth: a crop's score normally assumes no
fertilizer, but switches to the fertilized-cycle economics once the live
FERTILIZER *sell* price (there is no way to buy it - see
`kagg.gamelib.market`'s own module docstring) drops below a threshold.

And the decisive correction to this module's first draft: the horizon
must value a tile's **whole remaining life**, not one cycle's rate - a
plant's tile is replanted after every harvest, all the way to the
season's last day, and an animal keeps producing every day through that
same last day. This mirrors `tile_economics_30d.py`'s own original N-day
table methodology (`crop_report()`'s `cycles = (DAYS-1)//h` repeated
full-life cycles plus a partial tail cycle; `animal_report()`'s day-by-
day simulation), generalized from that script's fixed `DAYS`/static
prices to a live `days_remaining`/live prices - exactly the two things
the user asked to change.

Two things this module deliberately reuses rather than re-derives:

- **Animals**: `kagg.policy.strategy.animal_revenue_per_tile_day`'s own
  `net_of_cost=True, care_aware=True` branch already nets an animal's
  cost/feed against a live `days_remaining` via `_animal_full_care_
  schedule` - an exact day-by-day simulation of continuous CARE+feeding
  through the literal last day of `days_remaining`, i.e. already exactly
  "placement, wait, collect, repeat, to the actual last day of the
  game." `animal_horizon_profit_per_day` below is a thin wrapper, not a
  reimplementation.
- **A crop's cycle *shape*** (which ages to water/fertilize/harvest,
  units produced, one life's length, for a `no_fertilizer` and a
  `fertilizer_best_rate` variant) is a fixed mechanical fact, independent
  of the current day or price - computed once offline by a DP search
  over the real engine (`tools/tile_economics_30d.py:best_crop_cycle`/
  `best_crop_cycle_fert`, too slow to run per-turn: strawberry alone is
  ~20M DP states) and shipped as a static snapshot,
  `kagg/params/tile_economics.json` (mirrors `kagg.policy.params`'s own
  `policy.json` loading convention and its build-bundle inclusion - see
  `tools/build_submission.py`).

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

import json
import os

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0
from kagg.gamelib.growth import forecast_one_time_yield, forecast_ongoing_schedule
from kagg.gamelib.market import expected_consumption_over_horizon, expected_daily_consumption, price
from kagg.policy.strategy import animal_revenue_per_tile_day, wheat_feed_credit_per_tile_day

_SHAPES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "params", "tile_economics.json"
)


def _load_plant_shapes() -> dict:
    """`tasks/data/tile_economics.json`'s `plants` section, keyed by crop
    name - never crashes on a missing/corrupt file (same defensive
    convention as `kagg.policy.params.load_params`), just falls back to
    "no shape data," which makes every crop score 0 (see
    `crop_horizon_profit_per_day`) rather than raising mid-episode.
    """
    try:
        with open(_SHAPES_PATH) as f:
            data = json.load(f)
        return data["plants"]
    except (OSError, ValueError, KeyError):
        return {}


_PLANT_SHAPES = _load_plant_shapes()


def units_per_cycle(crop: str) -> int:
    """The DP-optimal (no-fertilizer) full-life yield of one planting of
    `crop`, from the same static shape data every other function in this
    module scores with - `0` for a crop with no shape data. Public (T8.71)
    so `decide.py`'s `_pending_crop_supply` can use the exact same
    "standard yield" estimate for a still-growing tile as the rest of
    this module already uses everywhere else, instead of a second,
    separately-derived number.
    """
    shape = _PLANT_SHAPES.get(crop)
    return shape["variants"]["no_fertilizer"]["units"] if shape else 0


def _is_fertilizer_active(day: int, fertilized_days) -> bool:
    """Mirrors `kagg.gamelib.growth._is_fertilizer_active` (private to
    that module - reimplemented here as the same one-line rule rather
    than imported, since it's tiny and this module has its own, ongoing-
    crop-specific use for it below)."""
    return any(f <= day <= f + 2 for f in fertilized_days)


def _one_time_tail_units(crop: str, rest: int, water_days, fert_days) -> int:
    """Partial-tail yield for a one-time crop (WHEAT/CARROT/MELON)
    planted at the start of a tail window `rest` days long - truncates
    the variant's own (already DP-optimal for the *full* cycle) watering/
    fertilizing ages to `<= rest` and replays them through the real
    yield mechanic (`forecast_one_time_yield`). An approximation (the
    true DP-optimal schedule for a *shorter* window could differ) traded
    deliberately for speed - re-running the DP live is the ~20M-state
    cost this module exists to avoid; truncating the known-good full
    schedule is the same "reuse the static shape, price it live"
    approach the whole module takes.
    """
    truncated_water = {d for d in water_days if d <= rest}
    truncated_fert = {d for d in fert_days if d <= rest}
    return forecast_one_time_yield(crop, truncated_water, truncated_fert)


def _ongoing_tail_units(crop: str, rest: int, fert_days) -> int:
    """Partial-tail yield for an ongoing crop (TOMATO/STRAWBERRY) planted
    at the start of a tail window `rest` days long - each of the crop's
    fixed production ticks (`forecast_ongoing_schedule`, independent of
    watering: kaggriculture.py's `_daily_refresh_plants` fires a tick on
    schedule regardless) that falls within the window contributes 1 unit,
    or 2 if a fertilizer application from `fert_days` (ages, truncated the
    same way as the one-time case) is active that tick's day.
    """
    schedule = forecast_ongoing_schedule(crop, planted_day=0)
    truncated_fert = {d for d in fert_days if d <= rest}
    total = 0
    for day in schedule:
        if day > rest:
            break
        total += 2 if _is_fertilizer_active(day, truncated_fert) else 1
    return total


def crop_horizon_profit_per_day(
    crop: str,
    days_remaining: int,
    sell_at_inventory: int,
    already_committed_units: int = 0,
    expected_consumption: float = 0,
    fertilizer_price: float = 0.0,
    fertilizer_price_threshold: float = 0.0,
) -> tuple[float, bool]:
    """Net profit per day for one tile of `crop`, replanted every time it
    matures, all the way through `days_remaining` (request point 2's
    "whole remaining life", not one cycle's rate) - `(profit_per_day,
    used_fertilizer)`, the `bool` telling a caller whether this turn's
    score assumed the fertilized cycle (needed by `tasks.py` to actually
    apply FERTILIZE on the crops this ranking counted on, not just in the
    score - see `score_portfolio_v2`'s own docstring).

    Falls back to `(0.0, False)` when `days_remaining <= 0` or no shape
    data was loaded for `crop` (see `_load_plant_shapes`) - a graceful
    default, not a crash, matching every other function in this package's
    "missing information means no signal, not an error" convention.

    **Fertilizer gate** (request point 4): the fertilized variant is used
    only when the live FERTILIZER *sell* price is below `fertilizer_
    price_threshold` (there's no way to buy it - `market.py`'s own
    module docstring - so "the fertilizer price" can only mean the
    opportunity cost of selling it instead, the same framing this
    project's `wheat_feed_credit_per_tile_day` already uses for WHEAT)
    AND the fertilized variant's own `fert_days` is non-empty (MELON's
    is: fertilizer genuinely doesn't help it - its first harvest already
    lands before a second application could matter - so it never
    switches, confirmed directly in the saved table).

    **Whole-horizon accounting**, mirroring `tile_economics_30d.py`'s own
    `crop_report()` (generalized from its fixed `DAYS` to live `days_
    remaining`): `cycles = (days_remaining - 1) // cycle_days` full
    plant -> harvest (-> dig, if ongoing) -> replant cycles fit inside
    the horizon; `rest = (days_remaining - 1) - cycles * cycle_days` days
    are left over after the last one. A **partial tail cycle** (request
    point 2) is planted in that leftover window when it's actually worth
    it - not merely net-positive on its own (`crop_report`'s own
    `partial = p_units * price > seed` rule, the first version of this
    function's own criterion, at live price instead of the table's
    static one), but only when blending it in doesn't drag the combined
    per-day rate below what the full cycles alone already earn (see the
    denominator paragraph below for why a merely-net-positive tail isn't
    automatically an improvement once the denominator is tile-days, not
    `days_remaining`) - this is also what naturally handles "not even one
    full cycle fits" (`cycles == 0`, `rest = days_remaining - 1` is
    simply the whole horizon, any net-positive tail is strictly better
    than the 0.0 fallback), no separate branch needed.

    Every unit across the *whole* horizon (every full cycle's, plus the
    tail's if it clears its own bar) is priced with the same per-unit
    lockstep self-impact walk `strategy.crop_revenue_per_tile_day` uses
    (T8.3f) - starting at `sell_at_inventory + already_committed_units -
    expected_consumption`, walked once across every one of those units,
    not just one cycle's: a tile that gets replanted many times over a
    long horizon really does depress its own future sale prices more
    than a single cycle's rate could ever show. `expected_consumption`
    is assumed already scaled to the *whole* `days_remaining` by the
    caller (`score_portfolio_v2` computes it as `expected_daily_
    consumption(...) * days_remaining`), matching `crop_revenue_per_
    tile_day`'s own "caller supplies the already-scaled number"
    convention for this argument.

    **Denominator: tile-days actually occupied by this plan, not the
    full `days_remaining`** (found and fixed after the first version of
    this formula was measured and lost head-to-head to `strategy.rank_
    portfolio` - T8.68's own tasks/todo.md entry has the full trace).
    Dividing by `days_remaining` charges a crop for calendar days beyond
    its own last harvest that this specific plan never actually uses -
    days the tile sits free and gets a *fresh* re-ranking next turn
    anyway (this function is called again every strategic tick), not
    days genuinely wasted by this crop. That mismatch systematically
    penalized a long-`cycle_days` crop (STRAWBERRY, 16 days) relative to
    a short one (TOMATO, 11 days) whenever `days_remaining` didn't divide
    evenly by the longer crop's cycle - exactly the 11-14-day-remaining
    window a real trace caught it switching a turn's top pick from
    STRAWBERRY to TOMATO 3-4 days earlier than the old, flat-rate ranking
    ever would. `occupied_days = cycles * cycle_days`, plus `rest + 1`
    (the tail's own window, end-inclusive) only when a partial tail is
    actually included - a tile with no worthwhile tail is simply free for
    the remaining days, which isn't this crop's cost to bear.
    """
    if days_remaining <= 0:
        return 0.0, False
    shapes = _PLANT_SHAPES.get(crop)
    if not shapes:
        return 0.0, False
    no_fert = shapes["variants"]["no_fertilizer"]
    fert = shapes["variants"].get("fertilizer_best_rate")
    used_fertilizer = (
        fert is not None
        and bool(fert.get("fert_days"))
        and fertilizer_price < fertilizer_price_threshold
    )
    variant = fert if used_fertilizer else no_fert
    cycle_days = variant["cycle_days"]
    units_per_cycle = variant["units"]
    seed_cost = variant["cost_seed"]
    fert_days = variant.get("fert_days", []) if used_fertilizer else []
    fert_apps_per_cycle = len(fert_days)

    cycles = (days_remaining - 1) // cycle_days
    rest = (days_remaining - 1) - cycles * cycle_days
    total_units_full = cycles * units_per_cycle

    start = sell_at_inventory + already_committed_units - expected_consumption

    full_revenue = sum(price(crop, start + k) for k in range(total_units_full))
    full_cost = cycles * seed_cost + cycles * fert_apps_per_cycle * fertilizer_price
    full_days = cycles * cycle_days

    partial_units = 0
    partial_fert_apps = 0
    first_yield_day = CROPS[crop]["first_yield_day"]
    if rest >= first_yield_day:
        if CROPS[crop]["ongoing"]:
            candidate_units = _ongoing_tail_units(crop, rest, fert_days)
        else:
            candidate_units = _one_time_tail_units(crop, rest, variant["water_days"], fert_days)
        if candidate_units > 0:
            candidate_fert_apps = sum(1 for d in fert_days if d <= rest)
            tail_start = start + total_units_full
            tail_value = sum(price(crop, tail_start + k) for k in range(candidate_units))
            tail_cost = seed_cost + candidate_fert_apps * fertilizer_price
            tail_days = rest + 1
            # T8.68 (found while digging into the STRAWBERRY/TOMATO
            # crossover): a net-positive tail on its own isn't
            # automatically worth blending in - a thin, barely-profitable
            # tail can still drag the combined rate BELOW what the full
            # cycles alone already earn, since it adds a lot more days
            # (tail_days) than value. Include it only when doing so
            # doesn't make the blended per-day rate worse than skipping
            # it (cycles == 0 has no "cycles alone" rate to protect, so
            # any net-positive tail is strictly better than the 0.0
            # fallback below).
            if cycles == 0:
                worth_it = tail_value > tail_cost
            else:
                base_rate = (full_revenue - full_cost) / full_days
                combined_rate = (full_revenue + tail_value - full_cost - tail_cost) / (full_days + tail_days)
                worth_it = combined_rate >= base_rate
            if worth_it:
                partial_units = candidate_units
                partial_fert_apps = candidate_fert_apps

    total_units = total_units_full + partial_units
    if total_units == 0:
        return 0.0, used_fertilizer
    n_plant = cycles + (1 if partial_units > 0 else 0)
    n_fert = cycles * fert_apps_per_cycle + partial_fert_apps

    total_revenue = sum(price(crop, start + k) for k in range(total_units))
    total_cost = n_plant * seed_cost + n_fert * fertilizer_price
    occupied_days = cycles * cycle_days + (rest + 1 if partial_units > 0 else 0)
    return (total_revenue - total_cost) / max(1, occupied_days), used_fertilizer


def crop_cycle_profit_per_day(
    crop: str,
    days_remaining: int,
    market_inventory_level: int,
    pending_supply: int = 0,
    expected_consumption: float = 0,
    fertilizer_price: float = 0.0,
    fertilizer_price_threshold: float = 0.0,
) -> tuple[float, bool]:
    """T8.71 - the user's own redesign, replacing `crop_horizon_profit_
    per_day`'s "whole remaining life" projection with a single-cycle
    score, gated by `crop_pending_supply_aware`.

    The user's own reasoning, stated directly: `decide()` re-ranks every
    crop, for every candidate tile, on EVERY turn, from scratch - a tile
    that finishes this cycle gets a fresh, independently-computed score
    next time around (possibly a different crop entirely, possibly the
    same one), so projecting several more of THIS tile's own hypothetical
    future cycles today only adds speculation this function has no real
    information to back up. Score only the one cycle that would actually
    start if this crop were planted right now - full cycle if `days_
    remaining` allows it, else the same partial-tail yield `crop_horizon_
    profit_per_day` computes for a season-end tail (`_one_time_tail_
    units`/`_ongoing_tail_units` - the same truncation helpers, not
    re-derived), with no full-vs-tail "worth it" blend to weigh, since
    there is no "full cycles" rate left to protect once this function
    never claims more than the one cycle in the first place.

    The price pressure this one cycle's own units face is priced from
    `pending_supply` - the REAL, already-known production pipeline (shed
    + units' hands + growing-but-ready + growing-but-not-yet-ready tiles,
    all currently existing, never hypothetical - see `decide._pending_
    crop_supply`) - and `expected_consumption`, which the caller computes
    over the horizon up to THIS crop's own first harvest (`CROPS[crop]
    ["first_yield_day"]`), not the whole remaining season: both are real,
    computable numbers (the game's own Price Function and town/shop
    consumption formulas), not projections about future turns' choices.
    """
    if days_remaining <= 0:
        return 0.0, False
    shapes = _PLANT_SHAPES.get(crop)
    if not shapes:
        return 0.0, False
    no_fert = shapes["variants"]["no_fertilizer"]
    fert = shapes["variants"].get("fertilizer_best_rate")
    used_fertilizer = (
        fert is not None
        and bool(fert.get("fert_days"))
        and fertilizer_price < fertilizer_price_threshold
    )
    variant = fert if used_fertilizer else no_fert
    cycle_days = variant["cycle_days"]
    fert_days = variant.get("fert_days", []) if used_fertilizer else []

    first_yield_day = CROPS[crop]["first_yield_day"]
    start = market_inventory_level + pending_supply - expected_consumption

    if days_remaining - 1 >= cycle_days:
        units = variant["units"]
        n_fert = len(fert_days)
        days_used = cycle_days
    else:
        rest = days_remaining - 1
        if rest < first_yield_day:
            return 0.0, used_fertilizer
        if CROPS[crop]["ongoing"]:
            units = _ongoing_tail_units(crop, rest, fert_days)
        else:
            units = _one_time_tail_units(crop, rest, variant["water_days"], fert_days)
        if units == 0:
            return 0.0, used_fertilizer
        n_fert = sum(1 for d in fert_days if d <= rest)
        days_used = rest + 1

    revenue = sum(price(crop, start + k) for k in range(units))
    cost = variant["cost_seed"] + n_fert * fertilizer_price
    return (revenue - cost) / max(1, days_used), used_fertilizer


def animal_horizon_profit_per_day(
    animal: str,
    days_remaining: int,
    sell_at_inventory: int,
    expected_consumption: float = 0,
    feed_price: float = 0,
    fertilizer_income_aware: bool = False,
    fertilizer_sell_at_inventory: int = MARKET_I0,
    consumption_horizon_aware: bool = False,
    consumption_rate: float = 0,
) -> float:
    """Net profit per day for one placed `animal`, fed and cared for
    every day through the literal last day of `days_remaining` (request
    point 1) - a thin wrapper around `strategy.animal_revenue_per_tile_
    day`'s already-exact `net_of_cost=True, care_aware=True` day-by-day
    simulation (`_animal_full_care_schedule`), not a reimplementation -
    see that function's own docstring for the full mechanic and cost/
    price accounting (already live-priced throughout, via `price()`).
    """
    return animal_revenue_per_tile_day(
        animal,
        sell_at_inventory,
        expected_consumption,
        days_remaining,
        net_of_cost=True,
        feed_price=feed_price,
        fertilizer_income_aware=fertilizer_income_aware,
        fertilizer_sell_at_inventory=fertilizer_sell_at_inventory,
        care_aware=True,
        consumption_horizon_aware=consumption_horizon_aware,
        consumption_rate=consumption_rate,
    )


def score_portfolio_v2(
    market_inventory: dict,
    days_remaining: int,
    crop_tile_counts: dict | None = None,
    unlocked_shops: list | None = None,
    fertilizer_price_threshold: float = 10.0,
    animal_fertilizer_income_aware: bool = False,
    animal_consumption_horizon_aware: bool = False,
    wheat_self_sufficiency_aware: bool = False,
    wheat_feed_units_needed: int = 0,
    current_day: int = 0,
    shop_unlock_forecast_aware: bool = False,
    potential_new_tiles: int = 0,
    crop_pending_supply_aware: bool = False,
    pending_crop_supply: dict | None = None,
) -> tuple[dict[str, float], frozenset[str]]:
    """Every crop and animal name mapped to its own whole-horizon profit
    per day (see `crop_horizon_profit_per_day`/`animal_horizon_profit_
    per_day`), plus the set of crops whose score assumed the fertilized
    cycle this turn (`fertilize_crops`) - `decide.py` threads this
    straight into `tasks.build_task_list` so the crops this ranking
    counted on fertilizing actually get FERTILIZEd, not just scored as if
    they would be (the user's own explicit follow-up request).

    Same "current market depth, not base price" input shape as `strategy.
    score_portfolio` (`market_inventory`/`crop_tile_counts`/`unlocked_
    shops`) - see that function's own docstring for `crop_tile_counts`/
    `unlocked_shops`'s meaning; this is a drop-in replacement, not a
    parallel system with its own conventions.

    `days_remaining` is the one shared horizon both sides use (request
    points 1 and 2 - no separate "season-aware" gate the way `strategy.
    score_portfolio`'s `rank_season_aware`/`animal_net_of_cost` are:
    since this whole module only exists to be horizon-aware, there's
    nothing to gate).

    `fertilizer_price_threshold` (request point 4) is passed straight
    through to `crop_horizon_profit_per_day` - see its own docstring.

    `animal_fertilizer_income_aware`/`animal_consumption_horizon_aware`/
    `wheat_self_sufficiency_aware`/`wheat_feed_units_needed` mirror
    `strategy.score_portfolio`'s own same-named arguments exactly (same
    mechanisms, reused not reimplemented - `wheat_feed_credit_per_tile_
    day` is the same function, animal fertilizer/consumption awareness is
    the same `animal_revenue_per_tile_day` machinery `animal_horizon_
    profit_per_day` already wraps).

    T8.70, both off by default, both purely additive to the inputs above:

    - `shop_unlock_forecast_aware` (needs `current_day`, ignored otherwise):
      swaps the flat `expected_daily_consumption(...) * days_remaining`
      below for `expected_consumption_over_horizon(...)`, which also
      prices in shops that will unlock later on the engine's own
      deterministic schedule, not just the ones unlocked today - see that
      function's own docstring in `kagg.gamelib.market`.
    - `potential_new_tiles`: added (capped by nothing here - the caller
      already caps it, see `decide.py`'s own comment at its call site) to
      every crop's `already_committed_units`, on top of the tiles it
      already occupies - every crop is scored as if *it* were the one
      about to claim the currently-free land, since at scoring time we
      don't yet know which crop will actually win the ranking (the same
      "each candidate judged as if it were the pick" framing `_top_
      investment_choice`'s own walk already uses). `0` (the default)
      reproduces today's `already_committed_units` exactly.

    T8.71, off by default: `crop_pending_supply_aware` swaps the whole
    crop-scoring path from `crop_horizon_profit_per_day` (this tile's own
    hypothetical whole remaining life) to `crop_cycle_profit_per_day`
    (one real cycle, priced off `pending_crop_supply` - see that
    function's own docstring for why). Supersedes `potential_new_tiles`
    for the crop it's on - `pending_crop_supply` already prices in every
    tile this crop currently occupies, real production pipeline and all,
    a strictly better estimate; `crop_tile_counts`/`potential_new_tiles`
    are simply not read on this path. `expected_consumption` is also
    computed differently here - over the horizon up to THIS crop's own
    first harvest (`CROPS[crop]["first_yield_day"]`), not the whole
    `days_remaining` - matching `crop_cycle_profit_per_day`'s own single-
    cycle framing (`shop_unlock_forecast_aware` still applies, just over
    the shorter horizon). `pending_crop_supply` is `decide.py`'s own
    `_pending_crop_supply(...)` result, a plain `{crop: int}` dict - `0`
    for a crop missing from it (a no-op, matching every other T8.7x
    flag's off-state elsewhere).
    """
    crop_tile_counts = crop_tile_counts or {}
    unlocked_shops = unlocked_shops or []
    pending_crop_supply = pending_crop_supply or {}
    fertilizer_price = price("FERTILIZER", market_inventory.get("FERTILIZER", MARKET_I0))

    scores: dict[str, float] = {}
    fertilize_crops: set[str] = set()
    for crop in CROPS:
        inv = market_inventory.get(crop, MARKET_I0)
        if crop_pending_supply_aware:
            first_yield_day = CROPS[crop]["first_yield_day"]
            if shop_unlock_forecast_aware:
                expected_consumption = expected_consumption_over_horizon(
                    crop, unlocked_shops, current_day, first_yield_day
                )
            else:
                expected_consumption = expected_daily_consumption(crop, unlocked_shops) * first_yield_day
            already_committed_units = pending_crop_supply.get(crop, 0)
            score, used_fertilizer = crop_cycle_profit_per_day(
                crop, days_remaining, inv, already_committed_units, expected_consumption,
                fertilizer_price, fertilizer_price_threshold,
            )
        else:
            shape = _PLANT_SHAPES.get(crop)
            crop_units_per_cycle = shape["variants"]["no_fertilizer"]["units"] if shape else 0
            already_committed_units = (
                crop_tile_counts.get(crop, 0) + potential_new_tiles
            ) * crop_units_per_cycle
            if shop_unlock_forecast_aware:
                expected_consumption = expected_consumption_over_horizon(
                    crop, unlocked_shops, current_day, days_remaining
                )
            else:
                expected_consumption = expected_daily_consumption(crop, unlocked_shops) * days_remaining
            score, used_fertilizer = crop_horizon_profit_per_day(
                crop, days_remaining, inv, already_committed_units, expected_consumption,
                fertilizer_price, fertilizer_price_threshold,
            )
        if used_fertilizer:
            fertilize_crops.add(crop)
        if crop == "WHEAT" and wheat_self_sufficiency_aware:
            score += wheat_feed_credit_per_tile_day(
                inv, wheat_feed_units_needed, already_committed_units, expected_consumption,
                days_remaining,
            )
        scores[crop] = score

    feed_price = price("WHEAT", market_inventory.get("WHEAT", MARKET_I0))
    fertilizer_sell_at_inventory = market_inventory.get("FERTILIZER", MARKET_I0)
    for animal, a in ANIMALS.items():
        inv = market_inventory.get(a["product"], MARKET_I0)
        if shop_unlock_forecast_aware:
            consumption_rate = expected_consumption_over_horizon(
                a["product"], unlocked_shops, current_day, a["interval"]
            ) / a["interval"]
        else:
            consumption_rate = expected_daily_consumption(a["product"], unlocked_shops)
        expected_consumption = consumption_rate * a["interval"]
        scores[animal] = animal_horizon_profit_per_day(
            animal, days_remaining, inv, expected_consumption, feed_price,
            animal_fertilizer_income_aware, fertilizer_sell_at_inventory,
            animal_consumption_horizon_aware, consumption_rate,
        )
    return scores, frozenset(fertilize_crops)


def rank_portfolio_v2(
    market_inventory: dict,
    days_remaining: int,
    crop_tile_counts: dict | None = None,
    unlocked_shops: list | None = None,
    fertilizer_price_threshold: float = 10.0,
    animal_fertilizer_income_aware: bool = False,
    animal_consumption_horizon_aware: bool = False,
    wheat_self_sufficiency_aware: bool = False,
    wheat_feed_units_needed: int = 0,
    current_day: int = 0,
    shop_unlock_forecast_aware: bool = False,
    potential_new_tiles: int = 0,
    crop_pending_supply_aware: bool = False,
    pending_crop_supply: dict | None = None,
) -> tuple[list[str], frozenset[str]]:
    """All crop and animal names, ranked descending by whole-horizon
    profit per day, plus `fertilize_crops` - a thin wrapper sorting
    `score_portfolio_v2`'s own dict, matching `strategy.rank_portfolio`'s
    own relationship to `score_portfolio`.
    """
    scores, fertilize_crops = score_portfolio_v2(
        market_inventory, days_remaining, crop_tile_counts, unlocked_shops,
        fertilizer_price_threshold, animal_fertilizer_income_aware,
        animal_consumption_horizon_aware, wheat_self_sufficiency_aware, wheat_feed_units_needed,
        current_day, shop_unlock_forecast_aware, potential_new_tiles,
        crop_pending_supply_aware, pending_crop_supply,
    )
    return sorted(scores, key=scores.__getitem__, reverse=True), fertilize_crops


def crops_worth_fertilizing(market_inventory: dict, fertilizer_price_threshold: float) -> frozenset[str]:
    """Every crop whose fertilized variant would actually be used this
    turn, purely from the live FERTILIZER price and each crop's own
    static shape - see `crop_horizon_profit_per_day`'s own fertilizer-
    gate paragraph for the mechanism. The switch decision itself doesn't
    depend on `days_remaining` or market depth for the crop's own
    product, so `decide()` calls this once to drive `tasks.build_task_
    list`'s FERTILIZE gate, instead of re-deriving the same set from a
    full `score_portfolio_v2` call for every ranking call site.
    """
    fertilizer_price = price("FERTILIZER", market_inventory.get("FERTILIZER", MARKET_I0))
    result = set()
    for crop, shape in _PLANT_SHAPES.items():
        fert = shape["variants"].get("fertilizer_best_rate")
        if fert and fert.get("fert_days") and fertilizer_price < fertilizer_price_threshold:
            result.add(crop)
    return frozenset(result)


def fertilize_ages(crop: str) -> frozenset[int]:
    """The DP-optimal ages (days since planting) to FERTILIZE `crop` at,
    from the same static shape data `crop_horizon_profit_per_day` scores
    with - `tasks.py`'s FERTILIZE age-gate reuses this so a fertilizer
    application actually lands on the day the score assumed, not
    scattered across the plant's life (T8.57's own finding: day-0
    fertilizing on WHEAT is "mostly wasted"). Empty for a crop with no
    shape data, or whose fertilized variant doesn't apply fertilizer at
    all (MELON).
    """
    shape = _PLANT_SHAPES.get(crop)
    if not shape:
        return frozenset()
    fert = shape["variants"].get("fertilizer_best_rate")
    if not fert:
        return frozenset()
    return frozenset(fert.get("fert_days", []))


def crop_has_time_to_produce(crop: str, current_day: int, season_length_days: int) -> bool:
    """A looser maturity check than `decide._crop_has_time_to_mature`,
    for the cycle-economics ranking path only: True if planting `crop`
    *today* leaves enough season left to reach its *first* harvest, not
    necessarily its full max-yield window.

    `decide._crop_has_time_to_mature`'s own hard `max_yield_day` gate is
    exactly what request point 2 asks to relax - a crop that can't reach
    full maturity but *can* still reach a worthwhile partial harvest
    should be scored (and chosen), not excluded outright. The partial-
    tail worth-it check inside `crop_horizon_profit_per_day` already
    handles "worth it decision" precisely - this function only rules out
    the cases with literally nothing to score (can't even reach first_
    yield_day/first scheduled production), mirroring `decide._animal_
    has_time_to_mature`'s own "first production must fit" looseness,
    applied to crops for the first time here.
    """
    cd = CROPS[crop]
    if cd["ongoing"]:
        first_production_day = forecast_ongoing_schedule(crop, planted_day=current_day)[0]
        return first_production_day < season_length_days
    return current_day + cd["first_yield_day"] < season_length_days
