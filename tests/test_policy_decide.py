"""Unit tests for kagg.policy.decide - the full three-layer integration
wiring strategy/tasks/market together. See SPEC-policy.md and
tasks/plan.md T3.5.

strategy.py/tasks.py/market.py are already individually tested - these
tests focus on the *glue* T3.5 adds: buying a seed when none is on hand
yet (a real gap none of T3.1-T3.3 covered - none of them ever emit
BUY_SEED), queuing HIRE/BUY_LAND from the strategic layer's decisions,
and the overall action shape/order cap.
"""

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0, PRODUCTS
from kagg.policy.decide import (
    _animal_has_time_to_mature,
    _crop_has_time_to_mature,
    _top_investment_choice,
    decide,
)
from kagg.policy.params import DEFAULT_PARAMS

_BASE_OBS = {
    "player": 0,
    "day": 0,
    "hour": 0,
    "farms": [
        {
            "money": 3000,
            "tiles": [[None] * 10 for _ in range(10)],
            "farmer": [4, 4],
            "hands": [],
            "unlocked_quadrants": ["NW"],
            "hires_today": 0,
        }
    ],
    "private": {"shed": {}, "seeds": {}, "inventories": [{}]},
    "market": {
        "inventory": {p: MARKET_I0 for p in PRODUCTS},
        "prices": {p: 0 for p in PRODUCTS},  # unused by decide() directly, gamelib.price recomputes
    },
    "town": {"unlocked_shops": []},
}


def _obs():
    import copy

    return copy.deepcopy(_BASE_OBS)


def test_decide_returns_a_valid_action_shape():
    action = decide(_obs(), DEFAULT_PARAMS)
    assert set(action) == {"farmer", "hands", "market"}
    assert isinstance(action["farmer"], list) and action["farmer"]
    assert isinstance(action["hands"], list)
    assert isinstance(action["market"], list)


def test_decide_buys_a_seed_for_the_top_ranked_crop_when_none_on_hand():
    action = decide(_obs(), DEFAULT_PARAMS)
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert len(buy_seed_orders) == 1
    crop = buy_seed_orders[0][1]
    assert crop in CROPS


def test_decide_does_not_rebuy_a_seed_already_on_hand():
    obs = _obs()
    # Give it a seed for whatever the top-ranked crop is, at I0 pricing.
    from kagg.policy.strategy import rank_portfolio

    top_crop = next(name for name in rank_portfolio(obs["market"]["inventory"]) if name in CROPS)
    obs["private"]["seeds"][top_crop] = 1
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_SEED"] == []


def test_decide_never_exceeds_ten_market_orders():
    obs = _obs()
    obs["private"]["shed"] = {p: 20 for p in PRODUCTS}
    action = decide(obs, DEFAULT_PARAMS)
    assert len(action["market"]) <= 10


def test_decide_queues_hire_when_hires_per_day_is_positive():
    obs = _obs()
    params = dict(DEFAULT_PARAMS, hires_per_day=2)
    action = decide(obs, params)
    hire_orders = [o for o in action["market"] if o == ["HIRE"]]
    assert len(hire_orders) == 2


def test_decide_passes_investment_anchor_param_to_build_task_list(monkeypatch):
    # T8.1: decide() is the only real caller of build_task_list, so this
    # is the glue test for whether params["investment_anchor"] actually
    # reaches it - tasks.py's own tests already cover what SHED vs UNIT
    # *does*.
    import kagg.policy.decide as decide_module

    captured = {}
    original = decide_module.build_task_list

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "build_task_list", spy)
    decide(_obs(), dict(DEFAULT_PARAMS, investment_anchor="UNIT"))
    assert captured.get("anchor") == "UNIT"


def test_decide_defaults_investment_anchor_to_unit_toward_shed_when_unset():
    # T8.3c accepted "UNIT_TOWARD_SHED" as the default (50/50 on both
    # self-play blocks against the previously-shipped plain "UNIT") -
    # see decide.py's own _DEFAULT_INVESTMENT_ANCHOR comment for the full
    # story, including why plain "SHED" (T8.1) was tried and rejected
    # first.
    import kagg.policy.decide as decide_module

    assert DEFAULT_PARAMS.get("investment_anchor") == "UNIT_TOWARD_SHED"
    assert decide_module._DEFAULT_INVESTMENT_ANCHOR == "UNIT_TOWARD_SHED"


def test_decide_does_not_hire_past_the_daily_target():
    obs = _obs()
    obs["farms"][0]["hires_today"] = 2
    params = dict(DEFAULT_PARAMS, hires_per_day=2)
    action = decide(obs, params)
    assert [o for o in action["market"] if o == ["HIRE"]] == []


def test_decide_queues_land_purchase_when_affordable_and_over_threshold():
    # Isolates the money/threshold logic from T8.3's occupancy gate
    # (_obs()'s fixture farm is a fully-empty, fully-unlocked 100-tile
    # board - under T8.3's now-accepted default the occupancy gate would
    # correctly decline here, since a fully-empty farm is exactly the
    # "don't buy more land yet" case; land_buy_max_free_tile_fraction=1.0
    # opts back into the fully-ungated mechanism to test threshold alone).
    obs = _obs()
    obs["farms"][0]["money"] = 10_000
    params = dict(DEFAULT_PARAMS, land_purchase_threshold_money=0, land_buy_max_free_tile_fraction=1.0)
    action = decide(obs, params)
    assert ["BUY_LAND"] in action["market"]


def test_decide_does_not_queue_land_purchase_below_threshold():
    obs = _obs()
    obs["farms"][0]["money"] = 500
    action = decide(obs, DEFAULT_PARAMS)  # default threshold is 10000 (T7.4)
    assert ["BUY_LAND"] not in action["market"]


def test_decide_does_not_buy_land_while_most_tiles_are_free_when_the_gate_is_enabled():
    # T8.3: decide() must pass real occupancy through, not just money -
    # the direct fix for the user's own observed defect.
    obs = _obs()  # _BASE_OBS's tiles are a fully-empty 10x10 board
    obs["farms"][0]["money"] = 1_000_000
    params = dict(DEFAULT_PARAMS, land_purchase_threshold_money=0, land_buy_max_free_tile_fraction=0.5)
    action = decide(obs, params)
    assert ["BUY_LAND"] not in action["market"]


def test_decide_buys_land_when_the_gate_is_enabled_and_few_free_tiles_remain():
    obs = _obs()
    obs["farms"][0]["money"] = 1_000_000
    for y in range(10):
        for x in range(10):
            if not (x < 2 and y < 2):  # leave only a 2x2 corner free
                obs["farms"][0]["tiles"][y][x] = {"kind": "WEED"}
    params = dict(DEFAULT_PARAMS, land_purchase_threshold_money=0, land_buy_max_free_tile_fraction=0.5)
    action = decide(obs, params)
    assert ["BUY_LAND"] in action["market"]


def test_crop_has_time_to_mature_rejects_a_one_time_crop_planted_too_late():
    # The exact scenario found while measuring T3.5: MELON's max_yield_day
    # is 12, planted on day 20 needs the season to run through day 32 - a
    # 30-day season doesn't have it.
    assert _crop_has_time_to_mature("MELON", current_day=20, season_length_days=30) is False


def test_crop_has_time_to_mature_accepts_a_one_time_crop_planted_early_enough():
    assert _crop_has_time_to_mature("MELON", current_day=10, season_length_days=30) is True


def test_crop_has_time_to_mature_only_needs_one_ongoing_production_to_fit():
    # TOMATO's schedule starts at first_yield_day=8; planted on day 21,
    # its first production (day 29) still fits a 30-day season even
    # though later scheduled productions (30, 31...) would not.
    assert _crop_has_time_to_mature("TOMATO", current_day=21, season_length_days=30) is True
    assert _crop_has_time_to_mature("TOMATO", current_day=22, season_length_days=30) is False


def test_top_investment_choice_skips_crops_that_cannot_mature_in_time():
    # Force MELON to the top of the ranking (it wins at base price -
    # T3.1's own test data) but plant it too late for it to matter -
    # the next-best crop that still has time should win instead.
    market_inventory = {p: MARKET_I0 for p in PRODUCTS}
    late_choice = _top_investment_choice(market_inventory, current_day=25, params=DEFAULT_PARAMS)
    assert late_choice is None or late_choice[0] != "MELON"


def test_top_investment_choice_returns_none_once_nothing_can_mature():
    market_inventory = {p: MARKET_I0 for p in PRODUCTS}
    # Day 29 (the last day of a 30-day season): even WHEAT (max_yield_day=4,
    # the shortest cycle) can't complete - and neither can any animal
    # (COW/SHEEP/GOOSE's first_yield_day all land past day 30 from here).
    assert _top_investment_choice(market_inventory, current_day=29, params=DEFAULT_PARAMS) is None


def test_animal_has_time_to_mature_rejects_an_animal_placed_too_late():
    # COW's first_yield_day is 8; placed on day 22 its first production
    # would land on day 30, which a 30-day season (days 0-29) doesn't have.
    assert _animal_has_time_to_mature("COW", current_day=22, season_length_days=30) is False


def test_animal_has_time_to_mature_only_needs_one_production_to_fit():
    # SHEEP's first production from day 22 lands on day 28 - still fits,
    # even though COW's (placed the same day) would not - verified via
    # gamelib.growth.forecast_animal_schedule directly before writing this.
    assert _animal_has_time_to_mature("SHEEP", current_day=22, season_length_days=30) is True


def test_animal_has_time_to_mature_handles_an_empty_forecast():
    # Late enough that forecast_animal_schedule returns nothing at all
    # within the season horizon (not just a too-late single production) -
    # must not raise on an empty list.
    assert _animal_has_time_to_mature("COW", current_day=29, season_length_days=30) is False


def test_top_investment_choice_picks_an_animal_when_it_outranks_every_crop():
    # Crash MELON's own price (heavy oversupply) the same way
    # test_rank_portfolio_reacts_to_a_crashed_price does - with MELON out
    # of the running, COW ranks first overall (verified directly:
    # rank_portfolio returns ['COW', 'SHEEP', 'GOOSE', ...] here).
    crashed_melon_inventory = {"MELON": MARKET_I0 + 100_000}
    choice = _top_investment_choice(crashed_melon_inventory, current_day=0, params=DEFAULT_PARAMS)
    assert choice == ("COW", "animal")


def test_top_investment_choice_skips_an_animal_that_cannot_mature_in_time():
    # Same crashed-MELON ranking, but late enough that COW (first
    # overall) can't mature - SHEEP (next in rank) still can (verified:
    # forecast_animal_schedule("SHEEP", placed_day=22) starts at day 28).
    crashed_melon_inventory = {"MELON": MARKET_I0 + 100_000}
    choice = _top_investment_choice(crashed_melon_inventory, current_day=22, params=DEFAULT_PARAMS)
    assert choice == ("SHEEP", "animal")


def test_decide_buys_a_seed_for_the_top_crop_alongside_the_top_animal_by_default():
    # T6.3 closes the gap T6.1 opened: now that tasks.py (T6.2) and
    # BUY_ANIMAL (T6.3) both exist, decide() acts on the animal choice
    # directly instead of falling back to a crop - see the module
    # docstring's revision history.
    #
    # T8.9 (tasks/plan.md) added a fallback that also buys a seed here
    # (params["plant_while_pursuing_animal"]) - shipped off at first
    # (measured to lose in isolation, pre-T8.2/T8.3), then accepted as
    # the default in T8.3b once cleanly re-measured on top of T8.2's
    # distance-aware servicing and T8.3's land gating: 50/50 wins on both
    # the working and held-out blocks - see
    # kagg.policy.decide._top_crop_choice's docstring for the full,
    # corrected story (the earlier "measured to lose" result was itself
    # measured on stale, pre-T8.2/T8.3 code).
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}  # crashes MELON - COW ranks first overall
    action = decide(obs, DEFAULT_PARAMS)
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert len(buy_seed_orders) == 1
    assert buy_seed_orders[0][1] in CROPS
    buy_animal_orders = [o for o in action["market"] if o[0] == "BUY_ANIMAL"]
    assert buy_animal_orders == [["BUY_ANIMAL", "COW", 1]]


def test_decide_can_still_disable_the_crop_fallback_explicitly():
    # The pre-T8.3b behavior stays reachable via an explicit override -
    # both purchases are independent market orders with no structural
    # reason to be exclusive, so disabling the fallback alone is enough
    # to reproduce the old "animal only" behavior.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}
    params = dict(DEFAULT_PARAMS, plant_while_pursuing_animal=False)
    action = decide(obs, params)
    assert [o for o in action["market"] if o[0] == "BUY_SEED"] == []
    buy_animal_orders = [o for o in action["market"] if o[0] == "BUY_ANIMAL"]
    assert buy_animal_orders == [["BUY_ANIMAL", "COW", 1]]


def test_decide_does_not_rebuy_an_animal_already_held():
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}
    obs["private"]["shed"]["COW"] = 1
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == []


def _placed_cow_tile() -> dict:
    return {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0, "yield_units": 0,
        "consecutive_unfed": 0, "fed_today": True, "cared_today": False,
        "fertilizer_available": False, "pending_care_bonus": 0,
    }


def test_decide_keeps_working_by_default_when_the_top_ranked_animal_is_already_placed_and_idle():
    # T8.9 found this real bug (tasks/plan.md): COW keeps ranking first
    # overall forever once it's the best animal type, regardless of
    # whether we already own and are producing from one -
    # rank_portfolio has no notion of ownership - so plant_crop (derived
    # solely from the single overall top choice) used to stay None and
    # the farmer could idle (PASS) despite a plantable seed on hand. This
    # is exactly the real-game symptom the user reported after Checkpoint
    # 8A ("crop production stops once animals appear") - confirmed and
    # fixed in T8.3b by shipping this fallback as the default (50/50 on
    # both self-play blocks, cleanly isolated from investment_anchor).
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}  # COW ranks first overall
    obs["farms"][0]["tiles"][4][4] = _placed_cow_tile()  # already placed and alive
    obs["farms"][0]["farmer"] = [0, 0]
    obs["private"]["seeds"]["STRAWBERRY"] = 1  # the top-ranked crop under this inventory
    action = decide(obs, DEFAULT_PARAMS)
    assert action["farmer"] != ["PASS"]


def test_decide_idles_when_the_crop_fallback_is_disabled_explicitly():
    # The pre-T8.3b behavior (the real bug) stays reachable and correct
    # via an explicit override, mirroring investment_anchor's own pattern.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}
    obs["farms"][0]["tiles"][4][4] = _placed_cow_tile()
    obs["farms"][0]["farmer"] = [0, 0]
    obs["private"]["seeds"]["STRAWBERRY"] = 1
    params = dict(DEFAULT_PARAMS, plant_while_pursuing_animal=False)
    action = decide(obs, params)
    assert action["farmer"] == ["PASS"]
    assert [o for o in action["market"] if o[0] == "BUY_SEED"] == []


def test_decide_does_not_buy_an_animal_when_money_is_insufficient():
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}
    obs["farms"][0]["money"] = ANIMALS["COW"]["cost"] - 1
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == []


def test_decide_does_not_buy_an_animal_when_the_shed_is_full():
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}
    obs["private"]["shed"] = {"WHEAT": 100}  # full at the real default shedCapacity=100
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == []


def test_decide_emits_a_build_task_when_animal_is_the_top_choice():
    # The base fixture's farmer already stands at (4, 4) - the nearest
    # (in fact, occupied) empty tile - so no movement step is needed to
    # exercise the BUILD op itself in a single decide() call.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}
    action = decide(obs, DEFAULT_PARAMS)
    assert action["farmer"] == ["BUILD_PASTURE"]  # COW's structure


def test_decide_picks_up_a_bought_animal_before_placing_it():
    # T6.4's central finding: BUY_ANIMAL delivers to the shed, but PLACE
    # needs the animal in the farmer's own inventory. The base fixture's
    # farmer stands at (4, 4), one of the four real shed-access tiles
    # (gamelib.farm.shed_access_tiles(10)) - so PICKUP fires immediately,
    # no movement needed.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}
    obs["farms"][0]["tiles"][2][4] = {"kind": "PASTURE"}  # already built
    obs["private"]["shed"]["COW"] = 1
    action = decide(obs, DEFAULT_PARAMS)
    assert action["farmer"] == ["PICKUP", "COW", 1]


def test_decide_finishes_a_stuck_animal_before_starting_anything_new():
    # T6.4's finding: a previously-bought animal already sitting in the
    # shed must be finished (built/picked-up/placed) before decide()
    # starts a *new* investment, even if the current top choice has since
    # shifted to something else entirely (here: MELON, a crop, at base
    # pricing) - without this, a shifting top choice abandoned paid-for
    # animals in the shed forever (measured: 21 BUY_ANIMAL orders against
    # only 18 PLACEs in one real episode).
    obs = _obs()
    obs["private"]["shed"]["COW"] = 1
    action = decide(obs, DEFAULT_PARAMS)
    assert action["farmer"] == ["BUILD_PASTURE"]  # not PLANT MELON
    assert [o for o in action["market"] if o[0] == "BUY_SEED"] == []


def test_decide_does_not_buy_a_new_animal_while_a_different_one_is_stuck():
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}  # COW would otherwise be top choice
    obs["private"]["shed"]["GOOSE"] = 1  # already bought, unplaced, a different animal
    action = decide(obs, DEFAULT_PARAMS)
    assert action["farmer"] == ["BUILD_COOP"]  # finishes GOOSE, not COW
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == []


def test_decide_does_not_buy_a_second_animal_of_a_type_already_placed_and_alive():
    # A second real bug found the same way as the stuck-animal one:
    # even with that fix, decide() kept re-buying *another* instance of
    # the top-ranked animal forever, even with one already placed and
    # producing - a live episode showed 18 BUY_ANIMAL orders for a farm
    # that only ever needed one of each. Deliberate simplification: never
    # pursue a second instance of an animal type already placed and
    # alive, correct for a single farmer that can't reliably tend more
    # than one anyway.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}  # COW is the top choice
    obs["farms"][0]["tiles"][3][3] = {
        "kind": "PASTURE",
        "animal": "COW",
        "placed_day": 0,
        "yield_units": 0,
        "consecutive_unfed": 0,
        "fed_today": True,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == []
    assert action["farmer"] != ["BUILD_PASTURE"]


def test_decide_plants_nothing_when_no_crop_can_mature_in_time():
    obs = _obs()
    obs["day"] = 29
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_SEED"] == []


def _fill_all_tiles(obs, filler=None):
    filler = filler or {"kind": "WEED"}
    obs["farms"][0]["tiles"] = [[dict(filler) for _ in range(10)] for _ in range(10)]
    return obs


def test_decide_does_not_buy_a_seed_when_the_farm_has_no_empty_tile():
    # T6.5's documented gap, closed: buying a seed with nowhere to plant
    # it just accumulates unused seeds - a farm with no free land at all
    # (every tile occupied, e.g. by weeds) shouldn't buy one.
    obs = _fill_all_tiles(_obs())
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_SEED"] == []


def test_decide_does_not_buy_an_animal_when_no_land_or_matching_structure_exists():
    obs = _fill_all_tiles(_obs())
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}  # COW is the top choice
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == []


def test_decide_still_buys_an_animal_when_a_matching_empty_structure_exists():
    # No empty *tile* to build on, but an existing empty PASTURE is
    # enough - the animal doesn't need free land, just somewhere to go.
    obs = _fill_all_tiles(_obs())
    obs["farms"][0]["tiles"][0][0] = {"kind": "PASTURE"}
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}  # COW is the top choice
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == [["BUY_ANIMAL", "COW", 1]]


def test_decide_assigns_hands_when_present():
    obs = _obs()
    obs["farms"][0]["hands"] = [[0, 0]]
    obs["private"]["inventories"] = [{}, {}]
    obs["farms"][0]["tiles"][0][0] = {"kind": "WEED"}
    action = decide(obs, DEFAULT_PARAMS)
    assert len(action["hands"]) == 1
    assert action["hands"][0] == ["DIG"]  # already standing on the weed tile
