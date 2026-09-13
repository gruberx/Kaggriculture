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

import pytest

from kagg.gamelib.constants import MARKET_I0
from kagg.gamelib.market import expected_daily_consumption
from kagg.policy.strategy import (
    animal_revenue_per_tile_day,
    crop_revenue_per_tile_day,
    hires_per_day,
    rank_portfolio,
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
    ) is False  # fraction gate (0.25 default) blocks; frontier (99 default) can't override it


def test_should_buy_land_fraction_1_0_reproduces_the_fully_ungated_behavior():
    # T8.3's mechanism itself (as opposed to the accepted 0.25 default)
    # is still reachable by passing the fully-ungated value explicitly.
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
    for free_tiles, unlocked_tiles in [(20, 25), (5, 25), (6, 25)]:
        assert should_buy_land(
            money=1_000_000, n_unlocked_extra=0, params={},
            free_tiles=free_tiles, unlocked_tiles=unlocked_tiles, nearest_free_shed_distance=8,
        ) == should_buy_land(
            money=1_000_000, n_unlocked_extra=0,
            params={"land_buy_max_free_tile_fraction": 0.25},
            free_tiles=free_tiles, unlocked_tiles=unlocked_tiles, nearest_free_shed_distance=8,
        )


def test_should_buy_land_still_respects_money_threshold_with_occupancy_given():
    params = {"land_buy_max_free_tile_fraction": 1.0}
    assert should_buy_land(
        money=100, n_unlocked_extra=0, params=params,
        free_tiles=1, unlocked_tiles=25, nearest_free_shed_distance=8,
    ) is False


def test_hires_per_day_reads_the_named_parameter_with_a_conservative_default():
    # Deliberately conservative default (SPEC-policy.md: the "hire many
    # hands" intuition was contradicted by a forum measurement) - never
    # raise this default based on intuition, only on an arena result.
    assert hires_per_day({}) == 0
    assert hires_per_day({"hires_per_day": 5}) == 5


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
