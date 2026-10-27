"""Unit tests for kagg.policy.cycle_economics (T8.68) - see that module's
own docstring for the full design story.

Every expected value here is computed independently, directly from
`kagg.gamelib.market.price` (Phase 1's own already-verified oracle) and
plain arithmetic on the static shape data in `tasks/data/tile_economics.
json` (mirrored at `kagg/params/tile_economics.json`) - never by calling
the function under test and asserting it equals itself.
"""

from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_I0
from kagg.gamelib.market import expected_consumption_over_horizon, expected_daily_consumption, price
from kagg.policy.cycle_economics import (
    animal_horizon_profit_per_day,
    crop_cycle_profit_per_day,
    crop_has_time_to_produce,
    crop_horizon_profit_per_day,
    crops_worth_fertilizing,
    fertilize_ages,
    rank_portfolio_v2,
    score_portfolio_v2,
    units_per_cycle,
)
from kagg.policy.strategy import _animal_full_care_schedule


def test_days_remaining_zero_or_negative_scores_zero():
    assert crop_horizon_profit_per_day("WHEAT", 0, MARKET_I0) == (0.0, False)
    assert crop_horizon_profit_per_day("MELON", -1, MARKET_I0) == (0.0, False)


def test_wheat_whole_horizon_multiple_full_cycles_no_partial():
    """days_remaining=9: WHEAT's no_fertilizer cycle is 4 days
    (plant day 0, harvest day 4) - two full replant cycles fit
    (cycles=(9-1)//4=2), with 0 days left over (rest=0, below
    first_yield_day=2, so no partial tail). Every one of the 8 units
    across BOTH cycles must be counted and priced along the same self-
    impact walk (request point "whole remaining life", not one cycle's
    rate) - this is exactly the assertion T8.68's plan called out by
    name: "WHEAT at days_remaining=20 must show ~5 replantings' worth of
    units, not 1" (here at a smaller, hand-checkable days_remaining=9,
    2 replantings).

    Denominator is the tile-days actually OCCUPIED by the two cycles
    (2*4=8), not the raw `days_remaining` (9) - the found-and-fixed
    STRAWBERRY/TOMATO crossover defect (see the module's own docstring
    paragraph on this): the 1 leftover day here isn't spent on WHEAT at
    all (no worthwhile tail - `rest=0 < first_yield_day=2`), so it must
    not dilute WHEAT's own score."""
    start = MARKET_I0
    expected_revenue = sum(price("WHEAT", start + k) for k in range(8))  # 2 cycles * 4 units
    expected_cost = 2 * CROPS["WHEAT"]["seed"]  # 2 plantings, no fertilizer
    expected = (expected_revenue - expected_cost) / 8  # occupied_days = 2 cycles * 4 days
    score, used_fertilizer = crop_horizon_profit_per_day("WHEAT", 9, MARKET_I0)
    assert score == expected
    assert used_fertilizer is False


def test_wheat_partial_tail_included_when_cycles_zero():
    """days_remaining=3: not even one full 4-day cycle fits (cycles=0,
    the whole horizon IS the tail's own window) - watering ages {0, 2}
    (the full schedule's own ages truncated to <= rest=2) yields 2 units
    (starting yield 1, +1 for the single in-window watering at age 2).
    Included because its own priced value clears its own seed cost
    (request point 2: partial credit instead of an all-or-nothing
    exclusion) - with no completed cycle to compare against, any net-
    positive tail is strictly better than the 0.0 fallback."""
    start = MARKET_I0
    tail_revenue = sum(price("WHEAT", start + k) for k in range(2))
    assert tail_revenue > CROPS["WHEAT"]["seed"]  # confirms the tail clears its own bar
    expected = (tail_revenue - CROPS["WHEAT"]["seed"]) / 3  # occupied_days = rest(2) + 1
    score, used_fertilizer = crop_horizon_profit_per_day("WHEAT", 3, MARKET_I0)
    assert score == expected
    assert used_fertilizer is False


def test_wheat_tail_excluded_when_it_would_drag_the_completed_cycle_s_rate_down():
    """days_remaining=7: one full cycle (4 days) fits, leaving rest=2
    days - a tail is net-positive on its own (2 units clear the seed
    cost - see test_wheat_partial_tail_included_when_cycles_zero's own
    numbers, the same tail shape), but blending it into the average would
    ADD 3 more days for only 2 more (already-cheaper, self-impact-walked)
    units - below the completed cycle's own strong rate. Found while
    digging into the STRAWBERRY/TOMATO crossover (T8.68's tasks/todo.md
    entry): a merely net-positive tail isn't automatically an
    improvement once the denominator is tile-days, not days_remaining -
    excluded here, so the score is exactly the completed cycle's own
    rate (matches days_remaining=8's per-cycle rate, occupied_days=4)."""
    start = MARKET_I0
    full_cycle_revenue = sum(price("WHEAT", start + k) for k in range(4))
    expected = (full_cycle_revenue - CROPS["WHEAT"]["seed"]) / 4  # tail excluded - only 1 cycle counted
    score, used_fertilizer = crop_horizon_profit_per_day("WHEAT", 7, MARKET_I0)
    assert score == expected
    assert used_fertilizer is False


def test_wheat_cycles_zero_partial_not_reachable():
    """days_remaining=2: not even one full 4-day cycle fits (cycles=0),
    and the leftover (rest=1) is below WHEAT's first_yield_day=2, so
    there's nothing to harvest at all - score is exactly 0, the natural
    "cycles==0 and no worthwhile tail" case the plan says needs no
    separate branch."""
    score, used_fertilizer = crop_horizon_profit_per_day("WHEAT", 2, MARKET_I0)
    assert score == 0.0
    assert used_fertilizer is False


def test_tomato_ongoing_multiple_full_fertilized_cycles():
    """days_remaining=23: TOMATO's fertilized cycle is 11 days (2
    internal harvest events/8 units per life, cheap fertilizer chosen) -
    two full replant cycles fit (cycles=(23-1)//11=2, rest=0). Confirms
    an ongoing crop's OWN multiple internal production events, across
    MULTIPLE replantings, are all counted - the user's own explicit
    "additional production cycles within one planting" example.

    Denominator is occupied_days = 2 cycles * 11 days = 22, not the raw
    `days_remaining` (23) - see test_wheat_whole_horizon_multiple_full_
    cycles_no_partial's own docstring for why (the 1 leftover day isn't
    spent on TOMATO at all: rest=0 has no worthwhile tail here)."""
    start = MARKET_I0
    fertilizer_price = 8.0  # below the threshold, so the fertilized variant is used
    expected_revenue = sum(price("TOMATO", start + k) for k in range(16))  # 2 cycles * 8 units
    expected_cost = 2 * 50 + (2 * 2) * fertilizer_price  # 2 plantings, 2 fert apps/cycle
    expected = (expected_revenue - expected_cost) / 22  # occupied_days = 2 cycles * 11 days
    score, used_fertilizer = crop_horizon_profit_per_day(
        "TOMATO", 23, MARKET_I0, fertilizer_price=fertilizer_price, fertilizer_price_threshold=10
    )
    assert score == expected
    assert used_fertilizer is True


def test_tomato_ongoing_partial_tail_included_when_cycles_zero():
    """days_remaining=11: not even one full 11-day TOMATO cycle fits
    (cycles=0, the whole horizon is the tail's own window) - 3 of its 4
    scheduled production ticks (ages 8, 9, 10; age 11 falls outside
    rest=10) fire, each getting the fertilizer bonus (applications at
    ages 7 and 10, both still active on their own covered ticks) for 6
    units total. With no completed cycle to compare against, this net-
    positive tail is included unconditionally (mirrors WHEAT's own
    cycles==0 case, now for an ongoing crop with multiple ticks in the
    tail itself)."""
    start = MARKET_I0
    fertilizer_price = 8.0
    tail_revenue = sum(price("TOMATO", start + k) for k in range(6))
    tail_cost = 50 + 2 * fertilizer_price  # both fertilizer applications (ages 7 and 10) fall in range
    assert tail_revenue > tail_cost
    expected = (tail_revenue - tail_cost) / 11  # occupied_days = rest(10) + 1
    score, used_fertilizer = crop_horizon_profit_per_day(
        "TOMATO", 11, MARKET_I0, fertilizer_price=fertilizer_price, fertilizer_price_threshold=10
    )
    assert score == expected
    assert used_fertilizer is True


def test_tomato_ongoing_tail_excluded_when_it_would_drag_the_completed_cycle_s_rate_down():
    """days_remaining=20: one full fertilized TOMATO cycle (11 days)
    fits, leaving rest=8 - a tail is net-positive on its own (2 units
    clear their own cost), but blending it in would add 9 more days for
    only 2 more units, below the completed cycle's own strong rate - the
    same T8.68 refinement WHEAT's own tail-exclusion test covers, now for
    an ongoing crop. Score is exactly the completed cycle's own rate."""
    start = MARKET_I0
    fertilizer_price = 8.0
    full_cycle_revenue = sum(price("TOMATO", start + k) for k in range(8))
    expected_cost = 50 + 2 * fertilizer_price  # tail excluded - only 1 cycle counted
    expected = (full_cycle_revenue - expected_cost) / 11  # occupied_days = 1 cycle * 11 days
    score, used_fertilizer = crop_horizon_profit_per_day(
        "TOMATO", 20, MARKET_I0, fertilizer_price=fertilizer_price, fertilizer_price_threshold=10
    )
    assert score == expected
    assert used_fertilizer is True


def test_fertilizer_price_threshold_switches_variant():
    score_hi, used_hi = crop_horizon_profit_per_day(
        "WHEAT", 20, MARKET_I0, fertilizer_price=100, fertilizer_price_threshold=10
    )
    score_lo, used_lo = crop_horizon_profit_per_day(
        "WHEAT", 20, MARKET_I0, fertilizer_price=5, fertilizer_price_threshold=10
    )
    assert used_hi is False
    assert used_lo is True
    assert score_lo != score_hi


def test_melon_never_switches_to_fertilizer():
    """MELON's fertilized variant is identical to its unfertilized one
    (fertilizer genuinely doesn't help it - confirmed in the saved
    table's own fert_days: []) - even a near-free fertilizer price must
    never flip it."""
    _score, used = crop_horizon_profit_per_day(
        "MELON", 20, MARKET_I0, fertilizer_price=0.01, fertilizer_price_threshold=1000
    )
    assert used is False
    assert fertilize_ages("MELON") == frozenset()


def test_animal_horizon_continues_through_literal_last_day():
    """A placed animal keeps producing all the way through the literal
    last day of days_remaining, not some fixed 30-day window (request
    point 1) - confirmed directly against strategy._animal_full_care_
    schedule (the same simulation animal_horizon_profit_per_day wraps),
    at a small days_remaining near a hypothetical season end."""
    schedule = _animal_full_care_schedule("GOOSE", 9)
    assert schedule[-1][0] == 9  # production still happens on the LAST day
    # A too-short horizon (below first_yield_day) produces nothing, and
    # the wrapper still returns a finite (very negative, cost-only) score
    # rather than crashing or falling back to an unbounded rate.
    assert _animal_full_care_schedule("GOOSE", 3) == []
    score = animal_horizon_profit_per_day("GOOSE", 3, MARKET_I0)
    assert score == (0.0 - ANIMALS["GOOSE"]["cost"]) / 3


def test_animal_horizon_matches_strategy_wrapper():
    """A thin wrapper, not a reimplementation - matches strategy.animal_
    revenue_per_tile_day's own net_of_cost=True, care_aware=True branch
    exactly for the same inputs."""
    from kagg.policy.strategy import animal_revenue_per_tile_day

    for animal in ANIMALS:
        expected = animal_revenue_per_tile_day(
            animal, MARKET_I0, 0, 15, net_of_cost=True, feed_price=2.0, care_aware=True,
        )
        got = animal_horizon_profit_per_day(animal, 15, MARKET_I0, feed_price=2.0)
        assert got == expected


def test_crops_worth_fertilizing_gate():
    assert crops_worth_fertilizing({}, 10) == frozenset()  # base FERTILIZER price (100) is above 10
    below = crops_worth_fertilizing({"FERTILIZER": MARKET_I0 * 100}, 10)  # very cheap once oversupplied
    assert "MELON" not in below  # never worth it regardless of price
    assert "WHEAT" in below


def test_crop_has_time_to_produce_looser_than_full_maturity():
    """MELON planted on day 19 of a 30-day season can't reach its full
    max_yield_day (12) - current_day + max_yield_day = 31 >= 30 - but CAN
    still reach its first_yield_day (10): 19 + 10 = 29 < 30. This is
    exactly the gap request point 2 asks to close."""
    assert crop_has_time_to_produce("MELON", 19, 30) is True
    assert 19 + CROPS["MELON"]["max_yield_day"] >= 30  # confirms the old hard filter would reject it
    assert crop_has_time_to_produce("MELON", 25, 30) is False  # can't even reach first_yield_day


def test_score_portfolio_v2_covers_every_crop_and_animal():
    scores, fertilize_crops = score_portfolio_v2({}, 20)
    assert set(scores) == set(CROPS) | set(ANIMALS)
    assert fertilize_crops == frozenset()  # base FERTILIZER price (100) is above the default threshold (10)


def test_rank_portfolio_v2_matches_score_portfolio_v2_sort_order():
    scores, fc1 = score_portfolio_v2({}, 20)
    ranked, fc2 = rank_portfolio_v2({}, 20)
    assert ranked == sorted(scores, key=scores.__getitem__, reverse=True)


def test_score_portfolio_v2_potential_new_tiles_defaults_to_a_no_op():
    """T8.70 (crop_own_future_supply_aware): potential_new_tiles=0 (the
    default) must reproduce today's score exactly, same convention as
    every other T8.70 flag's off-state."""
    days_remaining = 9
    crop_tile_counts = {"WHEAT": 1}
    with_default, _ = score_portfolio_v2({}, days_remaining, crop_tile_counts)
    with_explicit_zero, _ = score_portfolio_v2({}, days_remaining, crop_tile_counts, potential_new_tiles=0)
    assert with_default["WHEAT"] == with_explicit_zero["WHEAT"]


def test_score_portfolio_v2_potential_new_tiles_adds_to_already_committed_units():
    """potential_new_tiles is added on top of crop_tile_counts before
    already_committed_units is computed - verified against a direct
    crop_horizon_profit_per_day call with the combined tile count
    computed by hand (WHEAT's no_fertilizer variant produces 4 units per
    cycle - see test_wheat_whole_horizon_multiple_full_cycles_no_partial
    above)."""
    days_remaining = 9
    scores, _ = score_portfolio_v2({}, days_remaining, {"WHEAT": 1}, potential_new_tiles=2)
    expected_already_committed_units = (1 + 2) * 4
    # score_portfolio_v2 passes unlocked_shops=[] by default, which still
    # has a non-zero town-center-only consumption rate (WHEAT isn't
    # FERTILIZER) - must match that, not the bare 0.0 default.
    expected_consumption = expected_daily_consumption("WHEAT", []) * days_remaining
    expected_score, _ = crop_horizon_profit_per_day(
        "WHEAT", days_remaining, MARKET_I0, expected_already_committed_units, expected_consumption
    )
    assert scores["WHEAT"] == expected_score


def test_score_portfolio_v2_shop_unlock_forecast_aware_uses_horizon_consumption():
    """T8.70 (crop_shop_unlock_forecast_aware): swaps the flat
    expected_daily_consumption(...)*days_remaining for
    expected_consumption_over_horizon(...) - verified against a direct
    crop_horizon_profit_per_day call fed that same hand-computed
    consumption total (STRAWBERRY: listed by 4 shop types, so its
    forecast total noticeably exceeds the flat rate once shop-unlock
    forecasting is on)."""
    days_remaining = 12
    scores, _ = score_portfolio_v2(
        {}, days_remaining, unlocked_shops=[], current_day=0, shop_unlock_forecast_aware=True
    )
    expected_consumption = expected_consumption_over_horizon(
        "STRAWBERRY", [], current_day=0, days_remaining=days_remaining
    )
    expected_score, _ = crop_horizon_profit_per_day(
        "STRAWBERRY", days_remaining, MARKET_I0, 0, expected_consumption
    )
    assert scores["STRAWBERRY"] == expected_score
    # And it must actually differ from the flag-off score - a change with
    # no observable effect would defeat the point of the flag.
    baseline_scores, _ = score_portfolio_v2({}, days_remaining, unlocked_shops=[], current_day=0)
    assert scores["STRAWBERRY"] != baseline_scores["STRAWBERRY"]


def test_units_per_cycle_matches_the_static_shape_data():
    # Matches test_wheat_whole_horizon_multiple_full_cycles_no_partial's
    # own "2 cycles * 4 units" - WHEAT's no_fertilizer variant yields 4
    # units per planting.
    assert units_per_cycle("WHEAT") == 4


def test_crop_cycle_profit_per_day_full_cycle_prices_one_cycle_only():
    """T8.71: days_remaining=9 (same setup as test_wheat_whole_horizon_
    multiple_full_cycles_no_partial) - WHEAT's cycle is 4 days, fits
    (9-1=8>=4). Unlike crop_horizon_profit_per_day, this prices only ONE
    cycle's 4 units, never the two cycles the whole-horizon version would
    project for the same days_remaining - the user's own "no future-cycle
    speculation" redesign."""
    start = MARKET_I0
    expected_revenue = sum(price("WHEAT", start + k) for k in range(4))
    expected_cost = CROPS["WHEAT"]["seed"]
    expected = (expected_revenue - expected_cost) / 4
    score, used_fertilizer = crop_cycle_profit_per_day("WHEAT", 9, MARKET_I0)
    assert score == expected
    assert used_fertilizer is False


def test_crop_cycle_profit_per_day_pending_supply_shifts_the_price_walk():
    # pending_supply moves the whole price walk up the same curve
    # price() itself uses - a real, already-known glut depresses this
    # cycle's own revenue, and must score strictly worse than pending_
    # supply=0 for the identical cycle.
    pending = 500
    start = MARKET_I0 + pending
    expected_revenue = sum(price("WHEAT", start + k) for k in range(4))
    expected_cost = CROPS["WHEAT"]["seed"]
    expected = (expected_revenue - expected_cost) / 4
    score, _ = crop_cycle_profit_per_day("WHEAT", 9, MARKET_I0, pending_supply=pending)
    assert score == expected
    baseline_score, _ = crop_cycle_profit_per_day("WHEAT", 9, MARKET_I0, pending_supply=0)
    assert score < baseline_score


def test_crop_cycle_profit_per_day_partial_tail_when_cycle_does_not_fit():
    """days_remaining=3: same tail shape as test_wheat_partial_tail_
    included_when_cycles_zero (2 units, occupied_days=rest+1=3) - the
    single-cycle path computes the identical number here, since the old
    function never had a completed cycle to blend against in this case
    either (cycles=0)."""
    start = MARKET_I0
    tail_revenue = sum(price("WHEAT", start + k) for k in range(2))
    expected = (tail_revenue - CROPS["WHEAT"]["seed"]) / 3
    score, used_fertilizer = crop_cycle_profit_per_day("WHEAT", 3, MARKET_I0)
    assert score == expected
    assert used_fertilizer is False


def test_crop_cycle_profit_per_day_returns_zero_when_not_even_a_partial_tail_fits():
    # days_remaining=2: rest=1 < WHEAT's first_yield_day=2 - nothing
    # reachable at all.
    score, used_fertilizer = crop_cycle_profit_per_day("WHEAT", 2, MARKET_I0)
    assert score == 0.0
    assert used_fertilizer is False


def test_score_portfolio_v2_pending_supply_aware_uses_first_yield_day_horizon():
    """crop_pending_supply_aware (T8.71): consumption is netted over the
    horizon up to THIS crop's own first harvest (CROPS[crop]["first_
    yield_day"]), not the whole days_remaining - verified against a
    direct crop_cycle_profit_per_day call fed that same hand-computed
    consumption total."""
    days_remaining = 12
    pending_crop_supply = {"WHEAT": 50}
    scores, _ = score_portfolio_v2(
        {}, days_remaining, unlocked_shops=[], current_day=0,
        crop_pending_supply_aware=True, pending_crop_supply=pending_crop_supply,
    )
    first_yield_day = CROPS["WHEAT"]["first_yield_day"]
    expected_consumption = expected_daily_consumption("WHEAT", []) * first_yield_day
    expected_score, _ = crop_cycle_profit_per_day(
        "WHEAT", days_remaining, MARKET_I0, 50, expected_consumption
    )
    assert scores["WHEAT"] == expected_score


def test_score_portfolio_v2_pending_supply_aware_defaults_to_todays_path():
    # Off by default - explicit False must match the implicit default
    # exactly (both use crop_horizon_profit_per_day, not crop_cycle_
    # profit_per_day).
    days_remaining = 9
    with_default, _ = score_portfolio_v2({}, days_remaining)
    with_explicit_false, _ = score_portfolio_v2({}, days_remaining, crop_pending_supply_aware=False)
    assert with_default["WHEAT"] == with_explicit_false["WHEAT"]
