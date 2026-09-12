"""Unit tests for kagg.policy.decide - the full three-layer integration
wiring strategy/tasks/market together. See SPEC-policy.md and
tasks/plan.md T3.5.

strategy.py/tasks.py/market.py are already individually tested - these
tests focus on the *glue* T3.5 adds: buying a seed when none is on hand
yet (a real gap none of T3.1-T3.3 covered - none of them ever emit
BUY_SEED), queuing HIRE/BUY_LAND from the strategic layer's decisions,
and the overall action shape/order cap.
"""

from kagg.gamelib.constants import CROPS, MARKET_I0, PRODUCTS
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


def test_decide_does_not_hire_past_the_daily_target():
    obs = _obs()
    obs["farms"][0]["hires_today"] = 2
    params = dict(DEFAULT_PARAMS, hires_per_day=2)
    action = decide(obs, params)
    assert [o for o in action["market"] if o == ["HIRE"]] == []


def test_decide_queues_land_purchase_when_affordable_and_over_threshold():
    obs = _obs()
    obs["farms"][0]["money"] = 10_000
    params = dict(DEFAULT_PARAMS, land_purchase_threshold_money=0)
    action = decide(obs, params)
    assert ["BUY_LAND"] in action["market"]


def test_decide_does_not_queue_land_purchase_below_threshold():
    obs = _obs()
    obs["farms"][0]["money"] = 500
    action = decide(obs, DEFAULT_PARAMS)  # default threshold is 5000
    assert ["BUY_LAND"] not in action["market"]


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


def test_decide_falls_back_to_the_best_crop_when_an_animal_outranks_every_crop():
    # The real regression found while implementing T6.1, not a
    # hypothetical: a direct trace of a real "starter" episode showed
    # the top choice flipping to COW at day 18 (our own MELON sales had
    # depressed its price below COW's), after which decide() planted
    # nothing for the rest of the season without this fallback - about
    # 150-200 money lost per seed against the Checkpoint 5 baseline.
    obs = _obs()
    obs["market"]["inventory"] = {"MELON": MARKET_I0 + 100_000}  # crashes MELON - COW ranks first overall
    action = decide(obs, DEFAULT_PARAMS)
    buy_seed_orders = [o for o in action["market"] if o[0] == "BUY_SEED"]
    assert len(buy_seed_orders) == 1
    assert buy_seed_orders[0][1] in CROPS  # not COW - tasks.py/market.py can't act on an animal yet


def test_decide_plants_nothing_when_no_crop_can_mature_in_time():
    obs = _obs()
    obs["day"] = 29
    action = decide(obs, DEFAULT_PARAMS)
    assert [o for o in action["market"] if o[0] == "BUY_SEED"] == []


def test_decide_assigns_hands_when_present():
    obs = _obs()
    obs["farms"][0]["hands"] = [[0, 0]]
    obs["private"]["inventories"] = [{}, {}]
    obs["farms"][0]["tiles"][0][0] = {"kind": "WEED"}
    action = decide(obs, DEFAULT_PARAMS)
    assert len(action["hands"]) == 1
    assert action["hands"][0] == ["DIG"]  # already standing on the weed tile
