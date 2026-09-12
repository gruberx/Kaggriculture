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

# T8.3d (the user's own observed defect): shed stock left unsold at the
# episode's last step scores exactly zero (confirmed directly in the
# real kaggriculture.py engine - reward is final money only, no
# auto-liquidation), so the last few days of the season switch
# market.sell_orders into `liquidate` mode - see its own docstring for
# why. Accepted at 2 via direct self-play against the same code with the
# mechanism disabled (liquidation_days_before_end=0): 50/50 on both the
# working block (seeds 100-149) and the held-out block (seeds 900-949) -
# a clean, decisive win, expected: this is close to free money the old
# code was leaving on the table. 2 days x 24 turns/day is also
# comfortably more than enough turns to drain the whole shed even with
# the drip cap lifted (shedCapacity=100 vs a >2-turn drain at 50 units/
# order), so the value has a real mechanical justification, not just a
# swept number.
#
# A real, deliberately NOT chased lead found while sweeping candidate
# values (1/2/3/5/7/10/15/30, working block only, head-to-head): win
# rate keeps climbing the larger the window gets, all the way up to
# effectively disabling the PREMIUM_GOODS drip cap for the *entire*
# season (30). That is a materially different, unreviewed change (an
# always-on anti-price-crash protection turning out not to earn its
# keep at all under current single-farmer conditions) than "liquidate
# near the end", and deserves its own dedicated investigation rather
# than smuggling it in under this task's scope - see tasks/todo.md's
# T8.3d entry.
_DEFAULT_LIQUIDATION_DAYS_BEFORE_END = 2

# T8.1: anchors new-investment tile placement to the shed rather than the
# farmer's current position - see tasks.build_task_list's own docstring
# and the `_ANCHOR_*` constants there for the full story. Default kept at
# "UNIT" (the pre-T8.1 behavior), not "SHED".
#
# T8.3b (tasks/plan.md) got the clean, unconfounded measurement this
# needed - real Kaggle games from Checkpoint 8A's submission independently
# reproduced the exact symptom SHED targets (animal structures built at
# the far end of a long worked line), which prompted re-testing it
# properly rather than trusting the prior bundled result. Findings, each
# a real direct-self-play block on top of today's code (T8.2+T8.3), not
# reasoning:
#   - SHED alone (plant_while_pursuing_animal still False) lost 0/50 on
#     BOTH blocks - worse than the original pre-T8.2 result (0.26), not
#     better. Traced directly (action-count diagnostic, not guessed):
#     SHED speeds up the animal pipeline enough that the animal reaches
#     production fast and then ranks #1 forever (the exact
#     _top_crop_choice gap below), spiking PASS from ~30-50 turns/episode
#     to 266/719 in one traced seed - SHED alone re-triggers the T8.9 bug
#     even harder than UNIT does, it doesn't avoid it.
#   - SHED + plant_while_pursuing_animal=True (i.e. with the T8.9 bug
#     actually fixed) beats the plain shipped default 0.78/0.80 - a real
#     win over doing nothing - but loses decisively to UNIT +
#     plant_while_pursuing_animal=True, 0.10 working / 0.02 holdout.
#     Traced: SHED clusters animal-related PICKUP/FEED near the shed
#     (more of them fire) but each seed checked planted and watered
#     fewer crop tiles than UNIT achieved in the same episode - a real,
#     if modest, net trade against crops, which are still the larger
#     income source at this labor level.
# Net at that point: with the real T8.9 fix in place, plain UNIT anchor
# was the *best* measured option - a clean rejection of SHED, not an
# absence of evidence. But the runaway-line placement the user observed
# was real and still present; T8.1's SHED mechanism just wasn't the fix
# that pays for itself once T8.9 is fixed properly.
#
# T8.3c (tasks/plan.md), designed together with the user in response to
# that honest gap, found the actual fix: the traced root cause was never
# "anchor to the farmer instead of the shed" per se - it was that UNIT's
# tie-break among candidates *equally* close to the farmer is row-major
# scan order (see tasks.py's `_closest_pos`), which has no relationship
# to the shed and is what drove the marching-line pattern. "UNIT_TOWARD_
# SHED" keeps distance-to-farmer as the *primary* key (identical to
# plain UNIT - never a worse detour for that reason alone) and only
# breaks ties toward `shed_distance` instead of scan order. Measured
# clean self-play against the shipped default (UNIT + plant_while_
# pursuing_animal=True): 50/50 on BOTH the working and held-out blocks -
# the single cleanest win in this whole investigation. Traced, not just
# trusted: every seed checked did strictly more WATER/PLANT/HARVEST and
# fewer PASS turns than plain UNIT in the same episode, confirming the
# structural "never a worse detour" argument translates into a real
# efficiency gain, not just a differently-shaped equally-costly walk.
# Accepted as the new default. Plain "SHED" (T8.1) stays available and
# documented above as a real, tested, but rejected alternative.
_DEFAULT_INVESTMENT_ANCHOR = "UNIT_TOWARD_SHED"

# T8.3b (tasks/plan.md): ACCEPTED as the default, correcting the earlier
# "measured to lose" conclusion, which was itself measured on stale, pre-
# T8.2/T8.3 code (0.26 working / 0.46 holdout) and never re-checked
# afterward. Real Kaggle games from Checkpoint 8A's submission
# independently reproduced the exact symptom this fixes (crop production
# stopping in the second half of the game once an animal locks in as
# _top_investment_choice's permanent #1 pick - see _top_crop_choice's own
# docstring for the mechanism). Re-measured cleanly, alone (investment_
# anchor held at "UNIT"), on top of today's code: 50/50 wins on BOTH the
# working and held-out blocks - the single cleanest accepted result in
# Phase 8 so far. Also the best of all four anchor/fallback combinations
# tested (see _DEFAULT_INVESTMENT_ANCHOR's comment above for the other
# three) - UNIT + True beat SHED + True 0.90/0.98 head-to-head.
_DEFAULT_PLANT_WHILE_PURSUING_ANIMAL = True


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
    """Best CROP alone, ignoring animals entirely - a fallback
    (`params["plant_while_pursuing_animal"]`, default **on** since
    T8.3b) used *alongside* (not instead of) `_top_investment_choice`'s
    single overall pick, for a real gap that pick can't express (T8.9,
    tasks/plan.md): `rank_portfolio` has no notion of ownership, so an
    animal type that's already fully placed and simply producing can keep
    ranking #1 forever, exactly as if it still needed buying - and
    without this fallback, `plant_crop` is derived solely from the single
    overall top choice, so that animal silently blocks crop planting for
    the rest of the game the moment it ranks first. Directly observed:
    one representative episode spent 47 of its farmer's 719 turns on PASS
    once an animal locked in as the permanent #1 choice - and a real
    Kaggle submission built on Checkpoint 8A (before this fix was
    accepted) independently reproduced the same symptom: the user
    reported crop production stopping mid-game once animals appeared.

    Accepted as the default in T8.3b (tasks/plan.md), correcting an
    earlier, real mistake - not silently overwritten, stated plainly:
    this WAS measured to lose (13/50, Wilson [0.159, 0.396]) and shipped
    off, then combined with T8.1's shed anchor it won the working block
    (0.72) but not the held-out one (0.56) - but every one of those
    measurements ran on stale, pre-T8.2/T8.3 code, and after T8.2 landed
    only the SHED+this-fallback *bundle* was ever re-tested (0.28/0.18
    loss), never this fallback in isolation. T8.3b finally ran the clean,
    unconfounded test: `plant_while_pursuing_animal=True` ALONE (anchor
    left at "UNIT") against today's code (T8.2+T8.3) won 50/50 on BOTH
    the working and held-out blocks - and separately beat the SHED-
    anchored combination head-to-head, 0.90/0.98. T8.2's much higher
    baseline throughput plausibly changes the earlier "extra BUY_SEED
    competes for cash" tradeoff enough to flip the sign, though the
    mechanism isn't independently reconfirmed, only the result. See
    `_DEFAULT_INVESTMENT_ANCHOR`'s own comment for the full four-way
    comparison and why `investment_anchor` itself stays at "UNIT" even
    though this fallback is now on.

    Mirrors T3.5's original `_top_crop_choice` (removed in T6.3 once
    nothing called it - see the module docstring's revision history) -
    reintroduced for a different role: not decide()'s only investment
    signal, but a second, independent one that runs alongside the animal
    pipeline instead of being pre-empted by it.
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

    season_length_days = params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS)
    liquidation_days_before_end = params.get(
        "liquidation_days_before_end", _DEFAULT_LIQUIDATION_DAYS_BEFORE_END
    )
    liquidate = current_day >= season_length_days - liquidation_days_before_end

    market = market_orders(
        shed,
        obs["market"]["inventory"],
        obs["market"]["prices"],
        wheat_on_hand=shed.get("WHEAT", 0),
        params=params,
        max_orders=_MAX_MARKET_ORDERS,
        wheat_reserve=wheat_reserve,
        liquidate=liquidate,
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
