"""Loads params/policy.json - see SPEC-policy.md "Parameters" and
tasks/plan.md T3.4.

Lives inside kagg.policy (a normally-imported submodule) rather than
agent_main.py itself, specifically so it has a working `__file__` to
locate its own sibling `params/` directory - agent_main.py's raw-exec
loading by kaggle_environments never has one (see agent_main.py's own
module docstring for the full explanation, and SPEC-agent.md's
correction). Resolves relative to *this* file, which sits at
`kagg/policy/params.py` in both the dev tree and the built bundle
(`build_submission.py` copies `src/kagg/` verbatim - see SPEC.md's
"Project structure" correction, found while building this very module -
so the two layouts are identical by construction, not by coincidence).

Standard library only - ships inside the submission bundle.
"""

from __future__ import annotations

import json
import os

_DEFAULT_PARAMS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "params", "policy.json"
)

# Every default used across kagg.policy's strategy/tasks/market modules,
# collected in one place so the full tunable surface is visible without
# hunting through each module. Individual functions still carry their own
# matching defaults too (belt and braces) - a partially-written params
# file, or this loader never being called at all, shouldn't behave any
# differently than a fully-populated one.
DEFAULT_PARAMS = {
    # T8.42, real-data-calibrated: T8.40's saved top-leaderboard extract
    # showed top players buy their 2nd quadrant leaving essentially zero
    # cash reserve (several team-seasons as low as $1-$88 right after the
    # purchase), decisively contradicting the $15,000 reserve this
    # project had carried since T8.8. T8.33 alone already tried lowering
    # this (0-10000) with labor left at the old min_hires_per_day=2 and
    # found it decisively lost - land bought without labor to work it
    # just sits idle. T8.42 lowered this *jointly* with min_hires_per_day
    # (below) at real-data-calibrated levels and found the joint change
    # wins decisively: 96% (n=50), 89.5% confirmed on a 200-seed holdout
    # (tools/measure_t842.py) - see kagg.policy.strategy's own
    # _DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY comment for the full story.
    "land_purchase_threshold_money": 0,
    # T8.7: raised 0 -> 1 - T7.4's own hires_per_day=0 result was invalid
    # (ran against real bugs, fixed by T8.4/T8.6), and the re-run sweep
    # flipped completely: every nonzero value tried won 96-100% direct
    # self-play against the checked-in baseline, held-out-gated at 50/50
    # for the accepted value 1 - see kagg.policy.strategy.
    # _DEFAULT_HIRES_PER_DAY's own comment for the full measured story.
    "hires_per_day": 1,
    # T8.12, the user's own observation: a flat constant can't reflect
    # how much work actually needs doing - hires_per_day() gains a
    # dynamic mode that scales the hiring target from the real task
    # backlog (turns_per_task_estimate-weighted) instead.
    # T8.12 originally measured and rejected this (2/50 working, 4/50
    # holdout - `len(tasks)` counted recurring watering the same as
    # genuine bottleneck work, over-hiring with many hands left idle).
    # T8.16(a) fixed that exact root cause (routine WATER/FEED excluded
    # from the count) - measured alone: 62%/48%, a real recovery but not
    # yet decisive. **T8.16(d) found the missing piece and ACCEPTED this
    # default**: a joint sweep (min_hires_per_day, max_hires_per_day,
    # turns_per_task_estimate, hire_buffer_fraction) found min_hires_per_
    # day=2 (not the flat constant's old value of 1) took the working
    # block from 0.62 to 0.94, and the held-out gate cleared decisively
    # (49W/1L/0T, 98%). See kagg.policy.strategy's own dynamic_hiring
    # comment (near _DEFAULT_HIRE_CASH_RESERVE) for the full traced story
    # and tools/measure_t816d.py/tools/trace_t816d.py for the sweep and
    # seed-900 confirmation.
    "dynamic_hiring": True,
    # T8.42, real-data-calibrated: T8.40's saved top-leaderboard extract
    # showed hired-hand count front-loaded from day 0 far beyond anything
    # tested before (median 4 on day 0, 8 by day 6, 10 by day 9) - T8.41
    # traced why raising labor alone (without land) doesn't help (nothing
    # extra to work), and T8.34 found a *reactive* hiring signal
    # (workload_forecast_free_tile_weight) mistimed and losing. This
    # raises the same stable floor mechanism T8.32 first tried (4) all
    # the way to the shipped max_hires_per_day ceiling (8) - a flat,
    # non-reactive target from day 0, jointly with land_purchase_
    # threshold_money=0 above. See that param's own comment for the
    # measured story.
    # 2026-09-20, the user's explicit decision (T8.46 follow-up): min=2/max=12
    # together with day_plan_hiring_aware (below) and the T8.45 purchase flags
    # replace the T8.42 flat 8/8 floor. **Measured against the previous
    # default before flipping, and worse there**: min=2 + T8.45 bundle + dump
    # scored 0.400 (20W/30L, n=50) against the old flat-8 default in self-
    # play (tools/measure_t846.py); dump alone on the old hiring scored
    # 1.000 (200W/0L holdout). The old values were min_hires_per_day=8,
    # max_hires_per_day=8, day_plan_hiring_aware=False, bulk_*=False,
    # plant_while_animal_pending=False, drip_sell_max_per_turn=5.
    "min_hires_per_day": 2,
    "max_hires_per_day": 12,
    "turns_per_task_estimate": 2.0,  # T8.16(d): swept, stayed at this value
    "hire_cash_reserve": 0,  # the user's own "protect starting capital" ask
    # T8.16, the user's own explicit ask ("небольшой запас рабочей силы
    # для компенсации всплеска потребности работы, на вскидку 5-10%") -
    # scales dynamic_hiring's raw target up before clipping to
    # [min_hires_per_day, max_hires_per_day]. T8.16(d)'s joint sweep found
    # every nonzero value tried (0.1, 0.2) hurt badly (0.02 working win
    # rate) - the day-1 floor alone was the real fix, not a buffer on top
    # of it. 0.0 (no buffer) stays the accepted value.
    "hire_buffer_fraction": 0.0,
    # T8.26, the user's own proposed formula: a proactive, tile-count-
    # derived hiring forecast (known in full at hour 0) instead of
    # dynamic_hiring's reactive pending_task_count path (which only grows
    # as the day's turns reveal more work). T8.26 itself was **measured
    # and decisively rejected** (tools/measure_t826.py, Stage 1: alone,
    # crop-only farm, vs the plain T8.16(d) baseline): 10%/0% - traced to
    # reproducing T8.12's own original rejected mistake - the ported
    # _crop_actions_per_tile_day/_animal_actions_per_tile_day count routine
    # WATER/FEED/CARE/COLLECT_FERTILIZER at their full per-day rate, but
    # pending_task_count (the reactive path) deliberately excludes the
    # routine crop-side ops (T8.16(a)'s own measured fix) - a tile needs
    # exactly one WATER/FEED per day *regardless* of labor size, so
    # counting it as scaling demand over-hires without a matching gain.
    #
    # T8.27 fixed the diagnosed cause directly (a new scaling_only=True
    # argument on both per-tile functions, always passed from this
    # forecast branch - see strategy.hires_per_day's own docstring) and
    # re-measured (tools/measure_t827.py). **Stage 1 - this flag alone,
    # against the exact shipped baseline - reversed completely: 92%/98%
    # (working/holdout), Wilson [0.812, 0.968] entirely clear of 50%,
    # accept_candidate=True. Accepted - default flipped True.** Stage 2
    # (combined with a separate, not-yet-shipped animal-economics bundle -
    # animal_care_aware/animal_fertilizer_income_aware/parallel_animal_
    # acquisition/wheat_urgency_reserve=3/max_animals_per_type raised to
    # 2-4) stayed decisively rejected (12-24%, worse than T8.25 alone).
    # Traced (tools/trace_t827.py, seed 900): hand count is nearly
    # identical between the reactive and proactive paths there (both clip
    # to min_hires_per_day=2 almost the whole episode) - ruling out gross
    # under-hiring as the cause; a genuinely open question for whoever
    # next revisits max_animals_per_type, not a defect in this flag's own,
    # separately-earned Stage-1 win (T8.3b's isolation discipline).
    #
    # **T8.28 correction to the causal story above**: "hand count is
    # nearly identical between the two paths" was true but read at the
    # time as "the two paths behave similarly", not checked for *why*. A
    # direct read-only computation found the shipped scaling_only=True
    # forecast's raw pre-clip target is 0 at every realistic farm size
    # (25 MELON + 1 COW: total_turns=8.7; 50 MELON + 3 COW: total_
    # turns=18.4 - both far under the 24-turn denominator), so it is
    # *always* clipped to min_hires_per_day=2. The accepted default is,
    # in practice, flat 2 hands/day - the tile-count scaling term this
    # comment describes never actually engages at any farm size tried.
    # Stage 1's real, honestly-measured finding is "flat 2 hands/day
    # beats the reactive backlog-scaled path (which climbed to 8)", not
    # "proactive tile-count sizing works" - and this directly explains
    # Stage 2's regression: the reactive path's own ability to climb
    # above 2 was helping in the animal-heavy bundle, and this forecast
    # removed that headroom outright. See kagg.policy.strategy's own
    # _DEFAULT_WORKLOAD_FORECAST_SCALING_ONLY comment and workload_
    # forecast_scaling_only below for the T8.28 re-sweep this finding
    # prompted. The Stage-1 win rate/Wilson interval above are unaffected
    # by this correction - only the causal explanation was wrong.
    "workload_forecast_hiring_aware": True,
    # T8.28: a read-only check found the forecast's raw pre-clip target is
    # 0 at every realistic farm size when this is True (e.g. 25 MELON + 1
    # COW: total_turns=8.7, raw_target=0), so T8.27's shipped default is,
    # in practice, flat min_hires_per_day hiring - the scaling term never
    # engages. This flag (new - T8.27 hardcoded True with no way to turn
    # it off) makes that a named, swept knob so the alternative (the
    # per-tile functions' full total, which does scale) can be measured
    # at its own turns_per_task_estimate/min/max_hires_per_day instead of
    # the ones T8.16(d) fitted to the unrelated reactive pending_task_
    # count path. See kagg.policy.strategy.hires_per_day's own docstring
    # and tools/measure_t828.py for the sweep. Default True stays
    # bit-identical to what T8.27 shipped.
    "workload_forecast_scaling_only": True,
    # T8.32 Stage 2, the user's own follow-up after Stage 1's own
    # measured-but-not-accepted joint land-gate/hiring-floor sweep (64%
    # held-out, real but short of the acceptance bar - tasks/todo.md's
    # own T8.32 entry): hires_per_day's forecast has always only counted
    # already-planted tiles, never free/unlocked-but-unplanted land, so
    # hiring never proactively ramps ahead of newly-opened land. Weights
    # free_tiles into the same forecast. Default 0.0 (bit-identical for
    # every caller that doesn't set it) - not yet measured in self-play,
    # see kagg.policy.strategy.hires_per_day's own docstring for the
    # mechanism.
    "workload_forecast_free_tile_weight": 0.0,
    # T8.44, the user's own follow-up after T8.43 Stage 3's mechanical
    # proof that workload_forecast_hiring_aware's own formula can never
    # exceed 8 hires from a realistic board (total_turns > 216 needed,
    # unreachable at any free_tile_weight tried): a burst-day-aware
    # alternative built from real per-tile-today action counts (`kagg.
    # policy.tasks.crop_tile_day_actions`/`animal_tile_day_actions`) plus
    # this turn's already-decided new planting/animal-acquisition, in
    # place of _crop_actions_per_tile_day's lifetime-averaged rate. See
    # kagg.policy.strategy.hires_per_day's own docstring for the formula.
    # Default False (bit-identical) - see tasks/todo.md's T8.44 entry for
    # the measured sweep and accept/reject verdict.
    "day_plan_hiring_aware": True,  # see min_hires_per_day above
    # Real, hand-verified per-tile action costs (this session's own
    # derivation, checked directly against kaggriculture.py): a fresh
    # crop tile costs PLANT+WATER=2 actions its first day; a fresh animal
    # costs BUILD+PICKUP+PLACE+FEED=4 (PICKUP/PLACE must be the same
    # unit - PLACE consumes the acting unit's own inventory).
    "day_plan_new_crop_tile_actions": 2.0,
    "day_plan_new_animal_actions": 4.0,
    # Caps the day-plan forecast's planned-new-crop-tiles term at one
    # quadrant (25) per day - guards against assuming the entire free
    # board gets planted in a single day.
    "day_plan_max_new_tiles_per_day": 25,
    # Additionally caps planned-new-crop-tiles by what's actually
    # affordable (seeds held + what today's money can buy) - keeps a
    # freshly-opened, still-broke quadrant from forecasting phantom work
    # it can't fund. True is the physically honest bound.
    "day_plan_new_tiles_cash_aware": True,
    # T8.44: a same-day top-up hire (e.g. a BUY_LAND settling mid-day)
    # only queues further HIRE orders this turn if at least this many
    # turns remain today, unless zero hires have happened yet today (the
    # escape hatch - never leave the farm with zero labor for a whole
    # day). Default 0 (bit-identical - the gate always passes).
    "hire_min_turns_left": 0,
    # T8.44: caps how many HIRE orders the emission loop queues in one
    # turn - load-bearing once target_hires can exceed roughly
    # _MAX_MARKET_ORDERS=10 (day_plan_hiring_aware's whole point): hires
    # is listed first in the final truncated market-order list, so an
    # uncapped burst would silently drop every BUY_SEED/BUY_ANIMAL/
    # BUY_LAND/wheat-restock order that turn. Defaults to 10, matching
    # _MAX_MARKET_ORDERS (bit-identical at today's shipped max_hires_per_
    # day=8, which never reaches this cap anyway).
    "max_hire_orders_per_turn": 10,
    # T8.44 follow-up, tried and reverted (the user's own observation
    # after reviewing a per-day trace table with real план_ход/реал_ход
    # columns, then a follow-up measurement): a quadrant-count-aware
    # turns_per_task list (real per-quadrant-count measured ratios: 1
    # quadrant 2.386, 2 quadrants 2.841, 3 quadrants 3.390) was tried and
    # decisively made every grid point worse (headline 0.360 -> 0.220,
    # two points collapsed to a flat 0.000) - the averaged-per-quadrant-
    # count ratios blended quiet steady-state days with busy expansion
    # days and over-hired on the quiet ones. See kagg.policy.strategy's
    # own comment (right above hires_per_day, the constant that used to
    # sit here) for the full measured story and the follow-up interp-
    # olation hypothesis that was also checked and refuted before ever
    # being implemented. No param here any more - hires_per_day's day_
    # plan branch uses the flat turns_per_task_estimate unconditionally.
    #
    # T8.44 follow-up (the user's own second observation from the same
    # trace review): kaggriculture.py's real DIG handler clears a WEED
    # tile straight to None - it does NOT restore a plant - so keeping a
    # weeded tile productive needs a follow-up PLANT+WATER right after
    # DIG, not just the DIG itself. When True, a WEED tile's maintenance_
    # actions_today contribution becomes 1 (DIG) + day_plan_new_crop_
    # tile_actions (the same PLANT+WATER cost a fresh tile already costs)
    # instead of just 1. Defaults True - only affects maintenance_
    # actions_today, which is itself unused unless day_plan_hiring_aware
    # is also on.
    "day_plan_weed_replant_aware": True,
    # T8.47 (default flipped to True on the user's explicit request,
    # 2026-09-20): count the PLANT+WATER follow-up of every one-time crop tile
    # whose HARVEST empties it today (for WHEAT/CARROT only on the last
    # ripening day when deferring, and only while something is worth
    # planting). Old value: False.
    "day_plan_harvest_replant_aware": True,
    "sell_margin": 0,
    # 2026-09-20, the user's explicit decision after T8.46: premium goods
    # (MELON/STRAWBERRY/MILK/WOOL) are sold in one order instead of 5 per
    # turn (the old default). Self-play vs the shipped drip-seller 200W/0L
    # (a same-market race - see tasks/todo.md T8.46); vs the external
    # golden opponents +551 (starter) / +3120 (pass) mean money over 20
    # seeds, mixed per seed.
    "drip_sell_max_per_turn": 1000,
    "wheat_restock_threshold": 5,
    "wheat_restock_qty": 10,
    # T8.25 Part 1: found to be a real, previously undiscovered bug rather
    # than a deliberately-tuned ceiling - see kagg.policy.market.buy_
    # wheat_order's own comment for the traced story (a static, never-
    # swept cap that silently blocks all feed restocking once market
    # price structurally drifts past it, every sufficiently long game).
    # **Re-swept and NOT raised**: tools/measure_t825.py's Stage 1 found
    # unconditionally raising this cap (80/150/1_000_000, all three tried,
    # identical results) is a real, decisive net LOSS for the animal_care_
    # aware-alone scenario (12%/28%) - traced directly (a single animal's
    # shed buffer already survives to episode end without any restock
    # above $40; raising the cap just buys the same already-surviving
    # buffer back at a worse price, ~$200-300/episode wasted with no
    # escape ever actually at risk there). wheat_urgency_reserve below is
    # the real, working fix - a targeted override, not a blanket raise.
    # Stays at 40, unchanged.
    "wheat_max_buy_price": 40,
    # T8.25 Part 2: 0 disables the override below (see buy_wheat_order's
    # own comment). **Measured, real, working - but kept off by default**:
    # tools/measure_t825b.py found wheat_urgency_reserve=3 alone (cap left
    # at 40) bit-identical in practice to Part 1's blanket raise (the
    # restock-threshold gate means on-hand stock is already at or below
    # the reserve by the time a restock is attempted post-$40) - it closes
    # T8.22's own max_animals_per_type rejection substantially (cap=3:
    # 14%/14% -> 40%/44%) and directly confirmed via seed-900 trace
    # (tools/trace_t825.py): 5/5 animals now survive the full season vs
    # 0/5 before, final money +11.5% on that seed. But it does NOT reverse
    # T8.22's rejection in aggregate, and - like Part 1 - is a net loss at
    # today's shipped max_animals_per_type=1 (the same single-animal
    # buffer-already-survives effect). Kept available (tested) for a
    # future combination once max_animals_per_type itself is revisited.
    # 2026-09-20, enabled as a *required companion* to the user's decision to move the
    # defaults to day-plan min=2/max=12 + T8.45 flags + dump (tasks/todo.md T8.46): under
    # the new defaults the T8.38 golden escape guardrail failed (starter/seed 2, day 28,
    # a COW). Traced: from day 25 WHEAT trades at 48-50, above wheat_max_buy_price=40,
    # so buy_wheat_order silently refuses to restock, the shed's last WHEAT runs out and
    # the COW goes unfed two days in a row. This override (below) is exactly the T8.25
    # Part 2 fix for that; with it all six golden pairs have zero escapes for -0.7% mean
    # money. wheat_max_buy_price=70 gave the identical result; the targeted override was
    # chosen over a blanket cap raise.
    "wheat_urgency_reserve": 3,
    # T8.1: "SHED" (shed-anchored placement) is implemented and tested,
    # but T8.3b's clean, isolated re-measurement (on top of T8.2+T8.3)
    # found it a real net loss even combined with the fallback below.
    # T8.3c found the actual fix instead: "UNIT_TOWARD_SHED" keeps
    # distance-to-farmer as the primary key (never a worse detour than
    # plain UNIT) and only breaks ties toward the shed - accepted after
    # winning 50/50 on both self-play blocks - see kagg.policy.decide's
    # _DEFAULT_INVESTMENT_ANCHOR comment for the full story.
    "investment_anchor": "UNIT_TOWARD_SHED",
    # T8.9: fixes a real bug (an animal ranking #1 forever can otherwise
    # block crop planting for the rest of the game). Accepted as the
    # default in T8.3b after a clean, isolated re-measurement on top of
    # T8.2+T8.3 (50/50 on both self-play blocks) - the earlier "measured
    # to lose" result was itself stale, pre-T8.2/T8.3 - see
    # kagg.policy.decide._top_crop_choice's docstring for the full story.
    "plant_while_pursuing_animal": True,
    # T8.3: occupancy-aware land-purchase gate. Accepted 1.0 -> 0.25 via
    # direct self-play immediately after the mechanism landed - see
    # kagg.policy.strategy.should_buy_land's own docstring for the
    # mechanism and tasks/todo.md's T8.3 entry for the full story.
    # **T8.8 re-swept once hires_per_day=1 (T8.7) landed, and the result
    # went the opposite direction the plan's own hypothesis expected**:
    # even *stricter* (0.25 -> 0.1) decisively beat 0.25, held-out-gated
    # (0.84, Wilson [0.715, 0.917]) - every looser value tried (0.4, 0.6,
    # 0.8, 1.0) lost outright. Two units still can't profitably use even
    # one 25-tile quadrant; land now competes with T8.6's larger seed/
    # animal spend for the same cash on top of T8.3's original finding.
    # See kagg.policy.strategy's own _DEFAULT_LAND_BUY_MAX_FREE_TILE_
    # FRACTION comment for the full measured story.
    "land_buy_max_free_tile_fraction": 0.1,
    # No evidence yet this second gate is needed once the fraction gate
    # above already prevents nearly all land purchases - stays disabled.
    "land_buy_min_frontier_distance": 99,
    # T8.3d: the user's own observed defect - unsold shed stock scores
    # zero at episode end (confirmed directly in the real
    # kaggriculture.py engine: reward is final money only, no
    # auto-liquidation), so the last `liquidation_days_before_end` days
    # of the season lift market.sell_orders's margin check and premium-
    # goods drip cap entirely. Accepted at 2 via direct self-play (2 vs
    # the mechanism disabled/0): 50/50 on both the working and held-out
    # blocks - see kagg.policy.decide's _DEFAULT_LIQUIDATION_DAYS_BEFORE_END
    # comment for the full story, including a real, deliberately NOT
    # chased lead: a follow-up sweep found win rate keeps climbing all
    # the way up to disabling the drip cap for the *entire* season, which
    # would be a materially different, unreviewed change (removing an
    # anti-price-crash protection outright, not just liquidating near the
    # end) - out of scope for this task, flagged in tasks/todo.md for a
    # dedicated follow-up.
    "liquidation_days_before_end": 2,
    # T8.3e: the user's own observed defect - FERTILIZER was only ever
    # collected and sold, never applied via the real FERTILIZE action
    # (a real yield-doubling lever). Built and tested, but **rejected as
    # the default** after direct self-play measurement, mirroring the
    # SHED anchor's own history - a real, decisive loss at both priority
    # tiers tried (0 wins across every differing episode in either self-
    # play block, either tier), traced to FERTILIZE and
    # COLLECT_FERTILIZER sharing the same PRIORITY_MAINTENANCE tier: a
    # second consumer of the farmer's scarce lowest-priority turns
    # directly reduces COLLECT_FERTILIZER's own throughput - a real
    # single-farmer capacity limit, not a tunable-away default. See
    # kagg.policy.decide's _DEFAULT_USE_FERTILIZER comment for the full
    # story. Kept available (like "SHED") for a future re-check once a
    # second unit (T8.6/T8.7) gives real spare capacity.
    "use_fertilizer": False,
    # T8.3f: the user's own observation - a crop's revenue score now
    # prices in the farm's *existing* commitment to that same crop (many
    # tiles already growing MELON crash even the next tile's own price),
    # not just a single hypothetical tile's negligible self-impact alone.
    # Accepted: 50/50 on both self-play blocks against the mechanism
    # disabled, traced to real crop diversification (switching off MELON
    # once already heavily planted, instead of crashing its own price
    # further) - see kagg.policy.decide's
    # _DEFAULT_CROP_SELF_IMPACT_AWARE comment for the full story and
    # kagg.policy.strategy.rank_portfolio's own docstring for the
    # mechanism.
    "crop_self_impact_aware": True,
    # T8.3g/T8.3h: extends T8.3f to also count the opponent's already-
    # planted tiles (obs["farms"] is shared, fully visible - see
    # kagg.policy.decide._combined_crop_tile_counts's own docstring), at
    # this fraction of the weight our own tiles get (always 1.0). Every
    # nonzero weight tried (0.1/0.25/0.5/0.75/1.0) lost or at best tied
    # 0.0 in direct self-play - graduating the weight softens the loss
    # but doesn't rescue the mechanism, since the real flaw is missing
    # timing information about the opponent's tiles, not merely the size
    # of the discount. See kagg.policy.decide's
    # _DEFAULT_CROP_SELF_IMPACT_OPPONENT_WEIGHT comment for the full
    # measured story across every weight tried.
    "crop_self_impact_opponent_weight": 0.0,
    # T8.3i: the user's own follow-up question - elevated town-shop
    # demand (e.g. YARN_STORE for WOOL, PET_CAFE for CARROT) was
    # previously only reflected *reactively*, once the price had already
    # moved (obs["town"]["unlocked_shops"] was never read at all before
    # this). Accepted: a strong, decisive win (49/50 working block, 48/50
    # held-out block) - see kagg.policy.decide's
    # _DEFAULT_CROP_SHOP_DEMAND_AWARE comment for the full measured story.
    "crop_shop_demand_aware": True,
    # T8.3k: the user's own observation - time is a scarce, hard-capped
    # resource in this game, so profitability should be net profit per
    # day spent, not gross revenue per day spent. A crop's seed cost was
    # never subtracted anywhere in the ranking before this, only used
    # separately as an affordability check unrelated to whether the
    # purchase is worth it. Accepted: unlike other T8.3-series flags,
    # this one only changes outcomes in a narrow crossover window (most
    # games tie exactly), but among the games it does decide the edge is
    # real and reproducible (18W/2L working, 21W/4L held-out) - see
    # kagg.policy.decide's _DEFAULT_CROP_NET_OF_SEED_COST comment for the
    # full measured story.
    "crop_net_of_seed_cost": True,
    # T8.3l: the user's own observed defect - "our agent looks like it
    # constantly buys and sells 10 WHEAT". Confirmed, traced to a real
    # two-rule conflict (buy_wheat_order restocks on shed WHEAT alone;
    # sell_orders sells everything above a reserve that's 0 until an
    # animal is placed) - 147 buy/sell pairs in one traced episode with
    # no animal ever involved. Only restock feed when an animal is
    # placed or currently the top investment choice. Accepted: a real,
    # decisive win against the actual previously-committed code (49/50
    # working block, 47/50 held-out) - a first self-play measurement via
    # params-flag toggling suggested only a near-$0 gain, but that
    # measurement was itself invalid (the toggle didn't isolate the fix
    # cleanly) and is corrected in place, not left standing - see
    # kagg.policy.decide's _DEFAULT_WHEAT_BUY_ONLY_WHEN_FEED_NEEDED
    # comment for the full story.
    "wheat_buy_only_when_feed_needed": True,
    # T8.36: still off (False) until measured and accepted - see
    # kagg.policy.decide's _DEFAULT_WHEAT_RESTOCK_COUNTS_CARRIED_INVENTORY
    # comment for the traced defect this targets (a daily buy/sell churn
    # spotted directly in tools/daily_dashboard.py's price columns).
    "wheat_restock_counts_carried_inventory": False,
    # T8.3l, found while tracing the same defect: sell_orders was also
    # keeping wheat_reserve off the table during end-of-season
    # liquidation (T8.3d), stranding ~10 WHEAT unsold once an animal had
    # been placed - dead weight per T8.3d's own finding that anything
    # unsold at episode end scores exactly zero. See kagg.policy.decide's
    # _DEFAULT_LIQUIDATE_WHEAT_RESERVE comment for the full story.
    "liquidate_wheat_reserve": True,
    # T8.3m: rank_portfolio had no notion of the current day or the
    # remaining season - an ongoing crop (TOMATO/STRAWBERRY) could be
    # scored at its full multi-production lifetime revenue even on the
    # last few days of the season, when only one production (or none)
    # will actually happen. Gates whether the crop side truncates its
    # scored schedule to what remains - see
    # kagg.policy.decide._DEFAULT_RANK_SEASON_AWARE and
    # kagg.policy.strategy._crop_yield_and_tile_days's own docstrings for
    # the mechanism. **Measured and rejected**: 1/44 working, 2/47
    # held-out against the checked-in baseline - a real, decisive loss
    # traced to a pre-existing single-farmer capacity limit (the same
    # class of defect as T8.3e's FERTILIZE rejection), not a wiring bug -
    # see kagg.policy.decide's own comment for the full traced story.
    # Kept available for a future re-check once Stage B (hired hands)
    # relieves that congestion.
    "rank_season_aware": False,
    # T8.3m, the animal-side twin: nets ANIMALS[animal]["cost"] and the
    # recurring WHEAT feed cost out of an animal's score over the
    # remaining season, instead of scoring an unbounded steady-state
    # rate - see kagg.policy.decide._DEFAULT_ANIMAL_NET_OF_COST and
    # kagg.policy.strategy.animal_revenue_per_tile_day's own docstrings.
    # Independently gated from rank_season_aware for a clean, isolated
    # measurement of each mechanism before any bundled test - a real
    # methodological precaution, not a formality: rank_season_aware
    # measured a decisive loss alone (see above) while this measured the
    # strongest win of the whole T8.3-series investigation so far (50/50
    # working, 49/50 held-out) - bundling them would have hidden that
    # split result entirely. Accepted as the default.
    "animal_net_of_cost": True,
    # T8.3q: every placed animal sets fertilizer_available=True at the
    # end of every day it survives, regardless of feeding/care - a real,
    # always-on revenue stream (~$2,819 over 30 days for a COW,
    # recomputed directly) T8.3m's net-of-cost model never counted.
    # **Measured and rejected**: 0/50 on both self-play blocks against
    # the checked-in baseline - traced to the exact promised revenue
    # never being collected (COLLECT_FERTILIZER sits at the lowest task
    # priority and the single farmer has no spare turns for it once
    # pursuing an animal on top of its crop work) - the same class of
    # defect as use_fertilizer's own rejection. See
    # kagg.policy.decide._DEFAULT_ANIMAL_FERTILIZER_INCOME_AWARE for the
    # full traced story. Kept available for a re-check once Stage B
    # (hired hands) gives real spare labor.
    "animal_fertilizer_income_aware": False,
    # T8.3q Part 2: CARE (kaggriculture.py's "Animal Care" mechanic) banks
    # a yield bonus paid out on the animal's next scheduled production -
    # a real, previously completely unbuilt lever (recomputed directly:
    # nearly doubles-to-quadruples an animal's raw product yield over a
    # 30-day season). Gates both the new CARE task
    # (kagg.policy.tasks.build_task_list's care_aware) and the matching
    # ranking term (kagg.policy.strategy.animal_revenue_per_tile_day's
    # care_aware) with one flag.
    # **Measured and rejected**: 0/50 on both self-play blocks, matching
    # Part 1's fertilizer-income result exactly - traced to zero real
    # CARE actions ever firing (same MAINTENANCE-tier single-farmer
    # capacity wall). See kagg.policy.decide._DEFAULT_ANIMAL_CARE_AWARE
    # for the full traced story. Kept available for a re-check once
    # Stage B (hired hands) gives real spare labor.
    "animal_care_aware": False,
    # T8.10, the user's own observation: rank_portfolio's animal side only
    # ever estimated town/shop consumption over one production interval
    # (1-3 days), a real, asymmetric gap against the crop side's own
    # full-tile-occupancy horizon (T8.3f/T8.3i). Traced on seed 100's real
    # shop draw: COW's modeled net rate roughly doubled ($46.5 -> $94.4
    # per tile-day at days_remaining=28) once each scheduled unit is
    # priced at its own production day's drained market level instead of
    # one flat offset.
    # **Measured and rejected**: 1/50 working, 0/50 held-out - traced to
    # a real mechanism, not noise: bringing COW's score close enough to
    # STRAWBERRY's lets a 2-turn intraday market wobble flip
    # _top_investment_choice's pick, and with no hysteresis on that
    # single-turn pick, one flip is enough to commit real capital
    # (BUY_ANIMAL) that the existing stuck_animal logic then correctly,
    # but wastefully, finishes acquiring - diverting real farmer turns
    # from the crop the ranking reverted back to one turn later. See
    # kagg.policy.decide._DEFAULT_ANIMAL_CONSUMPTION_HORIZON_AWARE for
    # the full traced story and the concrete follow-up lead (a lead
    # margin/turn-count gate on investment commitment) it exposes. Kept
    # available (tested, off by default) for that future fix.
    "animal_consumption_horizon_aware": False,
    # T8.14: exactly the follow-up lead named above - a minimum score
    # margin an animal candidate must clear over the best crop before
    # _top_investment_choice will return it, protecting against a
    # razor-thin, single-turn lead flipping on ordinary market movement.
    # Default 0.0 (no margin, exact pre-T8.14 behavior). Not yet measured
    # in self-play - see kagg.policy.decide's own comment for the
    # mechanism.
    "investment_commit_margin": 0.0,
    # T8.31, the user's own follow-up after T8.29: Stage 0 measured that
    # loosening investment_commit_margin cannot make an animal win
    # _top_investment_choice's single strict top-pick ranking (even
    # margin=-0.5 produced zero behavioral change across 400 self-play
    # games - the real score gap to a strong crop like MELON is far too
    # wide). This decouples animal acquisition from that ranking
    # entirely instead: when set and the farm has no animal anywhere in
    # any form, the single best-scoring animal (scored on its own, never
    # compared against the crop ranking) is pursued in parallel with
    # whatever crop the normal ranking already picked. **Measured and
    # accepted**: working 94% (47W/3L/0T), holdout 96% (48W/2L/0T),
    # Wilson [0.865, 0.989] - a decisive win, stronger than predicted.
    # Traced (seed 900): the candidate acquires a COW by day 1 and holds
    # it the whole game (zero animals on the baseline throughout), final
    # money slightly higher (37023 vs 36814) even with the 2nd quadrant
    # opening one day later - see kagg.policy.decide's own comment for
    # the mechanism.
    "always_pursue_one_animal": True,
    # T8.43, the user's own observation, confirmed as a real mechanism
    # gap: always_pursue_one_animal's own gate was a one-shot trigger -
    # it permanently disables itself the instant *any* animal exists
    # anywhere, of any type, which is the actual reason max_animals_per_
    # type has never once bound in any measurement this project has run
    # (T8.41 traced animals_total stuck at exactly 1 regardless of the
    # cap's value). Generalizes "at least one, ever" to a count: the
    # mechanism keeps firing until this many placed animals exist,
    # excluding types already at max_animals_per_type's own cap from the
    # ranking (so it diversifies across types rather than re-buying the
    # same one).
    #
    # **Measured a strong win rate, then REJECTED on a stricter guardrail,
    # not on win rate** (tools/measure_t843_stage2.py/trace_t843_stage2.py):
    # target_count=3 (all three animal types, cap left at its shipped 1)
    # won decisively on self-play - working 86% (43W/7L/0T), holdout 83.5%
    # (167W/33L/0T), Wilson [0.777, 0.880] - and traced cleanly (reaches
    # GOOSE+SHEEP+COW by day 3 in every traced seed, wins on final money in
    # all 5). But `test_no_animal_escapes_across_the_golden_seeds` (T8.38's
    # own never-re-recordable guardrail) then found **30 real animal
    # escapes across the 6 golden seeds** at target_count=3 (zero at
    # target_count=1) - per that guardrail's own explicit rule, an escape
    # is disqualifying regardless of win rate, so this was reverted despite
    # the strong measured number. Root cause, verified structurally in
    # code, not just inferred from the count: `decide._WHEAT_FEED_RESERVE`
    # (10) and `wheat_restock_threshold`/`wheat_restock_qty` (5/10) are all
    # flat constants, sized for "at most 1 animal" (the only case that ever
    # existed before this task) - three animals with different feed
    # schedules (GOOSE interval=1, SHEEP interval=3, COW interval=2)
    # roughly triple simultaneous feed demand with no matching scale-up,
    # causing recurring `consecutive_unfed>=2` escapes, especially before
    # hiring ramps up early game. Kept available (tested, target_count=1 -
    # bit-identical to every pre-T8.43 caller) for a future revisit once
    # the feed-supply chain itself scales with animal count (a concrete,
    # named next step, not built here - see kagg.policy.decide._DEFAULT_
    # ALWAYS_PURSUE_ANIMAL_TARGET_COUNT for the full mechanism and numbers).
    "always_pursue_animal_target_count": 1,
    # T8.11, the user's own observation, traced to a real bottleneck: the
    # real WATER handler only adds yield for a one-time crop on ages
    # inside its bonus window - every other day's watering is pure
    # anti-weed insurance. Traced on seed 100: 20 MELON tiles at age 0
    # burned ~140 farmer turns on out-of-window watering over days 3-10
    # while 4 free tiles and 2 seeds in hand sat unplanted the whole time.
    # **Measured and rejected**: 7/50 working, 3/50 holdout, 0 ties either
    # block - traced (seed 900) to a real, self-inflicted weed-conversion
    # cost: PLANT count did rise (42 -> 48) but WEED count at episode end
    # more than tripled (4 -> 13), net money down. Demoting a non-urgent
    # WATER all the way to PRIORITY_MAINTENANCE (tied with DIG, below
    # PLANT) conflates "not yield-productive today" with "not needed
    # today" - the anti-weed rule only cares about consecutive misses,
    # not the bonus window. See kagg.policy.decide._DEFAULT_WATER_BONUS_
    # WINDOW_AWARE for the full traced story and the concrete follow-up
    # lead it exposes (a middle priority tier, not all the way to
    # MAINTENANCE). Kept available (tested, off by default) for that
    # future revision.
    "water_bonus_window_aware": False,
    # T8.18: PICKUP has no structural prerequisite (verified directly
    # against kaggriculture.py) - only PLACE needs both an animal in hand
    # and a matching built structure. Off by default reproduces the
    # exact prior serial BUILD -> PICKUP -> PLACE pipeline; see
    # kagg.policy.decide._DEFAULT_PARALLEL_ANIMAL_ACQUISITION for the
    # mechanism and kagg.policy.tasks._new_investment_tasks for the fix.
    "parallel_animal_acquisition": False,
    # T8.39, the user's own concern: only the farmer can FEED an animal
    # or PICKUP its wheat (tasks._PINNED_UNIT_INDEX), so a busy farmer
    # leaves a needy animal unfed even with a free hand standing right
    # next to it, even though the real FEED/PICKUP handlers never check
    # which unit acts. Off by default reproduces the exact prior
    # farmer-only pipeline; see kagg.policy.decide._DEFAULT_FEED_PICKUP_
    # UNPINNED for the mechanism and kagg.policy.tasks.build_task_list's
    # own docstring for why the WHEAT scan specifically needs this gate
    # (a real found coupling with HARVEST, not just a style choice).
    "feed_pickup_unpinned": False,
    # T8.41, the user's own follow-up to feed_pickup_unpinned: the animal
    # PICKUP is the one remaining action still pinned only to the farmer
    # (tasks._PINNED_UNIT_INDEX). Off by default reproduces the exact
    # prior farmer-only pickup; see kagg.policy.decide._DEFAULT_ANIMAL_
    # PICKUP_UNPINNED for the mechanism.
    "animal_pickup_unpinned": False,
    # T8.41, the user's own observation: once bought, an animal's setup
    # (BUILD_COOP/BUILD_PASTURE/PICKUP/PLACE) is emitted at the same
    # priority tier as ordinary crop planting and gets starved of free
    # units whenever prevent-loss/harvest/routine-care work already
    # claimed them all - the expected case on a busy farm, not an edge
    # case. Off by default reproduces the exact prior tier; see
    # kagg.policy.decide._DEFAULT_PRIORITIZE_ANIMAL_SETUP for the
    # mechanism and kagg.policy.tasks.PRIORITY_ANIMAL_SETUP for why it
    # still yields to PREVENT_LOSS.
    "prioritize_animal_setup": False,
    # T8.43, the user's own observation, confirmed as a real ranking/
    # task-layer inconsistency: strategy._crop_yield_and_tile_days
    # already scores a one-time crop assuming its full watering_bonus_
    # window is watered before harvest, but tasks._is_actually_
    # harvestable has always proposed HARVEST the instant it's legally
    # harvestable, forfeiting that assumed bonus yield entirely for
    # WHEAT/CARROT (zero bonus days ever realized). Scoped to crops whose
    # window starts at/after first_yield_day (WHEAT/CARROT, not MELON -
    # see kagg.policy.tasks._is_actually_harvestable's own docstring for
    # why an unscoped first attempt was rejected).
    #
    # **Measured (tools/measure_t843.py): 0.300 win rate (15W/12L/23T,
    # n=50) - not a clearing accept_candidate result on its own (mostly
    # ties, since WHEAT/CARROT are rarely top-ranked under current play -
    # the mechanism doesn't even activate in most games), but 15W/12L
    # (0.556) where it does activate, and bit-identical (a tie) whenever
    # it doesn't. Enabled by the user's own explicit decision, 2026-09-19:
    # "Включи вторую версию 1 этапа по умолчанию. Она не ухудшает
    # ситуацию, но потенциально может улучшить если использовать эти
    # культуры" - a deliberate call to ship a no-worse/possibly-better
    # mechanism ahead of a full n=200 holdout confirmation, not a project-
    # default acceptance verdict.** See kagg.policy.decide._DEFAULT_DEFER_
    # ONE_TIME_HARVEST_TO_MAX_YIELD and kagg.policy.tasks._is_actually_
    # harvestable for the mechanism.
    "defer_one_time_harvest_to_max_yield": True,
    # T8.19, the user's own observation: committing every new tile to a
    # single top-ranked product invites a double price-crash risk (our
    # own volume plus a plausible independent opponent bet on the same
    # good). 1 (the single top pick) reproduces the exact prior behavior
    # for every caller that doesn't set it - see kagg.policy.decide's
    # _top_crop_basket for the mechanism.
    # **Measured and rejected**: 2 -> 10%/8% (working/holdout), 3 ->
    # 6%/6% - both decisive, consistent losses, not noise
    # (tools/measure_t819.py). The predicted tradeoff resolved against
    # the hedge: spreading tiles into a worse-ranked crop (e.g.
    # STRAWBERRY's $21.6/tile-day vs MELON's $109 - SPEC.md's own
    # profitability table) pays a real, large per-tile cost every
    # episode, while the double-price-crash scenario it hedges against
    # apparently doesn't materialize often enough in these seeds/this
    # opponent to pay for it. crop_self_impact_aware (already on by
    # default) already provides *some* real protection reactively - see
    # T8.19's own plan section - so a proactive basket may simply be
    # redundant with that, not a distinct win. Kept available (tested,
    # off by default) in case a future opponent/seed mix changes this.
    "portfolio_basket_size": 1,
    # T8.22, the user's own request once corrected unit economics showed
    # animals can be competitive (tools/analyze_unit_economics.py: a
    # fully-cared animal beats every crop on raw $/tile-day at N=1, and
    # still beats even contested MELON at realistic end-game shop-
    # consumption scale): BUY_ANIMAL has no same-type limit in the real
    # game (verified directly against kaggriculture.py, only shed_
    # capacity/money gate it) - the prior "never pursue a second instance
    # of an already-placed animal type" rule was entirely this module's
    # own simplification. 1 reproduces that exact prior behavior for
    # every caller that doesn't set it - see kagg.policy.decide's
    # placed_animal_type_counts gate for the mechanism. Deliberately a
    # simple swept scalar, not a labor-derived formula - matches
    # hires_per_day/min_hires_per_day's own precedent.
    "max_animals_per_type": 1,
    # T8.24, the user's own follow-up: once real animal-feed demand
    # exists, growing WHEAT domestically instead of always buying it
    # (kagg.policy.market.buy_wheat_order) avoids a real, previously
    # unpriced BUY-side price - see kagg.policy.strategy.wheat_feed_
    # credit_per_tile_day for the make-vs-buy mechanism. Off by default -
    # the exact prior WHEAT ranking for every caller that doesn't set it.
    "wheat_self_sufficiency_aware": False,
    # T8.6 (tasks/plan.md): parallel planting + batched seed purchase -
    # lets plant_qty scale with the real labor force (1 + hires_per_day)
    # instead of the fixed "one PLANT task per turn" baked in since
    # Phase 3. Chosen so labor_units=1 (today's shipped hires_per_day=0)
    # reproduces exactly today's behavior bit-identically (confirmed -
    # golden table unchanged). See kagg.policy.decide's own plant_qty
    # comment for the exact formula. None of these four are tuned yet -
    # T8.7 sweeps hires_per_day itself; these stay at their
    # geometry-derived, behavior-preserving defaults until then.
    "max_plants_per_unit": 100,  # the board size - cannot bind at labor_units=1
    "max_plant_tasks_per_turn": 8,
    "seed_buffer_per_unit": 1,
    "seed_cash_reserve": 0,
    # T8.45 (the user's own request, after a per-hour day-0 trace showed 21
    # of 24 planned tiles planted despite 33 idle unit-turns): see
    # kagg.policy.decide._DEFAULT_BULK_SEED_PURCHASE's own comment. All
    # default off/bit-identical - measured in tools/measure_t845.py.
    "bulk_seed_purchase": True,  # T8.45 flags on by the user's decision, 2026-09-20
    "bulk_seed_buffer_fraction": 0.10,
    "bulk_animal_purchase": True,
    "bulk_animal_buffer_fraction": 0.0,
    "bulk_purchase_max_new_tiles": 25,
    "plant_while_animal_pending": True,
    # T8.46: two-step "sell everything, buy seeds on the real new prices" -
    # see kagg.policy.decide._DEFAULT_DEFER_SEED_PURCHASE_ON_CROP_SALE. 0 = off.
    "defer_seed_purchase_on_crop_sale": 0,
    # T8.48: no BUY_SEED while >= this many HARVEST (resp. WATER above PLANT's
    # tier) tasks are still queued - they outrank PLANT, so the seeds would sit
    # idle and lock cash. None = off.
    "seed_purchase_max_pending_harvest": None,
    "seed_purchase_max_pending_water": None,
}


def load_params(path: str | None = None) -> dict:
    """Load params/policy.json, merged onto a copy of DEFAULT_PARAMS (a
    partial file only needs to override what it changes).

    Never raises: a missing file, invalid JSON, or a non-dict top level
    all fall back to plain DEFAULT_PARAMS untouched. This is a
    construction-time concern, not a per-turn one, so it is not covered
    by agent()'s own try/except (SPEC-agent.md "Fault tolerance") - a
    broken params file must not be able to crash agent construction
    itself, which is this module's entire reason to exist separately
    from a bare `json.load`.
    """
    path = path or _DEFAULT_PARAMS_PATH
    merged = dict(DEFAULT_PARAMS)
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except (OSError, ValueError):
        # ValueError covers json.JSONDecodeError (a ValueError subclass)
        # without importing json.JSONDecodeError by name.
        return merged
    if isinstance(loaded, dict):
        merged.update(loaded)
    return merged
