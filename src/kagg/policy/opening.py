"""T8.67: the "animal opening" - a whole herd bought in one go, set up in parallel, with the wheat
tiles that feed it.

Pure functions, no state between turns (decide() stays a function of obs + params). Everything
here is switched on by `params["animal_opening"]`; with it off none of these functions is called
and the agent is bit-identical to the pre-T8.67 one.

The pieces, in the order decide() uses them:

* `herd_quota` / `plan_herd_purchase` - how many animals the farm should have for the land it
  owns, and which types to buy for the missing ones (one purchase, several types).
* `opening_setup_tasks` - one pinned task per unit for the animal set-up chain
  PICKUP (animal) -> PICKUP (1 wheat if it is fed today) -> BUILD -> PLACE, so that the units leave
  the shed already carrying their animal and finish on their own tile (FEED/CARE follow from the
  ordinary tile tasks, the unit standing there is the nearest). It also reports the tiles kept
  free for the structures, so that planting does not take them.
* `runner_tasks` - the day after a herd is placed, unit 0 collects every animal's first
  fertilizer and carries it to the shed (sold at once; pays for the day's feed).
* `feed_need_today` - how many animals must be fed today (the purchase of feed follows it).
* `wheat_tiles_needed` / `seed_plan` / `planting_sequence` - the wheat tiles that keep pace with
  the herd, and the seeds for them and for the rest of the free land.
"""

from __future__ import annotations

import math

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0
from kagg.gamelib.farm import shed_access_tiles, shed_distance, tile_distance
from kagg.gamelib.growth import forecast_animal_schedule
from kagg.gamelib.market import price
from kagg.policy.strategy import _animal_full_care_schedule, animal_revenue_per_tile_day
from kagg.policy.tasks import Task, feed_skipped

# Above emergency water/feeding (PRIORITY_PREVENT_LOSS = 0), below everything else.
PRIORITY_OPENING_SETUP = 0.25
PRIORITY_OPENING_RUNNER = 0.3

_STRUCTURE_BUILD_OP = {"COOP": "BUILD_COOP", "PASTURE": "BUILD_PASTURE"}
_DEFAULT_INITIAL = {"COW": 2, "SHEEP": 3}
_DEFAULT_SKIP_AGES = {"COW": [0, 2]}


def initial_mix(params: dict) -> dict[str, int]:
    return dict(params.get("animal_opening_initial", _DEFAULT_INITIAL))


def skip_ages(params: dict) -> dict:
    return params.get("animal_feed_skip_ages", _DEFAULT_SKIP_AGES)


def herd_quota(n_quadrants: int, params: dict) -> int:
    """Animals the farm should hold: the opening herd plus one more batch per extra quadrant."""
    return sum(initial_mix(params).values()) + params.get("animal_opening_per_quadrant", 5) * max(
        0, n_quadrants - 1
    )


def _units_per_animal(animal: str, days_remaining: int, care_aware: bool) -> int:
    if care_aware:
        return sum(u for _, u in _animal_full_care_schedule(animal, days_remaining))
    return len(forecast_animal_schedule(animal, placed_day=0, horizon_days=days_remaining))


def _marginal_score(
    animal: str, taken: int, market_inventory: dict, days_remaining: int, params: dict
) -> float:
    """Net profit per day of one more `animal` when `taken` of its type are bought already: the
    animal's own product sells into a market that our earlier animals of the type have filled."""
    a = ANIMALS[animal]
    care_aware = params.get("animal_care_aware", False)
    net_of_cost = params.get("animal_net_of_cost", False)
    inv = market_inventory.get(a["product"], MARKET_I0)
    if taken:
        inv += taken * _units_per_animal(animal, days_remaining, care_aware)
    feed_price = 0
    if net_of_cost:
        feed_price = price("WHEAT", market_inventory.get("WHEAT", MARKET_I0))
    return animal_revenue_per_tile_day(
        animal, inv, 0, days_remaining if net_of_cost else None, net_of_cost, feed_price,
        params.get("animal_fertilizer_income_aware", False),
        market_inventory.get("FERTILIZER", MARKET_I0), care_aware,
        params.get("animal_consumption_horizon_aware", False), 0,
    )


def _has_time_to_mature(animal: str, current_day: int, season: int) -> bool:
    """An animal placed today still makes its first production before the season ends."""
    schedule = forecast_animal_schedule(animal, placed_day=current_day, horizon_days=season)
    return bool(schedule) and schedule[0] < season


def plan_herd_purchase(
    *, n_quadrants: int, existing_by_type: dict, market_inventory: dict, current_day: int, params: dict,
) -> dict[str, int]:
    """{animal type: qty} to buy now, in one purchase; empty when the herd is complete.

    First quadrant: the configured mix (`animal_opening_initial`) minus what exists. Later
    quadrants: the missing animals are picked one at a time from the `animal_opening_quadrant_types`
    best types, each pick priced as if the earlier picks' production were already on the market
    (our own supply lowers the price), so the batch is split between the types by marginal value.
    The batch is always the full quota (`animal_opening_per_quadrant`), whatever the marginal score.
    """
    season = params.get("season_length_days", 30)
    days_remaining = season - current_day
    deficit = herd_quota(n_quadrants, params) - sum(existing_by_type.values())
    if deficit <= 0 or days_remaining <= 0:
        return {}
    fits = {name for name in ANIMALS if _has_time_to_mature(name, current_day, season)}
    if n_quadrants <= 1:
        plan = {}
        for name, want in initial_mix(params).items():
            qty = max(0, want - existing_by_type.get(name, 0))
            if qty > 0 and name in fits:
                plan[name] = qty
        # Never more than the deficit (an earlier partial herd may already hold some of them).
        over = sum(plan.values()) - deficit
        for name in list(plan):
            cut = min(plan[name], max(0, over))
            plan[name] -= cut
            over -= cut
        return {k: v for k, v in plan.items() if v > 0}
    ranked = sorted(
        (n for n in ANIMALS if n in fits),
        key=lambda n: -_marginal_score(n, 0, market_inventory, days_remaining, params),
    )
    types = ranked[: max(1, params.get("animal_opening_quadrant_types", 2))]
    plan: dict[str, int] = {}
    for _ in range(deficit):
        scores = {n: _marginal_score(n, plan.get(n, 0), market_inventory, days_remaining, params) for n in types}
        best = max(scores, key=scores.get, default=None)
        if best is None:
            break
        plan[best] = plan.get(best, 0) + 1
    return plan


def animals_in_hand(inventories: list, shed: dict) -> dict[str, int]:
    """Bought animals not placed yet: in the shed or on a unit."""
    out: dict[str, int] = {}
    for a in ANIMALS:
        n = shed.get(a, 0) + sum(inv.get(a, 0) for inv in inventories)
        if n > 0:
            out[a] = n
    return out


def opening_setup_tasks(
    tiles, unit_positions, inventories, shed, board_size, *, to_buy: int = 0, skip_ages_by_type=None,
) -> tuple[list[Task], frozenset, int]:
    """(tasks, reserved tiles, number of reserved *empty* tiles) for the animals not placed yet.

    Every unit gets at most one pinned task, derived from its own state each turn:
      * holds an animal, stands on an empty matching structure -> PLACE;
      * holds an animal that is fed on its placement day but no wheat, stands at the shed, wheat
        is there -> PICKUP one WHEAT;
      * holds an animal -> walk to its own target tile (BUILD there, PLACE once built);
      * holds nothing, an animal waits in the shed -> PICKUP it (units nearest to the shed first).
    A unit's target is the nearest reserved tile nobody with a lower index claimed; the reserved
    tiles are the empty structures plus the nearest free tiles to the shed, as many as animals
    still lack a structure. After BUILD the unit stands on its structure (distance 0), so the
    binding is stable from turn to turn without any memory.
    """
    skip_ages_by_type = skip_ages_by_type or {}
    n_units = len(unit_positions)
    free_tiles: list[tuple[int, int]] = []
    empty_struct: dict[tuple[int, int], str] = {}
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if tile is None:
                free_tiles.append((x, y))
            elif isinstance(tile, dict) and tile.get("kind") in _STRUCTURE_BUILD_OP and "animal" not in tile:
                empty_struct[(x, y)] = tile["kind"]

    def inv_of(i):
        return inventories[i] if i < len(inventories) else {}

    held: dict[int, str] = {}
    for i in range(n_units):
        for a in ANIMALS:
            if inv_of(i).get(a, 0) > 0:
                held[i] = a
                break
    shed_animals = [a for a in ANIMALS for _ in range(shed.get(a, 0))]
    unplaced = len(shed_animals) + sum(
        inv_of(i).get(a, 0) for i in range(n_units) for a in ANIMALS
    ) + to_buy
    n_reserved_free = max(0, unplaced - len(empty_struct))
    reserved_free = sorted(free_tiles, key=lambda p: (shed_distance(p, board_size), p))[:n_reserved_free]
    reserved = frozenset(empty_struct) | frozenset(reserved_free)
    if not unplaced:
        return [], reserved, len(reserved_free)

    def feed_due_at_placement(animal):
        return 0 not in skip_ages_by_type.get(animal, ())

    tasks: list[Task] = []
    claimed: set = set()
    handled: set = set()
    # Units already standing on an empty structure of the right kind place at once.
    for i, a in held.items():
        pos = tuple(unit_positions[i])
        if empty_struct.get(pos) == ANIMALS[a]["structure"] and pos not in claimed:
            tasks.append(Task(PRIORITY_OPENING_SETUP, pos, "PLACE", animal=a, unit_index=i))
            claimed.add(pos)
            handled.add(i)
    for i in sorted(held):
        if i in handled:
            continue
        a = held[i]
        pos = tuple(unit_positions[i])
        kind = ANIMALS[a]["structure"]
        candidates = [p for p, k in empty_struct.items() if k == kind and p not in claimed]
        candidates += [p for p in reserved_free if p not in claimed]
        if not candidates:
            continue
        target = min(candidates, key=lambda p: (tile_distance(pos, p), shed_distance(p, board_size), p))
        claimed.add(target)
        handled.add(i)
        if (
            feed_due_at_placement(a) and inv_of(i).get("WHEAT", 0) == 0 and shed.get("WHEAT", 0) > 0
            and shed_distance(pos, board_size) == 0
        ):
            tasks.append(Task(
                PRIORITY_OPENING_SETUP, pos, "PICKUP", item="WHEAT", qty=1, unit_index=i
            ))
        elif target in empty_struct:
            tasks.append(Task(PRIORITY_OPENING_SETUP, target, "PLACE", animal=a, unit_index=i))
        else:
            tasks.append(Task(PRIORITY_OPENING_SETUP, target, _STRUCTURE_BUILD_OP[kind], unit_index=i))
    # Empty-handed units fetch the animals still in the shed (those needing feed today first, so
    # the units that also pick up wheat start early); never more than there are tiles left.
    room = len([p for p, k in empty_struct.items() if p not in claimed]) + len(
        [p for p in reserved_free if p not in claimed]
    )
    shed_animals.sort(key=lambda a: (not feed_due_at_placement(a), list(ANIMALS).index(a)))
    free_units = sorted(
        (i for i in range(n_units) if i not in held),
        key=lambda i: (shed_distance(unit_positions[i], board_size), i),
    )
    access = shed_access_tiles(board_size)
    for i, a in zip(free_units, shed_animals[:room]):
        pos = min(access, key=lambda p: (tile_distance(unit_positions[i], p), p))
        tasks.append(Task(PRIORITY_OPENING_SETUP, pos, "PICKUP", item=a, qty=1, unit_index=i))
    return tasks, reserved, len(reserved_free)


def runner_tasks(
    tiles, unit_positions, inventories, board_size, current_day: int, hour: int, turns_per_day: int,
) -> tuple[list[Task], list[Task]]:
    """(tasks, drop tasks) for unit 0 on the day after a herd was placed: collect the first
    fertilizer of every animal placed yesterday, then carry it to the shed - the sale pays for the
    feed. The drop task is also returned separately so decide() counts it in `dropped_now`."""
    if not unit_positions:
        return [], []
    inv = inventories[0] if inventories else {}
    cohort = [
        (x, y)
        for y, row in enumerate(tiles)
        for x, tile in enumerate(row)
        if isinstance(tile, dict) and "animal" in tile
        and tile.get("placed_day") == current_day - 1 and tile.get("fertilizer_available", False)
    ]
    carried = inv.get("FERTILIZER", 0)
    pos0 = tuple(unit_positions[0])
    late = hour >= turns_per_day - 4
    if cohort and not late:
        target = min(cohort, key=lambda p: (tile_distance(pos0, p), p))
        return [Task(PRIORITY_OPENING_RUNNER, target, "COLLECT_FERTILIZER", unit_index=0)], []
    if carried > 0:
        access = shed_access_tiles(board_size)
        pos = min(access, key=lambda p: (tile_distance(pos0, p), p))
        drop = Task(PRIORITY_OPENING_RUNNER, pos, "DROP_GOODS", item="FERTILIZER", qty=carried, unit_index=0)
        return [drop], [drop]
    return [], []


def feed_need_today(tiles, current_day: int, skip_ages_by_type: dict, unplaced: dict) -> int:
    """Animals that still have to be fed today: placed and unfed ones (unless today is one of the
    skipped ages), plus the animals bought but not placed yet, which are fed on their placement
    day unless that age is skipped for their type."""
    need = 0
    for row in tiles:
        for tile in row:
            if isinstance(tile, dict) and "animal" in tile:
                if not tile.get("fed_today", False) and not feed_skipped(tile, current_day, skip_ages_by_type):
                    need += 1
    for animal, n in unplaced.items():
        if 0 not in skip_ages_by_type.get(animal, ()):
            need += n
    return need


def wheat_tiles_needed(animals_total: int, wheat_growing: int, params: dict) -> int:
    """How many more WHEAT tiles keep pace with `animals_total` animals (`wheat_tiles_per_animal`
    tiles each); tiles already growing count, wherever they are."""
    return max(0, math.ceil(params.get("wheat_tiles_per_animal", 1.0) * animals_total) - wheat_growing)


def seed_plan(
    *, budget: float, free_tiles: int, seeds_held: dict, wheat_needed: int, ranked_crops: list,
    fill_cheaper: bool,
) -> list[tuple[str, int]]:
    """Ordered [(crop, qty)] seed purchases: the wheat for the herd first, then as many of the best
    crop as the money allows for the remaining free tiles; with `fill_cheaper` the money left
    goes to the next-ranked (cheaper) crops, again as many as fit."""
    plan: list[tuple[str, int]] = []
    tiles_left = max(0, free_tiles - sum(seeds_held.values()))
    wheat_q = min(max(0, wheat_needed - seeds_held.get("WHEAT", 0)), tiles_left, int(budget // CROPS["WHEAT"]["seed"]))
    if wheat_q > 0:
        plan.append(("WHEAT", wheat_q))
        budget -= wheat_q * CROPS["WHEAT"]["seed"]
        tiles_left -= wheat_q
    crops = [c for c in ranked_crops if c != "WHEAT"]
    for k, crop in enumerate(crops):
        if k > 0 and not fill_cheaper:
            break
        if tiles_left <= 0:
            break
        qty = min(tiles_left, int(budget // CROPS[crop]["seed"]))
        if qty > 0:
            plan.append((crop, qty))
            budget -= qty * CROPS[crop]["seed"]
            tiles_left -= qty
    return plan


def planting_sequence(
    *, cap: int, seeds: dict, wheat_needed: int, ranked_crops: list,
) -> list[str]:
    """The crops to plant this turn, one per tile: the wheat that is missing first, then the seeds
    held of the ranked crops, best first; at most `cap` tiles."""
    seq: list[str] = []
    seq += ["WHEAT"] * min(cap, wheat_needed, seeds.get("WHEAT", 0))
    for crop in [c for c in ranked_crops if c != "WHEAT"]:
        if len(seq) >= cap:
            break
        seq += [crop] * min(cap - len(seq), seeds.get(crop, 0))
    return seq
