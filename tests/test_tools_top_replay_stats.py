"""Tests for tools/top_replay_stats.py - see tasks/todo.md's T8.40 entry.

Follows tests/test_tools_daily_dashboard.py's convention: small literal
dict fixtures, no oracle, no replay file needed on disk (must pass on a
clean checkout with data/ empty). Functions that mirror an already-tested
rule (classify_plant_transition/classify_animal_transition, order_fill)
are exercised here only to confirm the wiring - not re-tested for their
own logic, which tests/test_tools_daily_dashboard.py already covers.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import top_replay_stats  # noqa: E402


# --- fixture builders (mirror test_tools_daily_dashboard.py's own style) --


def _board(size=10):
    return [[None for _ in range(size)] for _ in range(size)]


def _plant_tile(crop="WHEAT", consecutive_unwatered=0, watered_today=False, yield_units=0, max_lifespan_step=-1):
    return {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": 0,
        "watered_today": watered_today,
        "consecutive_unwatered": consecutive_unwatered,
        "yield_units": yield_units,
        "max_lifespan_step": max_lifespan_step,
        "fertilized_until_day": -1,
    }


def _animal_tile(animal="GOOSE", consecutive_unfed=0, fed_today=False):
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


def _farm(tiles=None, hands=None, hires_today=0, money=3000.0, unlocked_quadrants=None, farmer=None):
    return {
        "farmer": farmer or [0, 0],
        "hands": hands or [],
        "hires_today": hires_today,
        "money": money,
        "tiles": tiles if tiles is not None else _board(),
        "unlocked_quadrants": list(unlocked_quadrants or ["NW"]),
    }


def _private(seeds=None, shed=None):
    return {"seeds": dict(seeds or {}), "shed": dict(shed or {}), "inventories": [{}]}


def _step(day, hour, farm0, farm1, private0, private1, action0=None, action1=None, town_shops=None, prices=None):
    farms = [farm0, farm1]
    town = {"unlocked_shops": list(town_shops or [])}
    market = {"prices": dict(prices or {}), "inventory": {}}
    obs0 = {"day": day, "hour": hour, "player": 0, "farms": farms, "private": private0, "town": town, "market": market}
    obs1 = {"day": day, "hour": hour, "player": 1, "farms": farms, "private": private1, "town": town, "market": market}
    return [
        {"action": action0, "observation": obs0, "reward": farm0["money"], "status": "ACTIVE"},
        {"action": action1, "observation": obs1, "reward": farm1["money"], "status": "ACTIVE"},
    ]


# --- count_tiles ------------------------------------------------------


def test_count_tiles_handles_locked_and_empty_and_populated_tiles():
    tiles = _board(2)
    tiles[0][1] = "LOCKED"
    tiles[1][0] = _plant_tile("WHEAT")
    tiles[1][1] = _animal_tile("COW")
    counts = top_replay_stats.count_tiles({"tiles": tiles})
    assert counts["empty"] == 1
    assert counts["locked"] == 1
    assert counts["plants"] == {"WHEAT": 1}
    assert counts["animals"] == {"COW": 1}
    assert counts["plants_total"] == 1
    assert counts["animals_total"] == 1


def test_count_tiles_counts_bare_structures_and_weeds_separately_from_animals():
    tiles = _board(2)
    tiles[0][0] = {"kind": "COOP"}  # empty structure - never held or already escaped
    tiles[0][1] = {"kind": "WEED"}
    counts = top_replay_stats.count_tiles({"tiles": tiles})
    assert counts["structures"] == {"COOP": 1}
    assert counts["weeds"] == 1
    assert counts["animals_total"] == 0


# --- day_turns ----------------------------------------------------------


def test_day_turns_normal_day():
    assert list(top_replay_stats.day_turns(720, 2, 24)) == list(range(48, 72))


def test_day_turns_clips_at_episode_end():
    assert list(top_replay_stats.day_turns(50, 2, 24)) == list(range(48, 50))


def test_day_turns_entirely_beyond_episode_is_empty():
    assert list(top_replay_stats.day_turns(24, 5, 24)) == []


# --- hands_for_day --------------------------------------------------------


def test_hands_for_day_hour_zero_undercounts_hands_max_catches_a_late_hire():
    turns = []
    for hour in range(24):
        if hour < 20:
            farm0 = _farm(hands=[], hires_today=0)
        else:
            farm0 = _farm(hands=[[1, 1]], hires_today=1)
        turns.append(_step(0, hour, farm0, _farm(), _private(), _private()))
    result = top_replay_stats.hands_for_day(turns, day=0, team=0, at_hour=12)
    assert result == {"hands_max": 1, "hands_at_mid_day": 0, "hires_today": 1}


def test_hands_for_day_picks_up_hires_today_correctly():
    turns = [_step(0, h, _farm(hires_today=h), _farm(), _private(), _private()) for h in range(5)]
    result = top_replay_stats.hands_for_day(turns, day=0, team=0, at_hour=0, turns_per_day=5)
    assert result["hires_today"] == 4


# --- money_for_day --------------------------------------------------------


def test_money_for_day_open_close_min_max_on_a_synthetic_dip():
    values = [1000, 800, 600, 900, 1200]
    turns = [_step(0, h, _farm(money=v), _farm(), _private(), _private()) for h, v in enumerate(values)]
    result = top_replay_stats.money_for_day(turns, day=0, team=0, turns_per_day=len(values))
    assert result == {"open": 1000, "close": 1200, "min": 600, "max": 1200}


def test_money_for_day_truncated_final_day_does_not_raise():
    turns = [_step(0, h, _farm(money=100 + h), _farm(), _private(), _private()) for h in range(3)]
    result = top_replay_stats.money_for_day(turns, day=0, team=0, turns_per_day=24)
    assert result["open"] == 100
    assert result["close"] == 102


# --- action_counts --------------------------------------------------------


def test_action_counts_generalizes_to_an_unlisted_op_without_a_code_change():
    action0 = {"farmer": ["FERTILIZE"], "hands": [["FERTILIZE"]], "market": []}
    turns = [_step(0, 0, _farm(), _farm(), _private(), _private(), action0=action0)]
    result = top_replay_stats.action_counts(turns, day=0, team=0, turns_per_day=1)
    assert result["farmer"] == {"FERTILIZE": 1}
    assert result["hands"] == {"FERTILIZE": 1}


def test_action_counts_skips_an_empty_market_order_without_raising():
    action0 = {"farmer": ["PASS"], "hands": [], "market": [[], ["BUY_SEED", "WHEAT", 5]]}
    turns = [_step(0, 0, _farm(), _farm(), _private(), _private(), action0=action0)]
    result = top_replay_stats.action_counts(turns, day=0, team=0, turns_per_day=1)
    assert result["market"]["BUY_SEED"] == {"count": 1, "quantity": 5}


def test_action_counts_counts_a_length_one_order_as_quantity_one():
    action0 = {"farmer": ["PASS"], "hands": [], "market": [["HIRE"]]}
    turns = [_step(0, 0, _farm(), _farm(), _private(), _private(), action0=action0)]
    result = top_replay_stats.action_counts(turns, day=0, team=0, turns_per_day=1)
    assert result["market"]["HIRE"] == {"count": 1, "quantity": 1}


def test_action_counts_sums_quantities_across_multiple_same_turn_orders():
    action0 = {"farmer": ["PASS"], "hands": [], "market": [["BUY_SEED", "WHEAT", 3], ["BUY_SEED", "WHEAT", 2]]}
    turns = [_step(0, 0, _farm(), _farm(), _private(), _private(), action0=action0)]
    result = top_replay_stats.action_counts(turns, day=0, team=0, turns_per_day=1)
    assert result["market"]["BUY_SEED"] == {"count": 2, "quantity": 5}


def test_action_counts_pass_fraction_on_a_known_ratio():
    actions = [{"farmer": ["PASS"], "hands": [["PASS"], ["NORTH"]], "market": []} for _ in range(3)]
    actions.append({"farmer": ["NORTH"], "hands": [["PASS"], ["PASS"]], "market": []})
    turns = [_step(0, h, _farm(), _farm(), _private(), _private(), action0=actions[h]) for h in range(4)]
    result = top_replay_stats.action_counts(turns, day=0, team=0, turns_per_day=4)
    assert result["farmer_pass_fraction"] == 3 / 4
    assert result["hands_pass_fraction"] == 5 / 8  # 1 PASS in each of 3 turns + 2 PASSes in the 4th


# --- wheat_flow -------------------------------------------------------


def test_wheat_flow_tallies_feed_bought_sold_and_shed_levels():
    action0 = {"farmer": ["FEED"], "hands": [["FEED"]], "market": [["BUY_PRODUCT", "WHEAT", 10], ["SELL", "WHEAT", 4]]}
    tiles_mid = _board()
    tiles_mid[0][0] = _plant_tile("WHEAT")
    turns = [
        _step(0, 0, _farm(), _farm(), _private(shed={"WHEAT": 2}), _private(), action0=action0),
        _step(0, 1, _farm(tiles=tiles_mid), _farm(), _private(shed={"WHEAT": 8}), _private()),
    ]
    result = top_replay_stats.wheat_flow(turns, day=0, team=0, turns_per_day=2)
    assert result["feed_actions"] == 2
    assert result["wheat_bought"] == 10
    assert result["wheat_sold"] == 4
    assert result["wheat_shed_open"] == 2
    assert result["wheat_shed_close"] == 8
    assert result["wheat_plant_tiles"] == 1


def test_wheat_flow_cannot_distinguish_feed_wheat_from_sale_wheat():
    # Documents the real scope limit (see module docstring): a WHEAT PLANT
    # tile carries no destination marker, so two identical tiles are
    # indistinguishable from tile state alone - wheat_flow reports a flow
    # balance instead of a guessed feed/sale split.
    assert _plant_tile("WHEAT") == _plant_tile("WHEAT")


# --- cash_flow_for_day ---------------------------------------------------


def test_cash_flow_for_day_tallies_categories_and_net_reconciles_with_money():
    private_open = _private(seeds={"WHEAT": 0}, shed={"CARROT": 10})
    private_close = _private(seeds={"WHEAT": 5}, shed={"CARROT": 7})
    farm_open = _farm(money=3000, hires_today=0)
    farm_close = _farm(money=3054, hires_today=1)  # +105 sell, -1 hire, -50 seed = +54
    action0 = {"farmer": ["PASS"], "hands": [], "market": [["HIRE"], ["BUY_SEED", "WHEAT", 5], ["SELL", "CARROT", 3]]}
    turns = [
        _step(0, 0, farm_open, _farm(), private_open, _private(), prices={"CARROT": 35}),
        _step(0, 1, farm_close, _farm(), private_close, _private(), action0=action0, prices={"CARROT": 33}),
    ]
    result = top_replay_stats.cash_flow_for_day(turns, day=0, team=0, turns_per_day=2)
    assert result["hire_cost"] == 1  # labor.hire_cost(0) == FARM_HAND_COST_MULT * fib(0) == 1
    assert result["seed_cost"] == 50  # 5 * CROPS["WHEAT"]["seed"] (10)
    assert result["sell_revenue"] == 105  # 3 * the order's own prior price (35, not the post-sale 33)
    assert result["land_cost"] == 0
    assert result["animal_cost"] == 0
    assert result["wheat_restock_cost"] == 0
    assert result["other_cost"] == 0
    assert result["net"] == 54
    money = top_replay_stats.money_for_day(turns, day=0, team=0, turns_per_day=2)
    assert money["close"] - money["open"] == result["net"]


def test_cash_flow_for_day_does_not_double_count_several_hires_in_one_turn():
    # A real replay can submit multiple HIRE orders in a single turn -
    # order_fill's per-order diff would double-count if called once per
    # order; cash_flow_for_day costs HIRE from a single per-turn diff.
    farm_open = _farm(hires_today=0)
    farm_close = _farm(hires_today=3)
    action0 = {"farmer": ["PASS"], "hands": [], "market": [["HIRE"], ["HIRE"], ["HIRE"]]}
    turns = [
        _step(0, 0, farm_open, _farm(), _private(), _private()),
        _step(0, 1, farm_close, _farm(), _private(), _private(), action0=action0),
    ]
    result = top_replay_stats.cash_flow_for_day(turns, day=0, team=0, turns_per_day=2)
    # labor.hire_cost(0) + hire_cost(1) + hire_cost(2) == 1 + 1 + 2 == 4
    assert result["hire_cost"] == 4


# --- stock_for_day --------------------------------------------------------


def test_stock_for_day_snapshots_and_zero_fills_missing_keys():
    private = _private(seeds={"WHEAT": 3}, shed={"WOOL": 2})
    turns = [_step(0, 12, _farm(), _farm(), private, _private())]
    result = top_replay_stats.stock_for_day(turns, day=0, team=0, at_hour=12, turns_per_day=24)
    assert result["seeds"]["WHEAT"] == 3
    assert result["seeds"]["CARROT"] == 0
    assert result["shed"]["WOOL"] == 2
    assert result["shed"]["COW"] == 0  # animals live in the shed dict too


# --- quadrant_unlock_days --------------------------------------------------


def test_quadrant_unlock_days_records_the_first_day_each_new_quadrant_is_seen():
    quads_by_turn = [["NW"], ["NW"], ["NW", "NE"], ["NW", "NE", "SW"]]
    turns = [_step(t, 0, _farm(unlocked_quadrants=q), _farm(), _private(), _private()) for t, q in enumerate(quads_by_turn)]
    result = top_replay_stats.quadrant_unlock_days(turns, team=0, turns_per_day=1)
    assert result == {"NE": 2, "SW": 3}


# --- shop_unlock_timeline --------------------------------------------------


def test_shop_unlock_timeline_records_each_new_instance_including_duplicates():
    shops_by_turn = [[], ["BAKERY"], ["BAKERY"], ["BAKERY", "BAKERY"]]
    turns = [_step(0, t, _farm(), _farm(), _private(), _private(), town_shops=s) for t, s in enumerate(shops_by_turn)]
    result = top_replay_stats.shop_unlock_timeline(turns, turns_per_day=24)
    assert result == [
        {"day": 0, "hour": 1, "shop": "BAKERY", "index": 0},
        {"day": 0, "hour": 3, "shop": "BAKERY", "index": 1},
    ]


# --- prices_for_day ---------------------------------------------------


def test_prices_for_day_open_close_min_max_global_not_per_team():
    turns = [
        _step(0, 0, _farm(), _farm(), _private(), _private(), prices={"WHEAT": 25}),
        _step(0, 1, _farm(), _farm(), _private(), _private(), prices={"WHEAT": 18}),
        _step(0, 2, _farm(), _farm(), _private(), _private(), prices={"WHEAT": 30}),
    ]
    result = top_replay_stats.prices_for_day(turns, day=0, turns_per_day=3)
    assert result["WHEAT"] == {"open": 25, "close": 30, "min": 18, "max": 30}


# --- animal_events_for_day / plant_events_for_day -------------------------


def test_animal_events_for_day_reuses_daily_dashboards_own_classification():
    prev_tiles = _board()
    prev_tiles[0][0] = _animal_tile("GOOSE", consecutive_unfed=1, fed_today=False)
    cur_tiles = _board()
    cur_tiles[0][0] = {"kind": "COOP"}
    turns = [
        _step(0, 0, _farm(tiles=prev_tiles), _farm(), _private(), _private()),
        _step(0, 1, _farm(tiles=cur_tiles), _farm(), _private(), _private()),
    ]
    events = top_replay_stats.animal_events_for_day(turns, day=0, team=0, turns_per_day=2)
    assert events == [{"pos": [0, 0], "animal": "GOOSE", "cause": "escaped", "hour": 1}]


def test_plant_events_for_day_reuses_daily_dashboards_own_classification():
    prev_tiles = _board()
    prev_tiles[0][0] = _plant_tile("WHEAT", consecutive_unwatered=1, watered_today=False)
    cur_tiles = _board()
    cur_tiles[0][0] = {"kind": "WEED"}
    turns = [
        _step(0, 0, _farm(tiles=prev_tiles), _farm(), _private(), _private()),
        _step(0, 1, _farm(tiles=cur_tiles), _farm(), _private(), _private()),
    ]
    events = top_replay_stats.plant_events_for_day(turns, day=0, team=0, turns_per_day=2)
    assert events == [{"pos": [0, 0], "crop": "WHEAT", "cause": "drought_death", "hour": 1}]


# --- percentile -------------------------------------------------------


def test_percentile_nearest_rank_single_value():
    assert top_replay_stats.percentile([42], 0.5) == 42


def test_percentile_nearest_rank_known_list_of_four():
    values = [10, 20, 30, 40]
    assert top_replay_stats.percentile(values, 0.25) == 10
    assert top_replay_stats.percentile(values, 0.5) == 20
    assert top_replay_stats.percentile(values, 0.75) == 30
    assert top_replay_stats.percentile(values, 1.0) == 40


# --- summarize --------------------------------------------------------


def test_summarize_dotted_field_access_and_cohort_filter():
    rows_ = [
        {"day": 0, "cohort": "top", "board": {"animals": {"COW": 3}}},
        {"day": 0, "cohort": "top", "board": {"animals": {"COW": 5}}},
        {"day": 0, "cohort": "ours", "board": {"animals": {"COW": 1}}},
    ]
    result = top_replay_stats.summarize(rows_, "board.animals.COW", cohort="top")
    assert result[0]["n"] == 2
    assert result[0]["median"] == 3
    assert result[0]["min"] == 3
    assert result[0]["max"] == 5


def test_summarize_per_day_n_differs_when_episodes_have_different_lengths():
    rows_ = [
        {"day": 0, "cohort": "top", "close": 100},
        {"day": 1, "cohort": "top", "close": 200},
    ]
    result = top_replay_stats.summarize(rows_, "close", cohort="top")
    assert result[0]["n"] == 1
    assert result[1]["n"] == 1
    assert 2 not in result


# --- compare_cohorts --------------------------------------------------


def test_compare_cohorts_delta_sign_and_independent_sample_sizes():
    rows_ = [
        {"day": 0, "cohort": "top", "close": 100},
        {"day": 0, "cohort": "top", "close": 200},
        {"day": 0, "cohort": "ours", "close": 50},
    ]
    result = top_replay_stats.compare_cohorts(rows_, "close", "top", "ours")
    assert result[0]["a_median"] == 100
    assert result[0]["b_median"] == 50
    assert result[0]["delta"] == 50
    assert result[0]["n_a"] == 2
    assert result[0]["n_b"] == 1


# --- shop_schedule_invariant -----------------------------------------


def test_shop_schedule_invariant_true_for_identical_sequences():
    records = [
        {"episode_id": "a", "shop_unlock_names": ["BAKERY", "PIZZA_SHOP"]},
        {"episode_id": "b", "shop_unlock_names": ["BAKERY", "PIZZA_SHOP"]},
    ]
    assert top_replay_stats.shop_schedule_invariant(records)["invariant"] is True


def test_shop_schedule_invariant_false_when_one_episode_differs():
    records = [
        {"episode_id": "a", "shop_unlock_names": ["BAKERY", "PIZZA_SHOP"]},
        {"episode_id": "b", "shop_unlock_names": ["YARN_STORE"]},
    ]
    assert top_replay_stats.shop_schedule_invariant(records)["invariant"] is False


# --- episode_record (end-to-end) ---------------------------------------


def test_episode_record_end_to_end_on_a_synthetic_two_day_episode():
    tiles_t0 = _board()
    tiles_t0[0][0] = _animal_tile("GOOSE", consecutive_unfed=1, fed_today=False)
    tiles_t1 = _board()
    tiles_t1[0][0] = {"kind": "COOP"}  # escaped between t0 and t1
    tiles_rest = _board()

    farm0_t0 = _farm(tiles=tiles_t0)
    farm0_t1 = _farm(tiles=tiles_t1)
    farm0_t2 = _farm(tiles=tiles_rest)
    farm0_t3 = _farm(tiles=tiles_rest)

    steps = [
        _step(0, 0, farm0_t0, _farm(), _private(), _private(), prices={"WHEAT": 25}),
        _step(0, 1, farm0_t1, _farm(), _private(), _private(), prices={"WHEAT": 30}),
        _step(1, 0, farm0_t2, _farm(), _private(), _private(), prices={"WHEAT": 40}),
        _step(1, 1, farm0_t3, _farm(), _private(), _private(), prices={"WHEAT": 35}),
    ]
    ep = {
        "steps": steps,
        "info": {"TeamNames": ["Alpha", "Beta"], "EpisodeId": 999, "seed": 42},
        "rewards": [3000.0, 3000.0],
    }
    rec = top_replay_stats.episode_record(ep, at_hour=0, cohort="top", turns_per_day=2)

    assert rec["episode_id"] == 999
    assert rec["seed"] == 42
    assert rec["cohort"] == "top"
    assert rec["team_names"] == ["Alpha", "Beta"]
    assert rec["n_days"] == 2
    assert rec["prices"][0]["WHEAT"] == {"open": 25, "close": 30, "min": 25, "max": 30}
    assert rec["prices"][1]["WHEAT"] == {"open": 40, "close": 35, "min": 35, "max": 40}

    team0 = rec["teams"][0]
    assert team0["team_name"] == "Alpha"
    assert len(team0["days"]) == 2
    assert len(team0["animal_escapes"]) == 1
    assert team0["animal_escapes"][0] == {"pos": [0, 0], "animal": "GOOSE", "cause": "escaped", "hour": 1, "day": 0}
    assert team0["plant_deaths"] == []


# --- save_records / load_saved_records (round trip) -----------------------


def test_save_and_load_records_round_trips_through_the_directory_and_the_index(tmp_path):
    records = [
        {"episode_id": "ep1", "cohort": "top", "teams": []},
        {"episode_id": "ep2", "cohort": "top", "teams": []},
    ]
    out_dir = str(tmp_path / "records")
    top_replay_stats.save_records(records, out_dir)
    assert os.path.exists(os.path.join(out_dir, "ep1.json"))
    assert os.path.exists(os.path.join(out_dir, "index.jsonl"))

    reloaded = top_replay_stats.load_saved_records(out_dir)
    assert reloaded == records
    reloaded_via_index = top_replay_stats.load_saved_records(os.path.join(out_dir, "index.jsonl"))
    assert reloaded_via_index == records
