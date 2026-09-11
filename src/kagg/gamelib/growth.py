"""One-time-crop watering/fertilizing yield forecast.

Mirrors kaggriculture.py's WATER/FERTILIZE handlers (the inline logic
inside `_apply_unit_action`, kaggriculture.py:431-482) as pure functions
with no environment/turn-loop dependency - see SPEC-gamelib.md "Scope" for
why this is explicitly limited to one-time crops (ongoing-crop scheduling
is forecast_ongoing_schedule(), a separate function).

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

from kagg.gamelib.constants import ANIMALS, CROPS

# A freshly planted one-time crop starts with yield_units=1 - mirrors
# kaggriculture.py's _new_plant(): "yield_units": 0 if cd["ongoing"] else 1.
_ONE_TIME_STARTING_YIELD = 1


def watering_bonus_window(crop: str) -> range:
    """Inclusive range of age-in-days (day - planted_day) during which
    watering a one-time crop adds yield. Mirrors the WATER handler's
    `window_start = (max_yield_day + 1) // 2` check (kaggriculture.py:440)
    - note this is `range(window_start, max_yield_day + 1)`, i.e. inclusive
    of `max_yield_day` itself, not "half the growth time" loosely rounded.
    """
    max_yield_day = CROPS[crop]["max_yield_day"]
    window_start = (max_yield_day + 1) // 2
    return range(window_start, max_yield_day + 1)


def _is_fertilizer_active(day: int, fertilized_days) -> bool:
    """True if any FERTILIZE application in `fertilized_days` is still
    active on `day`. Mirrors `fertilized_until_day = max(existing, day+2)`
    (kaggriculture.py:481): each application covers that day plus the
    following two - 3 days inclusive - and applications can overlap/extend
    each other, so this checks all of them rather than just the latest."""
    return any(f <= day <= f + 2 for f in fertilized_days)


def forecast_one_time_yield(
    crop: str, watered_days, fertilized_days=frozenset()
) -> int:
    """Final yield_units for a one-time crop given the set of ages (in
    days since planting) on which it was watered, and the set of ages on
    which FERTILIZE was *applied* (not the days the bonus is merely
    active - each application's bonus persists for that day plus the
    following two, per `_is_fertilizer_active`).

    Mirrors the WATER handler: each watering inside `watering_bonus_window`
    adds 1 (or 2 if fertilizer is active that day), clamped at the crop's
    max_yield. Order doesn't matter and duplicates are harmless -
    `watered_days` is treated as a set, matching the real handler where a
    second same-day WATER is a no-op and only the day (not order-within-
    day) matters.
    """
    cd = CROPS[crop]
    window = watering_bonus_window(crop)
    fertilized_days = set(fertilized_days)
    yield_units = _ONE_TIME_STARTING_YIELD
    for age in sorted(set(watered_days)):
        if age in window:
            bonus = 2 if _is_fertilizer_active(age, fertilized_days) else 1
            yield_units = min(cd["max_yield"], yield_units + bonus)
    return yield_units


def forecast_ongoing_schedule(crop: str, planted_day: int) -> list[int]:
    """Absolute days on which an ongoing crop (TOMATO/STRAWBERRY) produces
    its scheduled yield, regardless of watering/fertilizing that day.

    Mirrors _daily_refresh_plants' scheduling check (kaggriculture.py:769):
    a production tick fires at `next_day = planted_day + first_yield_day +
    k * interval` for k = 0, 1, ..., independent of whether the tile was
    watered that day - watering only decides whether the tick is worth 1
    (unfertilized) or 2 (fertilized that day), not whether it fires at all.
    That means this function takes no watering/fertilizing input at all;
    forecast_one_time_yield's fertilizer bonus is the analogous concern for
    one-time crops, but there is no `forecast_ongoing_yield` here - a
    caller reasoning about actual accumulated yield needs to fold in its
    own watering/fertilizing plan against this schedule itself.

    Finite by construction (`SPEC-gamelib.md` "Key subtleties" - ongoing
    crops are capped at `max_yield` scheduled productions, not indefinite):
    exactly `max_yield` entries, matching the documented examples (tomato:
    ages 8-11; strawberry: ages 10, 12, 14, 16).
    """
    cd = CROPS[crop]
    if not cd["ongoing"]:
        raise ValueError(f"{crop} is not an ongoing crop; use forecast_one_time_yield instead")
    interval = cd["interval"]
    first = cd["first_yield_day"]
    return [planted_day + first + k * interval for k in range(cd["max_yield"])]


def forecast_animal_schedule(animal: str, placed_day: int, horizon_days: int = 30) -> list[int]:
    """Absolute days, up to `horizon_days` (an absolute day number, default
    30 - the season length at the default `episodeSteps`/`turnsPerDay`
    configuration), on which a fed animal produces its base yield.

    Mirrors _daily_refresh_animals' scheduling check (kaggriculture.py:805):
    same `next_day = placed_day + first_yield_day + k * interval` form as
    ongoing crops, but - unlike ongoing crops - animals have no `max_yield`
    cap on the *number* of productions (SPEC.md's economic analysis: "no
    fixed occupancy to divide by"; `max_held` caps unharvested product on
    the tile, not lifetime output). `horizon_days` bounds the returned list
    to something finite and useful instead of requiring the genuinely
    unbounded schedule an unfed `while True` would imply.
    """
    a = ANIMALS[animal]
    interval = a["interval"]
    first = a["first_yield_day"]
    days = []
    k = 0
    while True:
        day = placed_day + first + k * interval
        if day > horizon_days:
            break
        days.append(day)
        k += 1
    return days
