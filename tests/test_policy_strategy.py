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
from kagg.policy.strategy import (
    animal_revenue_per_tile_day,
    crop_revenue_per_tile_day,
    hires_per_day,
    rank_portfolio,
    should_buy_land,
)

# Computed directly from gamelib (Phase 1, already property-tested) at
# I0 (base price), independently of this module:
#   WHEAT:      yield=4, tile_days=5  -> 4*25/5   = 20.000
#   CARROT:     yield=3, tile_days=4  -> 3*35/4   = 26.250
#   TOMATO:     yield=4, tile_days=12 -> 4*60/12  = 20.000
#   STRAWBERRY: yield=4, tile_days=17 -> 4*120/17 = 28.235...
#   MELON:      yield=6, tile_days=13 -> 6*250/13 = 115.385... (yield
#               capped at max_yield=6 - the window waters 7 days but the
#               cap is hit at age 10, matching SPEC-gamelib.md's own
#               worked example)
#   GOOSE: 50/1  = 50.000
#   COW:   160/2 = 80.000
#   SHEEP: 200/3 = 66.667...
_MARKET_AT_I0 = {}  # rank_portfolio falls back to MARKET_I0 per item when absent


def test_crop_revenue_per_tile_day_matches_independent_calculation():
    assert crop_revenue_per_tile_day("WHEAT", MARKET_I0) == pytest.approx(20.0)
    assert crop_revenue_per_tile_day("CARROT", MARKET_I0) == pytest.approx(26.25)
    assert crop_revenue_per_tile_day("TOMATO", MARKET_I0) == pytest.approx(20.0)
    assert crop_revenue_per_tile_day("STRAWBERRY", MARKET_I0) == pytest.approx(120 * 4 / 17)
    assert crop_revenue_per_tile_day("MELON", MARKET_I0) == pytest.approx(250 * 6 / 13)


def test_animal_revenue_per_tile_day_matches_independent_calculation():
    assert animal_revenue_per_tile_day("GOOSE", MARKET_I0) == pytest.approx(50.0)
    assert animal_revenue_per_tile_day("COW", MARKET_I0) == pytest.approx(80.0)
    assert animal_revenue_per_tile_day("SHEEP", MARKET_I0) == pytest.approx(200 / 3)


def test_rank_portfolio_orders_by_marginal_revenue_at_base_price():
    # MELON's huge per-tile-day revenue at base price is exactly the
    # "premium goods look great until you check market depth" trap
    # SPEC.md's economic analysis warns about - this ranking function
    # deliberately does NOT yet account for that (see its own docstring);
    # it's a first-pass ranking at *today's* price, not a full plan.
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


def test_hires_per_day_reads_the_named_parameter_with_a_conservative_default():
    # Deliberately conservative default (SPEC-policy.md: the "hire many
    # hands" intuition was contradicted by a forum measurement) - never
    # raise this default based on intuition, only on an arena result.
    assert hires_per_day({}) == 0
    assert hires_per_day({"hires_per_day": 5}) == 5
