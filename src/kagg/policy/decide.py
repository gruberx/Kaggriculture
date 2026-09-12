"""Full three-layer policy: wires strategy/tasks/market together into the
actual per-turn decision. See SPEC-policy.md and tasks/plan.md T3.5.

`params` is a required argument, not something this module loads itself -
SPEC-policy.md: params/policy.json is "loaded once at agent construction,
not per turn." Loading belongs to the caller (agent_main.py, once, at
module top level - see its own docstring on why that must happen at
top level, not lazily), never inside decide() itself, which runs every
turn.

Known gap, not an oversight: `_top_investment_choice` below already
ranks animals alongside crops (T6.1), but tasks.py/market.py can't yet
*act* on an animal choice - BUY_ANIMAL + BUILD_COOP/BUILD_PASTURE +
PLACE aren't implemented until T6.2/T6.3. `decide()` therefore falls
back to `_top_crop_choice` (the old, crop-only ranking) for the actual
PLANT/BUY_SEED decision whenever the overall top choice is an animal -
found to matter for real, not just hypothetically, while implementing
this: without the fallback, a direct trace of a real "starter" episode
showed the top choice flipping to COW at day 18 (our own MELON sales
had depressed its price below COW's), after which the episode planted
nothing for the rest of the season - a real ~150-200 money loss per
seed against the Checkpoint 5 baseline, not a contrived edge case. Once
T6.2/T6.3 land, `decide()` should be revisited to act on the animal
choice directly instead of falling back. Also not handled: a BUY_SEED
order doesn't check whether an empty tile actually exists to plant it
on - a farm with no free land could accumulate unused seeds. Smaller
and rarer than the season-maturity issue (a full farm still has *some*
replantable tile once something is harvested), left as a known
limitation (tracked as T6.5).

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

from kagg.gamelib.constants import ANIMALS, CROPS
from kagg.gamelib.growth import forecast_animal_schedule, forecast_ongoing_schedule
from kagg.policy.market import market_orders
from kagg.policy.strategy import hires_per_day, rank_portfolio, should_buy_land
from kagg.policy.tasks import action_for_unit, assign_units, build_task_list

_MAX_MARKET_ORDERS = 10

# Default season length in days (kaggriculture.json's default
# episodeSteps=720 / turnsPerDay=24 = 30). A named, tunable parameter
# rather than a bare literal since a non-default configuration would
# change it - see _crop_has_time_to_mature's own docstring for why this
# exists at all.
_DEFAULT_SEASON_LENGTH_DAYS = 30


def _crop_has_time_to_mature(crop: str, current_day: int, season_length_days: int) -> bool:
    """True if planting `crop` *today* still leaves enough season left to
    reach a useful harvest.

    Found by actually measuring T3.5's first attempt, not anticipated in
    advance: a melon planted on day 20 (first_yield_day=10, max_yield_day
    =12) needs the season to run through day 32, but the default season
    is only 30 days - so that specific plant accumulated yield_units via
    the watering-bonus window (which starts at age 6, well before
    first_yield_day) but could *never* actually be HARVESTed before the
    episode ended (the real HARVEST handler blocks on `day - planted_day
    < first_yield_day` regardless of yield_units already banked) - $80 of
    seed cost for zero return, and five real turns' final observation
    showed money completely flat while this played out.

    One-time crops need the *full* window (`max_yield_day`) to fit, not
    just first_yield_day - reaching only first_yield_day still forfeits
    the rest of the watering-bonus upside. Ongoing crops only need their
    *first* scheduled production to fit - unlike a one-time crop, an
    ongoing crop that gets even one production tick before the season
    ends has already returned something, even if later ticks are missed.
    """
    cd = CROPS[crop]
    if cd["ongoing"]:
        first_production_day = forecast_ongoing_schedule(crop, planted_day=current_day)[0]
        return first_production_day < season_length_days
    return current_day + cd["max_yield_day"] < season_length_days


def _top_crop_choice(market_inventory: dict, current_day: int, params: dict) -> str | None:
    """The highest-ranked *crop* (not animal) that still has time to
    mature this season. `None` if nothing does.

    Kept alongside the general `_top_investment_choice` below
    specifically as `decide()`'s fallback for the "top choice is an
    animal, but nothing can act on that yet" case - see the module
    docstring for the real regression this fallback avoids.
    """
    season_length_days = params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS)
    for name in rank_portfolio(market_inventory):
        if name not in CROPS:
            continue
        if _crop_has_time_to_mature(name, current_day, season_length_days):
            return name
    return None


def _animal_has_time_to_mature(animal: str, current_day: int, season_length_days: int) -> bool:
    """True if placing `animal` *today* still leaves enough season left
    for at least one production before the episode ends.

    Same reasoning as an ongoing crop's branch in
    _crop_has_time_to_mature: an animal produces indefinitely once
    placed (no max_yield cap on production count, unlike a one-time
    crop), so only its *first* scheduled production needs to fit - later
    ones missing the season end is not this animal's problem to avoid,
    the same way a late ongoing-crop tick isn't.

    forecast_animal_schedule can return an empty list (nothing scheduled
    within season_length_days at all, not just a too-late single
    production) - must not index into it blindly.
    """
    schedule = forecast_animal_schedule(animal, placed_day=current_day, horizon_days=season_length_days)
    return bool(schedule) and schedule[0] < season_length_days


def _top_investment_choice(market_inventory: dict, current_day: int, params: dict) -> tuple[str, str] | None:
    """The highest-ranked crop-or-animal that still has time to mature
    this season, as `(name, kind)` with `kind` "crop" or "animal". `None`
    if nothing does - late enough in the season, forcing a choice would
    only ever waste capital on something that can't pay off.

    Generalizes the old crop-only `_top_crop_choice` (T3.5) to rank
    animals too (T6.1) - see the module docstring for the real, temporary
    gap this opens until T6.2/T6.3 wire actual animal acquisition into
    tasks.py/market.py.
    """
    season_length_days = params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS)
    for name in rank_portfolio(market_inventory):
        if name in CROPS:
            if _crop_has_time_to_mature(name, current_day, season_length_days):
                return name, "crop"
        elif name in ANIMALS:
            if _animal_has_time_to_mature(name, current_day, season_length_days):
                return name, "animal"
    return None


def decide(obs: dict, params: dict) -> dict:
    """This turn's full action dict, combining the strategic, task, and
    market layers."""
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    seeds = private.get("seeds", {})
    shed = private.get("shed", {})

    current_day = obs.get("day", 0)
    investment = _top_investment_choice(obs["market"]["inventory"], current_day, params)
    desired_name, desired_kind = investment if investment is not None else (None, None)
    if desired_kind == "crop":
        desired_crop = desired_name
    else:
        # Top choice is an animal (or nothing at all) - only a crop is
        # actionable today (see module docstring's "Known gap"), so fall
        # back to the best crop specifically rather than planting
        # nothing - verified this fallback is load-bearing, not just
        # defensive (see module docstring for the real episode trace).
        desired_crop = _top_crop_choice(obs["market"]["inventory"], current_day, params)
    have_seed = desired_crop is not None and seeds.get(desired_crop, 0) > 0
    plant_crop = desired_crop if have_seed else None

    unit_positions = [tuple(me["farmer"])] + [tuple(h) for h in me.get("hands", [])]
    tasks = build_task_list(me["tiles"], unit_positions, plant_crop=plant_crop)
    assignment = assign_units(tasks, unit_positions)

    farmer_action = action_for_unit(unit_positions[0], assignment[0])
    hand_actions = [
        action_for_unit(unit_positions[i], assignment[i])
        for i in range(1, len(unit_positions))
    ]

    market = market_orders(
        shed,
        obs["market"]["inventory"],
        obs["market"]["prices"],
        wheat_on_hand=shed.get("WHEAT", 0),
        params=params,
        max_orders=_MAX_MARKET_ORDERS,
    )

    # Seed purchase: arrives next turn (market orders resolve after this
    # turn's unit actions) - the PLANT task above naturally starts firing
    # once the seed shows up in a future observation, no extra state
    # needed here.
    if desired_crop is not None and not have_seed and len(market) < _MAX_MARKET_ORDERS:
        seed_cost = CROPS[desired_crop]["seed"]
        if me["money"] >= seed_cost:
            market.append(["BUY_SEED", desired_crop, 1])

    # Land purchase, per the strategic layer's tunable threshold
    # (SPEC-policy.md "1. Strategic layer"). One order per turn - if
    # affordable for more than one quadrant at once, the next turn's
    # observation re-evaluates and queues the next purchase then.
    n_unlocked_extra = len(me.get("unlocked_quadrants", ["NW"])) - 1
    if len(market) < _MAX_MARKET_ORDERS and should_buy_land(me["money"], n_unlocked_extra, params):
        market.append(["BUY_LAND"])

    # Hiring: queues the remaining hires needed to reach this day's
    # target in one go - self-limiting via hires_today without needing an
    # explicit "only at hour==0" check, since hires_today only resets at
    # the next day boundary (SPEC.md's economic analysis: default 0 until
    # tuning measures the real answer, so this is a no-op by default).
    target_hires = hires_per_day(params)
    hires_today = me.get("hires_today", 0)
    while hires_today < target_hires and len(market) < _MAX_MARKET_ORDERS:
        market.append(["HIRE"])
        hires_today += 1

    return {"farmer": farmer_action, "hands": hand_actions, "market": market[:_MAX_MARKET_ORDERS]}
