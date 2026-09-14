"""Isolated unit-economics analysis: net profit for a single crop/animal
tile, with labor and market-depth costs made explicit - not aggregate
self-play win rate (a single COW's contribution to a full-game score is
swamped by noise from 50-90 crop tiles' worth of market variance, so
T8.17's near-50% self-play win rates for animal_care_aware/animal_
fertilizer_income_aware can't cleanly say whether the *unit economics*
themselves are good or bad - this script isolates that question).

Pure computation, no kaggle_environments episodes - instant, not a
self-play measurement. Reuses the exact same revenue formulas the real
policy ranks by (kagg.policy.strategy.crop_revenue_per_tile_day/
animal_revenue_per_tile_day).

**Revision history / two corrections from the user's own review of the
first version of this script, both real, both changed the model:**

1. Labor was originally priced by "opportunity cost of a farmer-turn"
   (dividing profit by action count and comparing to the best crop's own
   $/action) - inconsistent with this script's own finding that hiring
   is nearly free (see below): if actions cost nothing to acquire more
   of, dividing by action count to price them makes no sense. Fixed: a
   single tile/animal (N=1) never needs hiring at all (1-4 actions/day
   is trivial against the farmer's own ~12/day budget) - Part 1 below is
   therefore just plain net $/tile-day, no labor term. Only once N grows
   enough to actually require MORE hands than already exist (Part 2) is
   there a real hiring cost to subtract - and it's subtracted as an
   actual dollar amount (kagg.gamelib.labor.hire_cost, spread one hire
   per day - the cheapest real strategy, since a hire's cost resets to
   fib(0)=$1 every new day, verified directly in kaggriculture.py's
   _do_hire/_hire_cost), not an opportunity-cost proxy.

2. The original Part 2 N-scaling walked every product's price down from
   a flat MARKET_I0 with zero consumption offset - unfair to WOOL/MILK/
   EGG, which get *real* demand support from town shops as they unlock
   over the game (kagg.gamelib.market.expected_daily_consumption),
   support MELON structurally never gets: verified directly against
   SHOPS (kagg.gamelib.constants) - MELON appears in zero shop entries,
   while every other sellable product appears in at least one. Part 2
   below now shows two scenarios per product ("no shops unlocked" vs
   "one relevant shop unlocked", the latter clearly labeled as
   illustrative, not a claim about real unlock timing) to make this
   structural asymmetry visible with real numbers instead of asserting
   it qualitatively.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0, SHOPS  # noqa: E402
from kagg.gamelib.growth import forecast_animal_schedule  # noqa: E402
from kagg.gamelib.labor import hire_cost  # noqa: E402
from kagg.gamelib.market import expected_daily_consumption, price  # noqa: E402
from kagg.policy.strategy import (  # noqa: E402
    _animal_full_care_units,
    _crop_yield_and_tile_days,
    animal_revenue_per_tile_day,
    crop_revenue_per_tile_day,
)

SEASON_LENGTH_DAYS = 30
TURNS_PER_DAY = 24
TURNS_PER_TASK_ESTIMATE = 2.0  # matches kagg.policy.strategy._DEFAULT_TURNS_PER_TASK_ESTIMATE
ACTIONS_PER_HAND_PER_DAY = TURNS_PER_DAY / TURNS_PER_TASK_ESTIMATE  # ~12
HIRE_COST_PER_HAND = hire_cost(0)  # cheapest real hire: the 1st hire of its own day, $1 at defaults


def _crop_actions_per_tile_day(crop: str, days_remaining: int, use_fertilizer: bool) -> float:
    """Average farmer-actions/day for one fully-tended tile of `crop`,
    verified directly against kaggriculture.py's own handlers - see this
    module's own history for why this no longer prices labor by
    opportunity cost, only feeds Part 2's real hands-needed count.

    WATER 1/day for the tile's whole life (anti-weed, not just the yield
    bonus window); HARVEST once for a one-time crop (one call empties all
    banked yield_units and clears the tile) or once per scheduled
    production tick for an ongoing crop (harvested promptly, matching
    _animal_full_care_units's own "labor-unconstrained" assumption);
    FERTILIZE (optional) once every 3 days (fertilized_until_day covers
    today + 2 more); PLANT once at the start.
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
    """Average farmer-actions/day for one fully-tended animal, verified
    directly against kaggriculture.py's own handlers. FEED 1/day (an
    unfed animal risks escape); CARE (optional) 1/day; COLLECT_FERTILIZER
    (optional) 1/day - fertilizer_available is set True at the end of
    *every* day the animal survives, fed or not (_daily_refresh_animals);
    HARVEST once per scheduled production tick (forecast_animal_
    schedule's own count, harvested promptly); BUILD_*/PICKUP/PLACE: 3,
    one-time setup.
    """
    schedule = forecast_animal_schedule(animal, placed_day=0, horizon_days=days_remaining)
    feed_actions = days_remaining
    care_actions = days_remaining if care_aware else 0
    collect_fertilizer_actions = days_remaining if fertilizer_income_aware else 0
    harvest_actions = len(schedule)
    setup_actions = 3
    total_actions = feed_actions + care_actions + collect_fertilizer_actions + harvest_actions + setup_actions
    return total_actions / days_remaining


def _hands_needed(total_actions_per_day: float) -> int:
    """Extra hands beyond the always-present farmer needed to cover
    `total_actions_per_day` - 0 whenever the farmer's own ~12/day budget
    already suffices (true for any single tile/animal - Part 1 never
    needs this)."""
    return max(0, math.ceil(total_actions_per_day / ACTIONS_PER_HAND_PER_DAY) - 1)


print("=== Part 0: which products get town-shop demand support - MELON is in zero of them ===")
print("(verified directly against kagg.gamelib.constants.SHOPS - not asserted, printed from the real table)\n")
for product in ["MELON", "WOOL", "MILK", "EGG", "STRAWBERRY", "TOMATO", "CARROT", "WHEAT"]:
    shops = [s for s, items in SHOPS.items() if product in items]
    print(f"  {product:<12} shops that consume it: {shops if shops else '(none - town-center baseline only, forever)'}")

print("\n=== Part 1: isolated single-tile net profit (N=1, market at MARKET_I0) ===")
print(
    "No labor term here - even a fully-tended single tile/animal (1-4 actions/day) is trivially "
    f"covered by the farmer's own ~{ACTIONS_PER_HAND_PER_DAY:.0f} actions/day, so hiring is not "
    "triggered at N=1 regardless of choice. See this script's own module docstring for why labor "
    "isn't priced as a per-action opportunity cost any more. Town-center consumption (every product "
    "except FERTILIZER, 1 unit/day, always on - kagg.gamelib.constants.TOWN_CENTER_PRODUCTS) IS "
    "applied here, for consistency with Part 2's own 'no-shop' baseline below - a real, always-on "
    "effect, not specific to shops.\n"
)

print(f"{'option':<40} {'$/tile-day (net)':>18}")
crop_results = {}
for crop in CROPS:
    consumption = expected_daily_consumption(crop, unlocked_shops=[]) * SEASON_LENGTH_DAYS
    net = crop_revenue_per_tile_day(
        crop, sell_at_inventory=MARKET_I0, expected_consumption=consumption,
        net_of_seed_cost=True, days_remaining=SEASON_LENGTH_DAYS,
    )
    crop_results[crop] = net
for crop, net in sorted(crop_results.items(), key=lambda kv: -kv[1]):
    print(f"{crop:<40} {net:>18.2f}")

print()
feed_price = price("WHEAT", MARKET_I0)
animal_variants = [
    ("bare (feed only)", False, False),
    ("+ care_aware", True, False),
    ("+ care_aware + fertilizer_income_aware", True, True),
]
for animal in ANIMALS:
    a = ANIMALS[animal]
    consumption = expected_daily_consumption(a["product"], unlocked_shops=[]) * SEASON_LENGTH_DAYS
    for label, care_aware, fertilizer_income_aware in animal_variants:
        net = animal_revenue_per_tile_day(
            animal,
            sell_at_inventory=MARKET_I0,
            expected_consumption=consumption,
            days_remaining=SEASON_LENGTH_DAYS,
            net_of_cost=True,
            feed_price=feed_price,
            fertilizer_income_aware=fertilizer_income_aware,
            fertilizer_sell_at_inventory=MARKET_I0,
            care_aware=care_aware,
        )
        print(f"{animal + ' (' + label + ')':<40} {net:>18.2f}")

print(
    "\nAt N=1, animals (fully cared for) clearly beat every crop on raw $/tile-day - matches SPEC.md's "
    "own table. The real question Part 2 asks: does this survive once N grows enough to actually need "
    "more labor and start saturating the animal product's own market."
)


def _walk_price(product: str, start_inventory: int, n_units: int) -> float:
    return sum(price(product, start_inventory + k) for k in range(n_units))


def _unlocked_shops_for_scenario(product: str, scenario: str) -> list[str]:
    """`scenario`:
    - "none": no shops unlocked - town-center baseline only.
    - "one": exactly one relevant shop unlocked (the first found in
      SHOPS that lists this product) - a conservative illustrative case.
    - "expected_end_game": verified directly in kaggriculture.py
      (_advance_town, line ~890-891): shops unlock every
      townShopUnlockInterval=3 days, up to MAX_SHOP_INSTANCES=8 total,
      each draw `rng.choice(sorted(SHOPS))` - a UNIFORM, independent
      random pick among all 8 shop *types* (with replacement), not
      weighted by product. By day 24 of a 30-day season (8 * 3), a real
      game typically has all 8 slots filled. E[# instances of shop type
      X among 8 uniform draws] = 8 * (1/8) = 1 for every type X,
      regardless of correlation with other draws (linearity of
      expectation) - so "one instance of every shop type that lists this
      product" is the real expected end-game count, not a guess: MELON
      (0 relevant types) -> 0 forever; WOOL (1 type, YARN_STORE) -> ~1;
      EGG (2 types) -> ~2; MILK (3 types: PIZZA_SHOP/ICE_CREAM_SHOP/
      SMOOTHIE_SHOP) -> ~3 - exactly the asymmetry the user's own
      real-game observation pointed at.
    Applied as one flat offset to the starting inventory of the
    cumulative walk below, the same simplification crop_revenue_per_
    tile_day/animal_revenue_per_tile_day already use for their own
    `expected_consumption` parameter - and, for "expected_end_game", also
    optimistic in the shop's favor: shops unlock progressively from day 3
    onward, not all present from day 0, so this overstates early-game
    consumption relative to a real game.
    """
    if scenario == "none":
        return []
    if scenario == "one":
        for shop, items in SHOPS.items():
            if product in items:
                return [shop]
        return []
    if scenario == "expected_end_game":
        return [shop for shop, items in SHOPS.items() if product in items]
    raise ValueError(scenario)


def _consumption_offset(product: str, days_remaining: int, scenario: str) -> float:
    """Total units the town removes from `product`'s market over
    `days_remaining`, under `scenario` (see _unlocked_shops_for_scenario).
    For a product in zero shops (MELON), every scenario is identical by
    construction - that IS the point being measured.
    """
    rate = expected_daily_consumption(product, _unlocked_shops_for_scenario(product, scenario))
    return rate * days_remaining


def _animal_net_total_revenue_at_n(
    animal: str,
    n: int,
    days_remaining: int,
    care_aware: bool,
    fertilizer_income_aware: bool,
    scenario: str,
    opponent_multiplier: int = 1,
) -> float:
    """Total revenue (not per-tile-day) for `n` animals of the same type
    placed simultaneously (day 0), extending crop_revenue_per_tile_day's
    own self-impact walk to animals - animal_revenue_per_tile_day itself
    deliberately doesn't do this for one animal (no natural bound to walk
    to), but n animals sharing the same schedule do: n * units_per_animal
    total, all landing on the market across the same season. Purchase
    and feed costs are real per-animal costs, charged n times (not
    shared). `opponent_multiplier` (2 = "contested": an opponent
    independently runs the same N, doubling total units landing on the
    *shared* market - the user's own explicit caveat): walks the FULL
    shared total (our units + theirs) as one run, then takes our equal
    (symmetric) share of that shared revenue - neither side has any real
    information about landing "first," so splitting the joint walk
    evenly is the fair convention, not pricing our own share alone at
    the original (too generous) starting point or after the opponent's
    (arbitrary worst case). Reduces to the plain single-side walk exactly
    when opponent_multiplier=1."""
    a = ANIMALS[animal]
    if care_aware:
        units_per_animal = _animal_full_care_units(animal, days_remaining)
    else:
        units_per_animal = len(forecast_animal_schedule(animal, placed_day=0, horizon_days=days_remaining))
    our_units = n * units_per_animal
    total_units = our_units * opponent_multiplier
    consumption = _consumption_offset(a["product"], days_remaining, scenario)
    start = MARKET_I0 - consumption
    total_shared_revenue = _walk_price(a["product"], int(round(start)), total_units)
    total_revenue = total_shared_revenue / opponent_multiplier
    if fertilizer_income_aware:
        fert_consumption = _consumption_offset("FERTILIZER", days_remaining, scenario="none")  # never in SHOPS
        fert_start = MARKET_I0 - fert_consumption
        total_revenue += _walk_price("FERTILIZER", int(round(fert_start)), n * days_remaining)
    total_revenue -= n * a["cost"]
    total_revenue -= n * price("WHEAT", MARKET_I0) * days_remaining
    return total_revenue


def _crop_net_total_revenue_at_n(
    crop: str, n: int, days_remaining: int, scenario: str, opponent_multiplier: int = 1
) -> float:
    """Same shape as _animal_net_total_revenue_at_n (including the same
    symmetric-split contested-market convention), for n tiles of the
    same crop."""
    total_yield, tile_days = _crop_yield_and_tile_days(crop, days_remaining)
    our_units = n * total_yield
    total_units = our_units * opponent_multiplier
    consumption = _consumption_offset(crop, days_remaining, scenario)
    start = MARKET_I0 - consumption
    total_shared_revenue = _walk_price(crop, int(round(start)), total_units)
    total_revenue = total_shared_revenue / opponent_multiplier
    total_revenue -= n * CROPS[crop]["seed"]
    return total_revenue


print("\n=== Part 2: scaling N units of the same product (real hiring cost + shop-consumption scenarios) ===")
print(f"(hiring cost: ${HIRE_COST_PER_HAND}/extra hand, cheapest real strategy - one hire per day)")
print(
    "Three shop scenarios per product: 'none' (worst case), 'one' (conservative), 'end-game "
    "expected' (verified: 8 shop slots, each a uniform random pick among 8 types, unlock every 3 "
    "days - by day 24 of 30 a real game typically has all 8 filled, so E[instances of a type] = 1 "
    "each - MILK's 3 relevant types -> ~3, WOOL's 1 -> ~1, EGG's 2 -> ~2, MELON's 0 -> always 0).\n"
)

N_VALUES = [1, 2, 3, 5, 8, 12, 20, 30]
SCENARIOS = ["none", "one", "expected_end_game"]

print("--- MELON (all three shop-scenario columns are identical - zero relevant shops, by construction) ---")
actions_per_tile_day_melon = _crop_actions_per_tile_day("MELON", SEASON_LENGTH_DAYS, use_fertilizer=False)
_, melon_tile_days = _crop_yield_and_tile_days("MELON", SEASON_LENGTH_DAYS)
print(f"{'N':>4} {'none':>10} {'one':>10} {'end-game exp.':>14} {'extra hands':>12} {'hire cost':>10}")
for n in N_VALUES:
    total_actions_per_day = n * actions_per_tile_day_melon
    hands = _hands_needed(total_actions_per_day)
    hire_total = hands * HIRE_COST_PER_HAND
    vals = [
        (_crop_net_total_revenue_at_n("MELON", n, SEASON_LENGTH_DAYS, scenario) - hire_total)
        / n
        / melon_tile_days
        for scenario in SCENARIOS
    ]
    print(f"{n:>4} {vals[0]:>10.2f} {vals[1]:>10.2f} {vals[2]:>14.2f} {hands:>12} ${hire_total:>9}")

print("--- MELON, CONTESTED (opponent also plants the same N) ---")
print(f"{'N':>4} {'none':>10} {'one':>10} {'end-game exp.':>14}")
for n in N_VALUES:
    vals = [
        _crop_net_total_revenue_at_n("MELON", n, SEASON_LENGTH_DAYS, scenario, opponent_multiplier=2)
        / n
        / melon_tile_days
        for scenario in SCENARIOS
    ]
    print(f"{n:>4} {vals[0]:>10.2f} {vals[1]:>10.2f} {vals[2]:>14.2f}")

print()
for animal in ANIMALS:
    print(f"--- {animal} (+ care_aware + fertilizer_income_aware), solo ---")
    actions_per_tile_day = _animal_actions_per_tile_day(
        animal, SEASON_LENGTH_DAYS, care_aware=True, fertilizer_income_aware=True
    )
    print(f"{'N':>4} {'none':>10} {'one':>10} {'end-game exp.':>14} {'extra hands':>12} {'hire cost':>10}")
    for n in N_VALUES:
        total_actions_per_day = n * actions_per_tile_day
        hands = _hands_needed(total_actions_per_day)
        hire_total = hands * HIRE_COST_PER_HAND
        vals = [
            (
                _animal_net_total_revenue_at_n(
                    animal, n, SEASON_LENGTH_DAYS, care_aware=True, fertilizer_income_aware=True, scenario=scenario
                )
                - hire_total
            )
            / n
            / SEASON_LENGTH_DAYS
            for scenario in SCENARIOS
        ]
        print(f"{n:>4} {vals[0]:>10.2f} {vals[1]:>10.2f} {vals[2]:>14.2f} {hands:>12} ${hire_total:>9}")

    print(f"--- {animal} (+ care_aware + fertilizer_income_aware), CONTESTED (opponent runs the same N) ---")
    print(f"{'N':>4} {'none':>10} {'one':>10} {'end-game exp.':>14}")
    for n in N_VALUES:
        vals = [
            _animal_net_total_revenue_at_n(
                animal, n, SEASON_LENGTH_DAYS, care_aware=True, fertilizer_income_aware=True,
                scenario=scenario, opponent_multiplier=2,
            )
            / n
            / SEASON_LENGTH_DAYS
            for scenario in SCENARIOS
        ]
        print(f"{n:>4} {vals[0]:>10.2f} {vals[1]:>10.2f} {vals[2]:>14.2f}")
    print()

print(
    "Reading this table: hiring cost stays negligible at every N tested (confirms hiring itself was "
    "never the real constraint). Comparing 'none' to raw per-unit price at the same cumulative count "
    "(see this conversation's own price() trace) shows WOOL/MILK's own market is actually SHALLOWER "
    "than MELON's (crashes to the price floor at fewer units - MELON's own T=300 vs WOOL's T=105/"
    "MILK's T=122) - the resilience seen in real games is mostly (a) shop consumption credit (the "
    "'end-game expected' column) and (b) animals simply producing far fewer total units per season "
    "than a crop monoculture can (1 unit per 2-3 days per animal vs up to 6 per crop tile), not a "
    "deeper market. The CONTESTED rows show the user's own explicit caveat directly: two players both "
    "running N animals halves each one's own share of a market that was already shallow, degrading "
    "fastest for products with few or no shops (WOOL/MELON) and staying most resilient where the "
    "shop credit is largest (MILK)."
)
