"""Unit tests for kagg.policy.decide - the full three-layer integration
wiring strategy/tasks/market together. See SPEC-policy.md and
tasks/plan.md T3.5.

strategy.py/tasks.py/market.py are already individually tested - these
tests focus on the *glue* T3.5 adds: buying a seed when none is on hand
yet (a real gap none of T3.1-T3.3 covered - none of them ever emit
BUY_SEED), queuing HIRE/BUY_LAND from the strategic layer's decisions,
and the overall action shape/order cap.
"""

import copy

import pytest

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0, PRODUCTS
from kagg.policy.decide import (
    _animal_has_time_to_mature,
    _combined_crop_tile_counts,
    _crop_has_time_to_mature,
    _crop_tile_counts,
    _top_animal_choice,
    _top_crop_basket,
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


def test_portfolio_basket_size_defaults_to_one():
    assert DEFAULT_PARAMS.get("portfolio_basket_size", 1) == 1


def test_decide_buys_seed_for_every_basket_crop_when_portfolio_basket_size_is_above_one():
    # T8.19: a crashed MELON price (same fixture other tests in this file
    # use) leaves a clear, deterministic crop-only ranking to round-robin
    # across instead of always the single top pick.
    obs = _obs()
    market_inventory = {"MELON": MARKET_I0 + 100_000}
    obs["market"]["inventory"] = market_inventory
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False, portfolio_basket_size=2)
    basket = _top_crop_basket(market_inventory, current_day=0, params=params, basket_size=2)
    assert len(basket) == 2
    action = decide(obs, params)
    buy_seed_crops = {o[1] for o in action["market"] if o[0] == "BUY_SEED"}
    assert buy_seed_crops == set(basket)


def test_decide_plants_a_basket_of_crops_round_robin_when_portfolio_basket_size_is_above_one(monkeypatch):
    import kagg.policy.decide as decide_module

    captured = {}
    original = decide_module.build_task_list

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "build_task_list", spy)

    obs = _obs()
    market_inventory = {"MELON": MARKET_I0 + 100_000}
    obs["market"]["inventory"] = market_inventory
    # dynamic_hiring off (pin the static hires_per_day=2) so labor_units
    # is exactly 3, deterministic regardless of T8.16(d)'s backlog-scaled
    # default - this test is about the basket round-robin, not hiring.
    params = dict(
        DEFAULT_PARAMS, animal_net_of_cost=False, dynamic_hiring=False,
        hires_per_day=2, portfolio_basket_size=2,
    )
    basket = _top_crop_basket(market_inventory, current_day=0, params=params, basket_size=2)
    assert len(basket) == 2
    obs["private"]["seeds"] = {c: 5 for c in basket}
    decide(obs, params)
    plant_crop = captured.get("plant_crop")
    assert isinstance(plant_crop, list)
    # labor_units=3 (1 farmer + hires_per_day=2), free_tiles=100,
    # max_plants_per_unit=100 (plant_budget large), max_plant_tasks_per_
    # turn=8 default -> total_cap=3, round-robined basket[0], basket[1],
    # basket[0].
    assert plant_crop == [basket[0], basket[1], basket[0]]
    assert captured.get("plant_qty") == 3


def test_decide_does_not_rebuy_a_seed_already_on_hand():
    # T8.6/T8.7: the seed target scales with labor_units (1 +
    # hires_per_day(params)) * seed_buffer_per_unit - with the default
    # hires_per_day=1, that's 2, not 1, so this test stocks the full
    # target rather than assuming the pre-T8.6 flat "1 is always enough."
    # T8.29: dynamic_hiring off (pin the static hires_per_day=1) so
    # labor_units is exactly 2, deterministic - this test is about the
    # already-on-hand check, not the dynamic hiring forecast.
    obs = _obs()
    from kagg.policy.strategy import rank_portfolio

    top_crop = next(name for name in rank_portfolio(obs["market"]["inventory"]) if name in CROPS)
    obs["private"]["seeds"][top_crop] = 2
    action = decide(obs, dict(DEFAULT_PARAMS, dynamic_hiring=False))
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


def test_hire_is_never_crowded_out_by_sell_orders():
    # T8.5: the pre-T8.5 order (sells, then buys, HIRE emitted dead
    # last) could truncate HIRE entirely once enough sellable products
    # filled the 10-order cap - a hand hired at hour 1 instead of hour 0
    # loses a whole unit-day. hires + sells + tail puts HIRE at index 0,
    # never truncated.
    obs = _obs()
    obs["private"]["shed"] = {p: 20 for p in PRODUCTS}  # all 9 sellable products
    # dynamic_hiring explicitly off - this test is about order-list
    # construction/truncation priority (T8.5), not T8.16(d)'s backlog-
    # scaled hire count, so it pins the static value it actually asserts.
    params = dict(DEFAULT_PARAMS, dynamic_hiring=False, hires_per_day=4)
    action = decide(obs, params)
    assert action["market"][:4] == [["HIRE"]] * 4
    assert sum(1 for o in action["market"] if o == ["HIRE"]) == 4
    assert len(action["market"]) <= 10


def test_decide_dynamic_hiring_excludes_routine_watering_from_the_task_count(monkeypatch):
    # T8.16(a), fixing T8.12's own traced root cause: len(tasks) counted
    # routine, recurring WATER (and FEED) the same as genuine bottleneck
    # work (PLANT/HARVEST/acquisition), over-hiring without a
    # corresponding gain - see kagg.policy.strategy's own dynamic_hiring
    # rejection comment. pending_task_count must exclude WATER/FEED
    # specifically, not just count every queued task.
    import kagg.policy.decide as decide_module

    obs = _obs()
    tiles = obs["farms"][0]["tiles"]
    for i in range(5):
        tiles[0][i] = {
            "kind": "PLANT", "crop": "WHEAT", "planted_day": 0,
            "watered_today": False, "consecutive_unwatered": 0, "yield_units": 0,
            "max_lifespan_step": 120, "fertilized_until_day": -1,
        }

    captured_tasks = {}
    original_build = decide_module.build_task_list

    def build_spy(*args, **kwargs):
        result = original_build(*args, **kwargs)
        captured_tasks["tasks"] = result
        return result

    captured_hire_kwargs = {}
    original_hire = decide_module.hires_per_day

    def hire_spy(*args, **kwargs):
        if "pending_task_count" in kwargs:
            captured_hire_kwargs.update(kwargs)
        return original_hire(*args, **kwargs)

    monkeypatch.setattr(decide_module, "build_task_list", build_spy)
    monkeypatch.setattr(decide_module, "hires_per_day", hire_spy)
    decide(obs, dict(DEFAULT_PARAMS, dynamic_hiring=True))

    tasks = captured_tasks["tasks"]
    assert sum(1 for t in tasks if t.op == "WATER") == 5  # sanity: the 5 tiles really queue WATER
    expected = sum(1 for t in tasks if t.op not in ("WATER", "FEED"))
    assert captured_hire_kwargs.get("pending_task_count") == expected
    assert expected < len(tasks)  # the exclusion must actually remove something


def test_decide_passes_real_tile_counts_and_days_remaining_to_hires_per_day(monkeypatch):
    # T8.26: decide() must feed hires_per_day() the real, already-computed
    # tile-count signals (placed_animal_type_counts, own-tiles-only
    # _crop_tile_counts - NOT the opponent-blended _combined_crop_tile_
    # counts, which is for the unrelated crop-self-impact mechanism) and a
    # real days_remaining, regardless of workload_forecast_hiring_aware's
    # own on/off state - hires_per_day itself is what gates whether they're
    # used, matching every other "always pass the real signal, let the
    # callee's own flag decide" pattern in this module (e.g. animal_care_
    # aware passed to build_task_list unconditionally).
    import kagg.policy.decide as decide_module

    obs = _obs()
    obs["day"] = 5
    tiles = obs["farms"][0]["tiles"]
    tiles[3][3] = {
        "kind": "PASTURE", "animal": "COW", "placed_day": 0, "yield_units": 0,
        "consecutive_unfed": 0, "fed_today": True, "cared_today": False,
        "fertilizer_available": False, "pending_care_bonus": 0,
    }
    tiles[0][0] = {
        "kind": "PLANT", "crop": "WHEAT", "planted_day": 0, "watered_today": False,
        "consecutive_unwatered": 0, "yield_units": 0, "max_lifespan_step": 120,
        "fertilized_until_day": -1,
    }

    captured = {}
    original_hire = decide_module.hires_per_day

    def hire_spy(*args, **kwargs):
        if "animal_tile_counts" in kwargs:
            captured.update(kwargs)
        return original_hire(*args, **kwargs)

    monkeypatch.setattr(decide_module, "hires_per_day", hire_spy)
    decide(obs, dict(DEFAULT_PARAMS, dynamic_hiring=True))

    assert captured.get("animal_tile_counts") == {"COW": 1}
    assert captured.get("crop_tile_counts") == {"WHEAT": 1}
    season_length_days = DEFAULT_PARAMS.get("season_length_days", 30)
    assert captured.get("days_remaining") == season_length_days - 5


def test_decide_labor_units_reflects_the_real_dynamic_hiring_forecast_not_the_static_fallback(monkeypatch):
    # T8.29: labor_units used to be `1 + hires_per_day(params)` - a bare
    # call with no runtime arguments, so both the reactive and workload-
    # forecast paths fell straight through to the static fallback
    # (hires_per_day defaults to 1, labor_units hardcoded at 2) no matter
    # how large the farm's real workload was or what dynamic_hiring
    # (shipped default True) would actually target. This test builds a
    # farm whose real forecasted target clears the min_hires_per_day=2
    # floor - 75 already-placed, already-fed/cared COW tiles, hand-
    # verified via strategy._animal_actions_per_tile_day to forecast
    # exactly 3 hires under the shipped workload_forecast_hiring_aware/
    # scaling_only defaults (labor_units=4) - and checks plant_qty (the
    # clearest labor_units-gated observable, via free_tiles=25/seeds=100/
    # plant_budget=400, all non-binding) reflects that 4, not the old
    # bug's fixed 2.
    import kagg.policy.decide as decide_module

    obs = _obs()
    tiles = obs["farms"][0]["tiles"]
    for y in range(10):
        for x in range(10):
            if y * 10 + x < 75:
                tiles[y][x] = {
                    "kind": "PASTURE", "animal": "COW", "placed_day": 0, "yield_units": 0,
                    "consecutive_unfed": 0, "fed_today": True, "cared_today": False,
                    "fertilizer_available": False, "pending_care_bonus": 0,
                }
    market_inventory = {p: MARKET_I0 for p in PRODUCTS}
    market_inventory["MELON"] = 1  # scarce -> highest price -> ranks first
    obs["market"]["inventory"] = market_inventory
    obs["private"]["seeds"] = {"MELON": 100}

    captured = {}
    original = decide_module.build_task_list

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "build_task_list", spy)
    decide(obs, DEFAULT_PARAMS)

    assert captured.get("plant_crop") == "MELON"
    assert captured.get("plant_qty") == 4


def test_decide_labor_units_reflects_free_tiles_via_the_workload_forecast(monkeypatch):
    # T8.32 Stage 2: free_tiles is now threaded into both hires_per_day
    # call sites (labor_units's own early call, and the late HIRE-
    # queuing one) - this confirms the early one actually receives it,
    # mirroring test_decide_labor_units_reflects_the_real_dynamic_
    # hiring_forecast_not_the_static_fallback's own shape. The base
    # fixture's fresh, empty farm already has free_tiles=100 (every tile
    # is None) - hand-verified directly (not guessed) that plant_qty
    # goes 3 (default weight 0.0, an empty farm's own forecast clips to
    # min_hires_per_day=2, labor_units=3) -> 5 (workload_forecast_free_
    # tile_weight=0.5, labor_units=5) for otherwise-identical params.
    import kagg.policy.decide as decide_module

    obs = _obs()
    obs["market"]["inventory"]["MELON"] = 1  # scarce -> highest price -> ranks first
    obs["private"]["seeds"] = {"MELON": 100}

    captured = {}
    original = decide_module.build_task_list

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "build_task_list", spy)
    decide(obs, DEFAULT_PARAMS)
    assert captured.get("plant_qty") == 3

    captured.clear()
    params = dict(DEFAULT_PARAMS, workload_forecast_free_tile_weight=0.5)
    decide(obs, params)
    assert captured.get("plant_qty") == 5


def test_investment_buys_keep_a_reserved_slot_and_are_emitted_after_the_sells():
    # T8.5: BUY_SEED (part of `tail`) must still get a slot even when 9
    # sellable products alone would otherwise fill all 10, and must be
    # emitted *after* every SELL order in the list - buys placed ahead of
    # sells would see pre-sale money in the real interpreter's
    # index-by-index settlement.
    obs = _obs()
    obs["private"]["shed"] = {p: 20 for p in PRODUCTS}
    action = decide(obs, DEFAULT_PARAMS)  # hires_per_day=0 - no hire competition
    ops = [o[0] for o in action["market"]]
    assert "BUY_SEED" in ops
    sell_positions = [i for i, op in enumerate(ops) if op == "SELL"]
    buy_seed_position = ops.index("BUY_SEED")
    assert sell_positions and buy_seed_position > max(sell_positions)


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


def test_decide_liquidates_the_shed_near_the_end_of_the_season():
    # T8.3d: the user's own observed defect - a real end-of-episode SELL is
    # the last chance to realize any value from shed stock (confirmed in
    # the real kaggriculture.py engine: reward is final money only, no
    # auto-liquidation of leftover inventory), so the margin/drip-cap
    # protections that make sense mid-season must not strand it unsold.
    obs = _obs()
    obs["day"] = 29  # last day of the default 30-day season
    obs["private"]["shed"]["MELON"] = 50
    action = decide(obs, DEFAULT_PARAMS)
    sell_melon = [o for o in action["market"] if o[0] == "SELL" and o[1] == "MELON"]
    assert sell_melon == [["SELL", "MELON", 50]]


def test_decide_does_not_liquidate_early_in_the_season():
    obs = _obs()
    obs["day"] = 0
    obs["private"]["shed"]["MELON"] = 50
    action = decide(obs, DEFAULT_PARAMS)
    sell_melon = [o for o in action["market"] if o[0] == "SELL" and o[1] == "MELON"]
    assert sell_melon == [["SELL", "MELON", 5]]  # default drip_sell_max_per_turn still applies


def test_crop_tile_counts_counts_plant_tiles_by_crop():
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    tiles[0][1] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    tiles[1][0] = {"kind": "PLANT", "crop": "WHEAT", "planted_day": 0}
    tiles[2][0] = {"kind": "COOP"}  # not a PLANT tile - ignored
    assert _crop_tile_counts(tiles) == {"MELON": 2, "WHEAT": 1}


def test_decide_defaults_crop_self_impact_aware_to_true_when_unset():
    import kagg.policy.decide as decide_module

    assert DEFAULT_PARAMS.get("crop_self_impact_aware") is True
    assert decide_module._DEFAULT_CROP_SELF_IMPACT_AWARE is True


def test_decide_can_disable_crop_self_impact_awareness_explicitly():
    # Same setup as the enabled-by-default test below, but with the flag
    # off - decide() must fall back to rank_portfolio's pre-T8.3f
    # behavior (crop_tile_counts withheld entirely), still recommending
    # MELON despite the 30 already-committed tiles.
    obs = _obs()
    for i in range(30):
        obs["farms"][0]["tiles"][i % 10][i // 10] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    action = decide(obs, dict(DEFAULT_PARAMS, crop_self_impact_aware=False))
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert buy_seed_orders and buy_seed_orders[0][1] == "MELON"


def test_decide_stops_recommending_a_crop_the_farm_has_already_committed_many_tiles_to():
    # T8.3f, the user's own observation: end-to-end wiring check - once
    # the farm already has many MELON tiles (30, i.e. 180 melons in the
    # pipeline - enough to crash even the *next* tile's own average price
    # below every other crop's, per rank_portfolio's own docstring),
    # decide()'s own BUY_SEED choice must reflect the self-impact-
    # adjusted ranking, not just rank_portfolio tested in isolation.
    obs = _obs()
    for i in range(30):
        obs["farms"][0]["tiles"][i % 10][i // 10] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    action = decide(obs, DEFAULT_PARAMS)
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert buy_seed_orders and buy_seed_orders[0][1] != "MELON"


def test_combined_crop_tile_counts_gives_our_own_tiles_full_weight_always():
    # T8.3h: our own tiles are never discounted, regardless of
    # opponent_weight - only the opponent's contribution is graduated.
    my_tiles = [[None] * 10 for _ in range(10)]
    my_tiles[0][0] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    assert _combined_crop_tile_counts(my_tiles, other_farms=[], opponent_weight=0.0) == {"MELON": 1}


def test_combined_crop_tile_counts_scales_the_opponents_contribution_by_the_given_weight():
    my_tiles = [[None] * 10 for _ in range(10)]
    opponent_tiles = [[None] * 10 for _ in range(10)]
    opponent_tiles[0][0] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    opponent_tiles[0][1] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    combined = _combined_crop_tile_counts(my_tiles, other_farms=[{"tiles": opponent_tiles}], opponent_weight=0.5)
    assert combined == {"MELON": pytest.approx(1.0)}


def test_combined_crop_tile_counts_sums_my_own_and_the_opponents_at_full_weight():
    my_tiles = [[None] * 10 for _ in range(10)]
    my_tiles[0][0] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    opponent_tiles = [[None] * 10 for _ in range(10)]
    opponent_tiles[0][0] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    opponent_tiles[0][1] = {"kind": "PLANT", "crop": "WHEAT", "planted_day": 0}
    combined = _combined_crop_tile_counts(my_tiles, other_farms=[{"tiles": opponent_tiles}], opponent_weight=1.0)
    assert combined == {"MELON": 2, "WHEAT": 1}


def test_decide_defaults_crop_self_impact_opponent_weight_to_zero_when_unset():
    # T8.3g measured full weight (1.0) a clean, total self-play loss
    # (0/50 both blocks); T8.3h's graduated sweep (0.0/0.1/0.25/0.5/
    # 0.75/1.0) still found 0.0 the best - see decide.py's own
    # _DEFAULT_CROP_SELF_IMPACT_OPPONENT_WEIGHT comment for the full
    # measured story. Kept available (any weight can be set explicitly),
    # not the default.
    import kagg.policy.decide as decide_module

    assert DEFAULT_PARAMS.get("crop_self_impact_opponent_weight") == 0.0
    assert decide_module._DEFAULT_CROP_SELF_IMPACT_OPPONENT_WEIGHT == 0.0


def test_decide_ignores_the_opponent_by_default():
    # My own farm is empty, but the OPPONENT (fully visible via
    # obs["farms"] - see _combined_crop_tile_counts's own docstring)
    # already has 30 MELON tiles growing. By default this must NOT
    # change anything - MELON stays recommended, since
    # crop_self_impact_opponent_weight is 0.0 by default.
    obs = _obs()
    opponent_farm = copy.deepcopy(obs["farms"][0])
    for i in range(30):
        opponent_farm["tiles"][i % 10][i // 10] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    obs["farms"].append(opponent_farm)
    action = decide(obs, DEFAULT_PARAMS)
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert buy_seed_orders and buy_seed_orders[0][1] == "MELON"


def test_decide_demotes_a_crop_the_opponent_has_already_committed_many_tiles_to_when_explicitly_enabled():
    # T8.3g, the user's own follow-up: the mechanism itself works exactly
    # as designed when explicitly turned on (full weight) - it's just
    # measured a net loss in practice (see the rejection comment above),
    # not broken.
    obs = _obs()
    opponent_farm = copy.deepcopy(obs["farms"][0])
    for i in range(30):
        opponent_farm["tiles"][i % 10][i // 10] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    obs["farms"].append(opponent_farm)
    action = decide(obs, dict(DEFAULT_PARAMS, crop_self_impact_opponent_weight=1.0))
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert buy_seed_orders and buy_seed_orders[0][1] != "MELON"


def test_decide_defaults_crop_shop_demand_aware_to_true_when_unset():
    import kagg.policy.decide as decide_module

    assert DEFAULT_PARAMS.get("crop_shop_demand_aware") is True
    assert decide_module._DEFAULT_CROP_SHOP_DEMAND_AWARE is True


def test_decide_favors_a_crop_a_currently_unlocked_shop_is_consuming():
    # T8.3i, the user's own follow-up question: end-to-end wiring check.
    # 30 MELON tiles already committed pushes MELON itself out of the
    # running (same setup as the T8.3f test above) - among what's left,
    # STRAWBERRY is the plain crop-only leader with no shop information,
    # but PET_CAFE (sells only CARROT, doubled consumption rate) heavily
    # unlocked must tip the choice to CARROT instead.
    obs = _obs()
    for i in range(30):
        obs["farms"][0]["tiles"][i % 10][i // 10] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    obs["town"]["unlocked_shops"] = ["PET_CAFE"] * 8
    action = decide(obs, DEFAULT_PARAMS)
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert buy_seed_orders and buy_seed_orders[0][1] == "CARROT"


def test_decide_can_disable_shop_demand_awareness_explicitly():
    # Same setup as above, but with the flag off - PET_CAFE's demand must
    # be ignored, falling back to the plain crop-only leader (STRAWBERRY).
    obs = _obs()
    for i in range(30):
        obs["farms"][0]["tiles"][i % 10][i // 10] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0}
    obs["town"]["unlocked_shops"] = ["PET_CAFE"] * 8
    action = decide(obs, dict(DEFAULT_PARAMS, crop_shop_demand_aware=False))
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert buy_seed_orders and buy_seed_orders[0][1] == "STRAWBERRY"


def test_decide_defaults_crop_net_of_seed_cost_to_true_when_unset():
    import kagg.policy.decide as decide_module

    assert DEFAULT_PARAMS.get("crop_net_of_seed_cost") is True
    assert decide_module._DEFAULT_CROP_NET_OF_SEED_COST is True


def test_decide_passes_net_of_seed_cost_through_to_rank_portfolio(monkeypatch):
    # T8.3k, the user's own observation: decide() is the only real caller
    # of rank_portfolio (via _top_investment_choice/_top_crop_choice), so
    # this is the glue test for whether params["crop_net_of_seed_cost"]
    # actually reaches it - test_policy_strategy.py's own tests already
    # cover what the flag *does*.
    import kagg.policy.decide as decide_module

    captured = []
    original = decide_module.score_portfolio

    def spy(*args, **kwargs):
        captured.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "score_portfolio", spy)
    decide(_obs(), dict(DEFAULT_PARAMS, crop_net_of_seed_cost=False))
    assert captured and all(args[3] is False for args in captured)


def test_decide_defaults_use_fertilizer_to_false_when_unset():
    # T8.3e: built and tested, but measured to lose in direct self-play
    # at both priority tiers tried (see decide.py's own
    # _DEFAULT_USE_FERTILIZER comment for the full story) - kept
    # available, like "SHED", not the default.
    import kagg.policy.decide as decide_module

    assert DEFAULT_PARAMS.get("use_fertilizer") is False
    assert decide_module._DEFAULT_USE_FERTILIZER is False


def test_decide_does_not_fertilize_by_default():
    obs = _obs()
    obs["farms"][0]["tiles"][2][2] = {
        "kind": "PLANT", "crop": "WHEAT", "planted_day": 0, "watered_today": True,
        "consecutive_unwatered": 0, "yield_units": 0, "max_lifespan_step": 120,
        "fertilized_until_day": -1,
    }
    obs["private"]["inventories"] = [{"FERTILIZER": 1}]
    action = decide(obs, DEFAULT_PARAMS)
    assert action["farmer"][0] != "FERTILIZE"
    # Not held back either - sold normally, matching the pre-T8.3e default.
    obs["private"]["shed"]["FERTILIZER"] = 1
    action = decide(obs, DEFAULT_PARAMS)
    assert ["SELL", "FERTILIZER", 1] in action["market"]


def test_decide_fertilizes_when_explicitly_enabled():
    obs = _obs()
    obs["farms"][0]["tiles"][2][2] = {
        "kind": "PLANT", "crop": "WHEAT", "planted_day": 0, "watered_today": True,
        "consecutive_unwatered": 0, "yield_units": 0, "max_lifespan_step": 120,
        "fertilized_until_day": -1,
    }
    obs["farms"][0]["farmer"] = [2, 2]
    obs["private"]["inventories"] = [{"FERTILIZER": 1}]
    # always_pursue_one_animal explicitly off (T8.31's shipped default is
    # True): this test is about FERTILIZE's own priority, not the new
    # parallel animal-acquisition mechanism, which would otherwise move
    # the farmer toward the animal instead of fertilizing this turn.
    action = decide(obs, dict(DEFAULT_PARAMS, use_fertilizer=True, always_pursue_one_animal=False))
    assert action["farmer"] == ["FERTILIZE"]


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


# --- T8.19: portfolio_basket_size / _top_crop_basket ----------------------


def test_top_crop_basket_size_one_matches_the_full_ranking_s_top_maturing_crop():
    from kagg.policy.strategy import rank_portfolio

    market_inventory = {p: MARKET_I0 for p in PRODUCTS}
    basket = _top_crop_basket(market_inventory, current_day=0, params=DEFAULT_PARAMS, basket_size=1)
    ranked_crops = [n for n in rank_portfolio(market_inventory) if n in CROPS]
    assert basket == ranked_crops[:1]


def test_top_crop_basket_returns_up_to_basket_size_distinct_maturing_crops_in_rank_order():
    from kagg.policy.strategy import rank_portfolio

    market_inventory = {p: MARKET_I0 for p in PRODUCTS}
    basket = _top_crop_basket(market_inventory, current_day=0, params=DEFAULT_PARAMS, basket_size=3)
    ranked_crops = [n for n in rank_portfolio(market_inventory) if n in CROPS]
    assert basket == ranked_crops[:3]
    assert len(basket) == len(set(basket)) == 3


def test_top_crop_basket_skips_crops_that_cannot_mature_in_time():
    market_inventory = {p: MARKET_I0 for p in PRODUCTS}
    # Day 25: MELON (T3.1's own top pick at base price) can no longer
    # mature this season - mirrors test_top_investment_choice_skips_
    # crops_that_cannot_mature_in_time below.
    basket = _top_crop_basket(market_inventory, current_day=25, params=DEFAULT_PARAMS, basket_size=2)
    assert "MELON" not in basket


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
    # animal_net_of_cost explicitly off: this test is about
    # _top_investment_choice's own wiring (does it act on an animal top
    # choice at all), not about T8.3m's ranking economics - the T8.3m
    # ranking tests belong in test_policy_strategy.py.
    crashed_melon_inventory = {"MELON": MARKET_I0 + 100_000}
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False)
    choice = _top_investment_choice(crashed_melon_inventory, current_day=0, params=params)
    assert choice == ("COW", "animal")


def test_top_investment_choice_skips_an_animal_that_cannot_mature_in_time():
    # Same crashed-MELON ranking, but late enough that COW (first
    # overall) can't mature - SHEEP (next in rank) still can (verified:
    # forecast_animal_schedule("SHEEP", placed_day=22) starts at day 28).
    # animal_net_of_cost explicitly off - see the test above.
    crashed_melon_inventory = {"MELON": MARKET_I0 + 100_000}
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False)
    choice = _top_investment_choice(crashed_melon_inventory, current_day=22, params=params)
    assert choice == ("SHEEP", "animal")


def test_top_investment_choice_commit_margin_defaults_to_zero():
    # T8.14: investment_commit_margin defaults to 0.0 - bit-identical to
    # every pre-T8.14 caller, including this file's own crashed-MELON
    # wiring test above (COW at 86.0 vs STRAWBERRY's 36.06 - miles beyond
    # any margin, so this alone wouldn't distinguish default-off from a
    # margin - the point is DEFAULT_PARAMS itself carries no such key and
    # must not error or change behavior).
    crashed_melon_inventory = {"MELON": MARKET_I0 + 100_000}
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False)
    assert "investment_commit_margin" not in params or params["investment_commit_margin"] == 0.0
    choice = _top_investment_choice(crashed_melon_inventory, current_day=0, params=params)
    assert choice == ("COW", "animal")


def test_top_investment_choice_commit_margin_blocks_a_narrow_animal_lead():
    # T8.14, the user's own observation traced directly in this session's
    # own T8.10 rejection: a razor-thin animal lead over the best crop is
    # exactly the scenario that let a 2-turn market wobble fire a real,
    # irreversible BUY_ANIMAL. Constructed directly (verified via
    # score_portfolio, not guessed): at MILK inventory 10041 with MELON
    # crashed out of the running, COW scores 39.0 vs STRAWBERRY's own
    # 36.059 - an 8.16% lead, real but inside a 10% margin. With
    # investment_commit_margin=0.10, COW must NOT be returned - the
    # ranking falls through to the next candidate that clears the bar
    # (a crop needs no margin check at all - only animals do, matching
    # the exact traced failure mode).
    market_inventory = {"MELON": MARKET_I0 + 100_000, "EGG": MARKET_I0 + 100_000, "WOOL": MARKET_I0 + 100_000, "MILK": 10041}
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False, investment_commit_margin=0.10)
    choice = _top_investment_choice(market_inventory, current_day=0, params=params)
    assert choice == ("STRAWBERRY", "crop")


def test_top_investment_choice_commit_margin_allows_a_wide_animal_lead():
    # Same shape, MILK inventory 10040 - COW scores 40.0 vs STRAWBERRY's
    # 36.059, an 10.93% lead, just past the same 10% margin. Must still
    # return the animal - the margin blocks a narrow lead, not every one.
    market_inventory = {"MELON": MARKET_I0 + 100_000, "EGG": MARKET_I0 + 100_000, "WOOL": MARKET_I0 + 100_000, "MILK": 10040}
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False, investment_commit_margin=0.10)
    choice = _top_investment_choice(market_inventory, current_day=0, params=params)
    assert choice == ("COW", "animal")


def test_top_animal_choice_returns_the_best_scoring_animal_with_time_to_mature():
    # T8.31 Stage 1: _top_animal_choice ranks animals in isolation, never
    # against best_crop_score - a fresh market at day 0 under shipped
    # defaults (verified directly via score_portfolio, not guessed):
    # COW=23.23 > SHEEP=19.13 > GOOSE=6.50, all with time to mature.
    market_inventory = {p: MARKET_I0 for p in PRODUCTS}
    assert _top_animal_choice(market_inventory, current_day=0, params=DEFAULT_PARAMS) == "COW"


def test_top_animal_choice_skips_an_animal_that_cannot_mature_in_time():
    # animal_net_of_cost off (isolating wiring from T8.3m's ranking
    # economics, matching this file's own established convention) - at
    # this market, COW=86.0 > SHEEP=70.67 > GOOSE=50.0 (verified
    # directly). Day 22/season 30: COW can no longer mature
    # (_animal_has_time_to_mature confirms False) but SHEEP still can -
    # the walk must skip COW and return SHEEP, not None.
    market_inventory = {p: MARKET_I0 for p in PRODUCTS}
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False)
    assert _top_animal_choice(market_inventory, current_day=22, params=params) == "SHEEP"


def test_top_animal_choice_returns_none_once_nothing_can_mature():
    # Day 29 of a 30-day season: every animal's first production would
    # land past the season end (verified directly via
    # _animal_has_time_to_mature for all three) - forcing a purchase here
    # would only waste capital on something that can never pay off.
    market_inventory = {p: MARKET_I0 for p in PRODUCTS}
    assert _top_animal_choice(market_inventory, current_day=29, params=DEFAULT_PARAMS) is None


def test_decide_always_pursue_one_animal_off_reproduces_the_exact_pre_t831_either_or_behavior():
    # T8.31 Stage 1: always_pursue_one_animal is accepted True by
    # default (measured, tasks/todo.md), so the pre-T8.31 either/or
    # behavior stays reachable via an explicit override, mirroring
    # plant_while_pursuing_animal's own pattern - the base fixture's
    # default market (MELON wins the crop ranking outright, far
    # outranking any animal) must produce no BUY_ANIMAL order at all
    # with the flag explicitly off.
    obs = _obs()
    params = dict(DEFAULT_PARAMS, always_pursue_one_animal=False)
    action = decide(obs, params)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == []


def test_decide_always_pursue_one_animal_queues_the_best_animal_alongside_a_crop_top_pick():
    # With no animal anywhere yet and always_pursue_one_animal=True, the
    # best-scoring animal (COW at this fresh market - verified via
    # _top_animal_choice's own test above) is pursued in PARALLEL with
    # whatever the crop ranking already picked (MELON here), not instead
    # of it - mirrors plant_while_pursuing_animal's existing shape in the
    # opposite direction (that flag plants a crop while an animal is the
    # top pick; this one buys an animal while a crop is).
    obs = _obs()
    params = dict(DEFAULT_PARAMS, always_pursue_one_animal=True)
    action = decide(obs, params)
    buy_animal_orders = [o for o in action["market"] if o[0] == "BUY_ANIMAL"]
    assert buy_animal_orders == [["BUY_ANIMAL", "COW", 1]]
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert len(buy_seed_orders) == 1
    assert buy_seed_orders[0][1] == "MELON"


def test_decide_always_pursue_one_animal_stops_once_any_animal_exists_anywhere():
    # Once an animal exists in any form (placed, stuck in the shed, or in
    # farmer_inventory), this path must not fire again - the existing
    # stuck_animal/max_animals_per_type "finish what's already bought"
    # logic take over exactly as today, unaffected by this new flag.
    obs = _obs()
    obs["private"]["shed"]["COW"] = 1  # already bought, awaiting BUILD/PLACE
    params = dict(DEFAULT_PARAMS, always_pursue_one_animal=True)
    action = decide(obs, params)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == []


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
    # animal_net_of_cost explicitly off: this test is about the crop-
    # fallback wiring (T8.9/T8.3b), not T8.3m's ranking economics.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}  # crashes MELON - COW ranks first overall
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False)
    action = decide(obs, params)
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert len(buy_seed_orders) == 1
    assert buy_seed_orders[0][1] in CROPS
    buy_animal_orders = [o for o in action["market"] if o[0] == "BUY_ANIMAL"]
    assert buy_animal_orders == [["BUY_ANIMAL", "COW", 1]]


def test_decide_can_still_disable_the_crop_fallback_explicitly():
    # The pre-T8.3b behavior stays reachable via an explicit override -
    # both purchases are independent market orders with no structural
    # reason to be exclusive, so disabling the fallback alone is enough
    # to reproduce the old "animal only" behavior. animal_net_of_cost
    # explicitly off, same reason as the test above.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}
    params = dict(DEFAULT_PARAMS, plant_while_pursuing_animal=False, animal_net_of_cost=False)
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
    # animal_net_of_cost explicitly off, same reason as the tests above.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}
    obs["farms"][0]["tiles"][4][4] = _placed_cow_tile()
    obs["farms"][0]["farmer"] = [0, 0]
    obs["private"]["seeds"]["STRAWBERRY"] = 1
    params = dict(DEFAULT_PARAMS, plant_while_pursuing_animal=False, animal_net_of_cost=False)
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
    # animal_net_of_cost explicitly off - see the tests above.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False)
    action = decide(obs, params)
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


def test_decide_max_animals_per_type_defaults_to_one_bit_identical():
    # T8.22: max_animals_per_type defaults to 1 - the exact prior "never a
    # second instance" rule from
    # test_decide_does_not_buy_a_second_animal_of_a_type_already_placed_and_alive,
    # reproduced bit-identically for every caller that doesn't pass it.
    assert DEFAULT_PARAMS.get("max_animals_per_type", 1) == 1


def test_decide_pursues_a_second_animal_of_the_same_type_when_the_cap_allows_it():
    # T8.22, the user's own request once corrected unit economics showed
    # animals can be competitive: BUY_ANIMAL has no same-type limit at all
    # in the real game (kaggriculture.py) - the "never a second instance"
    # rule was entirely this module's own simplification. With
    # max_animals_per_type raised past the current count of 1, decide()
    # must resume pursuing another COW instead of refusing forever.
    obs = _obs()
    # Every crop crashed (not just MELON) - confirmed directly against
    # score_portfolio at animal_net_of_cost=True (the shipped default)
    # that COW only tops the *full* ranking, not just MELON, once every
    # crop is crashed this way (CARROT/WHEAT/TOMATO otherwise outrank it).
    obs["market"]["inventory"] = {c: MARKET_I0 + 100_000 for c in CROPS}
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
    params = dict(DEFAULT_PARAMS, max_animals_per_type=2)
    action = decide(obs, params)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == [["BUY_ANIMAL", "COW", 1]]


def test_decide_still_blocks_a_third_animal_once_the_raised_cap_is_reached():
    obs = _obs()
    obs["market"]["inventory"] = {c: MARKET_I0 + 100_000 for c in CROPS}  # COW is the top choice
    animal_tile = {
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
    obs["farms"][0]["tiles"][3][3] = dict(animal_tile)
    obs["farms"][0]["tiles"][3][4] = dict(animal_tile)
    params = dict(DEFAULT_PARAMS, max_animals_per_type=2)
    action = decide(obs, params)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == []


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
    # animal_net_of_cost explicitly off - see the tests above.
    obs = _fill_all_tiles(_obs())
    obs["farms"][0]["tiles"][0][0] = {"kind": "PASTURE"}
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}  # COW is the top choice
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False)
    action = decide(obs, params)
    assert [o for o in action["market"] if o[0] == "BUY_ANIMAL"] == [["BUY_ANIMAL", "COW", 1]]


def test_decide_assigns_hands_when_present():
    obs = _obs()
    obs["farms"][0]["hands"] = [[0, 0]]
    obs["private"]["inventories"] = [{}, {}]
    obs["farms"][0]["tiles"][0][0] = {"kind": "WEED"}
    action = decide(obs, DEFAULT_PARAMS)
    assert len(action["hands"]) == 1
    assert action["hands"][0] == ["DIG"]  # already standing on the weed tile


def test_decide_does_not_buy_wheat_before_any_animal_exists():
    # T8.3l: the user's own observed defect - decide() was buying 10
    # WHEAT every turn shed WHEAT fell below wheat_restock_threshold, then
    # market.sell_orders sold all of it right back (wheat_reserve is 0
    # until an animal is placed) - a real, decisive ping-pong traced in a
    # live episode (147 buy/sell pairs, seed 100), with no crop or animal
    # ever on the farm. With no animal placed and none being pursued
    # (crops rank ahead of every animal by default with an empty
    # market), there is no feed to restock for at all.
    # always_pursue_one_animal explicitly off (T8.31's shipped default is
    # True, which would otherwise pursue an animal in parallel here even
    # with crops ranking first) - this test is about the wheat-restock
    # ping-pong fix, not T8.31's own mechanism.
    params = dict(DEFAULT_PARAMS, always_pursue_one_animal=False)
    action = decide(_obs(), params)
    assert [o for o in action["market"] if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"] == []


def test_decide_buys_wheat_once_an_animal_is_being_pursued():
    # Once an animal is the top investment choice (crops crashed via the
    # market), feed is needed even before the animal is actually placed -
    # restocking should already be active so feed is on hand by the time
    # PLACE fires. animal_net_of_cost explicitly off - see the tests above.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}  # COW ranks first overall
    obs["private"]["shed"]["WHEAT"] = 0
    params = dict(DEFAULT_PARAMS, animal_net_of_cost=False)
    action = decide(obs, params)
    assert [o for o in action["market"] if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"] == [
        ["BUY_PRODUCT", "WHEAT", 10]
    ]


def test_decide_buys_wheat_once_an_animal_is_placed():
    obs = _obs()
    obs["farms"][0]["tiles"][2][4] = _placed_cow_tile()
    obs["private"]["shed"]["WHEAT"] = 0
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"] == [
        ["BUY_PRODUCT", "WHEAT", 10]
    ]


def test_decide_wheat_restock_ignores_carried_inventory_by_default():
    # T8.36 (user's own observed defect, spotted directly in
    # tools/daily_dashboard.py's buy/sell columns): tasks._WHEAT_PICKUP_
    # BATCH (10) grabs the whole reserve out of the shed into the
    # farmer's own inventory the moment any is needed for feeding - most
    # of that batch is unused that day and safely returns to the shed at
    # end-of-day (kaggriculture.py's own _drop_inventories_to_shed), but
    # buy_wheat_order's restock check only ever looks at the *shed*
    # count, blind to WHEAT already secured in a unit's inventory - so it
    # re-buys every single day even with 9 spare units already in hand.
    # Bit-identical to today's shipped (buggy) behavior with the flag
    # unset - this pins the bug down with a real regression test before
    # fixing it below, not just describing it in prose.
    obs = _obs()
    obs["farms"][0]["tiles"][2][4] = _placed_cow_tile()
    obs["private"]["shed"]["WHEAT"] = 0
    obs["private"]["inventories"] = [{"WHEAT": 9}]  # plenty on hand, just not in the shed
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"] == [
        ["BUY_PRODUCT", "WHEAT", 10]
    ]


def test_decide_wheat_restock_counts_carried_inventory_when_enabled():
    # Same fixture as the "by default" test above, flag turned on: total
    # wheat on hand (0 shed + 9 carried) clears wheat_restock_threshold
    # (5), so there is nothing to restock - the actual fix.
    obs = _obs()
    obs["farms"][0]["tiles"][2][4] = _placed_cow_tile()
    obs["private"]["shed"]["WHEAT"] = 0
    obs["private"]["inventories"] = [{"WHEAT": 9}]
    params = dict(DEFAULT_PARAMS, wheat_restock_counts_carried_inventory=True)
    action = decide(obs, params)
    assert [o for o in action["market"] if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"] == []


def test_decide_wheat_restock_counts_carried_inventory_still_buys_below_threshold():
    # The flag adds carried inventory to the total, it doesn't disable
    # the restock check entirely: 0 shed + 2 carried is still below
    # wheat_restock_threshold (5), so a restock still fires.
    obs = _obs()
    obs["farms"][0]["tiles"][2][4] = _placed_cow_tile()
    obs["private"]["shed"]["WHEAT"] = 0
    obs["private"]["inventories"] = [{"WHEAT": 2}]
    params = dict(DEFAULT_PARAMS, wheat_restock_counts_carried_inventory=True)
    action = decide(obs, params)
    assert [o for o in action["market"] if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"] == [
        ["BUY_PRODUCT", "WHEAT", 10]
    ]


def test_decide_wheat_restock_counts_carried_inventory_sums_every_unit():
    # private["inventories"] is [farmer, hand1, hand2, ...] - every
    # entry must count, not just index 0.
    obs = _obs()
    obs["farms"][0]["tiles"][2][4] = _placed_cow_tile()
    obs["private"]["shed"]["WHEAT"] = 0
    obs["private"]["inventories"] = [{"WHEAT": 3}, {"WHEAT": 4}]
    params = dict(DEFAULT_PARAMS, wheat_restock_counts_carried_inventory=True)
    action = decide(obs, params)
    assert [o for o in action["market"] if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"] == []


def test_decide_defaults_wheat_buy_only_when_feed_needed_to_true_when_unset():
    # Mirrors test_decide_defaults_crop_net_of_seed_cost_to_true_when_unset's
    # pattern: a params dict missing the key entirely must behave like the
    # documented default (True), not like it's off.
    # always_pursue_one_animal explicitly off - see test_decide_does_not_
    # buy_wheat_before_any_animal_exists's own comment for why.
    params = {
        k: v for k, v in DEFAULT_PARAMS.items() if k != "wheat_buy_only_when_feed_needed"
    }
    params["always_pursue_one_animal"] = False
    action = decide(_obs(), params)
    assert [o for o in action["market"] if o[0] == "BUY_PRODUCT" and o[1] == "WHEAT"] == []


def test_decide_liquidation_ignores_the_wheat_reserve():
    # T8.3l: sell_orders previously kept wheat_reserve units off the
    # liquidation sale too, stranding the feed reserve (worthless unsold
    # at episode end per T8.3d) once an animal had been placed.
    obs = _obs()
    obs["day"] = 29  # within liquidation_days_before_end=2 of season end (30)
    obs["farms"][0]["tiles"][2][4] = _placed_cow_tile()
    obs["private"]["shed"]["WHEAT"] = 10
    action = decide(obs, DEFAULT_PARAMS)
    sell_wheat_orders = [o for o in action["market"] if o[0] == "SELL" and o[1] == "WHEAT"]
    assert sell_wheat_orders == [["SELL", "WHEAT", 10]]


def test_decide_defaults_liquidate_wheat_reserve_to_true_when_unset():
    params = {k: v for k, v in DEFAULT_PARAMS.items() if k != "liquidate_wheat_reserve"}
    obs = _obs()
    obs["day"] = 29
    obs["farms"][0]["tiles"][2][4] = _placed_cow_tile()
    obs["private"]["shed"]["WHEAT"] = 10
    action = decide(obs, params)
    sell_wheat_orders = [o for o in action["market"] if o[0] == "SELL" and o[1] == "WHEAT"]
    assert sell_wheat_orders == [["SELL", "WHEAT", 10]]


def test_decide_defaults_rank_season_aware_to_false_when_unset():
    # T8.3m: built and tested, but measured to lose decisively in direct
    # self-play (1/44 working, 2/47 held-out) - see decide.py's own
    # _DEFAULT_RANK_SEASON_AWARE comment for the full traced story.
    import kagg.policy.decide as decide_module

    assert DEFAULT_PARAMS.get("rank_season_aware") is False
    assert decide_module._DEFAULT_RANK_SEASON_AWARE is False


def test_decide_defaults_animal_net_of_cost_to_true_when_unset():
    # T8.3m: accepted - the strongest measured result of the whole
    # T8.3-series investigation so far (50/50 working, 49/50 held-out) -
    # see decide.py's own _DEFAULT_ANIMAL_NET_OF_COST comment.
    import kagg.policy.decide as decide_module

    assert DEFAULT_PARAMS.get("animal_net_of_cost") is True
    assert decide_module._DEFAULT_ANIMAL_NET_OF_COST is True


def test_decide_passes_days_remaining_through_to_rank_portfolio_only_when_a_flag_is_on(monkeypatch):
    # T8.3m: decide() is the only real caller of rank_portfolio (via
    # _top_investment_choice/_top_crop_choice), so this is the glue test
    # for whether params["rank_season_aware"]/params["animal_net_of_cost"]
    # actually reach it, and that days_remaining stays None when neither
    # is set - test_policy_strategy.py's own tests already cover what
    # each flag *does*. animal_net_of_cost defaults to True (accepted),
    # so both-off is tested with it explicitly disabled.
    import kagg.policy.decide as decide_module

    captured = []
    original = decide_module.score_portfolio

    def spy(*args, **kwargs):
        captured.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "score_portfolio", spy)
    decide(_obs(), dict(DEFAULT_PARAMS, animal_net_of_cost=False))  # both flags off
    assert captured and all(args[4] is None and args[5] is False and args[6] is False for args in captured)

    captured.clear()
    obs = _obs()
    obs["day"] = 20
    decide(obs, dict(DEFAULT_PARAMS, rank_season_aware=True, animal_net_of_cost=False))
    assert captured and all(args[4] == 10 and args[5] is True and args[6] is False for args in captured)

    captured.clear()
    decide(obs, dict(DEFAULT_PARAMS, animal_net_of_cost=True))  # the accepted default
    assert captured and all(args[4] == 10 and args[5] is False and args[6] is True for args in captured)


def test_decide_defaults_animal_fertilizer_income_aware_to_false_when_unset():
    # T8.3q: built and not yet measured - see decide.py's own
    # _DEFAULT_ANIMAL_FERTILIZER_INCOME_AWARE comment.
    import kagg.policy.decide as decide_module

    assert DEFAULT_PARAMS.get("animal_fertilizer_income_aware") is False
    assert decide_module._DEFAULT_ANIMAL_FERTILIZER_INCOME_AWARE is False


def test_decide_passes_animal_fertilizer_income_aware_through_to_rank_portfolio(monkeypatch):
    import kagg.policy.decide as decide_module

    captured = []
    original = decide_module.score_portfolio

    def spy(*args, **kwargs):
        captured.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "score_portfolio", spy)
    decide(_obs(), dict(DEFAULT_PARAMS, animal_fertilizer_income_aware=True))
    assert captured and all(args[7] is True for args in captured)

    captured.clear()
    decide(_obs(), dict(DEFAULT_PARAMS, animal_fertilizer_income_aware=False))
    assert captured and all(args[7] is False for args in captured)


def test_decide_defaults_animal_care_aware_to_false_when_unset():
    import kagg.policy.decide as decide_module

    assert DEFAULT_PARAMS.get("animal_care_aware") is False
    assert decide_module._DEFAULT_ANIMAL_CARE_AWARE is False


def test_decide_passes_animal_care_aware_through_to_rank_portfolio(monkeypatch):
    import kagg.policy.decide as decide_module

    captured = []
    original = decide_module.score_portfolio

    def spy(*args, **kwargs):
        captured.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "score_portfolio", spy)
    decide(_obs(), dict(DEFAULT_PARAMS, animal_care_aware=True))
    assert captured and all(args[8] is True for args in captured)

    captured.clear()
    decide(_obs(), dict(DEFAULT_PARAMS, animal_care_aware=False))
    assert captured and all(args[8] is False for args in captured)


def test_decide_passes_care_aware_through_to_build_task_list(monkeypatch):
    # decide() is the only real caller of build_task_list - this is the
    # glue test for whether params["animal_care_aware"] reaches it;
    # test_policy_tasks.py's own tests already cover what the flag *does*.
    import kagg.policy.decide as decide_module

    captured = {}
    original = decide_module.build_task_list

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "build_task_list", spy)
    decide(_obs(), dict(DEFAULT_PARAMS, animal_care_aware=True))
    assert captured.get("care_aware") is True

    captured.clear()
    decide(_obs(), dict(DEFAULT_PARAMS, animal_care_aware=False))
    assert captured.get("care_aware") is False


def test_decide_stops_planting_a_late_season_ongoing_crop_when_season_aware():
    # A direct behavioral check, not just a glue check: with only 11 days
    # left, STRAWBERRY (which needs 17 tile-days for its full schedule)
    # must not be the crop decide() buys a seed for once rank_season_aware
    # is on, in a market rigged so STRAWBERRY would otherwise be the top
    # crop pick.
    from kagg.gamelib.constants import MARKET_I0, PRODUCTS

    obs = _obs()
    obs["day"] = 19  # 11 days left of the default 30-day season
    # Crash MELON (the base-price crop leader - see
    # test_rank_portfolio_orders_by_marginal_revenue_at_base_price in
    # test_policy_strategy.py) and make STRAWBERRY scarce, so STRAWBERRY
    # is the clear crop leader without season awareness.
    obs["market"]["inventory"] = {p: MARKET_I0 for p in PRODUCTS}
    obs["market"]["inventory"]["MELON"] = MARKET_I0 + 100_000
    obs["market"]["inventory"]["STRAWBERRY"] = MARKET_I0 - 90  # scarce -> high price
    action_unaware = decide(obs, DEFAULT_PARAMS)
    seed_unaware = next(o[1] for o in action_unaware["market"] if o[0] == "BUY_SEED")
    assert seed_unaware == "STRAWBERRY"

    action_aware = decide(obs, dict(DEFAULT_PARAMS, rank_season_aware=True))
    seeds_aware = [o[1] for o in action_aware["market"] if o[0] == "BUY_SEED"]
    assert "STRAWBERRY" not in seeds_aware


def test_decide_never_requests_more_plants_than_seeds_on_hand(monkeypatch):
    # T8.6: reproduces the real interpreter's own atomic PLANT validation
    # (kaggriculture.py: "blocked = {crop for crop, n in
    # plant_demand.items() if n > seeds.get(crop, 0)}" - if total PLANT
    # requests for a crop this turn exceed seeds held, ALL of them are
    # dropped, not just the excess). plant_qty must never exceed seeds on
    # hand, for every labor level - a permanent regression guard, swept
    # rather than checked at one point.
    import kagg.policy.decide as decide_module

    captured = {}
    original = decide_module.build_task_list

    def spy(*args, **kwargs):
        captured.clear()
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "build_task_list", spy)

    for n_seeds in range(4):  # 0..3
        for hires in range(6):  # 0..5
            obs = _obs()
            obs["private"]["seeds"] = {crop: n_seeds for crop in CROPS}
            decide(obs, dict(DEFAULT_PARAMS, hires_per_day=hires))
            plant_qty = captured.get("plant_qty", 0)
            assert plant_qty <= n_seeds, f"n_seeds={n_seeds} hires={hires}: plant_qty={plant_qty}"


def test_decide_batches_seed_purchase_into_one_order_when_labor_allows_more_than_one():
    # T8.6: seeds are bought as one BUY_SEED order with a quantity, not N
    # separate orders - costs exactly one market slot regardless of how
    # many seeds are requested (verified: the real interpreter's
    # _parse_order reads order[2] as the full remaining count).
    # T8.29: dynamic_hiring off (pin the static hires_per_day=3) so
    # labor_units is exactly 4, deterministic - this test is about
    # order-batching, not the dynamic hiring forecast.
    obs = _obs()
    params = dict(
        DEFAULT_PARAMS, dynamic_hiring=False, hires_per_day=3, seed_buffer_per_unit=2,
    )  # labor_units=4, target=8
    action = decide(obs, params)
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert len(buy_seed_orders) == 1
    assert buy_seed_orders[0][2] == 8  # one order, quantity 8 - not eight orders of 1


def test_decide_plant_qty_stops_at_the_watering_capacity_cap(monkeypatch):
    # T8.6: max_plants_per_unit is a real structural safeguard, not a
    # formality - a tile weeds at consecutive_unwatered>=2, so planted
    # area beyond what labor can water converts seed spend into WEEDs.
    # Forces plant_budget (not labor_units, seeds, or
    # max_plant_tasks_per_turn) to be the binding constraint.
    import kagg.policy.decide as decide_module

    captured = {}
    original = decide_module.build_task_list

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "build_task_list", spy)

    obs = _obs()
    for i in range(10):
        obs["farms"][0]["tiles"][5][i] = {
            "kind": "PLANT", "crop": "WHEAT", "planted_day": 0, "watered_today": True,
            "consecutive_unwatered": 0, "yield_units": 0, "max_lifespan_step": 120,
            "fertilized_until_day": -1,
        }
    obs["private"]["seeds"] = {crop: 10 for crop in CROPS}
    # T8.29: dynamic_hiring off (pin the static hires_per_day=5) so
    # labor_units is exactly 6, deterministic - this test is about
    # plant_budget capping planting, not the dynamic hiring forecast.
    params = dict(
        DEFAULT_PARAMS, dynamic_hiring=False, hires_per_day=5,
        max_plants_per_unit=2, max_plant_tasks_per_turn=8,
    )
    # labor_units=6, plant_budget=max(0, 2*6 - 10)=2 - strictly below
    # labor_units(6)/seeds(10)/max_plant_tasks_per_turn(8), so it's the
    # only term that can be observed binding here.
    decide(obs, params)
    assert captured.get("plant_qty") == 2


def test_top_crop_basket_threads_wheat_feed_units_needed_to_rank_portfolio():
    # T8.24: confirms the threading only - the underlying economics
    # (wheat_feed_credit_per_tile_day's own make-vs-buy mechanism) is
    # already covered directly in test_policy_strategy.py. _top_crop_
    # basket's own crop-only ranking must match rank_portfolio's own
    # output (filtered to crops, same maturity filter) when given the
    # identical wheat_self_sufficiency_aware/wheat_feed_units_needed -
    # exactly like every other score_portfolio-derived flag this
    # function already threads straight through.
    from kagg.policy.strategy import rank_portfolio

    market_inventory = {}
    params = dict(DEFAULT_PARAMS, wheat_self_sufficiency_aware=True)
    basket = _top_crop_basket(
        market_inventory, current_day=0, params=params, basket_size=8,
        wheat_feed_units_needed=20,
    )
    expected_full_ranking = rank_portfolio(
        market_inventory, wheat_self_sufficiency_aware=True, wheat_feed_units_needed=20,
    )
    expected_crop_ranking = [n for n in expected_full_ranking if n in CROPS][: len(basket)]
    assert basket == expected_crop_ranking


def test_top_crop_basket_wheat_feed_units_needed_defaults_to_zero():
    params = dict(DEFAULT_PARAMS, wheat_self_sufficiency_aware=True)
    assert _top_crop_basket({}, current_day=0, params=params, basket_size=8) == _top_crop_basket(
        {}, current_day=0, params=params, basket_size=8, wheat_feed_units_needed=0,
    )


def _spy_on_top_crop_basket(monkeypatch):
    # decide() calls _top_crop_basket with wheat_feed_units_needed passed
    # as a keyword (see its own call site) - captured straight from
    # kwargs, no positional-index guessing needed.
    import kagg.policy.decide as decide_module

    captured = {}
    original = decide_module._top_crop_basket

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(decide_module, "_top_crop_basket", spy)
    return captured


def test_decide_computes_zero_wheat_feed_demand_with_no_animal(monkeypatch):
    captured = _spy_on_top_crop_basket(monkeypatch)
    obs = _obs()
    params = dict(DEFAULT_PARAMS, wheat_self_sufficiency_aware=True)
    decide(obs, params)
    assert captured.get("wheat_feed_units_needed") == 0


def test_decide_computes_real_wheat_feed_demand_with_a_placed_animal(monkeypatch):
    captured = _spy_on_top_crop_basket(monkeypatch)
    obs = _obs()
    obs["day"] = 5
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
    params = dict(DEFAULT_PARAMS, wheat_self_sufficiency_aware=True)
    decide(obs, params)
    season_length_days = params.get("season_length_days", 30)
    assert captured.get("wheat_feed_units_needed") == season_length_days - 5


def test_decide_computes_zero_wheat_feed_demand_when_flag_is_off(monkeypatch):
    captured = _spy_on_top_crop_basket(monkeypatch)
    obs = _obs()
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
    params = dict(DEFAULT_PARAMS, wheat_self_sufficiency_aware=False)
    decide(obs, params)
    assert captured.get("wheat_feed_units_needed") == 0
