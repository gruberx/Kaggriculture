"""Task layer: a prioritized list of per-tile work, and greedy farmer/hand
assignment against it - see SPEC-policy.md "2. Task layer" (every turn).

Priority order per SPEC-policy.md: prevent-loss actions outrank harvest-
value, which outranks plant-new-tile, which outranks opportunistic
maintenance (DIG, COLLECT_FERTILIZER). This module adds one tier not
explicitly named in that list, between harvest-value and plant-new-tile:
*routine* watering/feeding - a plant/animal that's safe today
(consecutive_unwatered/consecutive_unfed == 0) but hasn't been tended yet
still needs it eventually (for the watering-bonus window, and because
`consecutive_unwatered` starts accumulating the moment it's skipped), but
it isn't the same urgent, "one more miss and it's gone" situation that
`consecutive_unwatered/consecutive_unfed >= 1` is (SPEC-gamelib.md: 2
consecutive misses converts the tile to a weed / the animal escapes).

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

from dataclasses import dataclass

from kagg.gamelib.farm import tile_distance

PRIORITY_PREVENT_LOSS = 0
PRIORITY_HARVEST = 1
PRIORITY_ROUTINE_CARE = 2
PRIORITY_PLANT = 3
PRIORITY_MAINTENANCE = 4


@dataclass(frozen=True)
class Task:
    priority: int
    pos: tuple[int, int]
    op: str  # "WATER" | "HARVEST" | "FEED" | "PLANT" | "DIG" | "COLLECT_FERTILIZER"
    crop: str | None = None  # only set for PLANT tasks


def build_task_list(tiles, plant_crop: str | None = None) -> list[Task]:
    """Scan the farm's tiles and produce a priority-sorted task list.

    `plant_crop` is the crop to plant on the first empty tile found, if
    any (sourced from the strategic layer's portfolio ranking - see
    SPEC-policy.md "1. Strategic layer" / kagg.policy.strategy) - `None`
    means don't plant this turn (no seeds available, or nothing worth
    planting). Only one PLANT task is ever produced per call: one action
    plants (at most) one tile, so there's nothing to gain from listing
    every empty tile as a candidate right now.
    """
    tasks: list[Task] = []
    planted_this_call = False
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            pos = (x, y)
            if tile is None:
                if plant_crop is not None and not planted_this_call:
                    tasks.append(Task(PRIORITY_PLANT, pos, "PLANT", crop=plant_crop))
                    planted_this_call = True
                continue
            if not isinstance(tile, dict):
                continue  # "LOCKED"
            kind = tile.get("kind")
            if kind == "WEED":
                tasks.append(Task(PRIORITY_MAINTENANCE, pos, "DIG"))
            elif kind == "PLANT":
                tasks.extend(_plant_tile_tasks(pos, tile))
            elif "animal" in tile:
                tasks.extend(_animal_tile_tasks(pos, tile))
            # An empty COOP/PASTURE (no "animal" key) has nothing to do.
    tasks.sort(key=lambda t: t.priority)
    return tasks


def _plant_tile_tasks(pos: tuple[int, int], tile: dict) -> list[Task]:
    tasks = []
    if not tile.get("watered_today", False):
        urgent = tile.get("consecutive_unwatered", 0) >= 1
        priority = PRIORITY_PREVENT_LOSS if urgent else PRIORITY_ROUTINE_CARE
        tasks.append(Task(priority, pos, "WATER"))
    if tile.get("yield_units", 0) > 0:
        tasks.append(Task(PRIORITY_HARVEST, pos, "HARVEST"))
    return tasks


def _animal_tile_tasks(pos: tuple[int, int], tile: dict) -> list[Task]:
    tasks = []
    if not tile.get("fed_today", False):
        urgent = tile.get("consecutive_unfed", 0) >= 1
        priority = PRIORITY_PREVENT_LOSS if urgent else PRIORITY_ROUTINE_CARE
        tasks.append(Task(priority, pos, "FEED"))
    if tile.get("yield_units", 0) > 0:
        tasks.append(Task(PRIORITY_HARVEST, pos, "HARVEST"))
    if tile.get("fertilizer_available", False):
        tasks.append(Task(PRIORITY_MAINTENANCE, pos, "COLLECT_FERTILIZER"))
    return tasks


def assign_units(tasks: list[Task], unit_positions: list[tuple[int, int]]) -> list[Task | None]:
    """Greedily assign each unit position to at most one task.

    Processes `tasks` in the order given (callers pass the priority-sorted
    output of build_task_list - this function doesn't re-sort, so a
    caller with a pre-filtered/reordered list gets exactly that order),
    claiming the *closest* still-unclaimed unit for each task in turn -
    priority dominates proximity by construction (an earlier, higher-
    priority task always gets first pick of units, even a distant one,
    before a later task - possibly closer to some idle unit - is
    considered at all), and proximity only breaks ties *within* a
    priority tier. At up to 100 tiles and a handful of units, this is a
    bounded greedy assignment, not a search problem (SPEC-policy.md).

    Returns a list the same length and order as `unit_positions`; an
    unassigned unit's slot is `None`.
    """
    assignment: list[Task | None] = [None] * len(unit_positions)
    claimed: set[int] = set()
    for task in tasks:
        candidates = [i for i in range(len(unit_positions)) if i not in claimed]
        if not candidates:
            break
        closest = min(candidates, key=lambda i: tile_distance(unit_positions[i], task.pos))
        assignment[closest] = task
        claimed.add(closest)
    return assignment


_MOVES = {
    "EAST": (1, 0),
    "WEST": (-1, 0),
    "SOUTH": (0, 1),
    "NORTH": (0, -1),
}


def action_for_unit(unit_pos: tuple[int, int], task: Task | None) -> list:
    """The farmer/hand op list for this turn, given a unit's current
    position and its assigned task (or None): a movement step toward the
    task's tile if not standing on it yet, otherwise the task's actual
    operation (units can only act on the tile they occupy).
    """
    if task is None:
        return ["PASS"]
    if unit_pos == task.pos:
        if task.op == "PLANT":
            return ["PLANT", task.crop]
        return [task.op]
    x, y = unit_pos
    tx, ty = task.pos
    dx, dy = tx - x, ty - y
    # Closes one axis at a time - either choice reduces Manhattan
    # distance by exactly 1 when one axis still differs, and FARMER_MOVES
    # has no diagonal, so there's no "more efficient" single-step choice
    # to prefer between them.
    if dx != 0:
        return ["EAST" if dx > 0 else "WEST"]
    return ["SOUTH" if dy > 0 else "NORTH"]
