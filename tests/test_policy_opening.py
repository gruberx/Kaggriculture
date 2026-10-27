"""T8.67: the animal opening (kagg.policy.opening and its wiring in tasks/decide)."""

import copy

from kaggle_environments.envs.kaggriculture.kaggriculture import _daily_refresh_animals, _new_animal

from kagg.gamelib.constants import ANIMALS, MARKET_I0, PRODUCTS
from kagg.policy import opening
from kagg.policy.decide import decide
from kagg.policy.params import DEFAULT_PARAMS
from kagg.policy.tasks import (
    PRIORITY_ANIMAL_CARE,
    Task,
    _animal_tile_tasks,
    assign_units,
    build_task_list,
    feed_skipped,
)

SKIP = {"COW": [0, 2]}
PARAMS = dict(DEFAULT_PARAMS, animal_opening=True)


def _tiles():
    """A 10x10 board: NW unlocked (None), the rest LOCKED."""
    return [[None if (x < 5 and y < 5) else "LOCKED" for x in range(10)] for y in range(10)]


def _animal_tile(animal="COW", placed_day=0, **kw):
    tile = _new_animal(animal, placed_day)
    tile.update(kw)
    return tile


# ---- feeding schedule ----


def test_feed_skipped_only_on_the_configured_ages_of_the_configured_type():
    cow = _animal_tile("COW", 3)
    assert [feed_skipped(cow, d, SKIP) for d in (3, 4, 5, 6)] == [True, False, True, False]
    assert not any(feed_skipped(_animal_tile("SHEEP", 3), d, SKIP) for d in (3, 4, 5))
    assert not feed_skipped(cow, 3, None) and not feed_skipped(cow, 3, {})
    assert not feed_skipped(cow, None, SKIP)


def test_feed_skip_never_applies_after_a_missed_day():
    # The day after an unfed day is the last chance before the escape.
    cow = _animal_tile("COW", 0, consecutive_unfed=1)
    assert not feed_skipped(cow, 2, SKIP)


def test_skipped_animal_gets_no_feed_and_no_care_task_but_still_harvest_and_fertilizer():
    cow = _animal_tile("COW", 5, yield_units=2, fertilizer_available=True)
    tasks, feed_priority = _animal_tile_tasks(
        (1, 1), cow, (0,), care_aware=True, current_day=5, feed_skip_ages=SKIP
    )
    assert feed_priority is None
    assert {t.op for t in tasks} == {"HARVEST", "COLLECT_FERTILIZER"}
    tasks, feed_priority = _animal_tile_tasks(
        (1, 1), cow, (0,), care_aware=True, current_day=6, feed_skip_ages=SKIP
    )
    assert feed_priority is not None and {"FEED", "CARE"} <= {t.op for t in tasks}


def _play(animal, days, skip):
    """The animal's yield after each midnight when fed/cared by the (skip) schedule, via the real
    engine refresh."""
    tile = _new_animal(animal, 0)
    farm = {"tiles": [[tile]]}
    yields = []
    for day in range(days):
        if not feed_skipped(tile, day, skip):
            tile["fed_today"] = True
            tile["cared_today"] = True
        _daily_refresh_animals(farm, day)
        yields.append(tile["yield_units"])
    return tile, yields


def test_cow_schedule_still_gives_the_full_first_milking_and_never_escapes():
    tile, yields = _play("COW", 8, SKIP)
    assert isinstance(tile, dict) and "animal" in tile  # not escaped
    assert yields[7] == 6  # first production (day 7 midnight), care bonus 5 + base 1
    # the same as feeding every day
    _, every_day = _play("COW", 8, {})
    assert yields == every_day


def test_sheep_and_goose_need_care_from_the_placement_day():
    for animal, day_of_first in (("SHEEP", 5), ("GOOSE", 3)):
        _, yields = _play(animal, day_of_first + 1, SKIP)
        assert yields[day_of_first] == {"SHEEP": 6, "GOOSE": 4}[animal]


# ---- herd purchase ----


def _inv(**over):
    inv = {p: MARKET_I0 for p in PRODUCTS}
    inv.update(over)
    return inv


def test_herd_quota_grows_by_one_batch_per_quadrant():
    assert opening.herd_quota(1, PARAMS) == 5
    assert opening.herd_quota(2, PARAMS) == 10
    assert opening.herd_quota(3, PARAMS) == 15


def test_first_quadrant_buys_the_configured_mix_minus_what_exists():
    plan = opening.plan_herd_purchase(
        n_quadrants=1, existing_by_type={}, market_inventory=_inv(), current_day=0, params=PARAMS
    )
    assert plan == {"COW": 2, "SHEEP": 3}
    plan = opening.plan_herd_purchase(
        n_quadrants=1, existing_by_type={"COW": 2, "SHEEP": 1}, market_inventory=_inv(), current_day=0,
        params=PARAMS,
    )
    assert plan == {"SHEEP": 2}
    assert not opening.plan_herd_purchase(
        n_quadrants=1, existing_by_type={"COW": 2, "SHEEP": 3}, market_inventory=_inv(), current_day=0,
        params=PARAMS,
    )


def test_new_quadrant_buys_five_in_one_batch_from_at_most_two_types():
    plan = opening.plan_herd_purchase(
        n_quadrants=2, existing_by_type={"COW": 2, "SHEEP": 3}, market_inventory=_inv(), current_day=6,
        params=PARAMS,
    )
    assert sum(plan.values()) == 5
    assert 1 <= len(plan) <= 2


def test_our_own_supply_shifts_the_split_to_the_other_type():
    # A flooded WOOL market makes wool worth less, so the batch tilts to the other type.
    flooded = _inv(WOOL=MARKET_I0 + 3000)
    plan = opening.plan_herd_purchase(
        n_quadrants=2, existing_by_type={"COW": 2, "SHEEP": 3}, market_inventory=flooded, current_day=6,
        params=PARAMS,
    )
    assert plan.get("SHEEP", 0) < 5


def test_no_herd_is_bought_when_it_cannot_produce_before_the_season_ends():
    assert not opening.plan_herd_purchase(
        n_quadrants=2, existing_by_type={"COW": 2, "SHEEP": 3}, market_inventory=_inv(), current_day=29,
        params=PARAMS,
    )


# ---- set-up tasks ----

SHED_ACCESS = (4, 4)


def _setup(units, inventories, shed, tiles=None, to_buy=0):
    return opening.opening_setup_tasks(
        tiles or _tiles(), units, inventories, shed, 10, to_buy=to_buy, skip_ages_by_type=SKIP
    )


def test_units_at_the_shed_each_pick_up_one_waiting_animal_sheep_first():
    units = [SHED_ACCESS] * 6
    tasks, reserved, n_free = _setup(units, [{}] * 6, {"COW": 2, "SHEEP": 3})
    picks = {t.unit_index: t.item for t in tasks if t.op == "PICKUP"}
    assert sorted(picks.values()) == ["COW", "COW", "SHEEP", "SHEEP", "SHEEP"]
    assert [picks[i] for i in sorted(picks)][:3] == ["SHEEP"] * 3
    assert len(picks) == 5 and all(t.priority < PRIORITY_ANIMAL_CARE for t in tasks)
    assert n_free == 5 and len(reserved) == 5
    # the reserved tiles are the ones nearest to the shed
    assert (4, 4) in reserved and (3, 4) in reserved and (4, 3) in reserved


def test_a_sheep_carrier_takes_one_wheat_before_leaving_the_shed_a_cow_does_not():
    units = [SHED_ACCESS, SHED_ACCESS]
    inventories = [{"SHEEP": 1}, {"COW": 1}]
    tasks, _, _ = _setup(units, inventories, {"WHEAT": 3})
    by_unit = {t.unit_index: t for t in tasks}
    assert (by_unit[0].op, by_unit[0].item, by_unit[0].qty) == ("PICKUP", "WHEAT", 1)
    assert by_unit[1].op == "BUILD_PASTURE"
    # once it holds the wheat it walks to its tile
    tasks, _, _ = _setup(units, [{"SHEEP": 1, "WHEAT": 1}, {"COW": 1}], {"WHEAT": 2})
    assert {t.unit_index: t.op for t in tasks} == {0: "BUILD_PASTURE", 1: "BUILD_PASTURE"}


def test_carriers_claim_different_tiles_and_a_built_structure_is_placed_by_whoever_stands_on_it():
    units = [(4, 4), (3, 4)]
    tasks, _, _ = _setup(units, [{"COW": 1}, {"COW": 1}], {})
    targets = {t.unit_index: t.pos for t in tasks}
    assert targets[0] != targets[1]
    assert targets[0] == (4, 4) and targets[1] == (3, 4)  # each one its own tile, no walking
    tiles = _tiles()
    tiles[4][4] = {"kind": "PASTURE"}
    tasks, _, _ = _setup(units, [{"COW": 1}, {"COW": 1}], {}, tiles=tiles)
    by_unit = {t.unit_index: t for t in tasks}
    assert (by_unit[0].op, by_unit[0].pos, by_unit[0].animal) == ("PLACE", (4, 4), "COW")
    assert by_unit[1].op == "BUILD_PASTURE" and by_unit[1].pos == (3, 4)


def test_reserved_tiles_are_not_offered_to_planting():
    tiles = _tiles()
    _, reserved, _ = _setup([SHED_ACCESS], [{}], {"COW": 1})
    tasks = build_task_list(
        tiles, [SHED_ACCESS], plant_crop="MELON", plant_qty=25, reserved_tiles=reserved
    )
    planted = {t.pos for t in tasks if t.op == "PLANT"}
    assert planted and not planted & set(reserved)


def test_no_tasks_when_there_is_no_animal_to_set_up():
    tasks, reserved, n_free = _setup([SHED_ACCESS], [{}], {})
    assert tasks == [] and n_free == 0


def test_setup_tasks_are_pinned_and_win_over_planting_in_assign_units():
    units = [SHED_ACCESS] * 3
    tasks, _, _ = _setup(units, [{}] * 3, {"COW": 1})
    plant = Task(1.75, (3, 3), "PLANT", crop="MELON")
    assignment = assign_units(sorted([plant, *tasks], key=lambda t: (t.priority, t.pos)), units)
    assert assignment[0].op == "PICKUP" and assignment[0].item == "COW"


# ---- fertilizer runner ----


def test_runner_collects_yesterdays_herd_then_carries_the_fertilizer_to_the_shed():
    tiles = _tiles()
    tiles[4][3] = _animal_tile("COW", 0, fertilizer_available=True)
    tiles[4][2] = _animal_tile("SHEEP", 0, fertilizer_available=True)
    tasks, drops = opening.runner_tasks(tiles, [(3, 4)], [{}], 10, 1, 2, 24)
    assert [(t.op, t.pos, t.unit_index) for t in tasks] == [("COLLECT_FERTILIZER", (3, 4), 0)]
    assert drops == []
    tiles[4][3]["fertilizer_available"] = False
    tiles[4][2]["fertilizer_available"] = False
    tasks, drops = opening.runner_tasks(tiles, [(3, 4)], [{"FERTILIZER": 2}], 10, 1, 9, 24)
    assert [(t.op, t.item, t.qty) for t in tasks] == [("DROP_GOODS", "FERTILIZER", 2)]
    assert drops == tasks
    # older animals are not the runner's business
    assert opening.runner_tasks(tiles, [(3, 4)], [{}], 10, 5, 2, 24) == ([], [])


# ---- feed / wheat / seeds ----


def test_feed_need_counts_unfed_animals_and_the_placement_day_feeds_but_skips_cows():
    tiles = _tiles()
    tiles[4][4] = _animal_tile("COW", 1)  # age 1: fed
    tiles[4][3] = _animal_tile("COW", 0)  # age 2 today: skipped
    tiles[4][2] = _animal_tile("SHEEP", 0)  # fed every day
    tiles[3][4] = _animal_tile("SHEEP", 0, fed_today=True)  # already fed
    assert opening.feed_need_today(tiles, 2, SKIP, {}) == 2
    # bought today, not placed yet: a cow is not fed at age 0, a sheep is
    assert opening.feed_need_today(_tiles(), 0, SKIP, {"COW": 2, "SHEEP": 3}) == 3


def test_wheat_tiles_follow_the_herd_and_count_what_already_grows():
    assert opening.wheat_tiles_needed(5, 0, PARAMS) == 5
    assert opening.wheat_tiles_needed(5, 3, PARAMS) == 2
    assert opening.wheat_tiles_needed(10, 12, PARAMS) == 0
    assert opening.wheat_tiles_needed(5, 0, dict(PARAMS, wheat_tiles_per_animal=1.2)) == 6


def test_seed_plan_wheat_first_then_best_crop_then_cheaper_ones_with_the_rest():
    plan = opening.seed_plan(
        budget=560, free_tiles=20, seeds_held={}, wheat_needed=5, ranked_crops=["MELON", "CARROT", "WHEAT"],
        fill_cheaper=True,
    )
    assert plan == [("WHEAT", 5), ("MELON", 6), ("CARROT", 1)]  # 50 + 480 + 20, 10 left
    plan = opening.seed_plan(
        budget=560, free_tiles=20, seeds_held={}, wheat_needed=5, ranked_crops=["MELON", "CARROT"],
        fill_cheaper=False,
    )
    assert plan == [("WHEAT", 5), ("MELON", 6)]
    # seeds already held count against the free tiles, and the wheat already in hand against the need
    plan = opening.seed_plan(
        budget=10_000, free_tiles=10, seeds_held={"WHEAT": 5, "MELON": 3}, wheat_needed=5,
        ranked_crops=["MELON"], fill_cheaper=True,
    )
    assert plan == [("MELON", 2)]


def test_planting_sequence_puts_the_missing_wheat_first_and_respects_the_cap():
    seq = opening.planting_sequence(
        cap=6, seeds={"WHEAT": 5, "MELON": 7, "CARROT": 3}, wheat_needed=4, ranked_crops=["MELON", "CARROT"]
    )
    assert seq == ["WHEAT"] * 4 + ["MELON"] * 2
    assert opening.planting_sequence(cap=3, seeds={"MELON": 7}, wheat_needed=0, ranked_crops=["MELON"]) == ["MELON"] * 3


# ---- decide() wiring ----


def _first_turn_obs():
    return {
        "player": 0, "day": 0, "hour": 0,
        "farms": [{
            "money": 3000, "tiles": _tiles(), "farmer": [4, 4], "hands": [],
            "unlocked_quadrants": ["NW"], "hires_today": 0,
        }],
        "private": {"shed": {}, "seeds": {}, "inventories": [{}]},
        "market": {"inventory": {p: MARKET_I0 for p in PRODUCTS}, "prices": {p: 0 for p in PRODUCTS}},
        "town": {"unlocked_shops": []},
    }


def test_first_turn_buys_the_whole_herd_its_feed_and_wheat_seeds_and_hires_four_or_five():
    orders = decide(_first_turn_obs(), PARAMS)["market"]
    assert ["BUY_ANIMAL", "COW", 2] in orders and ["BUY_ANIMAL", "SHEEP", 3] in orders
    assert ["BUY_PRODUCT", "WHEAT", 3] in orders  # the sheep are fed today, the cows are not
    assert ["BUY_SEED", "WHEAT", 5] in orders
    assert any(o[0] == "BUY_SEED" and o[1] == "MELON" for o in orders)
    assert 4 <= sum(1 for o in orders if o == ["HIRE"]) <= 5
    assert len(orders) <= 10


def test_flag_off_first_turn_has_no_herd_purchase():
    orders = decide(_first_turn_obs(), dict(PARAMS, animal_opening=False))["market"]
    assert ["BUY_ANIMAL", "COW", 2] not in orders and ["BUY_ANIMAL", "SHEEP", 3] not in orders


def test_herd_is_not_bought_twice():
    obs = _first_turn_obs()
    obs["private"]["shed"] = {"COW": 2, "SHEEP": 3, "WHEAT": 3}
    obs["hour"] = 1
    orders = decide(obs, PARAMS)["market"]
    assert not any(o[0] == "BUY_ANIMAL" for o in orders)


def test_the_units_pick_up_the_animals_on_the_turn_after_the_purchase():
    obs = _first_turn_obs()
    obs["hour"] = 1
    obs["farms"][0]["hands"] = [[4, 4]] * 4
    obs["farms"][0]["hires_today"] = 4
    obs["private"]["shed"] = {"COW": 2, "SHEEP": 3, "WHEAT": 3}
    obs["private"]["inventories"] = [{}] * 5
    action = decide(obs, PARAMS)
    picks = [a for a in [action["farmer"], *action["hands"]] if a[0] == "PICKUP"]
    assert sorted(a[1] for a in picks) == ["COW", "COW", "SHEEP", "SHEEP", "SHEEP"]


def test_wheat_is_never_sold_while_the_opening_runs():
    obs = _first_turn_obs()
    obs["day"] = 10
    obs["farms"][0]["tiles"][4][4] = _animal_tile("SHEEP", 5, fed_today=True, cared_today=True)
    obs["private"]["shed"] = {"WHEAT": 80, "MELON": 4}
    orders = decide(obs, PARAMS)["market"]
    assert not any(o[0] == "SELL" and o[1] == "WHEAT" for o in orders)
    assert any(o[0] == "SELL" and o[1] == "MELON" for o in orders)
