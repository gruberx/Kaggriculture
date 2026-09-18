"""Tests for tools/daily_dashboard.py's pure detection functions - see
tasks/todo.md's T8.35 entry.

Follows tests/test_harness_run_paired.py's sys.path convention (tools/
isn't a package, it's dev-only tooling that never ships).

No oracle needed for the transition classifiers - these mirror the real
engine's own end-of-day rules (kaggle_environments/envs/kaggriculture/
kaggriculture.py's _daily_refresh_plants/_daily_refresh_animals/
_decay_plants), documented precisely in tools/daily_dashboard.py's own
docstrings, not re-derived here.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import daily_dashboard  # noqa: E402


def _plant_tile(consecutive_unwatered=0, watered_today=False, yield_units=0, max_lifespan_step=-1) -> dict:
    return {
        "kind": "PLANT",
        "crop": "WHEAT",
        "planted_day": 0,
        "watered_today": watered_today,
        "consecutive_unwatered": consecutive_unwatered,
        "yield_units": yield_units,
        "max_lifespan_step": max_lifespan_step,
        "fertilized_until_day": -1,
    }


def _animal_tile(consecutive_unfed=0, fed_today=False, animal="GOOSE") -> dict:
    return {
        "kind": "COOP" if animal == "GOOSE" else "PASTURE",
        "animal": animal,
        "placed_day": 0,
        "yield_units": 0,
        "consecutive_unfed": consecutive_unfed,
        "fed_today": fed_today,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }


# --- classify_plant_transition -----------------------------------------


def test_plant_transition_watered_tile_survives():
    prev = _plant_tile(consecutive_unwatered=0, watered_today=True)
    cur = _plant_tile(consecutive_unwatered=0, watered_today=False)
    assert daily_dashboard.classify_plant_transition(prev, cur, prev_step=10) is None


def test_plant_transition_unwatered_neglect_is_drought_death():
    # consecutive_unwatered=1 going into end-of-day, still not watered
    # today -> the real engine's own "2 consecutive misses" rule fires.
    prev = _plant_tile(consecutive_unwatered=1, watered_today=False, max_lifespan_step=-1)
    cur = {"kind": "WEED"}
    assert daily_dashboard.classify_plant_transition(prev, cur, prev_step=23) == "drought_death"


def test_plant_transition_lifespan_decay_is_decay_death():
    # Well-watered (rules out drought), but at its exact decay-fire step
    # with yield_units already at 1 - the next decrement kills it.
    prev = _plant_tile(consecutive_unwatered=0, watered_today=True, yield_units=1, max_lifespan_step=50)
    cur = {"kind": "WEED"}
    assert daily_dashboard.classify_plant_transition(prev, cur, prev_step=50) == "decay_death"


def test_plant_transition_ambient_weed_spawn_is_not_a_death():
    # None -> WEED is _spawn_weeds' ambient noise, not a real loss.
    assert daily_dashboard.classify_plant_transition(None, {"kind": "WEED"}, prev_step=10) is None


def test_plant_transition_no_change_is_none():
    prev = _plant_tile(consecutive_unwatered=0, watered_today=True)
    cur = _plant_tile(consecutive_unwatered=0, watered_today=False)
    assert daily_dashboard.classify_plant_transition(prev, prev, prev_step=10) is None
    assert daily_dashboard.classify_plant_transition(prev, cur, prev_step=10) is None


# --- classify_animal_transition -----------------------------------------


def test_animal_transition_fed_animal_survives():
    prev = _animal_tile(consecutive_unfed=0, fed_today=True)
    cur = _animal_tile(consecutive_unfed=0, fed_today=False)
    assert daily_dashboard.classify_animal_transition(prev, cur) is None


def test_animal_transition_unfed_neglect_is_escape():
    prev = _animal_tile(consecutive_unfed=1, fed_today=False, animal="GOOSE")
    cur = {"kind": "COOP"}  # bare structure, no "animal" key
    assert daily_dashboard.classify_animal_transition(prev, cur) == "escaped"


def test_animal_transition_uses_correct_structure_for_pasture_animals():
    prev = _animal_tile(consecutive_unfed=1, fed_today=False, animal="COW")
    cur = {"kind": "PASTURE"}
    assert daily_dashboard.classify_animal_transition(prev, cur) == "escaped"


def test_animal_transition_still_occupied_is_none():
    prev = _animal_tile(consecutive_unfed=1, fed_today=False, animal="GOOSE")
    cur = _animal_tile(consecutive_unfed=0, fed_today=True, animal="GOOSE")
    assert daily_dashboard.classify_animal_transition(prev, cur) is None


# --- is_price_floor_pinned -----------------------------------------------


def test_price_floor_pinned_when_price_and_inventory_both_stick():
    prev_prices, cur_prices = {"WOOL": 1}, {"WOOL": 1}
    prev_inv, cur_inv = {"WOOL": 15000}, {"WOOL": 15000}
    assert daily_dashboard.is_price_floor_pinned(prev_prices, cur_prices, prev_inv, cur_inv, "WOOL") is True


def test_price_floor_not_pinned_when_inventory_still_moves():
    # Shouldn't happen per the engine's own "price>1 required to raise
    # inventory" rule, but the function must not crash on an unexpected
    # trace and must not claim "pinned" when inventory did move.
    prev_prices, cur_prices = {"WOOL": 1}, {"WOOL": 1}
    prev_inv, cur_inv = {"WOOL": 15000}, {"WOOL": 15001}
    assert daily_dashboard.is_price_floor_pinned(prev_prices, cur_prices, prev_inv, cur_inv, "WOOL") is False


def test_price_floor_not_pinned_when_price_above_floor():
    prev_prices, cur_prices = {"WOOL": 40}, {"WOOL": 38}
    prev_inv, cur_inv = {"WOOL": 9000}, {"WOOL": 9200}
    assert daily_dashboard.is_price_floor_pinned(prev_prices, cur_prices, prev_inv, cur_inv, "WOOL") is False


# --- track_daily_min_price -------------------------------------------------


def test_track_daily_min_price_records_the_cheapest_product():
    day_min = {}
    daily_dashboard.track_daily_min_price(day_min, day=0, prices={"WHEAT": 25, "CARROT": 35, "TOMATO": 18})
    assert day_min[0] == [18, "TOMATO"]


def test_track_daily_min_price_updates_on_a_lower_price_later_the_same_day():
    day_min = {0: [18, "TOMATO"]}
    daily_dashboard.track_daily_min_price(day_min, day=0, prices={"WHEAT": 25, "TOMATO": 12})
    assert day_min[0] == [12, "TOMATO"]


def test_track_daily_min_price_ignores_a_higher_price():
    day_min = {0: [18, "TOMATO"]}
    daily_dashboard.track_daily_min_price(day_min, day=0, prices={"WHEAT": 25, "TOMATO": 40})
    assert day_min[0] == [18, "TOMATO"]


def test_track_daily_min_price_keeps_each_day_independent():
    day_min = {}
    daily_dashboard.track_daily_min_price(day_min, day=0, prices={"WHEAT": 10})
    daily_dashboard.track_daily_min_price(day_min, day=1, prices={"WHEAT": 25})
    assert day_min[0] == [10, "WHEAT"]
    assert day_min[1] == [25, "WHEAT"]


# --- order_fill ------------------------------------------------------------


def test_order_fill_buy_seed_fully_filled():
    prev_private = {"seeds": {"WHEAT": 2}, "shed": {}}
    cur_private = {"seeds": {"WHEAT": 7}, "shed": {}}
    op, requested, filled = daily_dashboard.order_fill(
        ["BUY_SEED", "WHEAT", 5], prev_private, cur_private, prev_farm={}, cur_farm={}
    )
    assert (op, requested, filled) == ("BUY_SEED", 5, 5)


def test_order_fill_buy_seed_partially_filled():
    prev_private = {"seeds": {"WHEAT": 2}, "shed": {}}
    cur_private = {"seeds": {"WHEAT": 4}, "shed": {}}  # only 2 of 5 filled
    op, requested, filled = daily_dashboard.order_fill(
        ["BUY_SEED", "WHEAT", 5], prev_private, cur_private, prev_farm={}, cur_farm={}
    )
    assert (op, requested, filled) == ("BUY_SEED", 5, 2)


def test_order_fill_buy_land_uses_quadrant_count():
    prev_farm = {"unlocked_quadrants": ["NW"]}
    cur_farm = {"unlocked_quadrants": ["NW", "NE"]}
    op, requested, filled = daily_dashboard.order_fill(
        ["BUY_LAND"], prev_private={}, cur_private={}, prev_farm=prev_farm, cur_farm=cur_farm
    )
    assert (op, requested, filled) == ("BUY_LAND", 1, 1)


def test_order_fill_hire_uses_hires_today():
    prev_farm = {"hires_today": 1}
    cur_farm = {"hires_today": 1}  # engine silently rejected it
    op, requested, filled = daily_dashboard.order_fill(
        ["HIRE"], prev_private={}, cur_private={}, prev_farm=prev_farm, cur_farm=cur_farm
    )
    assert (op, requested, filled) == ("HIRE", 1, 0)


# --- land_gate_status ------------------------------------------------------


def test_land_gate_blocked_by_money():
    status = daily_dashboard.land_gate_status(
        money=5000, n_unlocked_extra=0, params={"land_purchase_threshold_money": 15000}
    )
    assert status == "blocked: money"


def test_land_gate_blocked_by_occupancy_when_cash_is_fine():
    # Plenty of cash, but occupancy gate (land_buy_max_free_tile_fraction)
    # not yet met - mirrors test_policy_strategy.py's own
    # test_should_buy_land_declines_while_most_tiles_are_still_free.
    status = daily_dashboard.land_gate_status(
        money=1_000_000, n_unlocked_extra=0,
        params={"land_purchase_threshold_money": 0, "land_buy_max_free_tile_fraction": 0.1},
        free_tiles=20, unlocked_tiles=25,
    )
    assert status == "blocked: occupancy"


def test_land_gate_ready_when_both_gates_clear():
    status = daily_dashboard.land_gate_status(
        money=1_000_000, n_unlocked_extra=0,
        params={"land_purchase_threshold_money": 0, "land_buy_max_free_tile_fraction": 0.1},
        free_tiles=2, unlocked_tiles=25,
    )
    assert status == "ready"


def test_land_gate_done_once_all_quadrants_bought():
    status = daily_dashboard.land_gate_status(
        money=1_000_000, n_unlocked_extra=3, params={}
    )
    assert status == "done"
