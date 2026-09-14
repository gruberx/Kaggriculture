"""Isolated unit-economics analysis: net profit per tile-day for a single
crop/animal, WITH labor cost explicitly priced in - not aggregate self-
play win rate (see the conversation this script was requested in: a
single COW's contribution to a full-game score is swamped by noise from
50-90 crop tiles' worth of market-price variance, so T8.17's near-50%
self-play win rates for animal_care_aware/animal_fertilizer_income_aware
can't cleanly say whether the *unit economics* themselves are good or
bad - this script isolates that question).

Pure computation, no kaggle_environments episodes - instant, not a
self-play measurement. Reuses the exact same revenue formulas the real
policy ranks by (kagg.policy.strategy.crop_revenue_per_tile_day/
animal_revenue_per_tile_day) and the exact same schedule/handler
semantics gamelib already mirrors from kaggriculture.py - verified
directly against the real HARVEST/FERTILIZE/FEED/CARE/COLLECT_FERTILIZER
handlers before writing the action-count model below (see this file's
own _crop_actions_per_tile_day/_animal_actions_per_tile_day docstrings).

**Key modeling decision, stated explicitly (flagged to the user as a
design choice, not a hidden assumption)**: labor is priced by
OPPORTUNITY COST, not by hire_cost. Verified directly in kaggriculture.py
(_hire_cost/_do_hire): a hire is a ONE-TIME fee that resets to fib(0)=$1
every new day (farm["hires_today"] resets daily) - spreading hires
across days makes additional labor *capacity* nearly free in dollar
terms (matches this project's own established finding, decide.py's
_DEFAULT_MAX_HIRES_PER_DAY comment: "hire #8 costs $21 - still
negligible"). So the real cost of spending a farmer-turn on animal care
isn't the wage to hire the hand - it's the revenue that same turn could
have earned tending the best available crop instead. Every "net profit"
number below is therefore *excess $ per action over the best crop's own
$/action* - the best crop's own row is defined to read exactly 0 by
construction (it IS the opportunity-cost baseline).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0  # noqa: E402
from kagg.gamelib.growth import forecast_animal_schedule, forecast_ongoing_schedule  # noqa: E402
from kagg.gamelib.market import price  # noqa: E402
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


def _crop_actions_per_tile_day(crop: str, days_remaining: int, use_fertilizer: bool) -> float:
    """Average farmer-actions/day needed to fully tend one tile of `crop`
    from planting through its last scheduled harvest, verified directly
    against kaggriculture.py's own handlers:

    - WATER: 1/day for the tile's entire life (tile_days) - not just
      during the yield-bonus window. The real WATER handler only grants a
      yield bonus inside the window, but watering is *also* the only way
      to keep consecutive_unwatered at 0 (2 consecutive misses converts
      the tile to a weed) - a fully-tended tile waters every day
      regardless, matching what the shipped policy actually does today
      (kagg.policy.tasks._plant_tile_tasks proposes WATER whenever
      `not watered_today`, every day, window or not).
    - HARVEST: verified in the real handler (kaggriculture.py:446-467) -
      one call empties *all* currently-banked yield_units at once. A
      one-time crop's tile is set back to None right after (its life
      ends there) - exactly 1 HARVEST ever. An ongoing crop's tile stays
      alive - harvesting *promptly* on every scheduled production tick
      (the same "labor-unconstrained, harvest promptly" assumption
      strategy.py's own _animal_full_care_units docstring already states
      for animals) means 1 HARVEST per scheduled tick, i.e. the same
      count crop_revenue_per_tile_day's own total_yield already uses.
    - FERTILIZE (optional): verified in the real handler - one
      application sets `fertilized_until_day = max(existing, day+2)`,
      i.e. covers today plus the next two days (3 days). Continuous
      coverage needs one application every 3 days: ceil(tile_days / 3).
    - PLANT: 1, one-time, at the start.
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
    """Average farmer-actions/day for one fully-tended animal over
    `days_remaining`, verified directly against kaggriculture.py's own
    handlers:

    - FEED: 1/day for the entire horizon (fed_today is a daily boolean,
      and an unfed animal risks escape - a fully-tended animal feeds
      every day).
    - CARE (optional): 1/day, same daily-boolean shape as FEED - only
      counted when `care_aware` (matches animal_revenue_per_tile_day's
      own `care_aware` flag, which only prices the yield bonus this
      produces).
    - COLLECT_FERTILIZER (optional): verified directly -
      `fertilizer_available` is set True at the end of *every* day the
      animal survives, fed or not (kaggriculture.py's _daily_refresh_
      animals) - realizing that income needs 1 COLLECT_FERTILIZER/day,
      only counted when `fertilizer_income_aware` (matches
      animal_revenue_per_tile_day's own flag, which only prices this
      income stream when set).
    - HARVEST: one call per scheduled production tick (forecast_animal_
      schedule's own count) - same "harvest promptly" assumption as
      crops above, matching _animal_full_care_units's own stated
      assumption.
    - BUILD_*/PICKUP/PLACE: 3, one-time, at the start (structure, then
      pick up the bought animal from the shed, then place it - see
      kagg.policy.tasks._new_investment_tasks's own docstring for why
      these are 3 separate steps).
    """
    schedule = forecast_animal_schedule(animal, placed_day=0, horizon_days=days_remaining)
    feed_actions = days_remaining
    care_actions = days_remaining if care_aware else 0
    collect_fertilizer_actions = days_remaining if fertilizer_income_aware else 0
    harvest_actions = len(schedule)
    setup_actions = 3
    total_actions = feed_actions + care_actions + collect_fertilizer_actions + harvest_actions + setup_actions
    return total_actions / days_remaining


def _crop_net_revenue_per_tile_day(crop: str, days_remaining: int, use_fertilizer: bool) -> float:
    """Same $/tile-day crop_revenue_per_tile_day already computes
    (net_of_seed_cost=True, market at MARKET_I0, no self-impact/
    consumption offset - isolated single-tile economics, matching this
    script's own "one square vs one square" framing), plus the FERTILIZER
    unit's own purchase cost when use_fertilizer is on (bought, not
    collected, for this isolated comparison - fertilizer's own revenue
    when *sourced from an animal* is a separate, cross-product question
    this script doesn't attempt).
    """
    revenue = crop_revenue_per_tile_day(
        crop, sell_at_inventory=MARKET_I0, net_of_seed_cost=True, days_remaining=days_remaining
    )
    if use_fertilizer:
        _, tile_days = _crop_yield_and_tile_days(crop, days_remaining)
        n_applications = math.ceil(tile_days / 3)
        fertilizer_cost = n_applications * price("FERTILIZER", MARKET_I0)
        revenue -= fertilizer_cost / tile_days
    return revenue


def _animal_net_revenue_per_tile_day(
    animal: str, days_remaining: int, care_aware: bool, fertilizer_income_aware: bool
) -> float:
    feed_price = price("WHEAT", MARKET_I0)
    return animal_revenue_per_tile_day(
        animal,
        sell_at_inventory=MARKET_I0,
        days_remaining=days_remaining,
        net_of_cost=True,
        feed_price=feed_price,
        fertilizer_income_aware=fertilizer_income_aware,
        fertilizer_sell_at_inventory=MARKET_I0,
        care_aware=care_aware,
    )


print("=== Part 1: isolated single-tile net profit per action (N=1, market at MARKET_I0, no self-impact) ===")
print(f"(labor priced by opportunity cost - see this script's own module docstring for why, not hire_cost)")
print(f"season horizon: {SEASON_LENGTH_DAYS} days, {ACTIONS_PER_HAND_PER_DAY:.1f} actions/hand/day\n")

crop_rows = []
for crop in CROPS:
    net_per_tile_day = _crop_net_revenue_per_tile_day(crop, SEASON_LENGTH_DAYS, use_fertilizer=False)
    actions_per_tile_day = _crop_actions_per_tile_day(crop, SEASON_LENGTH_DAYS, use_fertilizer=False)
    net_per_action = net_per_tile_day / actions_per_tile_day
    crop_rows.append((crop, net_per_tile_day, actions_per_tile_day, net_per_action))

best_crop = max(crop_rows, key=lambda r: r[3])
opportunity_cost_per_action = best_crop[3]
print(f"opportunity cost baseline (best crop's own $/action): {best_crop[0]} @ ${opportunity_cost_per_action:.2f}/action\n")

print(f"{'option':<24} {'$/tile-day':>12} {'actions/tile-day':>17} {'$/action':>10} {'excess $/action':>16}")
for crop, net_per_tile_day, actions_per_tile_day, net_per_action in sorted(
    crop_rows, key=lambda r: -r[3]
):
    excess = net_per_action - opportunity_cost_per_action
    print(f"{crop:<24} {net_per_tile_day:>12.2f} {actions_per_tile_day:>17.2f} {net_per_action:>10.2f} {excess:>16.2f}")

print()
animal_variants = [
    ("bare (feed only)", False, False),
    ("+ care_aware", True, False),
    ("+ care_aware + fertilizer_income_aware", True, True),
]
for animal in ANIMALS:
    for label, care_aware, fertilizer_income_aware in animal_variants:
        net_per_tile_day = _animal_net_revenue_per_tile_day(
            animal, SEASON_LENGTH_DAYS, care_aware, fertilizer_income_aware
        )
        actions_per_tile_day = _animal_actions_per_tile_day(
            animal, SEASON_LENGTH_DAYS, care_aware, fertilizer_income_aware
        )
        net_per_action = net_per_tile_day / actions_per_tile_day
        excess = net_per_action - opportunity_cost_per_action
        name = f"{animal} ({label})"
        print(f"{name:<40} {net_per_tile_day:>12.2f} {actions_per_tile_day:>17.2f} {net_per_action:>10.2f} {excess:>16.2f}")

print(
    "\nReading this table: 'excess $/action' > 0 means this option earns more per farmer-turn than "
    "the best crop does - i.e. it's genuinely worth diverting scarce labor to, independent of tile "
    "count. <= 0 means every turn spent on it earns less than the same turn would tending more of "
    "the best crop instead - the SPEC.md $/tile-day ceiling never accounted for this."
)


def _animal_net_revenue_per_tile_day_at_n(
    animal: str, n: int, days_remaining: int, care_aware: bool, fertilizer_income_aware: bool
) -> float:
    """Same per-animal $/tile-day as _animal_net_revenue_per_tile_day, but
    for `n` animals of the same type placed simultaneously (day 0),
    extending crop_revenue_per_tile_day's own self-impact walk (verified
    against kaggriculture.py's per-unit lockstep SELL quoting) to
    animals - animal_revenue_per_tile_day itself deliberately doesn't do
    this (its own docstring: "no natural total_yield to walk across
    without picking an arbitrary horizon" - true for one animal, but n
    animals sharing the same schedule *do* have a natural bound: n *
    units_per_animal, all landing on the market across the same season).
    Each animal's own revenue is that shared walk's total, split n ways
    (they're interchangeable - same schedule, same product) - so this
    reduces to plain animal_revenue_per_tile_day exactly when n=1.
    """
    a = ANIMALS[animal]
    if care_aware:
        units_per_animal = _animal_full_care_units(animal, days_remaining)
    else:
        units_per_animal = len(forecast_animal_schedule(animal, placed_day=0, horizon_days=days_remaining))
    total_units = n * units_per_animal
    total_revenue = sum(price(a["product"], MARKET_I0 + k) for k in range(total_units))
    if fertilizer_income_aware:
        total_fert_units = n * days_remaining
        total_revenue += sum(price("FERTILIZER", MARKET_I0 + k) for k in range(total_fert_units))
    per_animal_revenue = total_revenue / n
    per_animal_revenue -= a["cost"]
    per_animal_revenue -= price("WHEAT", MARKET_I0) * days_remaining
    return per_animal_revenue / days_remaining


print("\n=== Part 2: scaling N animals of the same type (market self-impact + labor-capacity check) ===")
print("(full care + fertilizer collection - the variant closest to parity in Part 1)\n")

N_VALUES = [1, 2, 3, 5, 8, 12, 20, 30]
for animal in ANIMALS:
    print(f"--- {animal} (+ care_aware + fertilizer_income_aware) ---")
    actions_per_tile_day = _animal_actions_per_tile_day(
        animal, SEASON_LENGTH_DAYS, care_aware=True, fertilizer_income_aware=True
    )
    print(
        f"{'N':>4} {'$/tile-day (per animal)':>26} {'$/action':>10} {'excess $/action':>16} "
        f"{'actions/day (all N)':>20} {'extra hands needed':>19}"
    )
    for n in N_VALUES:
        net_per_tile_day = _animal_net_revenue_per_tile_day_at_n(
            animal, n, SEASON_LENGTH_DAYS, care_aware=True, fertilizer_income_aware=True
        )
        net_per_action = net_per_tile_day / actions_per_tile_day
        excess = net_per_action - opportunity_cost_per_action
        # actions_per_tile_day is already an average per animal per day
        # (its own denominator is days_remaining, matching one tile-day) -
        # n animals need n times that many actions/day, total.
        total_actions_per_day = n * actions_per_tile_day
        hands_needed = max(0, math.ceil(total_actions_per_day / ACTIONS_PER_HAND_PER_DAY) - 1)
        print(
            f"{n:>4} {net_per_tile_day:>26.2f} {net_per_action:>10.2f} {excess:>16.2f} "
            f"{total_actions_per_day:>20.1f} {hands_needed:>19}"
        )
    print()

print(
    "Reading this table: 'excess $/action' tracks pure market self-impact as N grows (same formula "
    "as Part 1, now walked across N animals' combined lifetime output) - labor capacity (extra hands "
    "needed) is shown separately since, per this script's own module docstring, hiring itself costs "
    "almost nothing in dollars (spread across days) - the real question is whether that many hands "
    "are *practically* fieldable (max_hires_per_day, board space for N structures) before the market "
    "crash from N units flooding the same product makes the per-action economics worse than crops."
)
