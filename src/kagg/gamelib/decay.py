"""Plant decay after max lifespan - mirrors kaggriculture.py's
_decay_plants().

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations


def decay_step(max_lifespan_step: int, step: int) -> bool:
    """True if a decay tick (yield_units -= 1) fires at this turn `step`.

    Mirrors _decay_plants (kaggriculture.py:752): `max_lifespan_step < 0`
    means the tile never decays (an ongoing crop that hasn't yet hit its
    cumulative production cap - see forecast_ongoing_schedule). Once
    `step >= max_lifespan_step`, decay fires every *other* turn starting
    exactly at `max_lifespan_step` itself - `step` here is a turn index
    across the whole game, not a day, matching `max_lifespan_step`'s own
    units (set as `(day + 1) * turns_per_day` for one-time crops, `_new_plant`).
    """
    if max_lifespan_step < 0 or step < max_lifespan_step:
        return False
    return (step - max_lifespan_step) % 2 == 0
