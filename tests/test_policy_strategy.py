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
