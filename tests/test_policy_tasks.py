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

from kagg.gamelib.farm import tile_distance
from kagg.policy.tasks import (
    PRIORITY_HARVEST,
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


def _animal_tile(consecutive_unfed=0, fed_today=False, yield_units=0, fertilizer_available=False) -> dict:
    return {
        "kind": "COOP",
        "animal": "GOOSE",
        "placed_day": 0,
        "yield_units": yield_units,
        "consecutive_unfed": consecutive_unfed,
        "fed_today": fed_today,
        "cared_today": False,
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


def test_build_task_list_flags_prevent_loss_feeding():
    tiles = _empty_tiles()
    tiles[3][3] = _animal_tile(consecutive_unfed=1, fed_today=False)
    tasks = build_task_list(tiles)
    assert any(t.priority == PRIORITY_PREVENT_LOSS and t.op == "FEED" and t.pos == (3, 3) for t in tasks)


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
    # turn's* candidate work, not "plant the whole farm at once."
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, plant_crop="CARROT")
    assert len([t for t in tasks if t.op == "PLANT"]) == 1


def test_build_task_list_plants_the_nearest_empty_tile_not_the_first_scanned():
    # T6.2's real, verified fix (found while explaining the game's board
    # geometry to the user): the farm spawns near the board center
    # (4,4), not (0,0) - picking the first empty tile in row-major scan
    # order previously meant walking to the far corner every time.
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], plant_crop="CARROT")
    assert len(tasks) == 1
    assert tasks[0].pos == (4, 4)  # farmer's own tile is empty and nearest possible


def test_build_task_list_plants_the_tile_closest_to_any_unit_among_several_empty():
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(9, 9)], plant_crop="CARROT")
    assert tasks[0].pos == (9, 9)  # nearest to the given unit, not (0, 0)


def test_build_task_list_falls_back_to_scan_order_without_unit_positions():
    # No unit_positions given - preserves the old, simpler behavior
    # rather than guessing (decide() always supplies real positions in
    # practice; this is a graceful default, not the intended real-play
    # path).
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, plant_crop="CARROT")
    assert tasks[0].pos == (0, 0)


# --- animal acquisition pipeline (T6.2) ----------------------------------


def _empty_structure(kind: str) -> dict:
    return {"kind": kind}


def test_build_task_list_builds_a_structure_when_none_exists_yet():
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], desired_animal="COW", have_animal=False)
    assert len(tasks) == 1
    assert tasks[0].op == "BUILD_PASTURE"  # COW's structure, per gamelib.constants.ANIMALS
    assert tasks[0].pos == (4, 4)


def test_build_task_list_builds_proactively_even_when_the_animal_is_already_held():
    # Design decision from tasks/plan.md T6.2: building doesn't wait on
    # already owning the animal - it can run in parallel with the
    # BUY_ANIMAL order.
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], desired_animal="COW", have_animal=True)
    assert len(tasks) == 1
    assert tasks[0].op == "BUILD_PASTURE"


def test_build_task_list_builds_coop_for_goose():
    tiles = _empty_tiles()
    tasks = build_task_list(tiles, unit_positions=[(4, 4)], desired_animal="GOOSE", have_animal=False)
    assert tasks[0].op == "BUILD_COOP"


def test_build_task_list_places_a_held_animal_on_a_matching_empty_structure():
    tiles = _empty_tiles()
    tiles[4][4] = _empty_structure("PASTURE")
    tasks = build_task_list(tiles, unit_positions=[(0, 0)], desired_animal="COW", have_animal=True)
    assert len(tasks) == 1
    assert tasks[0].op == "PLACE"
    assert tasks[0].pos == (4, 4)
    assert tasks[0].animal == "COW"


def test_build_task_list_does_nothing_when_structure_exists_but_animal_not_held():
    # Structure already built, BUY_ANIMAL hasn't landed yet (decide()'s
    # job, pending) - neither BUILD (already done) nor PLACE (nothing to
    # place) applies this turn.
    tiles = _empty_tiles()
    tiles[4][4] = _empty_structure("PASTURE")
    tasks = build_task_list(tiles, unit_positions=[(0, 0)], desired_animal="COW", have_animal=False)
    assert tasks == []


def test_build_task_list_ignores_a_mismatched_empty_structure():
    # An empty COOP sits idle when the desired animal needs a PASTURE.
    tiles = _empty_tiles()
    tiles[4][4] = _empty_structure("COOP")
    tasks = build_task_list(tiles, unit_positions=[(0, 0)], desired_animal="COW", have_animal=True)
    assert tasks[0].op == "BUILD_PASTURE"  # builds a fresh PASTURE elsewhere, ignoring the COOP


def test_build_task_list_places_on_the_nearest_matching_structure():
    tiles = _empty_tiles()
    tiles[0][0] = _empty_structure("PASTURE")
    tiles[9][9] = _empty_structure("PASTURE")
    tasks = build_task_list(tiles, unit_positions=[(9, 8)], desired_animal="COW", have_animal=True)
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
