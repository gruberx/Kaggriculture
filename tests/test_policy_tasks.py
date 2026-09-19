"""Unit tests for kagg.policy.tasks - see SPEC-policy.md "2. Task layer"
and tasks/plan.md T3.2.

No oracle needed - this is new decision logic, not mirroring the real
interpreter. Priority order per SPEC-policy.md: prevent-loss > harvest-
value > plant-new-tile > maintenance. This module adds one tier not named
explicitly in that list - routine (non-urgent) watering/feeding, between
harvest-value and plant-new-tile - documented in tasks.py's own module
docstring; a plant that was watered yesterday (consecutive_unwatered==0)
isn't at risk today even if not yet watered, unlike one already at
consecutive_unwatered>=1 (SPEC-gamelib.md: 2 consecutive misses -> weed).
"""

from kagg.gamelib.farm import shed_access_tiles, shed_distance, tile_distance
from kagg.policy.tasks import (
    PRIORITY_ANIMAL_SETUP,
    PRIORITY_HARVEST,
    PRIORITY_LOW_VALUE_CARE,
    PRIORITY_MAINTENANCE,
    PRIORITY_PLANT,
    PRIORITY_PREVENT_LOSS,
    PRIORITY_ROUTINE_CARE,
    Task,
    action_for_unit,
    assign_units,
    build_task_list,
)


def _empty_tiles(size: int = 10) -> list:
    return [[None] * size for _ in range(size)]


def _plant_tile(consecutive_unwatered=0, watered_today=False, yield_units=0, planted_day=0) -> dict:
    return {
        "kind": "PLANT",
        "crop": "WHEAT",
        "planted_day": planted_day,
        "watered_today": watered_today,
        "consecutive_unwatered": consecutive_unwatered,
        "yield_units": yield_units,
        "max_lifespan_step": 120,
        "fertilized_until_day": -1,
    }


def _animal_tile(
    consecutive_unfed=0, fed_today=False, yield_units=0, fertilizer_available=False, cared_today=False
) -> dict:
    return {
        "kind": "COOP",
        "animal": "GOOSE",
        "placed_day": 0,
        "yield_units": yield_units,
        "consecutive_unfed": consecutive_unfed,
        "fed_today": fed_today,
        "cared_today": cared_today,
        "fertilizer_available": fertilizer_available,
        "pending_care_bonus": 0,
    }


# --- build_task_list ---------------------------------------------------


def test_build_task_list_flags_prevent_loss_watering():
    tiles = _empty_tiles()
    tiles[1][1] = _plant_tile(consecutive_unwatered=1, watered_today=False)
    tasks = build_task_list(tiles)
    assert any(t.priority == PRIORITY_PREVENT_LOSS and t.op == "WATER" and t.pos == (1, 1) for t in tasks)


def test_build_task_list_treats_already_watered_as_no_task():
    tiles = _empty_tiles()
    tiles[1][1] = _plant_tile(consecutive_unwatered=1, watered_today=True)
    tasks = build_task_list(tiles)
    assert tasks == []


def test_build_task_list_routine_watering_is_lower_priority_than_prevent_loss():
    tiles = _empty_tiles()
    tiles[2][2] = _plant_tile(consecutive_unwatered=0, watered_today=False)  # routine
    tasks = build_task_list(tiles)
    assert len(tasks) == 1
    assert tasks[0].priority == PRIORITY_ROUTINE_CARE


def test_build_task_list_water_bonus_window_aware_demotes_watering_outside_the_bonus_window():
    # T8.11, the user's own observation (extending the same trace this
    # module's module docstring already names as unbuilt: "a plausible
    # refinement, not yet measured to matter" - see _plant_tile_tasks'
    # own FERTILIZE comment on the old, un-window-aware WATER task).
    # WHEAT's bonus window is watering_bonus_window("WHEAT") = range(2, 5)
    # (max_yield_day=4, window_start=(4+1)//2=2) - watering at age 0 gives
    # zero yield, it only exists to avoid the 2-consecutive-miss weed
    # conversion. Gated: default behavior (flag off) keeps this at
    # PRIORITY_ROUTINE_CARE (see test_build_task_list_routine_watering_is_
    # lower_priority_than_prevent_loss, same fixture, flag omitted).
    #
    # T8.15: demotes to PRIORITY_LOW_VALUE_CARE, not PRIORITY_MAINTENANCE -
    # T8.11's own first attempt at PRIORITY_MAINTENANCE was measured and
    # rejected (WEED count tripled, see kagg.policy.decide's own
    # _DEFAULT_WATER_BONUS_WINDOW_AWARE comment) because it let watering
    # miss 2 consecutive days once PLANT filled the queue ahead of it.
    tiles = _empty_tiles()
    tiles[2][2] = _plant_tile(consecutive_unwatered=0, watered_today=False, planted_day=0)  # age 0, WHEAT
    tasks = build_task_list(tiles, current_day=0, water_bonus_window_aware=True)
    assert len(tasks) == 1
    assert tasks[0].priority == PRIORITY_LOW_VALUE_CARE
    assert tasks[0].op == "WATER"


def test_build_task_list_water_bonus_window_aware_keeps_routine_priority_inside_the_window():
    # Same WHEAT tile, but at age 2 - inside range(2, 5), watering today
    # actually adds yield. Must stay at the routine-care tier, not get
    # demoted just because the flag is on.
    tiles = _empty_tiles()
    tiles[2][2] = _plant_tile(consecutive_unwatered=0, watered_today=False, planted_day=0)  # WHEAT
    tasks = build_task_list(tiles, current_day=2, water_bonus_window_aware=True)
    assert len(tasks) == 1
    assert tasks[0].priority == PRIORITY_ROUTINE_CARE


def test_build_task_list_water_bonus_window_aware_never_demotes_an_urgent_watering():
    # consecutive_unwatered >= 1 is the real anti-weed safety valve (2
    # consecutive misses converts the tile to WEED) - this must never be
    # touched by the bonus-window optimization, window or no window.
    tiles = _empty_tiles()
    tiles[2][2] = _plant_tile(consecutive_unwatered=1, watered_today=False, planted_day=0)  # age 0, WHEAT
    tasks = build_task_list(tiles, current_day=0, water_bonus_window_aware=True)
    assert len(tasks) == 1
    assert tasks[0].priority == PRIORITY_PREVENT_LOSS


def test_build_task_list_water_bonus_window_aware_leaves_ongoing_crops_untouched():
    # T8.11's deliberate scope-narrowing, verified directly against the
    # real kaggriculture.py handler (not assumed): for an *ongoing* crop
    # (TOMATO/STRAWBERRY), WATER's own handler only ever sets
    # watered_today=True - it never touches yield_units at all (base
    # production fires purely on the _daily_refresh_plants schedule,
    # independent of watering; only the FERTILIZE *combo* bonus cares
    # whether the tile was watered that same day). There is no "bonus
    # window" concept for an ongoing crop's own watering the way there is
    # for a one-time crop, so this flag must leave ongoing-crop watering
    # priority completely unchanged, at any age.
    tiles = _empty_tiles()
    tile = _plant_tile(consecutive_unwatered=0, watered_today=False, planted_day=0)
    tile["crop"] = "STRAWBERRY"
    tiles[2][2] = tile
    tasks = build_task_list(tiles, current_day=0, water_bonus_window_aware=True)
    assert len(tasks) == 1
    assert tasks[0].priority == PRIORITY_ROUTINE_CARE


def test_build_task_list_water_bonus_window_aware_defaults_to_false():
    tiles = _empty_tiles()
    tiles[2][2] = _plant_tile(consecutive_unwatered=0, watered_today=False, planted_day=0)  # WHEAT, age 0
    without_flag = build_task_list(tiles, current_day=0)
    with_flag_off = build_task_list(tiles, current_day=0, water_bonus_window_aware=False)
    assert without_flag == with_flag_off == [Task(PRIORITY_ROUTINE_CARE, (2, 2), "WATER")]


def test_build_task_list_fertilizes_a_plant_when_fertilizer_is_on_hand():
    # T8.3e (tasks/plan.md), the user's own observed defect: FERTILIZER
    # was only ever collected and sold, never applied - the real
    # kaggriculture.py FERTILIZE handler doubles the watering bonus for
    # 3 days (day, day+1, day+2), a real yield lever left completely
    # unused.
    #
    # PRIORITY_MAINTENANCE, not PRIORITY_ROUTINE_CARE - measured, not
    # assumed: an earlier version at ROUTINE_CARE (tied with WATER, and
    # so outranking PRIORITY_PLANT) lost decisively in direct self-play
    # (0/50 working, 0/50 held-out - every non-tied episode was a loss),
    # traced to FERTILIZE crowding out both farther routine watering and
    # opening new PLANT tiles - a modest 3-day yield bump on one already-
    # productive tile is a worse trade than either. MAINTENANCE (below
    # PLANT, same tier as DIG/COLLECT_FERTILIZER) only fires once nothing
    # more pressing is queued - see tasks/todo.md's T8.3e entry.
    tiles = _empty_tiles()
    tiles[2][2] = _plant_tile()  # fertilized_until_day=-1, i.e. not active
    tasks = build_task_list(tiles, farmer_inventory={"FERTILIZER": 1})
    assert any(t.priority == PRIORITY_MAINTENANCE and t.op == "FERTILIZE" and t.pos == (2, 2) for t in tasks)


def test_build_task_list_does_not_fertilize_without_any_fertilizer_on_hand():
    tiles = _empty_tiles()
    tiles[2][2] = _plant_tile()
    tasks = build_task_list(tiles, farmer_inventory={})
    assert [t for t in tasks if t.op == "FERTILIZE"] == []


def test_build_task_list_does_not_waste_fertilizer_on_an_already_active_tile():
    # The real handler is `fertilized_until_day = max(existing, day+2)` -
    # reapplying while an earlier application still covers today is a
    # complete no-op there, so doing it anyway would waste a real unit of
    # FERTILIZER for nothing.
    tiles = _empty_tiles()
    tile = _plant_tile()
    tile["fertilized_until_day"] = 2  # still active on current_day=0
    tiles[2][2] = tile
    tasks = build_task_list(tiles, farmer_inventory={"FERTILIZER": 1}, current_day=0)
    assert [t for t in tasks if t.op == "FERTILIZE"] == []


def test_build_task_list_flags_prevent_loss_feeding():
    tiles = _empty_tiles()
    tiles[3][3] = _animal_tile(consecutive_unfed=1, fed_today=False)
    tasks = build_task_list(tiles, farmer_inventory={"WHEAT": 1})
    assert any(t.priority == PRIORITY_PREVENT_LOSS and t.op == "FEED" and t.pos == (3, 3) for t in tasks)


def test_build_task_list_picks_up_wheat_instead_of_feeding_without_any_on_hand():
    # Real gap found while implementing T6.4, not anticipated in advance:
    # the real FEED handler consumes WHEAT from the *acting unit's own
    # inventory* (kaggriculture.py's _inv_take(inv, "WHEAT", 1), where
    # inv is _farmer_inventory), not the shed - BUY_PRODUCT delivers to
    # the shed. Without a PICKUP step first, FEED silently fails forever
    # and every placed animal starves and escapes.
    tiles = _empty_tiles()
    tiles[3][3] = _animal_tile(consecutive_unfed=1, fed_today=False)
    tasks = build_task_list(
        tiles, unit_positions=[(4, 4)], farmer_inventory={}, shed={"WHEAT": 5}
    )
    assert [t for t in tasks if t.op == "FEED"] == []
    pickup = [t for t in tasks if t.op == "PICKUP"]
    assert len(pickup) == 1
    assert pickup[0].item == "WHEAT"
    assert pickup[0].priority == PRIORITY_PREVENT_LOSS  # as urgent as the FEED it stands in for
    assert pickup[0].pos in {(4, 4), (5, 4), (4, 5), (5, 5)}  # a real shed-access tile


def test_build_task_list_does_not_pick_up_wheat_the_shed_does_not_have():
    tiles = _empty_tiles()
    tiles[3][3] = _animal_tile(consecutive_unfed=0, fed_today=False)  # routine, not urgent
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], farmer_inventory={}, shed={})
    assert [t for t in tasks if t.op in ("FEED", "PICKUP")] == []


def test_build_task_list_wheat_pickup_is_routine_when_no_animal_is_urgent():
    tiles = _empty_tiles()
    tiles[3][3] = _animal_tile(consecutive_unfed=0, fed_today=False)
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], farmer_inventory={}, shed={"WHEAT": 5})
    pickup = [t for t in tasks if t.op == "PICKUP"]
    assert pickup[0].priority == PRIORITY_ROUTINE_CARE


def test_action_for_unit_includes_item_and_qty_for_pickup():
    task = Task(priority=PRIORITY_PREVENT_LOSS, pos=(4, 4), op="PICKUP", item="WHEAT", qty=5)
    assert action_for_unit((4, 4), task) == ["PICKUP", "WHEAT", 5]


def test_build_task_list_flags_harvest_ready_tiles():
    tiles = _empty_tiles()
    # WHEAT's first_yield_day is 2 - planted day 0, current day 2: legitimately harvestable.
    tiles[4][4] = _plant_tile(yield_units=3, watered_today=True, planted_day=0)
    tasks = build_task_list(tiles, current_day=2)
    assert tasks == [Task(priority=PRIORITY_HARVEST, pos=(4, 4), op="HARVEST")]


def test_build_task_list_does_not_harvest_a_one_time_crop_before_first_yield_day():
    # The real bug found while implementing T6.3, not a hypothetical:
    # kaggriculture.py's _new_plant() sets yield_units=1 immediately at
    # planting for a one-time crop (before it can legitimately be
    # harvested - the real HARVEST handler blocks on
    # `day - planted_day < first_yield_day` regardless). Proposing a
    # HARVEST task anyway gave it PRIORITY_HARVEST (above PLANT/BUILD/
    # PLACE's PRIORITY_PLANT), perpetually monopolizing the single
    # farmer on a no-op for the crop's entire maturation period -
    # harmless when there was nothing else to do anyway (pre-T6.2), but
    # directly measured to block BUILD_PASTURE for ~2 real days once an
    # animal investment became available (T6.3's golden-episode
    # regression from 5274 to 3932 traced to exactly this).
    tiles = _empty_tiles()
    tiles[4][4] = _plant_tile(yield_units=1, watered_today=True, planted_day=0)  # WHEAT, first_yield_day=2
    tasks = build_task_list(tiles, current_day=1)  # day 1 < planted_day(0) + first_yield_day(2)
    assert [t for t in tasks if t.op == "HARVEST"] == []


def test_build_task_list_harvests_an_ongoing_crop_as_soon_as_it_has_yield():
    # Ongoing crops (TOMATO/STRAWBERRY) only ever accumulate yield_units
    # after first_yield_day in the real interpreter (kaggriculture.py's
    # own HARVEST handler prints a warning if this is ever violated) -
    # yield_units > 0 alone is always a legitimate harvest signal for
    # these, unlike a fresh one-time crop.
    tiles = _empty_tiles()
    tile = _plant_tile(yield_units=1, watered_today=True, planted_day=0)
    tile["crop"] = "TOMATO"
    tiles[4][4] = tile
    tasks = build_task_list(tiles, current_day=1)  # well before TOMATO's own first_yield_day=8
    assert [t for t in tasks if t.op == "HARVEST"] == [Task(priority=PRIORITY_HARVEST, pos=(4, 4), op="HARVEST")]


def test_build_task_list_defer_one_time_harvest_to_max_yield_off_by_default_still_harvests_at_first_yield_day():
    # Bit-identical to every pre-T8.43 caller when the flag isn't passed
    # at all - same fixture/assertion as test_build_task_list_flags_
    # harvest_ready_tiles above, just spelled out explicitly here.
    tiles = _empty_tiles()
    tiles[4][4] = _plant_tile(yield_units=3, watered_today=True, planted_day=0)  # WHEAT
    tasks = build_task_list(tiles, current_day=2)  # first_yield_day=2, max_yield_day=4
    assert tasks == [Task(priority=PRIORITY_HARVEST, pos=(4, 4), op="HARVEST")]


def test_build_task_list_defers_wheat_harvest_to_max_yield_day_when_flag_is_on():
    # T8.43, the user's own observation: strategy._crop_yield_and_tile_
    # days already assumes a one-time crop's full watering_bonus_window
    # gets watered before harvest. WHEAT's window is ages {2,3,4} and
    # first_yield_day=2, so harvesting the instant it's legal (age 2)
    # forfeits every bonus day. With the flag on, harvest should not fire
    # yet at age 2 (first_yield_day reached, max_yield_day=4 not yet).
    tiles = _empty_tiles()
    tiles[4][4] = _plant_tile(yield_units=1, watered_today=True, planted_day=0)  # WHEAT
    tasks = build_task_list(tiles, current_day=2, defer_one_time_harvest_to_max_yield=True)
    assert [t for t in tasks if t.op == "HARVEST"] == []


def test_build_task_list_harvests_wheat_once_max_yield_day_is_reached_when_flag_is_on():
    tiles = _empty_tiles()
    tiles[4][4] = _plant_tile(yield_units=4, watered_today=True, planted_day=0)  # WHEAT
    tasks = build_task_list(tiles, current_day=4, defer_one_time_harvest_to_max_yield=True)  # max_yield_day=4
    assert [t for t in tasks if t.op == "HARVEST"] == [Task(priority=PRIORITY_HARVEST, pos=(4, 4), op="HARVEST")]


def test_build_task_list_harvests_early_once_yield_is_already_capped_when_flag_is_on():
    # No reason to keep waiting once yield_units already hit the crop's
    # own max_yield (e.g. a fertilizer-doubled bonus reaching the cap
    # before max_yield_day) - covers that case explicitly, not just the
    # age-based one.
    tiles = _empty_tiles()
    tiles[4][4] = _plant_tile(yield_units=6, watered_today=True, planted_day=0)  # WHEAT, max_yield=6
    tasks = build_task_list(tiles, current_day=3, defer_one_time_harvest_to_max_yield=True)  # age 3 < max_yield_day 4
    assert [t for t in tasks if t.op == "HARVEST"] == [Task(priority=PRIORITY_HARVEST, pos=(4, 4), op="HARVEST")]


def test_build_task_list_defer_one_time_harvest_to_max_yield_does_not_affect_ongoing_crops():
    # Ongoing crops (TOMATO/STRAWBERRY) have no bonus-window concept the
    # way one-time crops do (see _is_actually_harvestable's own
    # docstring) - the flag must not delay them at all.
    tiles = _empty_tiles()
    tile = _plant_tile(yield_units=1, watered_today=True, planted_day=0)
    tile["crop"] = "TOMATO"
    tiles[4][4] = tile
    tasks = build_task_list(tiles, current_day=1, defer_one_time_harvest_to_max_yield=True)  # first_yield_day=8
    assert [t for t in tasks if t.op == "HARVEST"] == [Task(priority=PRIORITY_HARVEST, pos=(4, 4), op="HARVEST")]


def test_build_task_list_flags_weeds_as_maintenance():
    tiles = _empty_tiles()
    tiles[5][5] = {"kind": "WEED"}
    tasks = build_task_list(tiles)
    assert tasks == [Task(priority=PRIORITY_MAINTENANCE, pos=(5, 5), op="DIG")]


def test_build_task_list_flags_available_fertilizer_as_maintenance():
    tiles = _empty_tiles()
    tiles[6][6] = _animal_tile(fed_today=True, fertilizer_available=True)
    tasks = build_task_list(tiles)
    assert tasks == [Task(priority=PRIORITY_MAINTENANCE, pos=(6, 6), op="COLLECT_FERTILIZER")]


def test_build_task_list_does_not_care_by_default():
    # T8.3q: care_aware defaults to False, matching use_fertilizer's own
    # gated-by-default convention - a real Kaggle action has a real
    # single-farmer turn cost.
    tiles = _empty_tiles()
    tiles[6][6] = _animal_tile(fed_today=True, cared_today=False)
    tasks = build_task_list(tiles)
    assert tasks == []


def test_build_task_list_cares_for_an_animal_when_enabled():
    tiles = _empty_tiles()
    tiles[6][6] = _animal_tile(fed_today=True, cared_today=False)
    tasks = build_task_list(tiles, care_aware=True)
    assert tasks == [Task(priority=PRIORITY_MAINTENANCE, pos=(6, 6), op="CARE")]


def test_build_task_list_does_not_recare_an_animal_already_cared_for_today():
    tiles = _empty_tiles()
    tiles[6][6] = _animal_tile(fed_today=True, cared_today=True)
    tasks = build_task_list(tiles, care_aware=True)
    assert tasks == []


def test_build_task_list_can_both_feed_and_care_for_the_same_animal_tile():
    tiles = _empty_tiles()
    tiles[6][6] = _animal_tile(consecutive_unfed=1, fed_today=False, cared_today=False)
    tasks = build_task_list(tiles, care_aware=True, farmer_inventory={"WHEAT": 5})
    ops = {t.op for t in tasks}
    assert ops == {"FEED", "CARE"}
    care_task = next(t for t in tasks if t.op == "CARE")
    assert care_task.priority == PRIORITY_MAINTENANCE


def test_build_task_list_plants_an_empty_tile_when_given_a_crop_hint():
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, plant_crop="CARROT")
    assert len(tasks) == 1
    assert tasks[0].priority == PRIORITY_PLANT
    assert tasks[0].op == "PLANT"
    assert tasks[0].crop == "CARROT"


def test_build_task_list_does_not_plant_without_a_crop_hint():
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, plant_crop=None)
    assert tasks == []


def test_build_task_list_only_plants_one_tile_per_call():
    # One PLANT action consumes one seed; the task list represents *this
    # turn's* candidate work, not "plant the whole farm at once." Default
    # plant_qty=1 reproduces this exactly - T8.6 only changes behavior
    # when a caller asks for more.
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, plant_crop="CARROT")
    assert len([t for t in tasks if t.op == "PLANT"]) == 1


def test_build_task_list_plants_multiple_distinct_tiles_when_plant_qty_is_given():
    # T8.6: parallel planting - one PLANT task per available unit, up to
    # plant_qty, each on its own distinct empty tile.
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, plant_crop="CARROT", plant_qty=3, unit_positions=[(4, 4)])
    plant_tasks = [t for t in tasks if t.op == "PLANT"]
    assert len(plant_tasks) == 3
    positions = {t.pos for t in plant_tasks}
    assert len(positions) == 3  # all distinct
    for t in plant_tasks:
        assert t.crop == "CARROT"


def test_build_task_list_plant_crop_as_a_list_round_robins_crops_across_tiles():
    # T8.19: portfolio_basket_size - decide() passes a per-tile sequence
    # of crop names (already round-robined and seed-capped) instead of a
    # single crop string, so each of plant_qty's tiles gets the crop
    # named at the matching position in the list.
    tiles = _empty_tiles()
    tasks = build_task_list(
        tiles, plant_crop=["MELON", "STRAWBERRY", "MELON"], plant_qty=3, unit_positions=[(4, 4)]
    )
    plant_tasks = [t for t in tasks if t.op == "PLANT"]
    assert len(plant_tasks) == 3
    assert sorted(t.crop for t in plant_tasks) == ["MELON", "MELON", "STRAWBERRY"]
    positions = {t.pos for t in plant_tasks}
    assert len(positions) == 3  # all distinct


def test_build_task_list_caps_plant_qty_at_available_empty_tiles():
    tiles = [[{"kind": "WEED"} for _ in range(10)] for _ in range(10)]
    tiles[0][0] = None  # exactly one empty tile
    tasks = build_task_list(tiles, plant_crop="CARROT", plant_qty=5)
    assert len([t for t in tasks if t.op == "PLANT"]) == 1


def test_build_task_list_plant_qty_zero_plants_nothing():
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, plant_crop="CARROT", plant_qty=0)
    assert tasks == []


def test_build_task_list_plants_the_nearest_empty_tile_not_the_first_scanned():
    # T6.2's real, verified fix (found while explaining the game's board
    # geometry to the user): the farm spawns near the board center
    # (4,4), not (0,0) - picking the first empty tile in row-major scan
    # order previously meant walking to the far corner every time.
    # (4,4) is also a shed-access tile, so this holds under T8.1's new
    # shed-anchored default too, not just the old unit-anchored one.
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], plant_crop="CARROT")
    assert len(tasks) == 1
    assert tasks[0].pos == (4, 4)  # farmer's own tile is empty and nearest possible


def test_build_task_list_plants_next_to_the_shed_not_next_to_the_farmer():
    # T8.1's real fix: the old default anchored placement to the
    # farmer's *current* position, which made the planted plot grow as a
    # runaway line away from the shed every time the farmer moved
    # (verified directly: (4,4)->(4,3)->(4,2)->... starting from a
    # farmer standing away from spawn). Placement must be anchored to
    # the shed instead, since kaggriculture.py's _end_of_day teleports
    # the farmer back there and despawns every hand every single day -
    # travel-from-shed is what's actually repaid daily, not travel from
    # wherever a unit happened to be standing.
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(4, 0)], plant_crop="CARROT")
    assert tasks[0].pos == (4, 4)  # nearest the shed, not nearest the farmer at (4, 0)


def test_build_task_list_plants_the_tile_closest_to_any_unit_when_anchor_is_unit():
    # anchor="UNIT" is a deliberate escape hatch restoring the old
    # behavior exactly, for a clean arena A/B against the new default
    # rather than a hardcoded judgment call (tasks/plan.md T8.1).
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(9, 9)], plant_crop="CARROT", anchor="UNIT")
    assert tasks[0].pos == (9, 9)  # nearest to the given unit, not the shed


def test_build_task_list_falls_back_to_the_shed_nearest_tile_without_unit_positions():
    # No unit_positions given. Unlike the pre-T8.1 behavior (row-major
    # scan order -> (0,0)), the shed-anchored key doesn't depend on unit
    # positions at all, so there's nothing to "fall back" from - the
    # shed-nearest tile is always well-defined.
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, plant_crop="CARROT")
    assert tasks[0].pos == (4, 4)


def test_build_task_list_prefers_a_newly_unlocked_quadrant_tile_over_a_far_nw_tile():
    # The consequence T8.1's design relies on: once a new quadrant
    # unlocks, its tiles nearest the shed (including, here, an actual
    # shed-access tile at distance 0) beat whatever's left of the old
    # quadrant's far corners, even though the old quadrant still has a
    # free tile.
    tiles = [[_plant_tile() for _ in range(10)] for _ in range(10)]
    tiles[0][0] = None  # the one remaining free NW tile - shed distance 8
    for y in range(5):
        for x in range(5, 10):
            tiles[y][x] = None  # NE quadrant just unlocked, entirely empty
    tasks = build_task_list(tiles, plant_crop="CARROT")
    plant_task = next(t for t in tasks if t.op == "PLANT")
    assert plant_task.pos == (5, 4)  # NE's shed-access tile, distance 0
    assert shed_distance(plant_task.pos, 10) < shed_distance((0, 0), 10)


def test_build_task_list_breaks_a_farmer_distance_tie_toward_the_shed():
    # T8.3c (tasks/plan.md, designed together with the user): SHED alone
    # (anchor="SHED") was measured to lose in isolated self-play even
    # after the T8.9 fix (T8.3b) - it replaces the *primary* nearest-to-
    # farmer key entirely, which can force a real detour. UNIT_TOWARD_
    # SHED keeps distance-to-farmer as the primary key (never a worse
    # detour than plain "UNIT") and only changes the *tie-break* among
    # candidates that are exactly as close to the farmer - attacking the
    # actual traced cause of the runaway-line pathology (UNIT's tie-break
    # is row-major scan order, unrelated to the shed).
    #
    # Farmer at (0, 4). (1, 3) and (1, 5) are both at Manhattan distance
    # 2 from the farmer - a genuine tie. shed_distance((1,3), 10) == 4,
    # shed_distance((1,5), 10) == 3 (nearer) - verified by hand before
    # writing this test. Under anchor="UNIT" (row-major scan order,
    # y-then-x-ascending), (1,3) is encountered first and wins today.
    #
    # A third candidate, (4, 4) - the shed tile itself, shed_distance=0,
    # but farmer-distance 4 - is included specifically to distinguish
    # this from plain anchor="SHED" (which would wrongly prefer (4,4),
    # the real detour cost T8.3b measured SHED losing on): the *primary*
    # key must reject it for being farther from the farmer, regardless of
    # its better shed-distance.
    tiles = _empty_tiles()
    for y in range(10):
        for x in range(10):
            if (x, y) not in {(1, 3), (1, 5), (4, 4)}:
                tiles[y][x] = _plant_tile()  # occupy everything else
    tasks = build_task_list(tiles, unit_positions=[(0, 4)], plant_crop="CARROT", anchor="UNIT_TOWARD_SHED")
    plant_task = next(t for t in tasks if t.op == "PLANT")
    assert plant_task.pos == (1, 5)  # shed-nearer of the two farmer-distance-2 ties, not the farther shed tile


def test_build_task_list_unit_toward_shed_matches_unit_when_no_tie():
    # Same scenario as the plain-UNIT test above, but with the new
    # anchor - when there's a single unique nearest-to-farmer tile (no
    # tie to break), UNIT_TOWARD_SHED must agree with plain UNIT exactly.
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(9, 9)], plant_crop="CARROT", anchor="UNIT_TOWARD_SHED")
    assert tasks[0].pos == (9, 9)


def test_build_task_list_unit_toward_shed_never_costs_more_travel_than_unit():
    # The structural guarantee T8.3c's design relies on, made concrete
    # rather than left as prose: UNIT_TOWARD_SHED shares UNIT's primary
    # key (distance to the nearest unit), so across any board it must
    # pick a tile at exactly the same farmer-distance plain UNIT would -
    # never a worse (longer) walk, only a different choice among ties.
    boards = [
        (_empty_tiles(), [(0, 0)]),
        (_empty_tiles(), [(9, 9)]),
        (_empty_tiles(), [(3, 7)]),
        (_empty_tiles(), [(5, 5)]),
    ]
    for tiles, unit_positions in boards:
        unit_tasks = build_task_list(tiles, unit_positions=unit_positions, plant_crop="CARROT", anchor="UNIT")
        hybrid_tasks = build_task_list(
            tiles, unit_positions=unit_positions, plant_crop="CARROT", anchor="UNIT_TOWARD_SHED"
        )
        unit_dist = tile_distance(unit_tasks[0].pos, unit_positions[0])
        hybrid_dist = tile_distance(hybrid_tasks[0].pos, unit_positions[0])
        assert hybrid_dist == unit_dist, (unit_positions, unit_dist, hybrid_dist)


# --- animal acquisition pipeline (T6.2) ----------------------------------


def _empty_structure(kind: str) -> dict:
    return {"kind": kind}


def test_build_task_list_builds_a_structure_when_none_exists_yet():
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], desired_animal="COW")
    assert len(tasks) == 1
    assert tasks[0].op == "BUILD_PASTURE"  # COW's structure, per gamelib.constants.ANIMALS
    assert tasks[0].pos == (4, 4)


def test_build_task_list_builds_proactively_even_when_the_animal_is_already_held():
    # Design decision from tasks/plan.md T6.2: building doesn't wait on
    # already owning the animal - it can run in parallel with the
    # BUY_ANIMAL order.
    tiles = _empty_tiles()
    tasks = build_task_list(
        tiles, unit_positions=[(4, 4)], desired_animal="COW", farmer_inventory={"COW": 1}
    )
    assert len(tasks) == 1
    assert tasks[0].op == "BUILD_PASTURE"


def test_build_task_list_builds_coop_for_goose():
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], desired_animal="GOOSE")
    assert tasks[0].op == "BUILD_COOP"


def test_build_task_list_places_a_held_animal_on_a_matching_empty_structure():
    # "Held" specifically means in the *farmer's own inventory* - PLACE's
    # real handler (kaggriculture.py) consumes from there, not the shed
    # (T6.4's real finding - see the PICKUP tests below).
    tiles = _empty_tiles()
    tiles[4][4] = _empty_structure("PASTURE")
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0)], desired_animal="COW", farmer_inventory={"COW": 1}
    )
    assert len(tasks) == 1
    assert tasks[0].op == "PLACE"
    assert tasks[0].pos == (4, 4)
    assert tasks[0].animal == "COW"


def test_build_task_list_picks_up_an_animal_held_in_the_shed_but_not_in_hand():
    # T6.4's central finding: BUY_ANIMAL delivers to the shed, but PLACE
    # needs the animal in the farmer's own inventory - a PICKUP step
    # (standing on a real shed-access tile) is required in between, or
    # PLACE silently fails forever (verified directly against a real
    # episode: the animal just sat in the shed, never placed).
    tiles = _empty_tiles()
    tiles[4][4] = _empty_structure("PASTURE")
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0)], desired_animal="COW", shed={"COW": 1}
    )
    assert len(tasks) == 1
    assert tasks[0].op == "PICKUP"
    assert tasks[0].item == "COW"
    assert tasks[0].qty == 1
    assert tasks[0].pos in {(4, 4), (5, 4), (4, 5), (5, 5)}


def test_build_task_list_does_nothing_when_structure_exists_but_animal_not_bought_yet():
    # Structure already built, BUY_ANIMAL hasn't landed yet (decide()'s
    # job, pending) - neither BUILD (already done) nor PICKUP/PLACE
    # (nothing bought yet) applies this turn.
    tiles = _empty_tiles()
    tiles[4][4] = _empty_structure("PASTURE")
    tasks = build_task_list(tiles, unit_positions=[(0, 0)], desired_animal="COW")
    assert tasks == []


# --- T8.18: parallel animal acquisition -----------------------------------
#
# Verified directly against kaggriculture.py: PICKUP has no structural
# prerequisite at all (it only needs a shed-adjacent unit and a matching
# shed inventory entry) - only PLACE genuinely needs both an animal in
# hand and a matching built structure. The shipped serial if/elif chain
# blocks PICKUP on "no structure yet" even though nothing about PICKUP
# needs a structure, wasting a second labor unit (Stage B) that could be
# doing BUILD_* and PICKUP on the very same turn.


def test_build_task_list_serial_pipeline_still_blocks_pickup_on_the_missing_structure_by_default():
    # parallel_animal_acquisition defaults to False - bit-identical to
    # the original serial chain: with no structure yet, only BUILD_*
    # fires this turn even though the animal already sits in the shed.
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], desired_animal="COW", shed={"COW": 1})
    assert len(tasks) == 1
    assert tasks[0].op == "BUILD_PASTURE"


def test_build_task_list_parallel_animal_acquisition_builds_and_picks_up_in_the_same_turn():
    # With the flag on: no structure yet, but the animal is already in
    # the shed - BUILD_PASTURE and PICKUP are independent of each other
    # (PICKUP needs no structure), so both fire this turn, letting a
    # second labor unit do PICKUP while the farmer does BUILD.
    tiles = _empty_tiles()
    tasks = build_task_list(
        tiles, unit_positions=[(4, 4)], desired_animal="COW", shed={"COW": 1},
        parallel_animal_acquisition=True,
    )
    ops = {t.op for t in tasks}
    assert ops == {"BUILD_PASTURE", "PICKUP"}


def test_build_task_list_parallel_animal_acquisition_still_requires_both_for_place():
    # PLACE's real dependency (an animal in hand AND a matching built
    # structure) is real and doesn't go away - only one task fires here.
    tiles = _empty_tiles()
    tiles[4][4] = _empty_structure("PASTURE")
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0)], desired_animal="COW", farmer_inventory={"COW": 1},
        parallel_animal_acquisition=True,
    )
    assert len(tasks) == 1
    assert tasks[0].op == "PLACE"


def test_build_task_list_parallel_animal_acquisition_does_not_repropose_pickup_once_in_hand():
    # Once the animal is already in the farmer's own inventory, PICKUP
    # has nothing left to do even though the shed might still show a
    # stale/second unit of the same animal type - only PLACE applies.
    tiles = _empty_tiles()
    tiles[4][4] = _empty_structure("PASTURE")
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0)], desired_animal="COW",
        farmer_inventory={"COW": 1}, shed={"COW": 1},
        parallel_animal_acquisition=True,
    )
    ops = {t.op for t in tasks}
    assert ops == {"PLACE"}


def test_build_task_list_ignores_a_mismatched_empty_structure():
    # An empty COOP sits idle when the desired animal needs a PASTURE.
    tiles = _empty_tiles()
    tiles[4][4] = _empty_structure("COOP")
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0)], desired_animal="COW", farmer_inventory={"COW": 1}
    )
    assert tasks[0].op == "BUILD_PASTURE"  # builds a fresh PASTURE elsewhere, ignoring the COOP


def test_build_task_list_places_on_the_shed_nearest_matching_structure_by_default():
    # T8.1: PLACE's target is shed-anchored, not farmer-anchored - here
    # the farmer stands right next to one structure, but the *other*
    # structure (at the shed) is still preferred.
    tiles = _empty_tiles()
    tiles[0][0] = _empty_structure("PASTURE")
    tiles[4][4] = _empty_structure("PASTURE")
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0)], desired_animal="COW", farmer_inventory={"COW": 1}
    )
    assert tasks[0].pos == (4, 4)


def test_build_task_list_places_on_the_nearest_matching_structure_when_anchor_is_unit():
    tiles = _empty_tiles()
    tiles[0][0] = _empty_structure("PASTURE")
    tiles[9][9] = _empty_structure("PASTURE")
    tasks = build_task_list(
        tiles, unit_positions=[(9, 8)], desired_animal="COW", farmer_inventory={"COW": 1},
        anchor="UNIT",
    )
    assert tasks[0].pos == (9, 9)


def test_action_for_unit_includes_animal_for_place():
    task = Task(priority=PRIORITY_PLANT, pos=(4, 4), op="PLACE", animal="COW")
    assert action_for_unit((4, 4), task) == ["PLACE", "COW"]


def test_action_for_unit_build_ops_take_no_argument():
    task = Task(priority=PRIORITY_PLANT, pos=(4, 4), op="BUILD_PASTURE")
    assert action_for_unit((4, 4), task) == ["BUILD_PASTURE"]


def test_build_task_list_is_sorted_by_priority():
    tiles = _empty_tiles()
    tiles[0][0] = {"kind": "WEED"}  # maintenance
    tiles[1][1] = _plant_tile(yield_units=1, watered_today=True, planted_day=0)  # harvest (legit by day 2)
    tiles[2][2] = _plant_tile(consecutive_unwatered=1, watered_today=False)  # prevent-loss
    tasks = build_task_list(tiles, current_day=2)
    assert [t.priority for t in tasks] == sorted(t.priority for t in tasks)
    assert tasks[0].priority == PRIORITY_PREVENT_LOSS


# --- assign_units --------------------------------------------------------


def test_assign_units_picks_prevent_loss_over_harvest_with_one_unit():
    # tasks/plan.md T3.2's literal acceptance criterion: a tile one turn
    # from weeding and a tile ready to harvest - prevent-loss wins, even
    # though here the harvest tile is the *closer* one, proving priority
    # dominates proximity rather than merely happening to align with it.
    prevent_loss = Task(priority=PRIORITY_PREVENT_LOSS, pos=(8, 8), op="WATER")
    harvest = Task(priority=PRIORITY_HARVEST, pos=(0, 0), op="HARVEST")
    farmer_pos = (0, 1)  # one step from the harvest tile, far from prevent-loss

    assignment = assign_units([prevent_loss, harvest], [farmer_pos])

    assert assignment == [prevent_loss]


def test_assign_units_assigns_the_closer_unit_within_the_same_priority_tier():
    task = Task(priority=PRIORITY_HARVEST, pos=(5, 5), op="HARVEST")
    near = (5, 6)
    far = (0, 0)

    assignment = assign_units([task], [far, near])

    assert assignment == [None, task]


def test_assign_units_gives_each_unit_at_most_one_task():
    tasks = [
        Task(priority=PRIORITY_PREVENT_LOSS, pos=(0, 0), op="WATER"),
        Task(priority=PRIORITY_HARVEST, pos=(9, 9), op="HARVEST"),
    ]
    units = [(0, 1), (9, 8)]

    assignment = assign_units(tasks, units)

    assert assignment[0] is not None and assignment[1] is not None
    assert assignment[0] != assignment[1]


def test_assign_units_leaves_extra_units_idle_when_out_of_tasks():
    task = Task(priority=PRIORITY_HARVEST, pos=(5, 5), op="HARVEST")
    assignment = assign_units([task], [(5, 5), (0, 0), (9, 9)])
    assert assignment.count(None) == 2
    assert assignment.count(task) == 1


def test_assign_units_serves_the_nearest_task_within_a_tier():
    # T8.2's real fix (tasks/plan.md): the pre-T8.2 implementation
    # processed same-priority tasks in *list* order (row-major scan
    # order, since build_task_list's old sort never used distance), so a
    # single unit standing right on one WATER tile still got sent to a
    # farther one first if it happened to appear earlier in the list.
    on_tile = Task(priority=PRIORITY_ROUTINE_CARE, pos=(4, 4), op="WATER")
    far_tile = Task(priority=PRIORITY_ROUTINE_CARE, pos=(4, 0), op="WATER")
    assignment = assign_units([far_tile, on_tile], [(4, 4)])
    assert assignment == [on_tile]


def test_assign_units_priority_still_dominates_proximity_with_tier_local_matching():
    # Guards against T8.2 over-rotating on distance: a same-tier nearest-
    # match must never let a lower-priority-but-closer task jump ahead of
    # a higher-priority one, even in the rewritten tier-by-tier matcher.
    urgent_far = Task(priority=PRIORITY_PREVENT_LOSS, pos=(9, 9), op="WATER")
    routine_near = Task(priority=PRIORITY_ROUTINE_CARE, pos=(0, 1), op="WATER")
    assignment = assign_units([routine_near, urgent_far], [(0, 0)])
    assert assignment == [urgent_far]


def test_assign_units_gives_a_pinned_task_to_its_own_unit_even_if_farther():
    # T8.4: a hired hand standing right on the tile must NOT take a
    # pinned FEED - the real interpreter resolves FEED against the
    # *acting unit's own* inventory, and only unit 0 ever carries WHEAT
    # (decide.py's own inventories[0] model) - assigning it to the hand
    # would silently no-op forever.
    pinned_feed = Task(priority=PRIORITY_ROUTINE_CARE, pos=(9, 9), op="FEED", unit_index=0)
    farmer = (0, 0)  # far from the tile
    hand = (9, 9)  # standing right on it
    assignment = assign_units([pinned_feed], [farmer, hand])
    assert assignment == [pinned_feed, None]


def test_assign_units_drops_a_pinned_task_when_its_unit_is_already_busy():
    # Deliberate, accepted consequence (tasks/plan.md T8.4): a pinned
    # task whose unit is claimed by a higher-priority pinned task in the
    # same tier is simply not serviced this turn, not handed to a hand
    # (which would resolve against the wrong inventory).
    prevent_loss_feed = Task(priority=PRIORITY_PREVENT_LOSS, pos=(1, 1), op="FEED", unit_index=0)
    routine_pickup = Task(priority=PRIORITY_PREVENT_LOSS, pos=(2, 2), op="PICKUP", item="WHEAT", unit_index=0)
    assignment = assign_units([prevent_loss_feed, routine_pickup], [(0, 0), (9, 9)])
    # Only one of the two same-tier, same-unit-pinned tasks can win unit
    # 0 - pos (1,1) sorts before (2,2), so it wins; the hand at (9,9)
    # never picks up either (both are pinned to unit 0, never to it).
    assert assignment == [prevent_loss_feed, None]


def test_assign_units_pinned_task_does_not_block_unpinned_work_in_the_same_tier():
    pinned_place = Task(priority=PRIORITY_PLANT, pos=(0, 0), op="PLACE", animal="COW", unit_index=0)
    unpinned_plant = Task(priority=PRIORITY_PLANT, pos=(9, 9), op="PLANT", crop="WHEAT")
    farmer = (0, 0)
    hand = (9, 9)
    assignment = assign_units([pinned_place, unpinned_plant], [farmer, hand])
    assert assignment == [pinned_place, unpinned_plant]


def test_assign_units_hands_still_take_unpinned_ops():
    # Negative control against over-serializing (tasks/plan.md T8.4): a
    # hand nearer to WATER/HARVEST/DIG/PLANT than the farmer must still
    # take it - only the inventory-resolving ops are pinned.
    for op, kwargs in (("WATER", {}), ("HARVEST", {}), ("DIG", {}), ("PLANT", {"crop": "WHEAT"})):
        task = Task(priority=PRIORITY_HARVEST, pos=(9, 9), op=op, **kwargs)
        assignment = assign_units([task], [(0, 0), (9, 9)])
        assert assignment == [None, task], f"{op} was not taken by the nearer hand"


def test_build_task_list_pins_wheat_pickup_to_unit_0():
    tiles = _empty_tiles()
    tiles[5][5] = _animal_tile(fed_today=False, consecutive_unfed=1)  # needs feeding, no WHEAT in hand
    tasks = build_task_list(tiles, shed={"WHEAT": 5})
    pickup = next(t for t in tasks if t.op == "PICKUP" and t.item == "WHEAT")
    assert pickup.unit_index == 0


def test_build_task_list_binds_feed_to_the_unit_holding_wheat():
    # T8.39: FEED is no longer hard-pinned to unit_index=0 - it's bound
    # via eligible_units to whichever unit(s) actually hold WHEAT, which
    # today (farmer_inventory only, no inventories list given) reduces to
    # exactly the old pin: (0,).
    tiles = _empty_tiles()
    tiles[5][5] = _animal_tile(fed_today=False, consecutive_unfed=1)
    tasks = build_task_list(tiles, farmer_inventory={"WHEAT": 5})
    feed = next(t for t in tasks if t.op == "FEED")
    assert feed.unit_index is None
    assert feed.eligible_units == (0,)


def test_build_task_list_pins_place_to_unit_0():
    tiles = _empty_tiles()
    tiles[3][3] = {"kind": "PASTURE"}  # matching structure already built, empty
    tasks = build_task_list(
        tiles, desired_animal="COW", farmer_inventory={"COW": 1},
        unit_positions=[(4, 4)],
    )
    place = next(t for t in tasks if t.op == "PLACE")
    assert place.unit_index == 0


def test_build_task_list_pins_animal_pickup_to_unit_0():
    tiles = _empty_tiles()
    tiles[3][3] = {"kind": "PASTURE"}  # matching structure already built
    tasks = build_task_list(tiles, desired_animal="COW", shed={"COW": 1})
    pickup = next(t for t in tasks if t.op == "PICKUP" and t.item == "COW")
    assert pickup.unit_index == 0


def test_build_task_list_does_not_pin_water_harvest_dig_plant_or_build():
    tiles = _empty_tiles()
    tiles[0][0] = _plant_tile(consecutive_unwatered=1)  # -> WATER
    tiles[1][1] = _plant_tile(yield_units=1, planted_day=0)  # -> HARVEST (WHEAT matures fast)
    tiles[2][2] = {"kind": "WEED"}  # -> DIG
    tasks = build_task_list(tiles, plant_crop="CARROT")  # -> PLANT
    ops_seen = {t.op for t in tasks}
    assert {"WATER", "DIG", "PLANT"} <= ops_seen
    for t in tasks:
        assert t.unit_index is None, f"{t.op} should not be pinned"


# --- assign_units: the restricted stage (T8.39) ------------------------


def test_assign_units_restricted_task_beats_a_farther_unpinned_task_for_its_only_eligible_unit():
    feed = Task(priority=PRIORITY_ROUTINE_CARE, pos=(9, 9), op="FEED", eligible_units=(0,))
    water = Task(priority=PRIORITY_ROUTINE_CARE, pos=(0, 0), op="WATER")  # sits right on unit 0
    assignment = assign_units([feed, water], [(0, 0)])
    # unit 0 is the only unit eligible for FEED, so it must take FEED even
    # though WATER is right under its feet - restricted resolves before
    # plain unpinned in the same tier (most-constrained-first).
    assert assignment == [feed]


def test_assign_units_restricted_stage_sends_two_feeds_to_two_distinct_holders():
    feed_a = Task(priority=PRIORITY_ROUTINE_CARE, pos=(0, 5), op="FEED", eligible_units=(0, 1))
    feed_b = Task(priority=PRIORITY_ROUTINE_CARE, pos=(9, 5), op="FEED", eligible_units=(0, 1))
    unit0 = (0, 0)  # closer to feed_a
    unit1 = (9, 0)  # closer to feed_b
    assignment = assign_units([feed_a, feed_b], [unit0, unit1])
    assert assignment == [feed_a, feed_b]


def test_assign_units_drops_a_restricted_task_when_no_eligible_unit_is_free():
    # unit 0 is claimed by a higher-priority pinned task first - FEED's
    # only eligible unit is no longer free, so it's simply dropped this
    # turn, never handed to unit 1 (whose own inventory the real
    # interpreter wouldn't resolve it against).
    urgent_pinned = Task(priority=PRIORITY_PREVENT_LOSS, pos=(0, 0), op="PICKUP", item="WHEAT", unit_index=0)
    feed = Task(priority=PRIORITY_PREVENT_LOSS, pos=(9, 9), op="FEED", eligible_units=(0,))
    assignment = assign_units([urgent_pinned, feed], [(0, 0), (9, 9)])
    assert assignment == [urgent_pinned, None]


def test_assign_units_bit_identical_when_no_task_declares_eligible_units():
    # Negative control: with eligible_units unused throughout, the new
    # restricted stage never has anything to resolve - same outcome as
    # test_assign_units_serves_the_nearest_task_within_a_tier.
    near = Task(priority=PRIORITY_HARVEST, pos=(1, 0), op="HARVEST")
    far = Task(priority=PRIORITY_HARVEST, pos=(9, 9), op="HARVEST")
    assignment = assign_units([far, near], [(0, 0)])
    assert assignment == [near]


# --- build_task_list: FEED/PICKUP multi-unit awareness (T8.39) ---------


def test_build_task_list_lets_a_hand_feed_with_its_own_wheat_when_unpinned():
    tiles = _empty_tiles()
    tiles[5][5] = _animal_tile(fed_today=False, consecutive_unfed=1)
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0), (5, 5)],
        inventories=[{}, {"WHEAT": 3}],
        feed_pickup_unpinned=True,
    )
    feed = next(t for t in tasks if t.op == "FEED")
    assert feed.unit_index is None
    assert feed.eligible_units == (1,)


def test_build_task_list_ignores_a_hand_holding_wheat_when_not_unpinned():
    # feed_pickup_unpinned defaults False: only unit 0's own inventory is
    # ever consulted for WHEAT - a hand holding it is treated exactly
    # like nobody holding it, so a PICKUP is proposed instead of a FEED
    # (this is the real coupling documented in build_task_list's own
    # docstring: HARVEST can put WHEAT in a hand's inventory too, so this
    # can't be unconditional plumbing).
    tiles = _empty_tiles()
    tiles[5][5] = _animal_tile(fed_today=False, consecutive_unfed=1)
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0), (5, 5)],
        inventories=[{}, {"WHEAT": 3}],
        shed={"WHEAT": 5},
    )
    assert [t for t in tasks if t.op == "FEED"] == []
    pickup = [t for t in tasks if t.op == "PICKUP" and t.item == "WHEAT"]
    assert len(pickup) == 1
    assert pickup[0].unit_index == 0


def test_build_task_list_multiple_wheat_holders_give_ascending_eligible_units():
    tiles = _empty_tiles()
    tiles[5][5] = _animal_tile(fed_today=False, consecutive_unfed=1)
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0), (1, 1), (2, 2)],
        inventories=[{}, {"WHEAT": 2}, {"WHEAT": 1}],
        feed_pickup_unpinned=True,
    )
    feed = next(t for t in tasks if t.op == "FEED")
    assert feed.eligible_units == (1, 2)


def test_build_task_list_unpins_wheat_pickup_when_flag_is_on():
    tiles = _empty_tiles()
    tiles[5][5] = _animal_tile(fed_today=False, consecutive_unfed=1)
    tasks = build_task_list(tiles, shed={"WHEAT": 5}, feed_pickup_unpinned=True)
    pickup = next(t for t in tasks if t.op == "PICKUP" and t.item == "WHEAT")
    assert pickup.unit_index is None


def test_build_task_list_does_not_repropose_wheat_pickup_when_a_hand_already_holds_enough():
    # Livelock guard (T6.4/T8.4's original finding, now generalized): a
    # hand already carrying wheat must not trigger a fresh PICKUP -
    # feed_needed_tiles (1) does not exceed len(wheat_units) (1).
    tiles = _empty_tiles()
    tiles[5][5] = _animal_tile(fed_today=False, consecutive_unfed=1)
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0), (5, 5)],
        inventories=[{}, {"WHEAT": 3}],
        shed={"WHEAT": 5},
        feed_pickup_unpinned=True,
    )
    assert [t for t in tasks if t.op == "PICKUP" and t.item == "WHEAT"] == []
    feed = next(t for t in tasks if t.op == "FEED")
    assert feed.eligible_units == (1,)


def test_build_task_list_pickup_count_reflects_the_holder_shortfall():
    # Two animal tiles need feeding, only one unit holds wheat: N vs M -
    # still exactly one aggregate PICKUP task (batched, same as always),
    # but it IS required (2 needy tiles > 1 holder). Not reachable at
    # today's shipped max_animals_per_type=1, but the generalized
    # condition must still get this right.
    tiles = _empty_tiles()
    tiles[3][3] = _animal_tile(fed_today=False, consecutive_unfed=1)
    tiles[6][6] = _animal_tile(fed_today=False, consecutive_unfed=1)
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0)],
        farmer_inventory={"WHEAT": 3}, shed={"WHEAT": 5},
    )
    pickups = [t for t in tasks if t.op == "PICKUP" and t.item == "WHEAT"]
    assert len(pickups) == 1
    feeds = [t for t in tasks if t.op == "FEED"]
    assert len(feeds) == 2  # both tiles propose FEED bound to the same holder


def test_build_task_list_wheat_pickup_position_stays_farmer_anchored_when_unpinned():
    tiles = _empty_tiles()
    tiles[9][9] = _animal_tile(fed_today=False, consecutive_unfed=1)
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0), (9, 9)],
        shed={"WHEAT": 5}, feed_pickup_unpinned=True,
    )
    pickup = next(t for t in tasks if t.op == "PICKUP" and t.item == "WHEAT")
    # Anchored to unit_positions[:1] (the farmer) regardless of which unit
    # is nearest the shed or eventually executes it (T8.2's stability
    # argument - see build_task_list's own comment at this call site).
    assert pickup.pos in shed_access_tiles(10)


def test_build_task_list_binds_fertilize_to_the_unit_holding_fertilizer():
    tiles = _empty_tiles()
    tiles[2][2] = _plant_tile(watered_today=True)
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0), (2, 2)],
        inventories=[{}, {"FERTILIZER": 1}],
        use_fertilizer=True,
    )
    fert = next(t for t in tasks if t.op == "FERTILIZE")
    assert fert.unit_index is None
    assert fert.eligible_units == (1,)


def _step_toward(pos: tuple[int, int], target: tuple[int, int]) -> tuple[int, int]:
    if pos == target:
        return pos
    x, y = pos
    tx, ty = target
    dx, dy = tx - x, ty - y
    if dx != 0:
        return (x + (1 if dx > 0 else -1), y)
    return (x, y + (1 if dy > 0 else -1))


def test_greedy_assignment_is_stable_under_one_step_moves():
    # The no-memory stability property T8.2's design relies on
    # (tasks/plan.md's proof): once a unit is heading toward its
    # assigned task, re-running assign_units after each single-tile move
    # must keep assigning it the *same* task, never flip mid-walk to a
    # different one in the same tier - decide() is a pure function of the
    # observation with no memory of "what I was already doing."
    tasks = [
        Task(priority=PRIORITY_ROUTINE_CARE, pos=(0, 0), op="WATER"),
        Task(priority=PRIORITY_ROUTINE_CARE, pos=(9, 9), op="WATER"),
        Task(priority=PRIORITY_ROUTINE_CARE, pos=(5, 0), op="WATER"),
    ]
    units = [(2, 2), (7, 7), (5, 5)]
    assignment = assign_units(tasks, units)

    for _ in range(12):
        units = [
            _step_toward(u, assignment[i].pos) if assignment[i] is not None else u
            for i, u in enumerate(units)
        ]
        new_assignment = assign_units(tasks, units)
        for i in range(len(units)):
            if assignment[i] is not None and units[i] != assignment[i].pos:
                assert new_assignment[i] == assignment[i], (
                    f"unit {i} switched tasks before reaching {assignment[i].pos}"
                )
        assignment = new_assignment


# --- action_for_unit -----------------------------------------------------


def test_action_for_unit_returns_pass_with_no_task():
    assert action_for_unit((4, 4), None) == ["PASS"]


def test_action_for_unit_performs_the_op_when_already_on_the_tile():
    task = Task(priority=PRIORITY_HARVEST, pos=(4, 4), op="HARVEST")
    assert action_for_unit((4, 4), task) == ["HARVEST"]


def test_action_for_unit_includes_crop_for_plant():
    task = Task(priority=PRIORITY_PLANT, pos=(4, 4), op="PLANT", crop="WHEAT")
    assert action_for_unit((4, 4), task) == ["PLANT", "WHEAT"]


def test_action_for_unit_moves_toward_the_task_when_not_there_yet():
    task = Task(priority=PRIORITY_HARVEST, pos=(4, 4), op="HARVEST")
    action = action_for_unit((0, 4), task)
    assert action == ["EAST"]  # dx > 0


def test_action_for_unit_movement_actually_reduces_distance():
    task = Task(priority=PRIORITY_HARVEST, pos=(4, 4), op="HARVEST")
    start = (0, 0)
    move = action_for_unit(start, task)[0]
    deltas = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}
    dx, dy = deltas[move]
    new_pos = (start[0] + dx, start[1] + dy)
    assert tile_distance(new_pos, task.pos) < tile_distance(start, task.pos)


# --- T8.41: animal_pickup_unpinned -----------------------------------
#
# The one remaining farmer-only pin (see tasks._PINNED_UNIT_INDEX's own
# docstring) - mirrors feed_pickup_unpinned's own unit_index mechanism
# for the animal PICKUP task specifically.


def test_build_task_list_still_pins_animal_pickup_by_default():
    # Negative control / bit-identical-off check: matches the pre-T8.41
    # test_build_task_list_pins_animal_pickup_to_unit_0 exactly, just
    # naming the new flag explicitly at its default.
    tiles = _empty_tiles()
    tiles[3][3] = {"kind": "PASTURE"}
    tasks = build_task_list(
        tiles, desired_animal="COW", shed={"COW": 1}, animal_pickup_unpinned=False,
    )
    pickup = next(t for t in tasks if t.op == "PICKUP" and t.item == "COW")
    assert pickup.unit_index == 0


def test_build_task_list_unpins_animal_pickup_when_flag_is_on():
    tiles = _empty_tiles()
    tiles[3][3] = {"kind": "PASTURE"}
    tasks = build_task_list(
        tiles, desired_animal="COW", shed={"COW": 1}, animal_pickup_unpinned=True,
    )
    pickup = next(t for t in tasks if t.op == "PICKUP" and t.item == "COW")
    assert pickup.unit_index is None


def test_assign_units_lets_a_nearer_hand_take_the_unpinned_animal_pickup():
    # A free hand nearer the shed access tile than the farmer takes the
    # PICKUP once unpinned - the whole point (a busy/far farmer no
    # longer blocks animal setup).
    tiles = _empty_tiles()
    tiles[3][3] = {"kind": "PASTURE"}
    farmer, hand = (9, 9), (4, 4)  # hand stands right on a shed-access tile
    tasks = build_task_list(
        tiles, unit_positions=[farmer, hand],
        desired_animal="COW", shed={"COW": 1}, animal_pickup_unpinned=True,
    )
    pickup = next(t for t in tasks if t.op == "PICKUP" and t.item == "COW")
    assignment = assign_units([pickup], [farmer, hand])
    assert assignment == [None, pickup]  # the nearer hand (index 1), not the farmer


def test_build_task_list_unpinned_animal_pickup_position_stays_farmer_anchored():
    # Same convention as the wheat PICKUP (T8.2's stability argument):
    # the *target position* doesn't move just because execution can now
    # go to a different unit.
    tiles = _empty_tiles()
    tiles[3][3] = {"kind": "PASTURE"}
    tasks = build_task_list(
        tiles, unit_positions=[(4, 4), (9, 9)],
        desired_animal="COW", shed={"COW": 1}, animal_pickup_unpinned=True,
    )
    pickup = next(t for t in tasks if t.op == "PICKUP" and t.item == "COW")
    assert pickup.pos in shed_access_tiles(10)


# --- T8.41: prioritize_animal_setup -----------------------------------
#
# BUILD_COOP/BUILD_PASTURE/animal-PICKUP/PLACE default to PRIORITY_PLANT
# (the same tier as ordinary crop planting); this flag lifts them to
# PRIORITY_ANIMAL_SETUP (below PREVENT_LOSS/HARVEST, above ROUTINE_CARE/
# PLANT) instead.


def test_build_task_list_animal_tasks_stay_at_plant_priority_by_default():
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], desired_animal="COW", shed={"COW": 1})
    assert tasks[0].priority == PRIORITY_PLANT


def test_build_task_list_prioritizes_build_when_flag_is_on():
    tiles = _empty_tiles()
    tasks = build_task_list(
        tiles, unit_positions=[(4, 4)], desired_animal="COW", shed={"COW": 1},
        prioritize_animal_setup=True,
    )
    assert tasks[0].op == "BUILD_PASTURE"
    assert tasks[0].priority == PRIORITY_ANIMAL_SETUP


def test_build_task_list_prioritizes_animal_pickup_when_flag_is_on():
    tiles = _empty_tiles()
    tiles[3][3] = {"kind": "PASTURE"}
    tasks = build_task_list(
        tiles, desired_animal="COW", shed={"COW": 1}, prioritize_animal_setup=True,
    )
    pickup = next(t for t in tasks if t.op == "PICKUP" and t.item == "COW")
    assert pickup.priority == PRIORITY_ANIMAL_SETUP


def test_build_task_list_prioritizes_place_when_flag_is_on():
    tiles = _empty_tiles()
    tiles[4][4] = _empty_structure("PASTURE")
    tasks = build_task_list(
        tiles, unit_positions=[(0, 0)], desired_animal="COW", farmer_inventory={"COW": 1},
        prioritize_animal_setup=True,
    )
    assert tasks[0].op == "PLACE"
    assert tasks[0].priority == PRIORITY_ANIMAL_SETUP


def test_build_task_list_prioritize_animal_setup_does_not_affect_plant_crop_tasks():
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, plant_crop="CARROT", prioritize_animal_setup=True)
    assert all(t.priority == PRIORITY_PLANT for t in tasks if t.op == "PLANT")


def test_assign_units_prioritized_animal_setup_wins_over_harvest_and_care():
    # PRIORITY_ANIMAL_SETUP resolves before PRIORITY_ROUTINE_CARE/
    # PRIORITY_PLANT work, so on a farm with just one free unit, the
    # animal setup task wins over a routine (non-urgent) WATER even
    # though that WATER task sits right under the unit's feet.
    build = Task(priority=PRIORITY_ANIMAL_SETUP, pos=(9, 9), op="BUILD_PASTURE")
    routine_water = Task(priority=PRIORITY_ROUTINE_CARE, pos=(0, 0), op="WATER")
    assignment = assign_units([build, routine_water], [(0, 0)])
    assert assignment == [build]


def test_assign_units_prioritized_animal_setup_still_yields_to_prevent_loss():
    # An unplaced animal is idle capital, not at real risk - a genuine
    # PREVENT_LOSS task (something actually about to be lost) still
    # resolves first even with the flag on.
    urgent_water = Task(priority=PRIORITY_PREVENT_LOSS, pos=(9, 9), op="WATER")
    build = Task(priority=PRIORITY_ANIMAL_SETUP, pos=(0, 0), op="BUILD_PASTURE")
    assignment = assign_units([urgent_water, build], [(0, 0)])
    # Only one free unit: PREVENT_LOSS resolves first, leaving nothing
    # free for the animal-setup tier this turn.
    assert assignment == [urgent_water]
