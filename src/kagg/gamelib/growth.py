"""One-time-crop watering/fertilizing yield forecast.

Mirrors kaggriculture.py's WATER/FERTILIZE handlers (the inline logic
inside `_apply_unit_action`, kaggriculture.py:431-482) as pure functions
with no environment/turn-loop dependency - see SPEC-gamelib.md "Scope" for
why this is explicitly limited to one-time crops (ongoing-crop scheduling
is forecast_ongoing_schedule(), a separate function).

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

from kagg.gamelib.constants import CROPS

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
