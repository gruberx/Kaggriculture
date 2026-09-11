"""Property test for kagg.gamelib.growth's one-time-crop forecast functions
- see SPEC-gamelib.md.

Drives the real interpreter's _apply_unit_action against a scratch farm for
a randomized watering/fertilizing schedule and compares the resulting
yield_units to the forecast for the same schedule - the oracle SPEC-
gamelib.md itself prescribes ("plant a crop in a scratch _new_farm, apply
WATER/FERTILIZE/HARVEST via _apply_unit_action for a randomized watering
schedule, and compare final yield_units to the forecast").
"""

import random

from kaggle_environments.envs.kaggriculture import kaggriculture as real

from kagg.gamelib.constants import CROPS
from kagg.gamelib.growth import forecast_one_time_yield, watering_bonus_window

_BOARD_SIZE = 10
_TURNS_PER_DAY = 24
_ONE_TIME_CROPS = [c for c, data in CROPS.items() if not data["ongoing"]]


def _simulate(crop: str, watered_ages: set, fertilized_ages: set) -> int:
    """Plant `crop`, water it on each age in `watered_ages` (fertilizing
    first on each age in `fertilized_ages`), and return the real
    interpreter's final yield_units for that tile."""
    farm = real._new_farm(_BOARD_SIZE, starting_money=3000)
    private = real._new_private()
    private["seeds"][crop] = 1
    planted_day = 5  # arbitrary and non-zero, so absolute-day math isn't
    # accidentally hardcoded to start-of-episode in the implementation.

    real._apply_unit_action(
        farm, private, 0, ["PLANT", crop], _BOARD_SIZE, planted_day, _TURNS_PER_DAY
    )
    fx, fy = farm["farmer"]
    tile = farm["tiles"][fy][fx]
    assert tile is not None and tile["kind"] == "PLANT"

    inv = real._farmer_inventory(private, 0)
    for age in sorted(watered_ages):
        day = planted_day + age
        if age in fertilized_ages:
            real._inv_add(inv, "FERTILIZER", 1)
            real._apply_unit_action(farm, private, 0, ["FERTILIZE"], _BOARD_SIZE, day, _TURNS_PER_DAY)
        tile["watered_today"] = False  # simulate the day-boundary reset
        real._apply_unit_action(farm, private, 0, ["WATER"], _BOARD_SIZE, day, _TURNS_PER_DAY)

    return farm["tiles"][fy][fx]["yield_units"]


def test_watering_bonus_window_matches_documented_examples():
    # SPEC-gamelib.md's own worked example: melon's window is ages 6-12.
    assert list(watering_bonus_window("MELON")) == list(range(6, 13))
    # WHEAT: max_yield_day=4 -> window_start=(4+1)//2=2 -> range(2, 5).
    assert list(watering_bonus_window("WHEAT")) == list(range(2, 5))
    # CARROT: max_yield_day=3 -> window_start=(3+1)//2=2 -> range(2, 4).
    assert list(watering_bonus_window("CARROT")) == list(range(2, 4))


def test_forecast_one_time_yield_matches_real_simulation_unfertilized():
    rng = random.Random(1234)
    for crop in _ONE_TIME_CROPS:
        max_age = CROPS[crop]["max_yield_day"] + 2  # a bit past the window too
        for _ in range(20):
            k = rng.randint(0, max_age)
            watered_ages = set(rng.sample(range(max_age + 1), k))
            expected = _simulate(crop, watered_ages, fertilized_ages=set())
            actual = forecast_one_time_yield(crop, watered_ages, fertilized_days=set())
            assert actual == expected, (crop, watered_ages)


def test_forecast_one_time_yield_matches_real_simulation_with_fertilizer():
    rng = random.Random(5678)
    for crop in _ONE_TIME_CROPS:
        max_age = CROPS[crop]["max_yield_day"] + 2
        for _ in range(20):
            k = rng.randint(0, max_age)
            watered_ages = set(rng.sample(range(max_age + 1), k))
            # Fertilizer can only apply on a day that's also watered - the
            # real handler's FERTILIZE and WATER are separate actions, but
            # a fertilize-only day (never watered) can never bank a bonus,
            # since the bonus is only ever paid out inside the WATER
            # handler itself.
            fertilized_ages = set(rng.sample(sorted(watered_ages), rng.randint(0, len(watered_ages)))) if watered_ages else set()
            expected = _simulate(crop, watered_ages, fertilized_ages)
            actual = forecast_one_time_yield(crop, watered_ages, fertilized_days=fertilized_ages)
            assert actual == expected, (crop, watered_ages, fertilized_ages)
