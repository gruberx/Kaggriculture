"""Property tests for forecast_ongoing_schedule() and
forecast_animal_schedule() - see SPEC-gamelib.md.

Drives the real _daily_refresh_plants/_daily_refresh_animals against a
scratch farm and compares the days on which yield_units actually increases
to the forecast schedule - the harness SPEC-gamelib.md prescribes.
"""

from kaggle_environments.envs.kaggriculture import kaggriculture as real

from kagg.gamelib.constants import ANIMALS, CROPS
from kagg.gamelib.growth import forecast_animal_schedule, forecast_ongoing_schedule

_BOARD_SIZE = 10
_TURNS_PER_DAY = 24
_ONGOING_CROPS = [c for c, data in CROPS.items() if data["ongoing"]]


def _ongoing_production_days(crop: str, planted_day: int, horizon_days: int) -> list[int]:
    """Days on which the real interpreter's yield_units for a planted,
    always-watered ongoing crop actually increases."""
    farm = real._new_farm(_BOARD_SIZE, starting_money=3000)
    private = real._new_private()
    private["seeds"][crop] = 1
    real._apply_unit_action(
        farm, private, 0, ["PLANT", crop], _BOARD_SIZE, planted_day, _TURNS_PER_DAY
    )
    fx, fy = farm["farmer"]
    tile = farm["tiles"][fy][fx]
    assert tile is not None and tile["kind"] == "PLANT"

    production_days = []
    for day in range(planted_day, planted_day + horizon_days):
        if isinstance(farm["tiles"][fy][fx], dict) and farm["tiles"][fy][fx].get("kind") == "PLANT":
            farm["tiles"][fy][fx]["watered_today"] = False
            real._apply_unit_action(farm, private, 0, ["WATER"], _BOARD_SIZE, day, _TURNS_PER_DAY)
        before = farm["tiles"][fy][fx].get("yield_units", 0) if isinstance(farm["tiles"][fy][fx], dict) else 0
        real._daily_refresh_plants(farm, day, _TURNS_PER_DAY)
        tile_now = farm["tiles"][fy][fx]
        after = tile_now.get("yield_units", 0) if isinstance(tile_now, dict) else 0
        if after > before:
            production_days.append(day + 1)
    return production_days


def _animal_production_days(animal: str, placed_day: int, horizon_days: int) -> list[int]:
    """Days on which the real interpreter's yield_units for a placed,
    always-fed animal actually increases."""
    farm = real._new_farm(_BOARD_SIZE, starting_money=3000)
    private = real._new_private()
    structure_op = "BUILD_COOP" if ANIMALS[animal]["structure"] == "COOP" else "BUILD_PASTURE"
    real._apply_unit_action(farm, private, 0, [structure_op], _BOARD_SIZE, placed_day, _TURNS_PER_DAY)
    fx, fy = farm["farmer"]
    inv = real._farmer_inventory(private, 0)
    real._inv_add(inv, animal, 1)
    real._apply_unit_action(farm, private, 0, ["PLACE", animal], _BOARD_SIZE, placed_day, _TURNS_PER_DAY)
    assert "animal" in farm["tiles"][fy][fx]

    production_days = []
    for day in range(placed_day, placed_day + horizon_days):
        real._inv_add(inv, "WHEAT", 1)
        real._apply_unit_action(farm, private, 0, ["FEED"], _BOARD_SIZE, day, _TURNS_PER_DAY)
        before = farm["tiles"][fy][fx]["yield_units"]
        real._daily_refresh_animals(farm, day)
        after = farm["tiles"][fy][fx]["yield_units"]
        if after > before:
            production_days.append(day + 1)
        # Harvest immediately so yield_units never sits at max_held - a
        # never-harvested animal's production ticks keep firing on
        # schedule even after the tile caps out, but that stops being
        # *visible* as a yield_units increase once it's saturated. This
        # is a test-observability fix, not a change to the schedule being
        # tested: forecast_animal_schedule() has no opinion on harvesting.
        if farm["tiles"][fy][fx]["yield_units"] > 0:
            real._apply_unit_action(farm, private, 0, ["HARVEST"], _BOARD_SIZE, day + 1, _TURNS_PER_DAY)
    return production_days


def test_forecast_ongoing_schedule_matches_documented_examples():
    # SPEC-gamelib.md's own worked examples.
    assert forecast_ongoing_schedule("TOMATO", planted_day=0) == [8, 9, 10, 11]
    assert forecast_ongoing_schedule("STRAWBERRY", planted_day=0) == [10, 12, 14, 16]


def test_forecast_ongoing_schedule_matches_real_simulation():
    planted_day = 3
    for crop in _ONGOING_CROPS:
        horizon = CROPS[crop]["first_yield_day"] + CROPS[crop]["max_yield"] * CROPS[crop]["interval"] + 5
        expected = _ongoing_production_days(crop, planted_day, horizon)
        actual = [d for d in forecast_ongoing_schedule(crop, planted_day) if d < planted_day + horizon]
        assert actual == expected, crop


def test_forecast_animal_schedule_matches_real_simulation():
    placed_day = 3
    horizon_days = 40
    for animal in ANIMALS:
        expected = _animal_production_days(animal, placed_day, horizon_days)
        actual = forecast_animal_schedule(animal, placed_day, horizon_days=placed_day + horizon_days)
        assert actual == expected, animal
