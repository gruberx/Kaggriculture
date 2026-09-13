"""T8.3q documentation deliverable: min/max net $/tile-day profitability
table for all 9 products, plus a days-remaining sweep - the user's own
request after pushing back on T8.3m's initial animal-cost estimate
("рассчитай минимальную и максимальную чистую доходность с одной клетки
для каждого товара"). Generated from real code, not hand-arithmetic, so
it can be regenerated whenever the underlying game constants or pricing
model change - see SPEC.md's "Economic analysis" section, which this
script's output feeds directly.

Not part of the committed test suite - a reference-generation script, run
on demand (mirrors tools/measure_t83m.py's own "one-off, re-run when
needed" convention).

Definitions, all as ceilings/floors around real game mechanics (never
assumed):
  MIN care  - bare survival: watered/fed every other day (the engine's
              own "no 2 consecutive misses" rule - verified directly,
              production itself never gates on same-day watering/feeding
              for the *base* unit, only the escape/weed check does), no
              fertilizer, no CARE, no fertilizer collection.
  MAX care  - full daily watering/feeding, fertilizer applied only where
              it actually clears its own cost (proven structurally never
              worth it for ongoing crops/MELON - fertilizer changes
              nothing about their max_yield cap - and never worth it for
              WHEAT/CARROT's cheap marginal units either), full daily
              CARE + COLLECT_FERTILIZER for animals. A labor-unconstrained
              ceiling (a dedicated worker per tile) - not a claim today's
              single farmer can capture it; T8.3q's own measured result
              (0/50 self-play for both animal levers) is the real,
              labor-realistic answer for defaults.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0  # noqa: E402
from kagg.gamelib.growth import forecast_one_time_yield, watering_bonus_window, forecast_ongoing_schedule  # noqa: E402
from kagg.gamelib.market import price  # noqa: E402
from kagg.policy.strategy import _animal_full_care_units  # noqa: E402

SEASON_LENGTH_DAYS = 30


def _walk(product: str, units: int, start: int = MARKET_I0) -> float:
    return sum(price(product, start + k) for k in range(units))


def crop_min_max(crop: str) -> tuple[float, float]:
    cd = CROPS[crop]
    seed = cd["seed"]
    if cd["ongoing"]:
        # Fertilizer structurally adds nothing: each scheduled tick's
        # yield is capped at max_yield regardless of the fertilizer
        # doubling (verified against kaggriculture.py's ongoing-crop
        # refresh) - min and max both reduce to the same full schedule.
        schedule = forecast_ongoing_schedule(crop, planted_day=0)
        tile_days = schedule[-1] + 1
        units = min(cd["max_yield"], len(schedule))
        rev = _walk(crop, units)
        net = (rev - seed) / tile_days
        return net, net
    window = list(watering_bonus_window(crop))
    max_yd = cd["max_yield_day"]
    tile_days = max_yd + 1
    every_other = {d for d in range(0, max_yd + 1) if d % 2 == 0}
    min_watered = every_other & set(window)
    min_units = forecast_one_time_yield(crop, min_watered, frozenset())
    full_units = forecast_one_time_yield(crop, set(window), frozenset())
    fert_units = forecast_one_time_yield(crop, set(window), {window[0]})
    fert_helps = fert_units > full_units
    max_units = fert_units if fert_helps else full_units
    fert_cost = _walk("FERTILIZER", 1) if fert_helps else 0
    min_net = (_walk(crop, min_units) - seed) / tile_days
    max_net = (_walk(crop, max_units) - seed - fert_cost) / tile_days
    return min_net, max_net


def animal_min_max(animal: str, days_remaining: int = SEASON_LENGTH_DAYS) -> tuple[float, float]:
    a = ANIMALS[animal]
    feed_price = price("WHEAT", MARKET_I0)
    # MIN: every-other-day feeding still gets full base production (the
    # engine's base yield_units increment never checks fed_today, only
    # the escape counter does) - half the feed cost, no fertilizer/CARE.
    from kagg.gamelib.growth import forecast_animal_schedule

    schedule = forecast_animal_schedule(animal, placed_day=0, horizon_days=days_remaining)
    min_units = len(schedule)
    min_feed_cost = (days_remaining // 2) * feed_price
    min_net = (_walk(a["product"], min_units) - a["cost"] - min_feed_cost) / max(1, days_remaining)
    # MAX: full CARE + daily fertilizer collection.
    max_units = _animal_full_care_units(animal, days_remaining)
    max_feed_cost = days_remaining * feed_price
    max_fert_rev = _walk("FERTILIZER", days_remaining)
    max_net = (
        _walk(a["product"], max_units) + max_fert_rev - a["cost"] - max_feed_cost
    ) / max(1, days_remaining)
    return min_net, max_net


def print_day0_table() -> None:
    print("| Product | Min net $/tile-day | Max net $/tile-day |")
    print("|---|---|---|")
    for crop in ("WHEAT", "CARROT", "MELON", "TOMATO", "STRAWBERRY"):
        lo, hi = crop_min_max(crop)
        print(f"| {crop} | {lo:.1f} | {hi:.1f} |")
    for animal in ("GOOSE", "COW", "SHEEP"):
        lo, hi = animal_min_max(animal)
        print(f"| {animal} | {lo:.1f} | {hi:.1f} |")


def print_days_remaining_sweep() -> None:
    sweep_points = (30, 25, 22, 20, 18, 15, 12, 10, 8, 6, 4, 2)
    print("days_remaining ->", list(sweep_points))
    for crop in ("WHEAT", "CARROT", "MELON", "TOMATO", "STRAWBERRY"):
        cd = CROPS[crop]
        row = []
        for dr in sweep_points:
            if cd["ongoing"]:
                schedule = [d for d in forecast_ongoing_schedule(crop, planted_day=0) if d < dr]
                if not schedule:
                    row.append("None")
                    continue
                units = min(cd["max_yield"], len(schedule))
                tile_days = min(schedule[-1] + 1, dr)
                net = (_walk(crop, units) - cd["seed"]) / tile_days
            else:
                if dr <= cd["max_yield_day"]:
                    row.append("None")
                    continue
                window = list(watering_bonus_window(crop))
                units = forecast_one_time_yield(crop, set(window), frozenset())
                tile_days = min(cd["max_yield_day"] + 1, dr)
                net = (_walk(crop, units) - cd["seed"]) / tile_days
            row.append(f"{net:.1f}")
        print(f"{crop:12s}", row)
    print()
    from kagg.gamelib.growth import forecast_animal_schedule

    for animal in ("GOOSE", "COW", "SHEEP"):
        a = ANIMALS[animal]
        feed_price = price("WHEAT", MARKET_I0)
        row_min, row_max = [], []
        for dr in sweep_points:
            schedule = forecast_animal_schedule(animal, placed_day=0, horizon_days=dr)
            if not schedule or schedule[0] >= dr:
                row_min.append("None")
                row_max.append("None")
                continue
            min_units = len(schedule)
            # MIN feeds every other day (half the cost) - the engine's
            # base production never checks fed_today, only the escape
            # counter does, so this is genuinely the cheapest safe rate,
            # matching animal_min_max's own convention above.
            min_net = (_walk(a["product"], min_units) - a["cost"] - (dr // 2) * feed_price) / dr
            row_min.append(f"{min_net:.1f}")
            max_units = _animal_full_care_units(animal, dr)
            max_fert = _walk("FERTILIZER", dr)
            max_net = (_walk(a["product"], max_units) + max_fert - a["cost"] - dr * feed_price) / dr
            row_max.append(f"{max_net:.1f}")
        print(f"{animal:12s} MIN", row_min)
        print(f"{animal:12s} MAX", row_max)


if __name__ == "__main__":
    print("=== Day-0 (30 days remaining) min/max net $/tile-day ===")
    print_day0_table()
    print()
    print("=== Net $/day by days_remaining (MIN feed cost for animals) ===")
    print_days_remaining_sweep()
