"""Unit tests for kagg.policy.strategy - see SPEC-policy.md "1. Strategic
layer" and tasks/plan.md T3.1.

No oracle needed here - this is new decision logic we're inventing, not
mirroring the real interpreter (unlike gamelib's Phase 1 tests). Expected
values are computed independently in this file's own docstring/comments,
using gamelib's already Phase-1-verified functions directly, rather than
cross-checked against README.md's summary "Yield / tile / day" table -
that table's implicit tile-days convention isn't necessarily the same one
this module chooses, so treating it as an oracle would be comparing two
different definitions, not verifying this one.
"""

import math

import pytest

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0
from kagg.gamelib.growth import forecast_animal_schedule
from kagg.gamelib.market import expected_daily_consumption
from kagg.policy.strategy import (
    _animal_actions_per_tile_day,
    _crop_actions_per_tile_day,
    _crop_yield_and_tile_days,
    animal_revenue_per_tile_day,
    crop_revenue_per_tile_day,
    hires_per_day,
    rank_portfolio,
    score_portfolio,
    should_buy_land,
)

# Computed directly from gamelib (Phase 1, already property-tested) at
# I0 (base price), independently of this module:
#   WHEAT:      yield=4, tile_days=5
#   CARROT:     yield=3, tile_days=4
#   TOMATO:     yield=4, tile_days=12
#   STRAWBERRY: yield=4, tile_days=17
#   MELON:      yield=6, tile_days=13 (yield capped at max_yield=6 - the
#               window waters 7 days but the cap is hit at age 10,
#               matching SPEC-gamelib.md's own worked example)
#   GOOSE: 50/1  = 50.000
#   COW:   160/2 = 80.000
#   SHEEP: 200/3 = 66.667...
#
# T8.3f: crop_revenue_per_tile_day no longer prices the whole
# `total_yield`-unit run at one flat snapshot - it walks
# gamelib.market.price(crop, I0 + k) for k = 0, ..., total_yield-1 (see
# its own docstring). "Independently calculated" now means summing that
# same, already-Phase-1-verified price() directly here rather than
# hand-multiplying a single base price by total_yield.
_MARKET_AT_I0 = {}  # rank_portfolio falls back to MARKET_I0 per item when absent


def _independent_crop_revenue(crop: str, total_yield: int, tile_days: int, inventory: int = MARKET_I0) -> float:
    from kagg.gamelib.market import price as _price

    return sum(_price(crop, inventory + k) for k in range(total_yield)) / tile_days


def test_crop_revenue_per_tile_day_matches_independent_calculation():
    assert crop_revenue_per_tile_day("WHEAT", MARKET_I0) == pytest.approx(_independent_crop_revenue("WHEAT", 4, 5))
    assert crop_revenue_per_tile_day("CARROT", MARKET_I0) == pytest.approx(_independent_crop_revenue("CARROT", 3, 4))
    assert crop_revenue_per_tile_day("TOMATO", MARKET_I0) == pytest.approx(_independent_crop_revenue("TOMATO", 4, 12))
    assert crop_revenue_per_tile_day("STRAWBERRY", MARKET_I0) == pytest.approx(
        _independent_crop_revenue("STRAWBERRY", 4, 17)
    )
    assert crop_revenue_per_tile_day("MELON", MARKET_I0) == pytest.approx(_independent_crop_revenue("MELON", 6, 13))


def test_crop_revenue_per_tile_day_self_impact_never_exceeds_the_flat_price_estimate():
    # A tiny sanity check on the model's own direction, not a business
    # rule: since price() is non-increasing in inventory once at/above
    # I0, walking forward from a snapshot can never score *higher* than
    # pricing every unit at that same starting snapshot.
    for crop in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"):
        flat = _independent_crop_revenue(crop, *_yield_and_tile_days(crop))
        assert crop_revenue_per_tile_day(crop, MARKET_I0) <= flat + 1e-9


def _yield_and_tile_days(crop: str) -> tuple[int, int]:
    from kagg.gamelib.constants import CROPS
    from kagg.gamelib.growth import forecast_one_time_yield, forecast_ongoing_schedule, watering_bonus_window

    cd = CROPS[crop]
    if cd["ongoing"]:
        schedule = forecast_ongoing_schedule(crop, planted_day=0)
        return min(cd["max_yield"], len(schedule)), schedule[-1] + 1
    watered_days = set(watering_bonus_window(crop))
    return forecast_one_time_yield(crop, watered_days), cd["max_yield_day"] + 1


def test_crop_revenue_per_tile_day_drops_sharply_once_the_farm_already_commits_many_tiles():
    # T8.3f, the user's own observation: a single tile's own yield barely
    # moves its own price (measured: one melon tile's 6-unit run scores
    # unchanged at I0 - MELON's T=300 dwarfs 6 units), but committing to
    # many tiles of the same premium good is where the real crash the
    # user described actually shows up.
    one_tile = crop_revenue_per_tile_day("MELON", MARKET_I0, already_committed_units=0)
    many_tiles = crop_revenue_per_tile_day("MELON", MARKET_I0, already_committed_units=20 * 6)
    assert many_tiles < one_tile * 0.9


def test_crop_revenue_per_tile_day_net_of_seed_cost_matches_independent_calculation():
    # T8.3k, the user's own observation: time is a scarce resource, so
    # profitability should be net profit per day, not gross revenue per
    # day. gross_total_revenue - seed_cost, still divided by tile_days.
    assert crop_revenue_per_tile_day("WHEAT", MARKET_I0, net_of_seed_cost=True) == pytest.approx(
        (19.4 * 5 - 10) / 5
    )
    assert crop_revenue_per_tile_day("MELON", MARKET_I0, net_of_seed_cost=True) == pytest.approx(
        (115.384615 * 13 - 80) / 13, rel=1e-5
    )


def test_crop_revenue_per_tile_day_net_of_seed_cost_defaults_to_false():
    gross = crop_revenue_per_tile_day("STRAWBERRY", MARKET_I0)
    assert crop_revenue_per_tile_day("STRAWBERRY", MARKET_I0, net_of_seed_cost=False) == pytest.approx(gross)


def test_crop_revenue_per_tile_day_expected_consumption_raises_the_score():
    # T8.3i, the user's own follow-up: consumption pulls the opposite
    # direction from already_committed_units - it should raise the score
    # (scarcity from a shop already drawing this product down), not
    # lower it.
    baseline = crop_revenue_per_tile_day("CARROT", MARKET_I0)
    with_consumption = crop_revenue_per_tile_day("CARROT", MARKET_I0, expected_consumption=100)
    assert with_consumption > baseline


def test_animal_revenue_per_tile_day_matches_independent_calculation():
    assert animal_revenue_per_tile_day("GOOSE", MARKET_I0) == pytest.approx(50.0)
    assert animal_revenue_per_tile_day("COW", MARKET_I0) == pytest.approx(80.0)
    assert animal_revenue_per_tile_day("SHEEP", MARKET_I0) == pytest.approx(200 / 3)


def test_animal_revenue_per_tile_day_expected_consumption_raises_the_score():
    baseline = animal_revenue_per_tile_day("SHEEP", MARKET_I0)
    with_consumption = animal_revenue_per_tile_day("SHEEP", MARKET_I0, expected_consumption=100)
    assert with_consumption > baseline


def test_crop_revenue_per_tile_day_days_remaining_truncates_an_ongoing_crops_schedule():
    # T8.3m: STRAWBERRY's full schedule (planted_day=0) is [10, 12, 14,
    # 16] (4 productions). With only 13 days left, just the productions
    # on day 10 and 12 actually fit (14 and 16 don't) - 2 productions,
    # tile_days = 13 (last fitting production's day + 1).
    from kagg.gamelib.market import price as _price

    expected = sum(_price("STRAWBERRY", MARKET_I0 + k) for k in range(2)) / 13
    assert crop_revenue_per_tile_day("STRAWBERRY", MARKET_I0, days_remaining=13) == pytest.approx(expected)


def test_crop_revenue_per_tile_day_days_remaining_defaults_to_the_full_schedule():
    full = crop_revenue_per_tile_day("STRAWBERRY", MARKET_I0)
    assert crop_revenue_per_tile_day("STRAWBERRY", MARKET_I0, days_remaining=None) == pytest.approx(full)


def test_crop_revenue_per_tile_day_days_remaining_is_a_noop_for_a_still_maturable_one_time_crop():
    # MELON's tile_days is 13 (max_yield_day=12, +1); once it still has
    # time to mature (days_remaining >= 13), truncation must not touch a
    # one-time crop's already-fixed yield/tile_days at all.
    full = crop_revenue_per_tile_day("MELON", MARKET_I0)
    assert crop_revenue_per_tile_day("MELON", MARKET_I0, days_remaining=13) == pytest.approx(full)
    assert crop_revenue_per_tile_day("MELON", MARKET_I0, days_remaining=100) == pytest.approx(full)


def test_animal_revenue_per_tile_day_net_of_cost_matches_independent_calculation():
    # T8.3m: GOOSE (cost=300, first_yield_day=4, interval=1) with 6 days
    # left - forecast_animal_schedule(placed_day=0, horizon_days=6) gives
    # [4, 5, 6], 3 productions.
    from kagg.gamelib.market import price as _price

    expected = (sum(_price("EGG", MARKET_I0 + k) for k in range(3)) - 300 - 2 * 6) / 6
    got = animal_revenue_per_tile_day(
        "GOOSE", MARKET_I0, days_remaining=6, net_of_cost=True, feed_price=2
    )
    assert got == pytest.approx(expected)


def test_animal_revenue_per_tile_day_net_of_cost_can_go_negative_for_a_too_late_animal():
    # An animal commissioned with almost no season left should score a
    # real loss (purchase cost alone dwarfs 1-2 productions), not just a
    # smaller positive number - this is the whole point of netting real
    # costs against a bounded horizon instead of an unbounded steady-state
    # rate.
    got = animal_revenue_per_tile_day(
        "COW", MARKET_I0, days_remaining=9, net_of_cost=True, feed_price=5
    )
    assert got < 0


def test_animal_revenue_per_tile_day_net_of_cost_defaults_to_the_steady_state_rate():
    steady_state = animal_revenue_per_tile_day("COW", MARKET_I0)
    assert animal_revenue_per_tile_day("COW", MARKET_I0, net_of_cost=False) == pytest.approx(steady_state)
    # net_of_cost=True with no days_remaining given has no horizon to net
    # against - graceful fallback to the same steady-state rate, not an
    # error.
    assert animal_revenue_per_tile_day("COW", MARKET_I0, net_of_cost=True) == pytest.approx(steady_state)


def test_rank_portfolio_season_aware_demotes_a_long_ongoing_crop_near_season_end():
    # STRAWBERRY leads at base price with no season information at all
    # (see test_rank_portfolio_orders_by_marginal_revenue_at_base_price -
    # it's 5th, well below MELON/COW/SHEEP/GOOSE, so use a market where it
    # already leads among crops to make the demotion visible).
    market = {}
    without = rank_portfolio(market)
    with_season = rank_portfolio(market, days_remaining=11, rank_season_aware=True)
    # Only 1 of STRAWBERRY's 4 scheduled productions (day 10) fits inside
    # 11 remaining days - its relative rank against the other crops must
    # not improve, and its raw score must drop.
    assert with_season.index("STRAWBERRY") >= without.index("STRAWBERRY")


def test_rank_portfolio_season_aware_defaults_to_false():
    market = {}
    assert rank_portfolio(market, days_remaining=11) == rank_portfolio(market)


def test_rank_portfolio_animal_net_of_cost_can_make_a_late_animal_unattractive():
    market = {}
    without = rank_portfolio(market)
    with_cost = rank_portfolio(market, days_remaining=9, animal_net_of_cost=True)
    # COW/SHEEP/GOOSE rank 2nd-4th at base price with no cost information
    # at all (see the base-price ranking test above - only MELON beats
    # them); once real purchase + feed cost is netted against just 9
    # remaining days, every animal must fall behind every crop instead.
    assert without.index("COW") < without.index("STRAWBERRY")
    assert with_cost.index("STRAWBERRY") < with_cost.index("COW")
    assert with_cost.index("STRAWBERRY") < with_cost.index("SHEEP")
    assert with_cost.index("STRAWBERRY") < with_cost.index("GOOSE")


def test_rank_portfolio_animal_net_of_cost_defaults_to_false():
    market = {}
    assert rank_portfolio(market, days_remaining=9) == rank_portfolio(market)


def test_rank_portfolio_orders_by_marginal_revenue_at_base_price():
    # MELON's huge per-tile-day revenue at base price is exactly the
    # "premium goods look great until you check market depth" trap
    # SPEC.md's economic analysis warns about. With no `crop_tile_counts`
    # given (nothing planted yet), MELON still ranks first - T8.3f's
    # self-impact fix only demotes it once the farm has actually
    # committed real tiles to it (see the test below); a single
    # hypothetical new tile alone doesn't move its own price enough to
    # matter (see crop_revenue_per_tile_day's own docstring).
    assert rank_portfolio(_MARKET_AT_I0) == [
        "MELON",
        "COW",
        "SHEEP",
        "GOOSE",
        "STRAWBERRY",
        "CARROT",
        "WHEAT",
        "TOMATO",
    ]


def test_rank_portfolio_demotes_a_crop_the_farm_has_already_committed_many_tiles_to():
    # T8.3f, the user's own observation: 20 melon tiles already growing
    # means the *next* melon tile is priced starting from where those
    # 20 tiles' own 120-unit combined harvest would already have pushed
    # the market - MELON must drop out of first place once that's real,
    # not merely hypothetical.
    ranking = rank_portfolio(_MARKET_AT_I0, crop_tile_counts={"MELON": 20})
    assert ranking[0] != "MELON"


def test_rank_portfolio_wires_unlocked_shops_through_to_crop_scoring():
    # T8.3i, the user's own follow-up: rank_portfolio must actually pass
    # `unlocked_shops` through to crop_revenue_per_tile_day, not just
    # accept the argument - PET_CAFE only sells CARROT (a single-product
    # shop, doubled consumption rate), so heavily unlocking it must rank
    # CARROT no worse (and, at base price, strictly better) than with no
    # shop information at all.
    ranking_without = rank_portfolio(_MARKET_AT_I0)
    ranking_with = rank_portfolio(_MARKET_AT_I0, unlocked_shops=["PET_CAFE"] * 8)
    assert ranking_with.index("CARROT") < ranking_without.index("CARROT")


def test_rank_portfolio_favors_an_animal_product_a_currently_unlocked_shop_is_consuming():
    # Same mechanism, for an ANIMAL product (T8.3i extends
    # animal_revenue_per_tile_day too, unlike T8.3f's crop-only scope,
    # since a consumption estimate needs no lifetime-total bound) -
    # YARN_STORE only sells WOOL (SHEEP's product).
    ranking_without = rank_portfolio(_MARKET_AT_I0)
    ranking_with = rank_portfolio(_MARKET_AT_I0, unlocked_shops=["YARN_STORE"] * 8)
    assert ranking_with.index("SHEEP") <= ranking_without.index("SHEEP")


def test_rank_portfolio_net_of_seed_cost_can_reorder_two_close_crops():
    # T8.3k, the user's own observation: time is scarce, so profitability
    # should be net profit per day, not gross revenue per day. TOMATO's
    # seed ($50) costs far more per tile-day than WHEAT's ($10) - at a
    # slight scarcity that makes TOMATO's *gross* score edge out WHEAT's,
    # netting out each one's own seed cost flips the order back.
    market = {"TOMATO": MARKET_I0 - 50}
    gross_ranking = rank_portfolio(market)
    net_ranking = rank_portfolio(market, net_of_seed_cost=True)
    assert gross_ranking.index("TOMATO") < gross_ranking.index("WHEAT")
    assert net_ranking.index("WHEAT") < net_ranking.index("TOMATO")


def test_rank_portfolio_net_of_seed_cost_defaults_to_false():
    assert rank_portfolio(_MARKET_AT_I0) == rank_portfolio(_MARKET_AT_I0, net_of_seed_cost=False)


def test_rank_portfolio_reacts_to_a_crashed_price():
    # If melon's own market has already crashed (heavy oversupply), it
    # must drop out of the top spot - this is the entire point of scoring
    # "at market depth," not base price.
    crashed_melon_inventory = MARKET_I0 + 100_000  # far past melon's T=300
    ranking = rank_portfolio({"MELON": crashed_melon_inventory})
    assert ranking[0] != "MELON"


def test_should_buy_land_respects_the_threshold_parameter():
    # land_price(0) == 1000 (gamelib.farm, Phase 1). Default threshold
    # requires enough left over after buying, not just enough for the
    # purchase itself.
    assert should_buy_land(money=1000, n_unlocked_extra=0, params={"land_purchase_threshold_money": 0}) is True
    assert should_buy_land(money=999, n_unlocked_extra=0, params={"land_purchase_threshold_money": 0}) is False
    assert should_buy_land(money=1000, n_unlocked_extra=0, params={"land_purchase_threshold_money": 500}) is False
    assert should_buy_land(money=1500, n_unlocked_extra=0, params={"land_purchase_threshold_money": 500}) is True


def test_should_buy_land_is_false_once_all_quadrants_bought():
    assert should_buy_land(money=1_000_000, n_unlocked_extra=3, params={}) is False


def test_should_buy_land_ignores_occupancy_when_none_is_given():
    # No occupancy info -> the old, ungated behavior (money-only) -
    # decide() always supplies real occupancy in practice; this is a
    # graceful default for callers that don't care, not the real-play path.
    assert should_buy_land(money=1_000_000, n_unlocked_extra=0, params={}) is True


def test_should_buy_land_declines_while_most_tiles_are_still_free():
    # T8.3's real fix (tasks/plan.md): the user's own observation - land
    # was sometimes bought while plenty of free tiles remained.
    params = {"land_buy_max_free_tile_fraction": 0.25}
    assert should_buy_land(
        money=1_000_000, n_unlocked_extra=0, params=params,
        free_tiles=20, unlocked_tiles=25, nearest_free_shed_distance=2,
    ) is False


def test_should_buy_land_buys_once_free_tiles_drop_below_the_fraction():
    params = {"land_buy_max_free_tile_fraction": 0.25}
    assert should_buy_land(
        money=1_000_000, n_unlocked_extra=0, params=params,
        free_tiles=5, unlocked_tiles=25, nearest_free_shed_distance=2,
    ) is True


def test_should_buy_land_buys_anyway_when_remaining_free_tiles_are_far_from_the_shed():
    # The T8.1 interaction: a newly unlocked quadrant always contributes
    # tiles at shed-distance 1, so if our own remaining free tiles are
    # already farther than that, the new land is genuinely better, even
    # though we technically still have free tiles.
    params = {"land_buy_max_free_tile_fraction": 0.25, "land_buy_min_frontier_distance": 4}
    assert should_buy_land(
        money=1_000_000, n_unlocked_extra=0, params=params,
        free_tiles=20, unlocked_tiles=25, nearest_free_shed_distance=5,
    ) is True


def test_should_buy_land_frontier_gate_is_disabled_by_default():
    params = {"land_buy_max_free_tile_fraction": 0.25}
    assert should_buy_land(
        money=1_000_000, n_unlocked_extra=0, params=params,
        free_tiles=20, unlocked_tiles=25, nearest_free_shed_distance=8,
    ) is False


def test_should_buy_land_frontier_gate_defaults_to_disabled():
    # land_buy_min_frontier_distance alone stays an unswept no-op (99 -
    # never triggered by any real board) even with the fraction gate at
    # its own (now non-default) accepted value.
    assert should_buy_land(
        money=1_000_000, n_unlocked_extra=0, params={},
        free_tiles=20, unlocked_tiles=25, nearest_free_shed_distance=8,
    ) is False  # fraction gate (0.1 default, T8.8) blocks; frontier (99 default) can't override it


def test_should_buy_land_fraction_1_0_reproduces_the_fully_ungated_behavior():
    # T8.3's mechanism itself (as opposed to the accepted default, 0.1
    # since T8.8) is still reachable by passing the fully-ungated value
    # explicitly.
    for free_tiles in (0, 1, 12, 24, 25):
        assert should_buy_land(
            money=1_000_000, n_unlocked_extra=0, params={"land_buy_max_free_tile_fraction": 1.0},
            free_tiles=free_tiles, unlocked_tiles=25, nearest_free_shed_distance=8,
        ) is True


def test_should_buy_land_default_matches_the_accepted_fraction():
    # The module-level fallback constant is kept in sync with the
    # accepted params.py default, per this project's established
    # convention (see _DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY) - so
    # params={} and an explicit accepted value behave identically.
    # T8.8: re-swept to 0.1 (from 0.25) once hires_per_day=1 (T8.7)
    # landed - free_tiles/unlocked_tiles combos updated so at least one
    # still demonstrates a real True result under the stricter default.
    for free_tiles, unlocked_tiles in [(20, 25), (1, 25), (3, 25)]:
        assert should_buy_land(
            money=1_000_000, n_unlocked_extra=0, params={},
            free_tiles=free_tiles, unlocked_tiles=unlocked_tiles, nearest_free_shed_distance=8,
        ) == should_buy_land(
            money=1_000_000, n_unlocked_extra=0,
            params={"land_buy_max_free_tile_fraction": 0.1},
            free_tiles=free_tiles, unlocked_tiles=unlocked_tiles, nearest_free_shed_distance=8,
        )


def test_should_buy_land_still_respects_money_threshold_with_occupancy_given():
    params = {"land_buy_max_free_tile_fraction": 1.0}
    assert should_buy_land(
        money=100, n_unlocked_extra=0, params=params,
        free_tiles=1, unlocked_tiles=25, nearest_free_shed_distance=8,
    ) is False


def test_hires_per_day_reads_the_named_parameter_with_a_measured_default():
    # T8.7: raised 0 -> 1 on a real, held-out-gated self-play result
    # (50/50 at the accepted value, every nonzero value tried won
    # 96-100%) once T8.4/T8.6 fixed the real bugs that invalidated T7.4's
    # original hires_per_day=0 finding - never raised on intuition alone,
    # only on an arena result, in either direction.
    assert hires_per_day({}) == 1
    assert hires_per_day({"hires_per_day": 5}) == 5
    assert hires_per_day({"hires_per_day": 0}) == 0


def test_hires_per_day_dynamic_hiring_defaults_to_true():
    # T8.16(d): dynamic_hiring is now ON by default (superseding T8.12's
    # own rejection - see _DEFAULT_DYNAMIC_HIRING's own comment for the
    # full measured story) - a huge pending backlog now scales hiring up
    # to max_hires_per_day (default 8), not the plain static value.
    assert hires_per_day({}, pending_task_count=1000) == 8


def test_hires_per_day_dynamic_hiring_off_falls_back_to_the_static_value():
    # Explicit dynamic_hiring=False still reproduces the plain static
    # value exactly, regardless of backlog - the graceful-fallback path
    # every caller relied on before T8.16(d) flipped the default.
    params = {"dynamic_hiring": False}
    assert hires_per_day(params, pending_task_count=1000) == 1
    assert hires_per_day({"dynamic_hiring": False, "hires_per_day": 3}, pending_task_count=1000) == 3


def test_hires_per_day_dynamic_hiring_falls_back_to_static_without_task_info():
    # dynamic_hiring=True but no pending_task_count given - graceful
    # fallback to the static value, not an error (matches net_of_cost's
    # own "no days_remaining -> steady state" convention elsewhere in
    # this module).
    params = {"dynamic_hiring": True, "hires_per_day": 2}
    assert hires_per_day(params) == 2


def test_hires_per_day_dynamic_hiring_scales_with_pending_task_count():
    # 48 pending tasks, turns_per_task_estimate=2.0 (default - the
    # user's own request: size hiring from the real backlog, not a flat
    # number), 24 turns left today (hour=0): needed_unit_turns = 96,
    # target = ceil(96 / 24) - 1 = 3 (minus the farmer's own turn - the
    # farmer is already one of the labor units working the backlog).
    params = {"dynamic_hiring": True}
    got = hires_per_day(params, pending_task_count=48, hour=0, turns_per_day=24)
    assert got == 3


def test_hires_per_day_dynamic_hiring_accounts_for_hours_already_spent_today():
    # Same 48-task backlog, but only 4 turns left today (hour=20):
    # needed=96, turns_left=4, target=ceil(96/4)-1=23, clipped to
    # max_hires_per_day (default 8) - fewer turns left means more hands
    # needed to clear the same backlog before the day resets.
    params = {"dynamic_hiring": True}
    got = hires_per_day(params, pending_task_count=48, hour=20, turns_per_day=24)
    assert got == 8


def test_hires_per_day_dynamic_hiring_never_drops_below_min_hires_per_day():
    # Zero pending tasks - the formula alone computes a negative target
    # (ceil(0/24) - 1 = -1). The user's own point: a floor protects
    # limited starting capital from being spent on labor with nothing yet
    # to do. min_hires_per_day passed explicitly (not relying on the
    # ambient default, which T8.16(d) changed to 2) so this test keeps
    # verifying the floor *mechanism*, independent of its currently
    # accepted value - see the dedicated default-value test below.
    params = {"dynamic_hiring": True, "min_hires_per_day": 1}
    assert hires_per_day(params, pending_task_count=0, hour=0, turns_per_day=24) == 1


def test_hires_per_day_dynamic_hiring_min_hires_per_day_defaults_to_two():
    # T8.16(d): swept jointly with the other three dynamic_hiring knobs -
    # 2 (and 3, tied) decisively beat the old flat constant's value of 1
    # on the working block (0.94 vs 0.62); held-out gate cleared 49W/1L/0T
    # (98%) against the pre-T8.16(d) checked-in baseline. See
    # tools/measure_t816d.py for the full sweep.
    params = {"dynamic_hiring": True}
    assert hires_per_day(params, pending_task_count=0, hour=0, turns_per_day=24) == 2


def test_hires_per_day_dynamic_hiring_respects_a_custom_min_and_max():
    params = {"dynamic_hiring": True, "min_hires_per_day": 2, "max_hires_per_day": 4}
    assert hires_per_day(params, pending_task_count=0, hour=0, turns_per_day=24) == 2
    assert hires_per_day(params, pending_task_count=10_000, hour=0, turns_per_day=24) == 4


def test_hires_per_day_dynamic_hiring_respects_turns_per_task_estimate():
    # min_hires_per_day=1 passed explicitly so the formula's own result
    # (1) isn't masked by T8.16(d)'s now-higher default floor (2) - this
    # test is about turns_per_task_estimate's arithmetic, not the floor.
    params = {"dynamic_hiring": True, "turns_per_task_estimate": 1.0, "min_hires_per_day": 1}
    # 48 tasks * 1.0 turn/task = 48 needed, 24 turns left -> ceil(48/24)-1 = 1
    assert hires_per_day(params, pending_task_count=48, hour=0, turns_per_day=24) == 1


def test_hires_per_day_dynamic_hiring_respects_a_cash_reserve():
    # T8.12, the user's own observation: the starting capital is small
    # and shouldn't all go to labor before seeds/animals are affordable -
    # hire_cash_reserve makes that concern an explicit, swept parameter
    # instead of leaving it implicit inside min_hires_per_day alone.
    # Below the reserve, hiring stays at the floor regardless of backlog
    # size. min_hires_per_day passed explicitly (not the ambient default,
    # which T8.16(d) changed to 2) - this test is about the reserve gate,
    # not the floor's currently accepted value.
    params = {"dynamic_hiring": True, "hire_cash_reserve": 1000, "min_hires_per_day": 1}
    got = hires_per_day(params, pending_task_count=48, hour=0, turns_per_day=24, money=500)
    assert got == 1  # the floor passed explicitly above


def test_hires_per_day_dynamic_hiring_hires_normally_once_reserve_is_cleared():
    params = {"dynamic_hiring": True, "hire_cash_reserve": 1000}
    got = hires_per_day(params, pending_task_count=48, hour=0, turns_per_day=24, money=1500)
    assert got == 3


def test_hires_per_day_dynamic_hiring_cash_reserve_defaults_to_zero():
    # No hire_cash_reserve given - 0 by default, so even very little
    # money never blocks hiring on its own (the first hire costs $1 -
    # affordability is checked elsewhere in decide(), this reserve exists
    # only for the case the user actually named: protecting the starting
    # capital, not a blanket "never hire while poor" rule).
    params = {"dynamic_hiring": True}
    got = hires_per_day(params, pending_task_count=48, hour=0, turns_per_day=24, money=1)
    assert got == 3


def test_hires_per_day_dynamic_hiring_respects_a_spare_capacity_buffer():
    # T8.16, the user's own explicit ask ("небольшой запас рабочей силы
    # для компенсации всплеска потребности, на вскидку 5-10%"): the
    # computed target is scaled up by (1 + hire_buffer_fraction) before
    # clipping to [min, max]. 48 tasks, turns_per_task_estimate=2.0,
    # 24 turns left -> raw target = ceil(96/24) - 1 = 3; with a 10%
    # buffer, ceil(3 * 1.10) = ceil(3.3) = 4.
    params = {"dynamic_hiring": True, "hire_buffer_fraction": 0.10}
    got = hires_per_day(params, pending_task_count=48, hour=0, turns_per_day=24)
    assert got == 4


def test_hires_per_day_dynamic_hiring_buffer_defaults_to_zero():
    # No hire_buffer_fraction given - bit-identical to the unbuffered
    # formula for every pre-T8.16 caller.
    without_buffer = hires_per_day({"dynamic_hiring": True}, pending_task_count=48, hour=0, turns_per_day=24)
    with_zero_buffer = hires_per_day(
        {"dynamic_hiring": True, "hire_buffer_fraction": 0.0}, pending_task_count=48, hour=0, turns_per_day=24
    )
    assert without_buffer == with_zero_buffer == 3


def test_hires_per_day_dynamic_hiring_buffer_still_respects_max_hires_per_day():
    # A large buffer must not bypass the ceiling - clipping happens after
    # the buffer is applied, not instead of it.
    params = {"dynamic_hiring": True, "hire_buffer_fraction": 1.0, "max_hires_per_day": 3}
    got = hires_per_day(params, pending_task_count=48, hour=0, turns_per_day=24)
    assert got == 3


def test_crop_actions_per_tile_day_matches_independent_calculation():
    # T8.26: ported from tools/analyze_unit_economics.py's own verified
    # formula (this session's own unit-economics work, checked directly
    # against kaggriculture.py's WATER/HARVEST/FERTILIZE/PLANT handler
    # semantics) - WATER 1/day for the tile's whole life (anti-weed
    # insurance, not just the yield bonus window), HARVEST once for a
    # one-time crop or once per scheduled production for an ongoing crop,
    # FERTILIZE (optional) every 3 days (fertilized_until_day covers today
    # + 2 more), PLANT once at the start.
    for crop in ("MELON", "TOMATO"):
        for use_fertilizer in (False, True):
            total_yield, tile_days = _crop_yield_and_tile_days(crop, days_remaining=30)
            harvest_actions = total_yield if CROPS[crop]["ongoing"] else 1
            fertilize_actions = math.ceil(tile_days / 3) if use_fertilizer else 0
            expected = (tile_days + harvest_actions + fertilize_actions + 1) / tile_days
            got = _crop_actions_per_tile_day(crop, days_remaining=30, use_fertilizer=use_fertilizer)
            assert got == pytest.approx(expected)


def test_animal_actions_per_tile_day_matches_independent_calculation():
    # T8.26: ported from tools/analyze_unit_economics.py's own verified
    # formula - FEED 1/day (an unfed animal risks escape), CARE (optional)
    # 1/day, COLLECT_FERTILIZER (optional) 1/day (fertilizer_available is
    # set True at the end of *every* day the animal survives, fed or not),
    # HARVEST once per scheduled production tick, BUILD_*/PICKUP/PLACE: 3
    # one-time setup actions.
    for animal in ("COW", "SHEEP"):
        for care_aware in (False, True):
            for fertilizer_income_aware in (False, True):
                schedule = forecast_animal_schedule(animal, placed_day=0, horizon_days=30)
                feed_actions = 30
                care_actions = 30 if care_aware else 0
                collect_fertilizer_actions = 30 if fertilizer_income_aware else 0
                harvest_actions = len(schedule)
                expected = (feed_actions + care_actions + collect_fertilizer_actions + harvest_actions + 3) / 30
                got = _animal_actions_per_tile_day(animal, 30, care_aware, fertilizer_income_aware)
                assert got == pytest.approx(expected)


def test_hires_per_day_workload_forecast_hiring_aware_matches_a_hand_computed_target():
    # T8.26: the user's own proposed formula - total_turns = (per-type
    # actions/tile-day x tile counts, summed over every animal/crop type
    # present) x turns_per_task_estimate, buffered by hire_buffer_fraction,
    # divided by the *full* turns_per_day (not the shrinking remainder -
    # see hires_per_day's own docstring addendum for why), floor -1 for
    # the farmer's own turn, clipped to [min_hires_per_day, max_hires_per_
    # day]. A single COW tile plus 10 MELON tiles, hand-computed below.
    cow_actions = _animal_actions_per_tile_day("COW", 30, care_aware=False, fertilizer_income_aware=False)
    melon_actions = _crop_actions_per_tile_day("MELON", 30, use_fertilizer=False)
    total_turns = (cow_actions * 1 + melon_actions * 10) * 2.0  # turns_per_task_estimate
    expected = min(max(math.ceil(total_turns / 24) - 1, 2), 8)  # min/max_hires_per_day defaults
    params = {"dynamic_hiring": True, "workload_forecast_hiring_aware": True}
    got = hires_per_day(
        params,
        hour=12,  # must not matter - a fixed whole-day forecast, not hour-dependent
        turns_per_day=24,
        animal_tile_counts={"COW": 1},
        crop_tile_counts={"MELON": 10},
    )
    assert got == expected


def test_hires_per_day_workload_forecast_hiring_aware_is_hour_independent():
    # The whole point (see the plan's own reasoning): dividing by the full
    # day, not the remainder, so the target doesn't inflate through the
    # day for the same real tile-derived workload.
    params = {"dynamic_hiring": True, "workload_forecast_hiring_aware": True}
    at_hour_0 = hires_per_day(
        params, hour=0, turns_per_day=24, animal_tile_counts={"COW": 2}, crop_tile_counts={"MELON": 5}
    )
    at_hour_20 = hires_per_day(
        params, hour=20, turns_per_day=24, animal_tile_counts={"COW": 2}, crop_tile_counts={"MELON": 5}
    )
    assert at_hour_0 == at_hour_20


def test_hires_per_day_workload_forecast_hiring_aware_defaults_to_off():
    # Bit-identical to the existing dynamic_hiring/pending_task_count path
    # for every caller that doesn't pass the new flag - falls all the way
    # through to the static value here since no pending_task_count is
    # given either.
    params = {"dynamic_hiring": True}
    got = hires_per_day(
        params, hour=0, turns_per_day=24, animal_tile_counts={"COW": 2}, crop_tile_counts={"MELON": 5}
    )
    assert got == 1  # static default, matches test_hires_per_day_dynamic_hiring_falls_back_to_static_without_task_info


def test_hires_per_day_workload_forecast_hiring_aware_falls_back_without_tile_counts():
    # workload_forecast_hiring_aware=True but no tile-count dicts given -
    # graceful fallback to the pending_task_count path (or static, if
    # that's absent too), not an error.
    params = {"dynamic_hiring": True, "workload_forecast_hiring_aware": True, "hires_per_day": 4}
    assert hires_per_day(params) == 4


def test_hires_per_day_workload_forecast_hiring_aware_respects_the_buffer_and_clip():
    # A large buffer must not bypass max_hires_per_day, same invariant as
    # the pending_task_count path's own test above.
    params = {
        "dynamic_hiring": True,
        "workload_forecast_hiring_aware": True,
        "hire_buffer_fraction": 1.0,
        "max_hires_per_day": 3,
    }
    got = hires_per_day(
        params, hour=0, turns_per_day=24, animal_tile_counts={"COW": 5}, crop_tile_counts={"MELON": 20}
    )
    assert got == 3


def test_animal_revenue_per_tile_day_fertilizer_income_matches_independent_calculation():
    # T8.3q: kaggriculture.py's _daily_refresh_animals sets
    # fertilizer_available=True every surviving day regardless of
    # feeding/care - one FERTILIZER unit per day of days_remaining,
    # walked the same self-impact way as the animal's own product.
    from kagg.gamelib.market import price as _price

    days_remaining = 6
    schedule_units = 3  # GOOSE: first_yield_day=4, interval=1 -> days 4,5,6 within horizon=6
    expected = (
        sum(_price("EGG", MARKET_I0 + k) for k in range(schedule_units))
        + sum(_price("FERTILIZER", MARKET_I0 + k) for k in range(days_remaining))
        - 300
        - 2 * days_remaining
    ) / days_remaining
    got = animal_revenue_per_tile_day(
        "GOOSE", MARKET_I0, days_remaining=days_remaining, net_of_cost=True, feed_price=2,
        fertilizer_income_aware=True, fertilizer_sell_at_inventory=MARKET_I0,
    )
    assert got == pytest.approx(expected)


def test_animal_revenue_per_tile_day_fertilizer_income_raises_the_score():
    without = animal_revenue_per_tile_day("COW", MARKET_I0, days_remaining=30, net_of_cost=True, feed_price=25)
    with_fert = animal_revenue_per_tile_day(
        "COW", MARKET_I0, days_remaining=30, net_of_cost=True, feed_price=25,
        fertilizer_income_aware=True, fertilizer_sell_at_inventory=MARKET_I0,
    )
    assert with_fert > without
    # Recomputed directly (T8.3q's investigation): fertilizer income alone
    # should roughly triple+ COW's net rate at a full 30-day horizon.
    assert with_fert > without * 2


def test_animal_revenue_per_tile_day_fertilizer_income_defaults_to_false():
    steady_state = animal_revenue_per_tile_day("COW", MARKET_I0)
    assert animal_revenue_per_tile_day("COW", MARKET_I0, fertilizer_income_aware=True) == pytest.approx(
        steady_state
    )  # no-op without net_of_cost/days_remaining - nothing to bound the walk


def test_animal_revenue_per_tile_day_fertilizer_income_is_a_noop_without_net_of_cost():
    # fertilizer_income_aware alone (net_of_cost=False) has no horizon to
    # walk against - graceful fallback to the steady-state branch, not an
    # error, matching net_of_cost's own "no days_remaining" fallback.
    without = animal_revenue_per_tile_day("COW", MARKET_I0, days_remaining=30)
    with_fert_only = animal_revenue_per_tile_day(
        "COW", MARKET_I0, days_remaining=30, fertilizer_income_aware=True
    )
    assert with_fert_only == pytest.approx(without)


def test_rank_portfolio_animal_fertilizer_income_aware_lifts_animals_back_above_most_crops():
    # T8.3q: with net-of-cost alone (T8.3m's shipped default), COW ranks
    # below STRAWBERRY/CARROT/WHEAT/TOMATO at base price - fertilizer
    # income should lift it back above all of them (MELON still edges it
    # out narrowly - see this module's own worked numbers - so this
    # checks the real, decisive shift rather than an unrealistic "always
    # #1" claim).
    market = {}
    net_of_cost_only = rank_portfolio(market, days_remaining=30, animal_net_of_cost=True)
    with_fertilizer = rank_portfolio(
        market, days_remaining=30, animal_net_of_cost=True, animal_fertilizer_income_aware=True
    )
    assert net_of_cost_only.index("COW") > net_of_cost_only.index("STRAWBERRY")
    assert with_fertilizer.index("COW") < with_fertilizer.index("STRAWBERRY")


def test_rank_portfolio_animal_fertilizer_income_aware_defaults_to_false():
    market = {}
    assert rank_portfolio(market, days_remaining=30, animal_net_of_cost=True) == rank_portfolio(
        market, days_remaining=30, animal_net_of_cost=True, animal_fertilizer_income_aware=False
    )


def test_animal_revenue_per_tile_day_care_aware_matches_exact_day_by_day_simulation():
    # T8.3q Part 2: GOOSE (first_yield_day=4, interval=1) over 6 days with
    # continuous feeding+care. Hand-traced against the real
    # pending_care_bonus mechanic: day1-3 bank (no production yet, +1/day
    # each), day4 production pays out the bank (base 1 + pending 3 = 4,
    # capped at max_held=4), bank resets and re-accrues day4 (+1), day5
    # production pays 1+1=2 (capped at 4, no change), day6 production
    # pays 1+1=2 (capped at 4, no change) - total harvested = 4+2+2 = 8.
    from kagg.gamelib.market import price as _price

    days_remaining = 6
    expected_units = 8
    expected = (
        sum(_price("EGG", MARKET_I0 + k) for k in range(expected_units)) - 300 - 2 * days_remaining
    ) / days_remaining
    got = animal_revenue_per_tile_day(
        "GOOSE", MARKET_I0, days_remaining=days_remaining, net_of_cost=True, feed_price=2, care_aware=True
    )
    assert got == pytest.approx(expected)


def test_animal_revenue_per_tile_day_care_aware_raises_the_score():
    without = animal_revenue_per_tile_day("SHEEP", MARKET_I0, days_remaining=30, net_of_cost=True, feed_price=25)
    with_care = animal_revenue_per_tile_day(
        "SHEEP", MARKET_I0, days_remaining=30, net_of_cost=True, feed_price=25, care_aware=True
    )
    assert with_care > without


def test_animal_revenue_per_tile_day_care_aware_defaults_to_false():
    steady_state = animal_revenue_per_tile_day("COW", MARKET_I0)
    assert animal_revenue_per_tile_day("COW", MARKET_I0, care_aware=True) == pytest.approx(steady_state)


def test_animal_revenue_per_tile_day_care_aware_is_a_noop_without_net_of_cost():
    without = animal_revenue_per_tile_day("COW", MARKET_I0, days_remaining=30)
    with_care_only = animal_revenue_per_tile_day("COW", MARKET_I0, days_remaining=30, care_aware=True)
    assert with_care_only == pytest.approx(without)


def test_rank_portfolio_animal_care_aware_raises_an_animals_rank():
    market = {}
    without = rank_portfolio(market, days_remaining=30, animal_net_of_cost=True)
    with_care = rank_portfolio(market, days_remaining=30, animal_net_of_cost=True, animal_care_aware=True)
    assert with_care.index("COW") < without.index("COW")


def test_rank_portfolio_animal_care_aware_defaults_to_false():
    market = {}
    assert rank_portfolio(market, days_remaining=30, animal_net_of_cost=True) == rank_portfolio(
        market, days_remaining=30, animal_net_of_cost=True, animal_care_aware=False
    )


def test_animal_revenue_per_tile_day_consumption_horizon_aware_matches_independent_calculation():
    # T8.10, the user's own observation: rank_portfolio's animal-side
    # consumption estimate only ever covered one production interval
    # (`expected_consumption = rate * a["interval"]`, 1-3 days), while the
    # crop side already used the full tile-occupancy horizon (T8.3f). An
    # animal sells into a market the town drains *every day*, all season -
    # each scheduled unit should be priced against the market as drained
    # up to *that unit's own production day*, not a single flat offset.
    #
    # GOOSE (first_yield_day=4, interval=1), days_remaining=6:
    # forecast_animal_schedule gives [4, 5, 6]. At consumption_rate=3/day,
    # the k-th unit (k=0,1,2) sells at price(EGG, I0 - 3*day + k) for its
    # own schedule day, not a flat "I0 - 3*interval" offset.
    from kagg.gamelib.market import price as _price

    days_remaining = 6
    schedule = [4, 5, 6]
    rate = 3
    expected = (
        sum(_price("EGG", MARKET_I0 - rate * day + k) for k, day in enumerate(schedule))
        - 300
        - 2 * days_remaining
    ) / days_remaining
    got = animal_revenue_per_tile_day(
        "GOOSE", MARKET_I0, days_remaining=days_remaining, net_of_cost=True, feed_price=2,
        consumption_horizon_aware=True, consumption_rate=rate,
    )
    assert got == pytest.approx(expected)


def test_animal_revenue_per_tile_day_consumption_horizon_aware_lowers_a_late_producers_score():
    # A late-producing animal (COW: first_yield_day=8) sells most of its
    # units well after day 0 - by the time its later units sell, heavy
    # daily town/shop draw has pushed the price up a lot further than the
    # old flat "one interval" offset ever credited. The horizon-aware walk
    # must score COW *higher* than the flat-offset model once a real,
    # sustained consumption rate is given (scarcity raises price).
    flat = animal_revenue_per_tile_day(
        "COW", MARKET_I0, expected_consumption=25 * 2, days_remaining=28, net_of_cost=True, feed_price=25,
    )
    horizon_aware = animal_revenue_per_tile_day(
        "COW", MARKET_I0, days_remaining=28, net_of_cost=True, feed_price=25,
        consumption_horizon_aware=True, consumption_rate=25,
    )
    assert horizon_aware > flat


def test_animal_revenue_per_tile_day_consumption_horizon_aware_defaults_to_false():
    without = animal_revenue_per_tile_day(
        "COW", MARKET_I0, expected_consumption=999, days_remaining=28, net_of_cost=True, feed_price=25,
    )
    # consumption_horizon_aware defaults to False - consumption_rate must
    # be completely ignored, expected_consumption (the old path) still
    # drives the score, bit-identical to every pre-T8.10 caller.
    assert animal_revenue_per_tile_day(
        "COW", MARKET_I0, expected_consumption=999, days_remaining=28, net_of_cost=True, feed_price=25,
        consumption_rate=12345,
    ) == pytest.approx(without)


def test_animal_full_care_schedule_matches_total_units_and_hand_trace():
    # T8.21: _animal_full_care_schedule is the new per-production-day
    # breakdown (list[tuple[day, units]]) that _animal_full_care_units
    # (still returning just the total) is refactored to sum - same
    # GOOSE/6-day hand trace as
    # test_animal_revenue_per_tile_day_care_aware_matches_exact_day_by_day_simulation:
    # day4 pays out base 1 + banked 3 = 4 (capped at max_held=4), day5
    # pays 1+1=2, day6 pays 1+1=2.
    from kagg.policy.strategy import _animal_full_care_schedule, _animal_full_care_units

    schedule = _animal_full_care_schedule("GOOSE", 6)
    assert schedule == [(4, 4), (5, 2), (6, 2)]
    assert _animal_full_care_units("GOOSE", 6) == sum(units for _, units in schedule)


def test_animal_revenue_per_tile_day_consumption_horizon_aware_walks_the_real_care_schedule():
    # T8.21: closes the gap the old "is_a_noop_with_care_aware" test named
    # - _animal_full_care_schedule (above) gives a real per-production-day
    # breakdown, so consumption_horizon_aware no longer needs to fall back
    # to the flat expected_consumption offset when care_aware is also set.
    # Each of the 8 real units (day4 x4, day5 x2, day6 x2, in production
    # order) is priced at its own day's consumption-drained level, walked
    # lockstep across the whole 8-unit run (k=0..7), not per-day.
    from kagg.gamelib.market import price as _price

    days_remaining = 6
    rate = 3
    per_day_units = [(4, 4), (5, 2), (6, 2)]
    flat_units = [day for day, units in per_day_units for _ in range(units)]
    expected = (
        sum(_price("EGG", MARKET_I0 - rate * day + k) for k, day in enumerate(flat_units))
        - 300
        - 2 * days_remaining
    ) / days_remaining
    got = animal_revenue_per_tile_day(
        "GOOSE", MARKET_I0, days_remaining=days_remaining, net_of_cost=True, feed_price=2, care_aware=True,
        consumption_horizon_aware=True, consumption_rate=rate,
    )
    assert got == pytest.approx(expected)
    # And it must actually differ from the old flat-offset fallback -
    # otherwise this combination still isn't doing anything new.
    flat_fallback = animal_revenue_per_tile_day(
        "GOOSE", MARKET_I0, days_remaining=days_remaining, net_of_cost=True, feed_price=2, care_aware=True,
    )
    assert got != pytest.approx(flat_fallback)


def test_rank_portfolio_animal_consumption_horizon_aware_raises_cows_rank():
    # T8.10: with a real, sustained draw on MILK (three PIZZA_SHOP +
    # ICE_CREAM_SHOP, matching seed 100's own real shop draw), the
    # horizon-aware model must rank COW at least as high as the old flat
    # one-interval model - the whole point of the fix.
    market = {}
    shops = ["PIZZA_SHOP", "PIZZA_SHOP", "PIZZA_SHOP", "ICE_CREAM_SHOP"]
    flat = rank_portfolio(market, unlocked_shops=shops, days_remaining=28, animal_net_of_cost=True)
    horizon_aware = rank_portfolio(
        market, unlocked_shops=shops, days_remaining=28, animal_net_of_cost=True,
        animal_consumption_horizon_aware=True,
    )
    assert horizon_aware.index("COW") <= flat.index("COW")


def test_rank_portfolio_animal_consumption_horizon_aware_defaults_to_false():
    market = {}
    assert rank_portfolio(market, days_remaining=28, animal_net_of_cost=True) == rank_portfolio(
        market, days_remaining=28, animal_net_of_cost=True, animal_consumption_horizon_aware=False
    )


def test_score_portfolio_matches_rank_portfolio_ordering():
    # T8.14: rank_portfolio is refactored to be a thin wrapper of
    # score_portfolio - same arguments, same underlying numbers, this
    # test locks that relationship down directly rather than trusting it
    # by construction. score_portfolio exposes the raw {name: score}
    # dict rank_portfolio has always computed internally but never
    # returned - needed by _top_investment_choice's own commit-margin
    # check (T8.14), which must compare a candidate's score against the
    # best crop's score, not just its rank position.
    market = {"TOMATO": MARKET_I0 - 50}
    scores = score_portfolio(market, net_of_seed_cost=True)
    ranking = rank_portfolio(market, net_of_seed_cost=True)
    assert sorted(scores, key=scores.__getitem__, reverse=True) == ranking


def test_score_portfolio_returns_every_crop_and_animal():
    scores = score_portfolio(_MARKET_AT_I0)
    assert set(scores) == {"WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "GOOSE", "COW", "SHEEP"}


def test_score_portfolio_matches_independent_per_item_calculation():
    # Cross-checked directly against the same independently-verified
    # crop_revenue_per_tile_day/animal_revenue_per_tile_day calls
    # test_rank_portfolio_orders_by_marginal_revenue_at_base_price relies
    # on - score_portfolio must produce the *exact* per-item numbers
    # rank_portfolio's own ranking is silently built from today, not an
    # approximation. MELON's own town-center draw (1 unit/day, present
    # even with no unlocked_shops given) is real, non-zero expected
    # consumption score_portfolio always folds in - not comparable to a
    # bare crop_revenue_per_tile_day(..., expected_consumption=0) call.
    scores = score_portfolio(_MARKET_AT_I0)
    _, melon_tile_days = _crop_yield_and_tile_days("MELON")
    melon_consumption = expected_daily_consumption("MELON", []) * melon_tile_days
    assert scores["MELON"] == pytest.approx(
        crop_revenue_per_tile_day("MELON", MARKET_I0, expected_consumption=melon_consumption)
    )
    cow_consumption = expected_daily_consumption("MILK", []) * 2  # COW's own interval
    assert scores["COW"] == pytest.approx(
        animal_revenue_per_tile_day("COW", MARKET_I0, expected_consumption=cow_consumption)
    )


def test_wheat_feed_credit_per_tile_day_splits_yield_between_feed_and_sale():
    # T8.24, the user's own follow-up: growing WHEAT domestically instead
    # of always buying it (kagg.policy.market.buy_wheat_order) avoids the
    # real, currently-unpriced BUY-side price (price() quotes BUY at
    # *post-buy* inventory - falling as more is bought, pushing price UP)
    # instead of earning the (lower) SELL-side price (quoted at pre-sell
    # inventory - rising as more is sold, pushing price DOWN). A WHEAT
    # tile's total_yield=4 units (_crop_yield_and_tile_days, tile_days=5)
    # split: feed_units_needed=2 diverts 2 units to feed (avoided BUY
    # price), the remaining 2 are sold normally (SELL price) - this is a
    # pure DELTA versus selling the whole yield, addable on top of
    # crop_revenue_per_tile_day's own WHEAT score without double-counting
    # any unit.
    from kagg.gamelib.market import price as _price
    from kagg.policy.strategy import wheat_feed_credit_per_tile_day

    feed_units_needed = 2
    diverted_sale_revenue = sum(_price("WHEAT", MARKET_I0 + k) for k in range(feed_units_needed))
    feed_avoided_revenue = sum(_price("WHEAT", MARKET_I0 - k) for k in range(1, feed_units_needed + 1))
    expected = (feed_avoided_revenue - diverted_sale_revenue) / 5
    got = wheat_feed_credit_per_tile_day(MARKET_I0, feed_units_needed)
    assert got == pytest.approx(expected)


def test_wheat_feed_credit_per_tile_day_caps_feed_units_at_the_tiles_own_yield():
    # feed_units_needed way beyond total_yield=4 must not divert more
    # units than the tile actually produces - feed_units floors at
    # total_yield, not feed_units_needed itself. diverted_sale_revenue is
    # still the *full* total_yield-unit sale walk here (all 4 units are
    # diverted, so all 4 would otherwise have sold) - not zero: it's the
    # opportunity cost of *not* selling them, which needs the same
    # k=0..feed_units-1 walk crop_revenue_per_tile_day's own full-yield
    # sale price uses, regardless of how much feed demand exists beyond
    # that.
    from kagg.gamelib.market import price as _price
    from kagg.policy.strategy import wheat_feed_credit_per_tile_day

    total_yield = 4
    feed_avoided_revenue = sum(_price("WHEAT", MARKET_I0 - k) for k in range(1, total_yield + 1))
    diverted_sale_revenue = sum(_price("WHEAT", MARKET_I0 + k) for k in range(total_yield))
    expected = (feed_avoided_revenue - diverted_sale_revenue) / 5
    got = wheat_feed_credit_per_tile_day(MARKET_I0, feed_units_needed=100)
    assert got == pytest.approx(expected)


def test_wheat_feed_credit_per_tile_day_is_zero_with_no_feed_demand():
    from kagg.policy.strategy import wheat_feed_credit_per_tile_day

    assert wheat_feed_credit_per_tile_day(MARKET_I0, feed_units_needed=0) == 0.0


def test_score_portfolio_wheat_self_sufficiency_aware_matches_independent_calculation():
    # Cross-checked directly against wheat_feed_credit_per_tile_day itself
    # (same convention as test_score_portfolio_matches_independent_per_
    # item_calculation above), not asserted to always raise WHEAT's score
    # unconditionally - the delta's sign genuinely depends on real market
    # state (see wheat_feed_credit_per_tile_day's own docstring: it can
    # be negative when town-center consumption already favors the
    # sale-side price more than a same-turn buy order would cost at raw
    # inventory - a real, correct result, not a bug).
    _, wheat_tile_days = _crop_yield_and_tile_days("WHEAT")
    wheat_consumption = expected_daily_consumption("WHEAT", []) * wheat_tile_days
    without = score_portfolio(_MARKET_AT_I0)
    with_credit = score_portfolio(
        _MARKET_AT_I0, wheat_self_sufficiency_aware=True, wheat_feed_units_needed=4,
    )
    from kagg.policy.strategy import wheat_feed_credit_per_tile_day

    expected_delta = wheat_feed_credit_per_tile_day(MARKET_I0, 4, 0, wheat_consumption)
    assert expected_delta != 0  # the scenario must actually exercise a real, nonzero effect
    assert with_credit["WHEAT"] == pytest.approx(without["WHEAT"] + expected_delta)
    # Every other item must be untouched - this is a WHEAT-only credit.
    for name in without:
        if name != "WHEAT":
            assert with_credit[name] == pytest.approx(without[name])


def test_score_portfolio_wheat_self_sufficiency_aware_defaults_to_false():
    assert score_portfolio(_MARKET_AT_I0) == score_portfolio(
        _MARKET_AT_I0, wheat_self_sufficiency_aware=False, wheat_feed_units_needed=4,
    )


def test_score_portfolio_wheat_self_sufficiency_aware_is_a_noop_with_zero_feed_units():
    without = score_portfolio(_MARKET_AT_I0)
    with_flag_but_no_demand = score_portfolio(
        _MARKET_AT_I0, wheat_self_sufficiency_aware=True, wheat_feed_units_needed=0,
    )
    assert with_flag_but_no_demand == without
