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

from kagg.gamelib.constants import ANIMALS, CROPS
from kagg.gamelib.farm import shed_access_tiles, shed_distance, tile_distance
from kagg.gamelib.growth import watering_bonus_window

# investment_anchor values (params.py's DEFAULT_PARAMS["investment_anchor"]):
# SHED anchors new-investment placement to the board's shed center - the
# T8.1 fix (tasks/plan.md) for a real, measured defect: anchoring to the
# farmer's *current* position instead made the planted plot grow as a
# runaway line away from the shed, and kaggriculture.py's own _end_of_day
# teleports the farmer back to spawn (a shed-access tile) and despawns
# every hand every single day, so travel-from-shed is what's actually
# repaid daily. UNIT restores the pre-T8.1 behavior exactly, kept as a
# real, arena-checkable alternative rather than deleted outright - never
# hardcode a judgment call here that the arena can settle instead.
_ANCHOR_SHED = "SHED"
_ANCHOR_UNIT = "UNIT"
# T8.3c (tasks/plan.md), designed together with the user after T8.3b found
# plain SHED loses even combined with the accepted T8.9 fix: keeps
# distance-to-farmer as the *primary* key (SHED's mistake was replacing
# it entirely, which can force a real detour) and only changes the
# *tie-break* among candidates exactly as close to the farmer, toward
# shed_distance - attacking the actual traced cause of the runaway-line
# pathology (UNIT's own tie-break is row-major scan order, unrelated to
# the shed) without ever costing more travel than plain UNIT already
# does for that specific choice. See `_compact_position`'s docstring.
_ANCHOR_UNIT_TOWARD_SHED = "UNIT_TOWARD_SHED"

PRIORITY_PREVENT_LOSS = 0
PRIORITY_HARVEST = 1
PRIORITY_ROUTINE_CARE = 2
PRIORITY_PLANT = 3
# T8.15: a real intermediate tier between PLANT and MAINTENANCE - not
# named in SPEC-policy.md's original four-tier list, added specifically
# for `water_bonus_window_aware`'s out-of-window watering (see
# `_plant_tile_tasks`'s own docstring). T8.11 first tried demoting this
# work all the way to PRIORITY_MAINTENANCE and measured a real, decisive
# loss (WEED count tripled - see `kagg.policy.decide._DEFAULT_WATER_
# BONUS_WINDOW_AWARE`'s comment): tied with DIG/COLLECT_FERTILIZER, it
# could miss 2 consecutive days once PLANT tasks filled the queue ahead
# of it, converting productive tiles to weed. This tier still yields to
# PLANT (so PLANT keeps winning the tiles T8.11 was built to free), but
# outranks true opportunistic maintenance, giving a real shot at being
# reached before a second consecutive miss. `assign_units` groups tiers
# via `sorted({t.priority for t in tasks})` - any sortable value works,
# no other code needs to change to support a value between two existing
# integer tiers.
PRIORITY_LOW_VALUE_CARE = 3.5
PRIORITY_MAINTENANCE = 4

# How much WHEAT to PICKUP in one trip once any is needed for feeding -
# more than the 1 unit a single FEED consumes, so the farmer doesn't have
# to revisit the shed every single day an animal needs feeding. Matches
# params.DEFAULT_PARAMS's wheat_restock_qty default (10) in spirit, not
# by import - this module has no dependency on kagg.policy.params.
_WHEAT_PICKUP_BATCH = 10

# T8.4: decide() models only inventories[0] (`_farmer_inventory`'s own
# convention, documented there) - correct by construction only because
# every task the real interpreter resolves against the *acting unit's
# own* inventory (kaggriculture.py's PICKUP/FEED/PLACE handlers, verified
# directly) is pinned here to this exact unit index, so a hired hand can
# never silently pick up wheat/an animal, feed, or place one into an
# inventory slot decide() never looks at again. WATER/HARVEST/DIG/
# COLLECT_FERTILIZER/CARE/PLANT (consumes the shared private["seeds"],
# not any unit's inventory)/BUILD_COOP/BUILD_PASTURE are deliberately
# left unpinned - a hand doing one of those in parallel is free
# throughput at no correctness cost.
_PINNED_UNIT_INDEX = 0


@dataclass(frozen=True)
class Task:
    priority: int
    pos: tuple[int, int]
    # "WATER"|"HARVEST"|"FEED"|"FERTILIZE"|"PLANT"|"DIG"|"CARE"|
    # "COLLECT_FERTILIZER"|"BUILD_COOP"|"BUILD_PASTURE"|"PLACE"|"PICKUP"
    op: str
    crop: str | None = None  # only set for PLANT tasks
    animal: str | None = None  # only set for PLACE tasks
    item: str | None = None  # only set for PICKUP tasks
    qty: int = 1  # only meaningful for PICKUP tasks
    # T8.4: pins this task to a specific unit index (always 0, the
    # farmer, in practice today) rather than letting assign_units pick
    # whichever unit is nearest. Trailing field (with a default), so
    # every existing positional Task(...) construction in this module
    # and its tests keeps working unchanged. See
    # `_UNIT_BOUND_INVENTORY_OPS`/assign_units's own docstring for why
    # this exists at all and which ops need it.
    unit_index: int | None = None


def _closest_pos(candidates: list[tuple[int, int]], unit_positions) -> tuple[int, int] | None:
    """Nearest candidate position to any given unit, or the first
    candidate in scan order if no unit positions are known.

    Found and fixed as part of T6.2 (tasks/plan.md), not anticipated in
    advance: the farm spawns near the board's center (verified directly
    in kaggriculture.py: (4, 4), not (0, 0) - see tasks/plan.md's T6.2
    entry), so picking the first empty tile in row-major scan order
    meant walking to the far corner every time, a real, measured
    movement inefficiency, not a hypothetical one. The scan-order
    fallback (no unit_positions given) is a graceful default for callers
    that don't care which tile, not the intended real-play path -
    decide() always supplies real unit positions.
    """
    if not candidates:
        return None
    if not unit_positions:
        return candidates[0]
    return min(candidates, key=lambda pos: min(tile_distance(pos, u) for u in unit_positions))


def _compact_position(candidates, board_size: int, anchor: str, unit_positions) -> tuple[int, int] | None:
    """The single best candidate position for new investment work - see
    the `_ANCHOR_*` constants above.

    `anchor="UNIT"` delegates to `_closest_pos` verbatim (not a
    reimplementation) specifically to preserve its exact tie-break
    behavior (first-in-scan-order among equidistant candidates, since
    `min()` with no secondary key keeps the first element it encounters
    that ties the best). Found the hard way, not anticipated: an earlier
    version of this function used a `(distance, pos)` key for *both*
    anchors, which ties equidistant candidates by (x, y) tuple order
    instead - a *different* order than `empty_tiles`' actual append order
    (row-major, i.e. (y, x)) - and that alone silently changed two golden
    episodes' outcomes even with `anchor="UNIT"`, which is supposed to be
    indistinguishable from the pre-T8.1 code. Confirmed by reproducing
    the golden table with `anchor="UNIT"` forced and finding exactly
    those two mismatches before this fix.

    `anchor="SHED"` uses a real `(shed_distance, pos)` key instead: unlike
    the UNIT case, there is no "original order" to preserve here, and a
    deterministic tie-break is genuinely needed - the four shed-access
    tiles are always tied at distance 0. The pos tie-break also makes the
    SHED key totally independent of unit positions, which is what makes
    tier-local task *servicing* order stable turn to turn once units have
    no memory (T8.2 relies on task positions never chasing a moving
    unit - see that task's stability argument in the plan file).

    `anchor="UNIT_TOWARD_SHED"` (T8.3c) keeps distance-to-farmer as the
    *primary* key - identical to plain UNIT's own primary criterion, so
    this never picks a candidate with a worse farmer-distance than plain
    UNIT would for the same board - and only uses `shed_distance` to
    break ties among candidates exactly as close to the farmer, with
    `pos` as the final tie-break (kept simple - a directional/rotating
    tie-break would need classifying an arbitrary global candidate's
    direction from the farmer, real added complexity for a third-level
    tie-break expected to rarely fire; revisit only if self-play or a
    real episode shows an actual lopsided-growth problem from this)."""
    if not candidates:
        return None
    if anchor == _ANCHOR_UNIT:
        return _closest_pos(candidates, unit_positions)
    if anchor == _ANCHOR_UNIT_TOWARD_SHED:
        return min(candidates, key=lambda pos: (
            min(tile_distance(pos, u) for u in unit_positions) if unit_positions else 0,
            shed_distance(pos, board_size),
            pos,
        ))
    return min(candidates, key=lambda pos: (shed_distance(pos, board_size), pos))


def _compact_positions(candidates, board_size: int, anchor: str, unit_positions, n: int) -> list:
    """Up to `n` distinct candidate positions (T8.6, for planting more
    than one tile in parallel per turn), picked one at a time via
    `_compact_position` itself - never a reimplementation of its
    selection logic, for the identical reason `anchor="UNIT"` delegates
    to `_closest_pos` verbatim rather than reimplementing it (see
    `_compact_position`'s own docstring: an earlier version's
    reimplementation silently used a different tie-break than the real
    one and changed real episode outcomes). The first position picked is
    therefore bit-identical to what `_compact_position` alone would
    return for the same candidate set; each subsequent position is "the
    best remaining candidate" by the same rule, a straightforward greedy
    extension, not a different algorithm. `n <= 0` or no candidates
    returns an empty list.
    """
    remaining = list(candidates)
    picked: list = []
    for _ in range(n):
        pos = _compact_position(remaining, board_size, anchor, unit_positions)
        if pos is None:
            break
        picked.append(pos)
        remaining.remove(pos)
    return picked


def build_task_list(
    tiles,
    unit_positions=(),
    plant_crop: str | None = None,
    desired_animal: str | None = None,
    shed: dict | None = None,
    farmer_inventory: dict | None = None,
    current_day: int = 0,
    anchor: str = _ANCHOR_SHED,
    use_fertilizer: bool = True,
    care_aware: bool = False,
    plant_qty: int = 1,
    water_bonus_window_aware: bool = False,
) -> list[Task]:
    """Scan the farm's tiles and produce a priority-sorted task list.

    `plant_crop` is the crop to plant, if any (sourced from the strategic
    layer's portfolio ranking - see SPEC-policy.md "1. Strategic layer" /
    kagg.policy.strategy) - `None` means don't plant this turn (no seeds
    available, or nothing worth planting). `plant_qty` (T8.6) is how many
    *distinct* empty tiles to propose a PLANT task for in one call -
    defaults to 1, reproducing the original "plant the single nearest
    empty tile" behavior exactly; `decide()` computes a real value scaled
    to the current labor force (`1 + hires_per_day(params)`) and seed
    stock on hand, capped by a real watering-capacity safety valve - see
    its own `plant_qty` comment for the formula. Capped internally at
    `len(empty_tiles)` and at `plant_qty` itself by `_compact_positions`;
    this function does not re-check seed stock (`decide()`'s own
    `plant_qty` computation already bounds it by `seeds[crop]` - see its
    own docstring for why that specific bound is load-bearing, not just
    a nicety: the real interpreter drops *every* PLANT request for a crop
    in a turn once demand exceeds seeds held).

    `desired_animal` (T6.2/T6.3/T6.4) generalizes the same idea to animal
    acquisition, now a real multi-step pipeline: builds the matching
    structure (BUILD_COOP/BUILD_PASTURE) proactively on the nearest empty
    tile if none exists yet (tasks/plan.md T6.2's design decision: this
    does not wait on already owning the animal - it runs in parallel with
    the BUY_ANIMAL order); PICKUPs a bought animal from the shed into the
    farmer's own inventory once a matching structure exists (T6.4's real
    finding - see `_new_investment_tasks`'s docstring for why this step
    exists at all); then PLACEs it once actually held. `shed` and
    `farmer_inventory` are both needed because they mean different
    things: `shed` is what's been bought (BUY_ANIMAL delivers there, not
    to any unit's inventory), `farmer_inventory` is what the farmer is
    actually carrying (what PLACE - and FEED/FERTILIZE, below - really
    consume from). Simplification, not an oversight: this whole pipeline is
    modeled as the *farmer's* (not any hand's) inventory - correct while
    `hires_per_day` defaults to 0; revisit once hiring is tuned to a
    nonzero value, since a hand could end up carrying the animal instead.

    At most one new-investment task (`PLANT`/`BUILD_COOP`/
    `BUILD_PASTURE`/`PICKUP`/`PLACE`) is ever produced per call - one
    action advances at most one investment, so there's nothing to gain
    from listing every candidate right now. `desired_animal` takes
    priority over `plant_crop` if both are somehow given (callers are
    expected to supply only one, mirroring `_top_investment_choice`'s
    single top pick, but this keeps behavior well-defined either way).
    A *separate* PICKUP task (for WHEAT, not an animal) can also fire
    independently, in place of a blocked FEED - see `_animal_tile_tasks`.

    `current_day` gates HARVEST for one-time crops (T6.3's real bug fix,
    not anticipated in advance - see `_is_actually_harvestable`'s own
    docstring for the full story). Defaults to 0 for callers that don't
    pass it (e.g. existing tests using `planted_day=0` fixtures), not the
    intended real-play path - `decide()` always supplies the real day.

    `anchor` (T8.1) controls where new-investment work (PLANT/BUILD_*/
    PLACE's target tile) gets placed - see `_ANCHOR_*` and
    `_placement_key` above. Defaults to `"SHED"`, a real fix for a real,
    measured defect (tasks/plan.md T8.1), not the old `"UNIT"` behavior.

    `care_aware` (T8.3q) gates whether a `CARE` task fires for a placed
    animal not yet cared for today - see `_animal_tile_tasks`'s own
    docstring for the mechanism (`CARE` banks a yield bonus paid out on
    the animal's next scheduled production). Defaults to `False`
    (matches `use_fertilizer`'s own convention of a boolean flag rather
    than always-on, since a real Kaggle action has a real single-farmer
    turn cost - see `decide.py`'s `_DEFAULT_ANIMAL_CARE_AWARE` for the
    measured story).

    `water_bonus_window_aware` (T8.11) gates whether an out-of-bonus-
    window WATER on a one-time crop gets demoted to `PRIORITY_
    MAINTENANCE` instead of `PRIORITY_ROUTINE_CARE` - see
    `_plant_tile_tasks`'s own docstring for the mechanism and its
    deliberate one-time-crop-only scope. Defaults to `False`, reproducing
    the exact prior behavior (every non-urgent WATER task at `PRIORITY_
    ROUTINE_CARE` regardless of age) for every caller that doesn't pass
    it.
    """
    shed = shed or {}
    farmer_inventory = farmer_inventory or {}
    tasks: list[Task] = []
    empty_tiles: list[tuple[int, int]] = []
    matching_structure_tiles: list[tuple[int, int]] = []
    desired_structure = ANIMALS[desired_animal]["structure"] if desired_animal is not None else None
    wheat_pickup_priority: int | None = None

    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            pos = (x, y)
            if tile is None:
                empty_tiles.append(pos)
                continue
            if not isinstance(tile, dict):
                continue  # "LOCKED"
            kind = tile.get("kind")
            if kind == "WEED":
                tasks.append(Task(PRIORITY_MAINTENANCE, pos, "DIG"))
            elif kind == "PLANT":
                tasks.extend(
                    _plant_tile_tasks(
                        pos, tile, current_day, farmer_inventory, use_fertilizer, water_bonus_window_aware
                    )
                )
            elif "animal" in tile:
                animal_tasks, needs_wheat_priority = _animal_tile_tasks(pos, tile, farmer_inventory, care_aware)
                tasks.extend(animal_tasks)
                if needs_wheat_priority is not None:
                    wheat_pickup_priority = (
                        needs_wheat_priority
                        if wheat_pickup_priority is None
                        else min(wheat_pickup_priority, needs_wheat_priority)
                    )
            elif kind == desired_structure:
                matching_structure_tiles.append(pos)
            # An empty COOP/PASTURE not matching desired_structure has
            # nothing to do.

    if wheat_pickup_priority is not None and shed.get("WHEAT", 0) > 0:
        # unit_positions[:1] (the farmer only), not every unit: this
        # PICKUP is pinned to the farmer regardless of which unit is
        # nearest (T8.4 pins the task itself; here, picking the shed tile
        # nearest to a *hand* instead would make the target flip as hands
        # move, which is exactly the kind of unit-position dependence
        # T8.2's stability argument needs this module to avoid).
        pos = _closest_pos(shed_access_tiles(len(tiles)), unit_positions[:1])
        qty = min(shed["WHEAT"], _WHEAT_PICKUP_BATCH)
        tasks.append(
            Task(wheat_pickup_priority, pos, "PICKUP", item="WHEAT", qty=qty, unit_index=_PINNED_UNIT_INDEX)
        )

    tasks.extend(
        _new_investment_tasks(
            empty_tiles, matching_structure_tiles, unit_positions, len(tiles),
            plant_crop, desired_animal, desired_structure, shed, farmer_inventory, anchor, plant_qty,
        )
    )

    # (priority, pos): deterministic and unit-position-independent (T8.2,
    # tasks/plan.md) - proximity-based servicing now lives entirely in
    # assign_units, not here. The old `key=lambda t: t.priority` was a
    # *stable* sort, so same-priority tasks kept pure row-major scan
    # order - with one unit, assign_units always took tasks[0], i.e. the
    # northwest-most tile of the top tier, however far away it was.
    tasks.sort(key=lambda t: (t.priority, t.pos))
    return tasks


def _new_investment_tasks(
    empty_tiles, matching_structure_tiles, unit_positions, board_size,
    plant_crop, desired_animal, desired_structure, shed, farmer_inventory, anchor=_ANCHOR_SHED,
    plant_qty: int = 1,
) -> list[Task]:
    """T6.4's real finding, not anticipated when T6.2 first wrote this
    pipeline: PLACE's real handler (kaggriculture.py) consumes the animal
    from the *acting unit's own inventory*, not the shed - BUY_ANIMAL
    delivers to the shed (verified directly: a real episode showed PLACE
    silently failing forever, the animal just sitting in the shed).
    A PICKUP step (standing on a real shed-access tile - see
    gamelib.farm.shed_access_tiles) is required in between.

    `anchor` (T8.1) governs where PLANT/BUILD_*/PLACE's *target* tile is
    chosen from among `empty_tiles`/`matching_structure_tiles` - see
    `_compact_position`. The PICKUP steps below choose which *shed*-
    access tile to stand on instead, always anchored to the farmer alone
    (`unit_positions[:1]`) regardless of `anchor` - see build_task_list's
    matching comment for why.

    The animal pipeline still ever proposes at most one task per call
    (BUILD_*/PICKUP/PLACE all stay singular - T8.6 only parallelizes
    planting, not animal acquisition, which is already a serial,
    single-animal-at-a-time pipeline by design - see `decide.py`'s own
    "never buy a second instance of an already-placed animal type"
    comment). Only the `plant_crop` branch can return more than one task,
    up to `plant_qty` (T8.6), one PLANT task per distinct empty tile via
    `_compact_positions` - see its own docstring for why this reuses
    `_compact_position`'s selection logic rather than reimplementing it.
    """
    if desired_animal is not None:
        animal_in_hand = farmer_inventory.get(desired_animal, 0) > 0
        animal_in_shed = shed.get(desired_animal, 0) > 0
        if animal_in_hand and matching_structure_tiles:
            pos = _compact_position(matching_structure_tiles, board_size, anchor, unit_positions)
            return [Task(PRIORITY_PLANT, pos, "PLACE", animal=desired_animal, unit_index=_PINNED_UNIT_INDEX)]
        if not matching_structure_tiles and empty_tiles:
            pos = _compact_position(empty_tiles, board_size, anchor, unit_positions)
            build_op = "BUILD_COOP" if desired_structure == "COOP" else "BUILD_PASTURE"
            return [Task(PRIORITY_PLANT, pos, build_op)]
        if matching_structure_tiles and animal_in_shed and not animal_in_hand:
            pos = _closest_pos(shed_access_tiles(board_size), unit_positions[:1])
            return [Task(PRIORITY_PLANT, pos, "PICKUP", item=desired_animal, qty=1, unit_index=_PINNED_UNIT_INDEX)]
        return []
    if plant_crop is not None and empty_tiles and plant_qty > 0:
        positions = _compact_positions(empty_tiles, board_size, anchor, unit_positions, plant_qty)
        return [Task(PRIORITY_PLANT, pos, "PLANT", crop=plant_crop) for pos in positions]
    return []


def _plant_tile_tasks(
    pos: tuple[int, int],
    tile: dict,
    current_day: int,
    farmer_inventory: dict,
    use_fertilizer: bool = True,
    water_bonus_window_aware: bool = False,
) -> list[Task]:
    tasks = []
    if not tile.get("watered_today", False):
        urgent = tile.get("consecutive_unwatered", 0) >= 1
        priority = PRIORITY_PREVENT_LOSS if urgent else PRIORITY_ROUTINE_CARE
        if water_bonus_window_aware and not urgent:
            # T8.11, the user's own observation: the real WATER handler
            # (kaggriculture.py:431-443) only ever adds yield for a
            # *one-time* crop (WHEAT/CARROT/MELON), and only on ages
            # inside watering_bonus_window(crop) - the same window
            # _crop_yield_and_tile_days already relies on for the
            # profitability table. Every other day's watering is purely
            # anti-weed insurance (avoids consecutive_unwatered reaching
            # 2), not a source of yield. Traced directly on a real
            # episode (seed 100): 20 MELON tiles planted at age 0 with a
            # window that doesn't open until age 6 burned ~140 farmer
            # turns on out-of-window watering over 8 days alone - turns
            # that could have gone to PLANT instead (the exact "labor
            # never reaches PRIORITY_PLANT while a farm-wide watering
            # tier is saturated" bottleneck this task's own plan traced).
            #
            # Deliberately scoped to one-time crops only - verified
            # directly against the real handler, not assumed: for an
            # *ongoing* crop (TOMATO/STRAWBERRY), WATER only ever sets
            # watered_today=True; base production fires purely on
            # _daily_refresh_plants' own schedule, completely independent
            # of watering (only the FERTILIZE combo bonus cares whether
            # the tile was watered that same day). There is no "bonus
            # window" concept for an ongoing crop's watering the way
            # there is for a one-time crop, so demoting it here would be
            # guessing at a mechanism that doesn't exist - left
            # completely untouched, a real, honest scope-narrowing, not
            # an oversight.
            #
            # T8.15: demoted to PRIORITY_LOW_VALUE_CARE, not PRIORITY_
            # MAINTENANCE - T8.11's own first attempt at MAINTENANCE
            # (tied with DIG/COLLECT_FERTILIZER, below PLANT) was measured
            # and rejected: PLANT count did rise (+14%, confirming labor
            # really was freed) but WEED count more than tripled, because
            # a demoted watering could then miss 2 consecutive days once
            # PLANT filled the queue ahead of it. PRIORITY_LOW_VALUE_CARE
            # still yields to PLANT (the whole point) but sits above true
            # opportunistic maintenance, giving it a real shot at being
            # reached before a second miss - see that constant's own
            # docstring.
            cd = CROPS[tile["crop"]]
            if not cd["ongoing"]:
                age = current_day - tile["planted_day"]
                if age not in watering_bonus_window(tile["crop"]):
                    priority = PRIORITY_LOW_VALUE_CARE
        tasks.append(Task(priority, pos, "WATER"))
    if tile.get("yield_units", 0) > 0 and _is_actually_harvestable(tile, current_day):
        tasks.append(Task(PRIORITY_HARVEST, pos, "HARVEST"))
    if (
        use_fertilizer
        and farmer_inventory.get("FERTILIZER", 0) > 0
        and tile.get("fertilized_until_day", -1) < current_day
    ):
        # T8.3e: the user's own observed defect - FERTILIZER was only
        # ever collected and sold, never applied. The real FERTILIZE
        # handler doubles the yield bonus on any day it's active *and*
        # the tile is watered that day (kaggriculture.py's
        # _daily_refresh_plants/WATER handler both gate the bonus on
        # `was_watered` - "basic needs first") for `fertilized_until_day
        # = max(existing, day+2)`, i.e. today plus the next two days.
        # Gated on `fertilized_until_day < current_day` (not merely
        # "already active") so this never fires while an earlier
        # application still fully covers today - the real handler's own
        # `max()` would make a second application on top of that a
        # complete no-op, silently wasting a real unit of FERTILIZER for
        # nothing. No crop-maturity/remaining-life targeting yet (same
        # simplicity level as the existing WATER task, which doesn't
        # check watering_bonus_window either) - a plausible refinement,
        # not yet measured to matter.
        #
        # PRIORITY_MAINTENANCE (below PRIORITY_PLANT), not
        # PRIORITY_ROUTINE_CARE - measured, not assumed: an earlier
        # version at ROUTINE_CARE (tied with WATER, and so outranking
        # PLANT) lost decisively in direct self-play (0/50 working, 0/50
        # held-out - every non-tied episode was a loss), traced to
        # FERTILIZE crowding out both farther routine watering and
        # opening new PLANT tiles - a modest 3-day yield bump on one
        # already-productive tile is a worse trade than either. At
        # MAINTENANCE it only fires once nothing more pressing is queued,
        # same tier as DIG/COLLECT_FERTILIZER.
        tasks.append(Task(PRIORITY_MAINTENANCE, pos, "FERTILIZE"))
    return tasks


def _is_actually_harvestable(tile: dict, current_day: int) -> bool:
    """True if a PLANT tile with `yield_units > 0` can really be
    HARVESTed right now, not just banked toward a future harvest.

    Real bug found and fixed during T6.3, not anticipated in advance:
    kaggriculture.py's _new_plant() sets a one-time crop's yield_units to
    1 *immediately* at planting, well before `day - planted_day >=
    first_yield_day` - the real HARVEST handler's own gate, which blocks
    regardless of yield_units already banked (the exact mechanic T3.5
    already found for melon timing). Proposing a HARVEST task anyway gave
    it PRIORITY_HARVEST, above PLANT/BUILD_*/PLACE's PRIORITY_PLANT -
    perpetually monopolizing the single farmer on a doomed-to-fail no-op
    for the crop's entire maturation period. Harmless before T6.2 (there
    was nothing else productive to do with that time anyway); directly
    measured to block a pending BUILD_PASTURE for ~2 real days once an
    animal investment became available (T6.3's golden-episode regression
    from 5274 to 3932, traced to exactly this before being fixed here).

    Ongoing crops (TOMATO/STRAWBERRY) don't have this problem: the real
    interpreter's own _daily_refresh_plants only ever increments their
    yield_units *after* first_yield_day (kaggriculture.py's HARVEST
    handler even warns if this invariant is ever violated), so
    yield_units > 0 already implies harvestable for them.
    """
    cd = CROPS[tile["crop"]]
    if cd["ongoing"]:
        return True
    return current_day - tile["planted_day"] >= cd["first_yield_day"]


def _animal_tile_tasks(
    pos: tuple[int, int], tile: dict, farmer_inventory: dict, care_aware: bool = False
) -> tuple[list[Task], int | None]:
    """Returns (tasks, wheat_pickup_priority) - the second element is
    `None` unless this tile needs feeding and the farmer isn't currently
    carrying any WHEAT to do it with (T6.4's finding, same root cause as
    PLACE's: FEED's real handler consumes from the acting unit's own
    inventory, not the shed - see `_new_investment_tasks`'s docstring).
    The caller aggregates this across all animal tiles into at most one
    PICKUP task, at the most urgent priority found.

    `care_aware` (T8.3q, the user's own observation): `CARE` banks a
    yield bonus (`pending_care_bonus`) on any day both fed and cared for,
    paid out on the animal's next scheduled production if fed that day -
    verified directly in `kaggriculture.py`'s `_daily_refresh_animals`
    and the official "Animal Care" docs. No escape consequence the way
    `FEED` has (`consecutive_unfed` has no `CARE` analog), so there is no
    "urgent" tier for this task the way `FEED`'s has - fires at
    `PRIORITY_MAINTENANCE`, the same tier as `COLLECT_FERTILIZER`
    (a real, explicit design choice, not swept across tiers: T8.3e's own
    FERTILIZE investigation found tier placement didn't change a
    structural single-farmer-capacity rejection, only how *early* it lost
    - see `kagg.policy.decide._DEFAULT_ANIMAL_CARE_AWARE` for the
    measured result). Gated (default `False`) since a real turn is
    genuinely spent on this, mirroring `use_fertilizer`'s own convention.
    """
    tasks = []
    wheat_pickup_priority = None
    if not tile.get("fed_today", False):
        urgent = tile.get("consecutive_unfed", 0) >= 1
        priority = PRIORITY_PREVENT_LOSS if urgent else PRIORITY_ROUTINE_CARE
        if farmer_inventory.get("WHEAT", 0) > 0:
            tasks.append(Task(priority, pos, "FEED", unit_index=_PINNED_UNIT_INDEX))
        else:
            wheat_pickup_priority = priority
    if tile.get("yield_units", 0) > 0:
        tasks.append(Task(PRIORITY_HARVEST, pos, "HARVEST"))
    if tile.get("fertilizer_available", False):
        tasks.append(Task(PRIORITY_MAINTENANCE, pos, "COLLECT_FERTILIZER"))
    if care_aware and not tile.get("cared_today", False):
        tasks.append(Task(PRIORITY_MAINTENANCE, pos, "CARE"))
    return tasks, wheat_pickup_priority


def assign_units(tasks: list[Task], unit_positions: list[tuple[int, int]]) -> list[Task | None]:
    """Assign each unit position to at most one task, processing
    priority tiers in order and matching greedily by distance *within*
    each tier (T8.2, tasks/plan.md - see that task's write-up for the
    full stability argument summarized here).

    Priority dominates proximity by construction: every tier is fully
    resolved (until it runs out of free units or free tasks) before the
    next, lower-priority tier is even looked at - a distant PREVENT_LOSS
    task always gets first pick of units over a closer ROUTINE_CARE one.
    Within a tier, the globally nearest (unit, task) pair is matched
    first, then removed, and the process repeats - not "each task
    claims its closest unit" in list order (T8.2's real fix: the old
    version did exactly that, so a single unit could be sent to a
    farther same-tier task simply because it appeared earlier in the
    list). Ties break on `(task.pos, unit_index)`, both independent of
    any unit's actual position, which is what makes this stable turn to
    turn for a `decide()` that has no memory of what a unit was already
    heading toward: as a unit takes one step closer to its assigned
    task, that task's distance strictly decreases while every other
    task's distance can decrease by at most the same amount, so it
    remains a minimizer (and ties only ever *leave* the minimal set,
    never enter it) - re-running this function after each single-tile
    move reproduces the same assignment for any unit still en route.

    T8.4: within each tier, a task with `unit_index` set (wheat/animal
    `PICKUP`, `FEED`, `PLACE` - see `_PINNED_UNIT_INDEX`'s own docstring
    for why exactly these ops) is resolved *before* the distance-based
    matching below, and only ever against that exact unit - never handed
    to a nearer hand instead. Deliberate, accepted consequence: if the
    pinned unit is already claimed by a higher-priority pinned task this
    same tier, the task is simply dropped for this turn (not serviced by
    anyone) rather than assigned to a unit whose own inventory the real
    interpreter wouldn't resolve it against - a silent no-op, not a
    silent wrong-inventory bug. Ties among same-tier pinned tasks break
    on `pos`, matching the unpinned matching's own tie-break convention.
    This preserves T8.2's stability argument for the unpinned remainder
    unchanged (it's the identical algorithm over a - possibly smaller -
    free-unit set; pinning never depends on unit position, so it
    introduces no new position-dependence of its own). At `len(unit_
    positions) == 1` (today's shipped `hires_per_day=0`), pinning changes
    nothing observable - the one unit is always either the pinned target
    or not needed at all.

    Still "at most one task per unit, one unit per task" (SPEC-policy.md)
    and a bounded greedy assignment, not a search problem - at up to 100
    tiles and a handful of units this is cheap even at its O(tasks^2 *
    units) worst case within one tier.

    Returns a list the same length and order as `unit_positions`; an
    unassigned unit's slot is `None`.
    """
    assignment: list[Task | None] = [None] * len(unit_positions)
    free_units = set(range(len(unit_positions)))
    for priority in sorted({t.priority for t in tasks}):
        if not free_units:
            break
        tier = [t for t in tasks if t.priority == priority]
        pinned = sorted((t for t in tier if t.unit_index is not None), key=lambda t: t.pos)
        unpinned = [t for t in tier if t.unit_index is None]
        for t in pinned:
            if t.unit_index in free_units:
                assignment[t.unit_index] = t
                free_units.discard(t.unit_index)
        while free_units and unpinned:
            _, t_idx, u_idx = min(
                ((tile_distance(unit_positions[u], t.pos), t.pos, u), t_idx, u)
                for t_idx, t in enumerate(unpinned)
                for u in free_units
            )
            assignment[u_idx] = unpinned.pop(t_idx)
            free_units.discard(u_idx)
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
        if task.op == "PLACE":
            return ["PLACE", task.animal]
        if task.op == "PICKUP":
            return ["PICKUP", task.item, task.qty]
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
