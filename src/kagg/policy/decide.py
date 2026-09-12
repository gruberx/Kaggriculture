"""Full three-layer policy: wires strategy/tasks/market together into the
actual per-turn decision. See SPEC-policy.md and tasks/plan.md T3.5.

`params` is a required argument, not something this module loads itself -
SPEC-policy.md: params/policy.json is "loaded once at agent construction,
not per turn." Loading belongs to the caller (agent_main.py, once, at
module top level - see its own docstring on why that must happen at
top level, not lazily), never inside decide() itself, which runs every
turn.

Revision history worth knowing, not just the current state: T6.1 first
generalized the top-choice ranking to include animals
(`_top_investment_choice`), but tasks.py/market.py couldn't yet *act* on
an animal choice, so `decide()` briefly fell back to a crop-only ranking
(`_top_crop_choice`) whenever the overall top choice was an animal - a
real, measured gap, not hypothetical (a direct trace of a real "starter"
episode showed the top choice flipping to COW at day 18 once our own
MELON sales depressed its price, after which the episode planted
nothing for the rest of the season without the fallback - ~150-200
money lost per seed against the Checkpoint 5 baseline). T6.2 (the
acquisition pipeline in tasks.py) and T6.3 (BUY_ANIMAL below) closed
that gap, so `decide()` now acts on an animal top choice directly -
`_top_crop_choice` was removed once nothing called it any more (T6.3).

T6.5 closed a documented gap from T3.5: BUY_SEED/BUY_ANIMAL now both
check that there's somewhere to actually use the purchase (an empty
tile for a seed; an empty tile or an existing empty matching structure
for an animal) before spending on it - a full farm no longer
accumulates unused seeds or animals it can never place.

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

from kagg.gamelib.constants import ANIMALS, CROPS
from kagg.gamelib.farm import shed_distance
from kagg.gamelib.growth import forecast_animal_schedule, forecast_ongoing_schedule
from kagg.gamelib.shed import shed_room
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

# Real default (kaggriculture.json's shedCapacity=100) - like
# season_length_days above, this isn't exposed in the observation at
# all (only in env.configuration, which agent(obs) never receives -
# verified directly), so it's a named, tunable parameter with the real
# default baked in, not something read from obs.
_DEFAULT_SHED_CAPACITY = 100

# How much WHEAT to keep off the sell-everything arbitrage once any
# animal exists on the farm - see the wheat_reserve wiring below and
# market.sell_orders's own docstring for the real deadlock this avoids.
_WHEAT_FEED_RESERVE = 10

# T8.1: anchors new-investment tile placement to the shed rather than the
# farmer's current position - see tasks.build_task_list's own docstring
# and the `_ANCHOR_*` constants there for the full story. Default kept at
# "UNIT" (the pre-T8.1 behavior) deliberately, not "SHED": measured via
# direct self-play (pre-T8.2), SHED alone *lost* to UNIT (0.26 win rate,
# working block) due to a real interaction with the animal/crop choice
# gap _top_crop_choice documents; combined with that fix it won the
# working block (0.72) but not the held-out one (0.56, rejected by
# tuning.accept_candidate).
#
# Re-tested after T8.2 landed (distance-aware task servicing), on the
# hypothesis that SHED+plant_while_pursuing_animal was waiting on it -
# it wasn't: with T8.2 in place, SHED+plant_while_pursuing_animal=True
# *lost decisively* to plain UNIT (working 0.28, holdout 0.18 - a
# reversal, not just "still not accepted"). T8.2's distance-aware
# servicing already keeps the farmer working the nearest urgent tile
# regardless of the plot's shape, so the runaway-line placement T8.1
# targeted is far less costly once servicing order is smart - the two
# fixes overlap rather than compose. The mechanism (anchor="SHED") stays
# available as a tested, real capability for a future sweep, but there is
# now real evidence it does not pair well with T8.2, not just "unproven."
_DEFAULT_INVESTMENT_ANCHOR = "UNIT"

# T8.9 - see _top_crop_choice's own docstring for the real bug this
# fixes and why, despite that, it defaults to off. Same re-test after
# T8.2 as investment_anchor above, same reversal - see that comment.
_DEFAULT_PLANT_WHILE_PURSUING_ANIMAL = False


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


def _top_crop_choice(market_inventory: dict, current_day: int, params: dict) -> str | None:
    """Best CROP alone, ignoring animals entirely - an opt-in fallback
    (`params["plant_while_pursuing_animal"]`, default off) used
    *alongside* (not instead of) `_top_investment_choice`'s single
    overall pick, for a real gap that pick can't express (T8.9, tasks/
    plan.md): `rank_portfolio` has no notion of ownership, so an animal
    type that's already fully placed and simply producing can keep
    ranking #1 forever, exactly as if it still needed buying - and
    without this fallback, `plant_crop` is derived solely from the single
    overall top choice, so that animal silently blocks crop planting for
    the rest of the game the moment it ranks first. Directly observed:
    one representative episode spent 47 of its farmer's 719 turns on PASS
    once an animal locked in as the permanent #1 choice.

    Deliberately NOT the default, despite fixing a real, demonstrated
    defect - found by measuring, not assumed safe: enabling it (with
    placement otherwise unchanged) lost a direct 50-seed self-play block
    against the pre-fix baseline 13/50 (Wilson [0.159, 0.396], a real
    loss, not noise). The likely mechanism - not fully confirmed -
    is that the extra BUY_SEED spends cash that would otherwise go
    toward the animal purchase sooner, delaying a materially better
    investment even though the turns it fills were otherwise pure waste.
    Combined with T8.1's shed anchor, the pair *did* show a strong
    working-block win (0.72, Wilson [0.583, 0.825]) - but that did not
    survive the held-out block (0.56, Wilson [0.423, 0.689], rejected by
    `tuning.accept_candidate` against an even-odds baseline) - exactly
    the kind of gap SPEC-tuning.md's regression gate exists to catch.
    Re-tested again after T8.2 (distance-aware task servicing) landed, on
    the hypothesis that T8.2 was what the combination was waiting on -
    it wasn't: with T8.2 in place, the SHED+plant_while_pursuing_animal
    combination *lost decisively* (working 0.28, holdout 0.18) to plain
    UNIT/False - see `_DEFAULT_INVESTMENT_ANCHOR`'s own comment for the
    full story. Left here as a tested, real bug fix and a tunable the
    arena can sweep in its own right, not shipped as a silent default
    change on a working-block result alone.

    Mirrors T3.5's original `_top_crop_choice` (removed in T6.3 once
    nothing called it - see the module docstring's revision history) -
    reintroduced for a different role: not decide()'s only investment
    signal, but a second, independent one that can run alongside the
    animal pipeline instead of being pre-empted by it.
    """
    season_length_days = params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS)
    for name in rank_portfolio(market_inventory):
        if name in CROPS and _crop_has_time_to_mature(name, current_day, season_length_days):
            return name
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
    desired_crop = desired_name if desired_kind == "crop" else None
    desired_animal = desired_name if desired_kind == "animal" else None

    # T8.9, opt-in (see _top_crop_choice's own docstring for why this
    # isn't the default despite fixing a real bug): when enabled, the
    # crop to plant/buy-seed-for is the best crop the market supports
    # *regardless* of whether an animal separately ranks first overall.
    # Only re-ranks crops alone when the overall top choice is itself an
    # animal; when it's already a crop, `desired_crop` IS the best crop,
    # so there's nothing to recompute either way.
    if desired_crop is not None:
        fallback_crop = desired_crop
    elif params.get("plant_while_pursuing_animal", _DEFAULT_PLANT_WHILE_PURSUING_ANIMAL):
        fallback_crop = _top_crop_choice(obs["market"]["inventory"], current_day, params)
    else:
        fallback_crop = None
    have_seed = fallback_crop is not None and seeds.get(fallback_crop, 0) > 0
    plant_crop = fallback_crop if have_seed else None
    # Index 0 is always the farmer's own inventory (_farmer_inventory's
    # own indexing convention - hands are index 1+). PLACE/FEED's real
    # handlers consume from here, never the shed directly - see
    # tasks.build_task_list's own docstring for why both are needed.
    farmer_inventory = (private.get("inventories") or [{}])[0]

    # Real bug found while implementing T6.4: _top_investment_choice's
    # ranking can shift turn to turn as market prices move, and reacting
    # to it immediately meant repeatedly buying a *different* animal
    # before the previous one was ever placed - a direct episode trace
    # showed 21 BUY_ANIMAL orders against only 18 PLACEs, abandoning
    # several paid-for animals to rot in the shed forever (each purchase
    # a sunk $300-500 loss). Finish placing whatever's already been
    # bought - found here by scanning the shed/farmer_inventory directly,
    # not by remembering past turns (decide() stays a pure function of
    # obs+params) - before ever considering a new purchase, regardless of
    # what the current top choice ranks highest.
    stuck_animal = next(
        (a for a in ANIMALS if shed.get(a, 0) > 0 or farmer_inventory.get(a, 0) > 0), None
    )
    # One scan covers five questions at once: which animal types are
    # already placed (stuck/already-have-one logic above), whether any
    # empty tile exists at all, which structure kinds already sit empty
    # (T6.5: BUY_SEED/BUY_ANIMAL shouldn't fire with nowhere to use them -
    # a full farm just accumulates unused seeds/animals), and (T8.3) how
    # much unlocked land is free and how far the nearest free tile is
    # from the shed - should_buy_land's occupancy-aware gates.
    placed_animal_types: set[str] = set()
    free_tiles = 0
    unlocked_tiles = 0
    nearest_free_shed_distance: int | None = None
    empty_structure_kinds: set[str] = set()
    board_size = len(me["tiles"])
    for y, row in enumerate(me["tiles"]):
        for x, tile in enumerate(row):
            if tile is None:
                free_tiles += 1
                unlocked_tiles += 1
                d = shed_distance((x, y), board_size)
                if nearest_free_shed_distance is None or d < nearest_free_shed_distance:
                    nearest_free_shed_distance = d
            elif isinstance(tile, dict):
                unlocked_tiles += 1
                if "animal" in tile:
                    placed_animal_types.add(tile["animal"])
                elif tile.get("kind") in ("COOP", "PASTURE"):
                    empty_structure_kinds.add(tile["kind"])
    has_empty_tile = free_tiles > 0
    if stuck_animal is not None:
        acquisition_animal = stuck_animal
        plant_crop = None  # finish the paid-for animal before starting a new crop too
    elif desired_animal is not None and desired_animal in placed_animal_types:
        # A second real bug found the same way: even with the stuck-
        # animal fix above, decide() kept re-buying *another* instance of
        # the same top-ranked animal indefinitely - a live, well-fed,
        # already-producing COW is not "done" in _top_investment_choice's
        # eyes, so it commissioned a second one, then a third, forever.
        # Deliberate simplification, not a full fix: never pursue a
        # second instance of an animal type we already have placed and
        # alive, rather than re-ranking to find the next-best
        # alternative - correct and safe for a single farmer (which
        # can't reliably tend more than one animal's feeding anyway
        # while also farming crops); revisit once multiple hands make
        # tending more than one worthwhile.
        acquisition_animal = None
    else:
        acquisition_animal = desired_animal
    have_animal_anywhere = acquisition_animal is not None and (
        shed.get(acquisition_animal, 0) > 0 or farmer_inventory.get(acquisition_animal, 0) > 0
    )

    unit_positions = [tuple(me["farmer"])] + [tuple(h) for h in me.get("hands", [])]
    tasks = build_task_list(
        me["tiles"], unit_positions,
        plant_crop=plant_crop, desired_animal=acquisition_animal,
        shed=shed, farmer_inventory=farmer_inventory,
        current_day=current_day,
        anchor=params.get("investment_anchor", _DEFAULT_INVESTMENT_ANCHOR),
    )
    assignment = assign_units(tasks, unit_positions)

    farmer_action = action_for_unit(unit_positions[0], assignment[0])
    hand_actions = [
        action_for_unit(unit_positions[i], assignment[i])
        for i in range(1, len(unit_positions))
    ]

    # Reserve WHEAT from the sell-everything arbitrage once any animal
    # exists on the farm - see market.sell_orders's own docstring for the
    # real deadlock this avoids (found during T6.4: the arbitrage's own
    # SELL emptied the shed before a PICKUP for feeding could ever
    # complete, starving a placed COW to escape). Matches
    # tasks._WHEAT_PICKUP_BATCH's batch size, not by import (tasks.py has
    # no dependency on this module) - keep the two in sync by hand if
    # either changes.
    wheat_reserve = _WHEAT_FEED_RESERVE if placed_animal_types else 0

    market = market_orders(
        shed,
        obs["market"]["inventory"],
        obs["market"]["prices"],
        wheat_on_hand=shed.get("WHEAT", 0),
        params=params,
        max_orders=_MAX_MARKET_ORDERS,
        wheat_reserve=wheat_reserve,
    )

    # Seed/animal purchase: arrives next turn (market orders resolve
    # after this turn's unit actions) - the PLANT/PLACE task above
    # naturally starts firing once the seed/animal shows up in a future
    # observation, no extra state needed here. No longer mutually
    # exclusive as of T8.9: they used to be, "by construction," when both
    # came from `_top_investment_choice`'s single top pick - but
    # `fallback_crop` is now a genuinely independent second signal (see
    # its own docstring), so both purchases fire whenever both are
    # warranted, sharing the same 10-order cap via `len(market) <
    # _MAX_MARKET_ORDERS` on each. Both still gated on `stuck_animal is
    # None` - finish placing what's already bought (see the stuck_animal
    # comment above) before spending on anything else, seed or animal.
    # Also gated on somewhere to actually use the purchase (T6.5): a seed
    # needs an empty tile; an animal needs either an empty tile (to build
    # a fresh structure on) or an existing empty matching structure - it
    # doesn't need free land specifically, just somewhere to eventually
    # stand.
    if (
        stuck_animal is None
        and fallback_crop is not None
        and not have_seed
        and has_empty_tile
        and len(market) < _MAX_MARKET_ORDERS
    ):
        seed_cost = CROPS[fallback_crop]["seed"]
        if me["money"] >= seed_cost:
            market.append(["BUY_SEED", fallback_crop, 1])
    if (
        acquisition_animal is not None
        and not have_animal_anywhere
        and (has_empty_tile or ANIMALS[acquisition_animal]["structure"] in empty_structure_kinds)
        and len(market) < _MAX_MARKET_ORDERS
    ):
        animal_cost = ANIMALS[acquisition_animal]["cost"]
        shed_capacity = params.get("shed_capacity", _DEFAULT_SHED_CAPACITY)
        if me["money"] >= animal_cost and shed_room(shed, shed_capacity) > 0:
            market.append(["BUY_ANIMAL", acquisition_animal, 1])

    # Land purchase, per the strategic layer's tunable threshold
    # (SPEC-policy.md "1. Strategic layer") plus T8.3's occupancy gates.
    # One order per turn - if affordable for more than one quadrant at
    # once, the next turn's observation re-evaluates and queues the next
    # purchase then.
    n_unlocked_extra = len(me.get("unlocked_quadrants", ["NW"])) - 1
    if len(market) < _MAX_MARKET_ORDERS and should_buy_land(
        me["money"], n_unlocked_extra, params,
        free_tiles=free_tiles, unlocked_tiles=unlocked_tiles,
        nearest_free_shed_distance=nearest_free_shed_distance,
    ):
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
