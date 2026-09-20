"""Golden-episode regression fixture - see SPEC.md testing strategy
(layer 2) and tasks/plan.md T2.4.

Records exact final-money outcomes against deterministic opponents on
fixed seeds. Any future change to agent/policy that moves these numbers
needs a deliberate re-record (re-run and update _GOLDEN below), not a
silent pass - that's the entire point of a golden test.

Re-recorded for T3.5 (full three-layer policy replacing the Phase 0 wheat
loop) - see that commit for the full story: the first T3.5 measurement
showed all three seeds converging to an *identical* 4998.0 regardless of
seed or opponent, traced to a real bug (a melon planted too late in the
season to ever reach harvest eligibility - fixed via
decide._crop_has_time_to_mature()), not accepted as-is. These are the
numbers *after* that fix, and now beat "starter" for the first time
(T2.4's wheat-loop numbers lost to it: 3387-3391 vs 3506-3748).

Re-recorded again for T6.3 (BUY_ANIMAL wired in) - a much bigger story
than a simple re-baseline: adding animal investment exposed a real,
previously-latent bug in tasks.py's HARVEST-task logic
(kaggriculture.py's _new_plant() sets a one-time crop's yield_units to 1
*immediately* at planting, before it's actually harvestable - a
freshly-planted crop's doomed-to-fail HARVEST attempt outranked
PLANT/BUILD_*/PLACE's priority, so the single farmer got stuck
perpetually re-attempting it for the crop's entire maturation period).
Harmless before T6.2 (nothing else productive to do with that time
anyway); costly once BUILD_PASTURE became available and had to wait on
it (measured: 5274 -> 3932, a ~1342 regression). Fixed in
tasks._is_actually_harvestable() - and the fix alone (independent of
animals) unlocked a much larger, genuine improvement, since the farmer
was losing productive time on *every* one-time-crop planting all game,
not just the one that happened to coincide with an animal purchase.

Re-recorded a third time for T6.4 (real-episode integration): the T6.3
numbers above turned out to reflect a policy that could never actually
produce anything from an animal at all. Direct inspection of a real
episode found PLACE's real handler consumes the animal from the acting
unit's *own inventory*, never the shed BUY_ANIMAL delivers to - every
placed animal just sat un-placeable (or, once a PICKUP step was added,
placed but then starved: FEED has the identical inventory-vs-shed gap
for WHEAT, and the wheat buy/sell arbitrage's own SELL order emptied
the shed before a PICKUP for feeding could ever complete). Fixed with a
PICKUP task (tasks.py), a WHEAT sell-reservation once any animal exists
(market.py), and two "don't keep re-buying" guards in decide.py (finish
a stuck, already-bought animal before starting anything new; never buy
a second instance of an animal type already placed and alive - a real
episode trace found 21 BUY_ANIMAL orders against only 18 PLACEs before
these fixes). All three fixes together, not any one
alone, were needed before every seed showed a genuine improvement over
T6.3 (e.g. pass/seed1: 5510 -> 8078).

Re-recorded a fourth time for T7.4 (Stage 1's first real accepted
parameter change, not a bug fix this time): land_purchase_threshold_money
raised 5000 -> 10000. Found via a real, previously unnoticed
methodological pitfall in tuning's own opponent-panel design - blending
win rate across starter/random (both near a 100% win-rate ceiling
against basically any reasonable policy) with self-play against the
checked-in baseline dilutes the signal so heavily that a candidate
which actually *loses* to the baseline in direct self-play (measured:
0.34 win rate head-to-head) can still look like an improvement on the
blended aggregate (0.78 vs 0.667) - see kagg.policy.strategy's own
_DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY comment for the full story.
Direct self-play against the previous-best snapshot (not the blended
panel score) is what actually found this real change: 50/50 wins on
both the working block and the held-out block (95% Wilson interval
[0.929, 1.0] on each) - a genuinely accepted, held-out-gated result,
not an ad-hoc measurement.

Re-recorded a fifth time for T8.2 (distance-aware, tier-local task
servicing - tasks/plan.md): `assign_units` used to process same-priority
tasks in row-major scan order (a stable sort on priority alone never used
distance), so a single unit could be sent to the farthest same-tier task
first even while standing on a nearer one. Rewritten as tier-by-tier
greedy nearest-match, proved stable under decide()'s statelessness (see
tasks.assign_units's own docstring for the argument). This was the
biggest single accepted change of Phase 8 so far, dwarfing T8.1's
placement fix: direct self-play against the pre-T8.2 snapshot won 49/50
on the working block and 48/50 on the held-out block (95% Wilson interval
[0.895, 0.996] and [0.865, 0.989] respectively) - formally accepted by
tuning.accept_candidate against an even-odds baseline on both. Notably,
this also *reversed* T8.1's open question: investment_anchor="SHED" +
plant_while_pursuing_animal=True (T8.1/T8.9's opt-in fixes, still not the
default) were re-tested on top of T8.2 on the hypothesis that T8.2 was
what they were "waiting on" - instead they now *lose decisively*
(working 0.28, holdout 0.18) to the plain UNIT/False default. T8.2's
distance-aware servicing already keeps the farmer on the nearest urgent
tile regardless of the plot's shape, so T8.1's shed-anchored placement
and T8.2's smart servicing overlap rather than compose - see
kagg.policy.decide's _DEFAULT_INVESTMENT_ANCHOR comment for the full
story. Both toggles remain off by default.

Re-recorded a sixth time for T8.3 (land purchase gating - tasks/plan.md,
the user's own observed defect: land bought while plenty of free tiles
remained). `should_buy_land` gained an occupancy-aware gate
(`land_buy_max_free_tile_fraction`), and unlike T8.1/T8.9 this one was
swept and accepted immediately, not shipped opt-in: every tested value
(0.6, 0.4, 0.25, 0.1) beat the ungated default 50/50 on the working
block, confirmed 50/50 again on the held-out block for the accepted
value (0.25) - formally accepted by tuning.accept_candidate against an
even-odds baseline on both. Traced directly, not just trusted: with the
gate on, BUY_LAND stops firing almost entirely in real episodes and the
farm stays on the 25-tile NW quadrant - confirms a single farmer cannot
productively work even one full quadrant (one investment task per turn,
one farmer to service it), so every dollar spent unlocking more land was
pure waste. By far the largest single golden-table jump recorded so far
(e.g. starter/seed2: 18821 [T8.2's number] -> 25726, +37%).
Explicitly provisional (fit to a 1-unit farm) - must be re-swept once
labor works (T8.8).

Re-recorded a seventh time for T8.3b (tasks/plan.md) - a real correction
of a prior confounded/stale conclusion, not a new capability. Real
Kaggle games from Checkpoint 8A's submission independently reproduced
two symptoms the T8.1/T8.9 work had already built (but shipped off)
fixes for: animal structures ending up far from the shed (investment_
anchor="SHED"), and crop production stopping mid-game once an animal
locks in as the permanent top-ranked choice (plant_while_pursuing_
animal). Re-tested both cleanly in isolation on top of today's code
(T8.2+T8.3), which had never actually been done - the prior rejection
bundled both variables together and/or ran on stale pre-T8.2/T8.3 code.
Result: plant_while_pursuing_animal=True ALONE won 50/50 on both
self-play blocks and is now the default; investment_anchor="SHED" still
lost even in isolation (0/50 both blocks - worse than before, since it
now re-triggers the same animal-locks-in bug even harder) and combined
with the accepted fallback still lost to plain UNIT (0.10/0.02) - so
investment_anchor stays "UNIT". See kagg.policy.decide's
_DEFAULT_INVESTMENT_ANCHOR and _DEFAULT_PLANT_WHILE_PURSUING_ANIMAL
comments for the full four-way comparison. Money moved for the seeds
where an animal actually locked in as the long-term top choice (e.g.
starter/seed1: 18242 -> 25204, pass/seed1: 17970 -> 24979); seeds where
that never happened are close to unchanged, consistent with this being
a conditional bug fix, not a universal multiplier.

Re-recorded an eighth time for T8.3c (tasks/plan.md) - designed together
with the user in direct response to T8.3b's honest "SHED doesn't pay for
itself" finding. Traced the actual root cause precisely, not just
"SHED vs UNIT": UNIT's tie-break among candidates *equally* close to the
farmer is row-major scan order (`tasks._closest_pos`), which has no
relationship to the shed and is what drove the marching-line pattern -
not the nearest-to-farmer primary criterion itself, which SHED wrongly
replaced entirely (that replacement is exactly what cost it real travel
efficiency in T8.3b's measurements). The fix keeps distance-to-farmer as
the primary key (a new anchor, "UNIT_TOWARD_SHED") and only changes the
tie-break to `shed_distance` - provably never a worse detour than plain
UNIT for that specific choice, since tied candidates share the same
farmer-distance by definition. A user-proposed continuous-coordinate
distance formula (`|4.5-x|+|4.5-y|`) turned out to be algebraically
identical to the already-implemented `shed_distance` up to an irrelevant
+1 constant - confirmed before writing any code, so no new geometry was
needed. Measured: 50/50 wins on BOTH self-play blocks against the
previously-shipped default - the single cleanest result of this entire
investigation. Traced, not just trusted: every seed checked did strictly
more WATER/PLANT/HARVEST and fewer PASS turns than the old default in
the same episode. All 6 golden seeds improved this time (e.g.
starter/seed3: 21486 -> 25422), unlike T8.3b's conditional fix - this
one is a structural travel-efficiency improvement that applies in every
game, not just ones where a specific animal-lock-in scenario occurs.

Re-recorded a ninth time for T8.3f (tasks/plan.md) - the user's own
observation about the game's price-elasticity rules, refined together
with the user through direct measurement: an initial implementation
walked a single tile's own future yield against its own price
(`crop_revenue_per_tile_day`'s per-unit lockstep pricing), but measured
that this alone barely moves anything - one MELON tile's 6-unit run
scores unchanged (250 -> 250), since the market's elasticity scale (T)
is calibrated to a whole farm's output, not one tile's. The real fix
prices a *new* tile starting from where the farm's *existing* commitment
to that crop (`rank_portfolio`'s new `crop_tile_counts` argument, counted
from the farm's own tiles) would already have pushed the market -
measured directly: 20 melon tiles already growing crashes even the next
tile's own average price from 250 to 46, correctly demoting MELON below
every other crop once that commitment is real. Measured: 50/50 wins on
BOTH self-play blocks against the previously-shipped default. Traced,
not just trusted (seed 100): the self-impact-aware agent planted MELON
16 times before switching to STRAWBERRY for its remaining 7 plantings
($21452 final); the old code kept planting MELON 23 times (crashing its
own realized price) plus a few cheap CARROT/WHEAT fallbacks once MELON's
price cratered ($17765 final) - a real, structural diversification
effect, not a marginal tuning gain. 4 of 6 golden seeds changed this
time (both directions - this changes *what* gets planted, not simply
"more efficient at the same plan").

Re-recorded a tenth time for T8.3i (tasks/plan.md) - the user's own follow-up question: is
elevated town-shop demand already accounted for, or only as a lagging reaction once the price has
already moved? Confirmed it was purely the latter - `market_inventory` already reflects any
consumption a shop has *already* caused (the same shared object `_town_consume` mutates), but
`obs["town"]["unlocked_shops"]` was never read anywhere in this codebase before this, so nothing
looked ahead to what a *currently* unlocked shop will keep doing for the rest of the game. Added
`gamelib.market.expected_daily_consumption` (mirrors `_town_consume`'s own math, oracle-verified:
`SHOPS`/`TOWN_CENTER_PRODUCTS`/`MAX_SHOP_INSTANCES` all checked directly against the real engine)
and wired it into both `crop_revenue_per_tile_day` and (unlike T8.3f/g/h's crop-only self-impact
scope) `animal_revenue_per_tile_day` - a consumption estimate needs no bounded lifetime total the
way self-impact-from-production does, so animal products aren't excluded here. Measured: a strong,
decisive win - 49/50 on the working block and 48/50 on the held-out block. Traced (seed 100, 8
shops unlocked by season end): the shop-aware agent diversified its post-MELON fallback into
TOMATO and CARROT (both drawn down by the unlocked shops) instead of STRAWBERRY (the unaware
agent's plain crop-only leader) - $24078 final vs $21424, a real ~12% gain from knowing which
goods have elevated demand.

Re-recorded an eleventh time for T8.3k (tasks/plan.md) - the user's own observation: time is a
scarce, hard-capped resource in this game (a fixed 30-day season), so profitability should be
*net* profit per day spent, not *gross* revenue per day spent. A crop's own seed cost
(`CROPS[crop]["seed"]`) was never subtracted anywhere in the ranking before this - only used
separately as an affordability check (`money >= seed_cost`) unrelated to whether the purchase was
actually worth it relative to another crop. `crop_revenue_per_tile_day` now optionally nets out the
seed cost before dividing by `tile_days`, gated by `params["crop_net_of_seed_cost"]`. Measured with
an honest methodological note this run itself surfaced: unlike every other T8.3-series flag (which
changed nearly every game's outcome), this one only changes the crop-ranking *order* in a narrow
crossover window - most games tie exactly (30/50 working block, 25/50 held-out), since the gap
between top-ranked options usually dwarfs any seed-cost difference between them. Among the games it
*does* decide, the edge is real and reproducible: 18W/2L on the working block (Wilson interval on
the decided subset [0.70, 0.97]) and 21W/4L on the held-out block ([0.65, 0.94]) - 39W/6L combined,
nowhere near the 0.5 line. Traced (seed 104): the net-aware agent planted MELON 16 times and
STRAWBERRY 7, entirely skipping CARROT; the gross-revenue agent planted MELON 18, STRAWBERRY 5, and
CARROT 4 - CARROT's $20 seed cost against its own modest yield doesn't clear the bar once netted
out. $19903 vs $18584 final. Accepted as the default. 2 of 6 golden seeds changed this time (a
smaller footprint than T8.3f/T8.3i, consistent with the narrow-crossover-window finding above).

Re-recorded a twelfth time for T8.3m (tasks/plan.md) - the user's own observation, extending T8.3k's
"time is scarce" insight to the piece it didn't reach: `rank_portfolio` had no notion of the current
day or the remaining season, and `ANIMALS[animal]["cost"]` plus the recurring WHEAT feed cost were
never netted out anywhere. Two independent mechanisms measured in isolation (`rank_season_aware` for
crops, `animal_net_of_cost` for animals - T8.3b's own lesson about confounded measurements): the crop
side was a real, decisive **rejection** (1/44 working, 2/47 held-out, traced to a pre-existing
single-farmer capacity limit - see kagg.policy.decide's own comment), stays off by default. The
animal side was the strongest measured result of the whole T8.3-series investigation - 50/50 working,
49/50 held-out - **accepted** as the default. A major, deliberately-verified side effect, not an
oversight: once an animal's true cost (purchase + full-season feed) is priced in, no animal ever
tops the ranking at base market prices at any point in the season (checked directly, not assumed:
`rank_portfolio` at I0 across days 0-28 never once returns an animal first) and animal production
never occurs across 15 real episodes checked (seeds 100-114) - the whole T6.1-T6.5 acquisition
pipeline is now correctly avoided as economically uncompetitive under normal conditions rather than
pursued reflexively at a fictional unbounded steady-state rate (COW's old rate: 80/tile-day forever;
its real net rate at a full 30-day horizon: ~21/day, well below MELON/STRAWBERRY). The pipeline
itself is untouched and still verified working (see
test_at_least_one_animal_reaches_production_in_a_representative_episode, now exercised with
`animal_net_of_cost=False` explicitly to keep testing pipeline mechanics independent of today's
accepted economics). All 6 golden seeds improved (none decreased) - e.g. starter/seed1: 26386 ->
27524.

Re-recorded a thirteenth time for T8.7 (Stage B's payoff) - hires_per_day raised 0 -> 1.
T7.4's original hires_per_day=0 finding (every nonzero value lost 0.03-0.17) was invalid, not
merely stale: it ran against real bugs T8.4 (inventory pinning) and T8.6 (parallel planting) fixed -
a hired hand could silently strand wheat/an animal in an inventory decide() never looked at again,
and build_task_list proposed at most one new-investment task per turn regardless of hand count. The
re-run sweep (`tools/run_hiring_sweep.py`) flipped completely: every nonzero hires_per_day tried won
96-100% direct self-play against the checked-in baseline, held-out-gated at 50/50 (Wilson
[0.929, 1.0]) for the accepted value 1 - the most conservative value among several tied at the
measured ceiling. All 6 golden seeds improved substantially (none decreased) - e.g. starter/seed1:
27524 -> 37258, roughly +35%.

Re-recorded a fourteenth time for T8.8 (land re-sweep, now that labor works) -
land_purchase_threshold_money raised 10000 -> 15000 and land_buy_max_free_tile_fraction lowered
0.25 -> 0.1. A real, held-out-gated result (0.84, Wilson [0.715, 0.917]) that went the opposite
direction the plan's own hypothesis expected: with hires_per_day=1 (T8.7), land became *less*
attractive, not more - two units still can't profitably use even one 25-tile quadrant, and land now
competes with T8.6's larger seed/animal spend for the same cash. Golden seeds moved modestly in both
directions (4 up, 2 down slightly) - consistent with an 0.84 win rate, not a 50/50-both-blocks
sweep like T8.3's own original result.

"random" is deliberately excluded from the exact-match table: verified
empirically that kaggle_environments' own random_agent seeds its RNG with
`random.Random()` (no seed) fresh on every call, so even the *same*
episode seed produces a different outcome on our own side from run to run
(our policy reacts to market/town state that random_agent's unseeded
choices perturb). A separate robustness check below covers "random" with
invariants instead of an exact number.
"""

import os
import sys

from kaggle_environments import make

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import daily_dashboard  # noqa: E402
import tuning  # noqa: E402

AGENT_MAIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "kagg", "agent_main.py"
)

# (opponent, seed) -> (our exact final money, opponent's exact final money).
# Re-recorded for T8.16(d): dynamic_hiring flipped on by default
# (min_hires_per_day=2) after a joint parameter sweep found it decisively
# beats the prior static hires_per_day=1 default (49W/1L/0T, 98% on the
# held-out self-play block - see kagg.policy.strategy's own
# _DEFAULT_DYNAMIC_HIRING comment for the full traced story). A real,
# large jump on every one of these six seeds (e.g. starter/seed1: 38093
# -> 45650, +19.8%), consistent with the self-play result, not a
# regression to investigate.
#
# Re-recorded a sixteenth time for T8.27: workload_forecast_hiring_aware
# flipped on by default - a proactive, tile-count-derived hiring forecast
# (T8.26's own idea, corrected to exclude routine coverage ops per
# _ROUTINE_RECURRING_OPS's own reasoning) measured and accepted directly
# against this exact shipped baseline (tools/measure_t827.py, Stage 1:
# 92%/98% working/holdout, Wilson [0.812, 0.968] entirely clear of 50% -
# see kagg.policy.strategy's own _DEFAULT_WORKLOAD_FORECAST_HIRING_AWARE
# comment for the full traced story). Five of six seeds improved (e.g.
# pass/seed1: 43879 -> 44707, +1.9%); pass/seed3 dipped slightly (46818 ->
# 46536, -0.6%) - consistent with a real but not-100%-uniform self-play
# win, not a regression to investigate.
#
# Re-recorded a seventeenth time for T8.29: fixed labor_units's stale
# hiring signal - `1 + hires_per_day(params)` was a bare call with no
# runtime arguments, always falling through to the static fallback
# (labor_units hardcoded at 2 every turn regardless of dynamic_hiring's
# real forecast) - see kagg.policy.decide's own T8.29 comment above the
# fix for the full causal story. Measured and accepted directly against
# the exact pre-fix checked-in baseline (tools/measure_t829.py: 92%/98%
# working/holdout, 49W/1L/0T on the held-out block). A mixed but net
# real move across these six seeds (e.g. starter/seed2: 44914 -> 46745,
# +4.1%; pass/seed1: 44707 -> 44462, -0.5%), consistent with a real,
# large aggregate win that isn't uniform seed-by-seed (tools/trace_t829.py
# found the same pattern directly on seed 900: more tiles planted sooner,
# a quadrant opened a day earlier, but slightly lower final money on that
# one seed) - not a regression to investigate.
#
# Re-recorded an eighteenth time for T8.31: always_pursue_one_animal
# (default True) decouples animal acquisition from _top_investment_
# choice's single strict top-pick ranking - once the farm has no animal
# anywhere, the best-scoring animal is pursued in parallel with whatever
# crop the normal ranking already picked, instead of never being
# considered at all whenever a crop like MELON structurally outranks
# every animal (see kagg.policy.decide's own _DEFAULT_ALWAYS_PURSUE_
# ONE_ANIMAL comment for the full mechanism). Measured and accepted
# directly against the checked-in baseline (tools/measure_t831.py: 94%/
# 96% working/holdout, 48W/2L/0T on the held-out block, Wilson
# [0.865, 0.989]) - a decisive win, stronger than the prediction stated
# up front. Honest finding on these six fixed seeds, not glossed over:
# every single one moved *lower* (e.g. starter/seed2: 46745 -> 42108,
# -9.9%; pass/seed2: 45816 -> 45471, -0.8%) despite the large, decisive
# 96%-holdout self-play win - the real spend of always acquiring an
# animal (cost + ongoing feed) is a real cost these six particular seeds
# don't happen to recoup, while the much larger 100-seed self-play
# sample does recoup it on net. tools/trace_t831.py found the opposite on
# seed 900 specifically (COW acquired day 1, final money slightly
# *higher*: 36814 -> 37023) - genuine seed-to-seed variance, not a sign
# the fix is wrong; the self-play win rate over 100 seeds is the real
# acceptance signal here, not six fixed numbers.
#
# Re-recorded a nineteenth time for T8.42: land_purchase_threshold_money
# 15000 -> 0 and min_hires_per_day 2 -> 8, jointly, calibrated directly
# against T8.40's real top-leaderboard data (top players buy their 2nd
# quadrant leaving essentially zero cash reserve, and front-load hired-
# hand count far beyond this project's old floor). Measured and accepted
# directly against the checked-in baseline (tools/measure_t842.py: 96%
# working, 89.5% confirmed on a 200-seed holdout, Wilson
# [0.845, 0.930] entirely clear of the even-odds baseline) - the
# strongest, most decisively confirmed self-play result this project has
# measured for either land or labor (T8.32's own closest prior attempt
# regressed from 64% at n=50 to an unaccepted 54.5% at n=200; this result
# holds up, not a repeat of that noise trap). A real, large, and uniform
# jump across every one of these six seeds (e.g. starter/seed3: 44688 ->
# 67716, +51.5%; pass/seed1: 42123 -> 49283, +17.0%) - every single seed
# moved higher, unlike T8.31's own mixed-but-net-positive record just
# above; tools/trace_t842.py confirms the mechanism directly (hand count
# flat at 8 from day 0, all 4 quadrants reached by day ~15-20 vs. the old
# baseline's 2 by day ~22-25).
#
# Re-recorded a twentieth time for T8.43 Stage 1: defer_one_time_harvest_
# to_max_yield turned on (scoped to crops whose watering_bonus_window
# starts at/after first_yield_day - WHEAT/CARROT, not MELON; see kagg.
# policy.tasks._is_actually_harvestable's own docstring for the mechanism
# and why an unscoped first attempt was rejected). Not a project
# accept_candidate verdict - tools/measure_t843.py measured 0.300 win
# rate (15W/12L/23T, n=50), mostly ties since WHEAT/CARROT are rarely
# top-ranked under current play (the mechanism doesn't even activate in
# most games), but 15W/12L (0.556) where it does. Enabled by the user's
# own explicit decision, 2026-09-19 ("she doesn't make things worse, and
# could help once these crops are actually used") ahead of a full n=200
# holdout confirmation - see kagg.policy.decide._DEFAULT_DEFER_ONE_TIME_
# HARVEST_TO_MAX_YIELD for the full reasoning. Only 2 of these six seeds
# moved at all (starter/seed1: 47663 -> 54893, +15.2%; pass/seed1: 49283
# -> 56320, +14.3% - both higher, not lower); seeds 2/3 on both opponents
# were untouched, consistent with WHEAT/CARROT simply not being planted
# in those particular episodes. test_no_animal_escapes_across_the_golden_
# seeds (T8.38's own never-re-recordable guardrail) still passes
# unchanged - zero escapes, confirming this change is safe by that
# guardrail's own standard even without a full self-play accept.
# Re-recorded a 21st time on 2026-09-20, the user's explicit decision to move the
# shipped defaults to day-plan hiring min=2/max=12 + the T8.45 purchase flags +
# drip_sell_max_per_turn=1000 (tasks/todo.md T8.46), plus wheat_urgency_reserve=3 as the
# companion that keeps the T8.38 escape guardrail green (without it starter/seed 2 loses a
# COW on day 28 - WHEAT trades above wheat_max_buy_price=40 so the restock is refused).
# Every one of the six moved DOWN against these external opponents: starter 54893/64798/
# 67716 -> 46396/58953/54065 and pass 56320/61973/69306 -> 43540/58587/57699 (mean -15%).
# Kept visible on purpose - see T8.46 for the numbers and how to revert.
# Re-recorded a 22nd time on 2026-09-20, the user's explicit decision to default
# day_plan_harvest_replant_aware=True (tasks/todo.md T8.47): starter 46396/58953/54065 ->
# 49879/58430/56789 and pass 43540/58587/57699 -> 56732/62026/58144 (five of six up,
# starter/seed 2 -0.9%). T8.38 escape guardrail re-checked, not re-recorded.
# Re-recorded a 23rd time on 2026-09-20, the user's explicit decision to default the T8.49
# bundle on (drop_goods_to_shed with the overflow trigger only, bulk_purchase_counts_harvest_
# tiles, sell_orders_first_by_revenue; tasks/todo.md T8.49): starter 49879/58430/56789 ->
# 56924/55756/72845 and pass 56732/62026/58144 -> 57488/59281/74637 (four of six up, seed 2
# -4.6%/-4.4%). T8.38 escape guardrail re-checked, not re-recorded.
# Re-recorded a 24th time on 2026-09-20, the user's explicit decision to switch the T8.49 cash
# trigger on (drop_goods_cash_min_units=5, gated on a shed with nothing to sell besides feed
# WHEAT): starter 56924/55756/72845 -> 52867/51470/65073 and pass 57488/59281/74637 ->
# 43354/62881/69958 (five of six DOWN, pass/seed 1 -25%; measured -3.6%/-4.9% on 40 external
# seeds, tasks/todo.md T8.49). Revert = drop_goods_cash_min_units None (restores the 23rd table).
# T8.38 escape guardrail re-checked, not re-recorded.
# Re-recorded a 25th time on 2026-09-20, the user's explicit decision to block the 4th quadrant
# (max_extra_quadrants=2, tasks/todo.md T8.50): starter 52867/51470/65073 -> 61199/55910/65088
# and pass 43354/62881/69958 -> 47962/62881/72078 (none down). T8.38 escape guardrail re-checked,
# not re-recorded. Revert = max_extra_quadrants None (restores the 24th table).
# Re-recorded a 26th time on 2026-09-20, the user's explicit decision to default
# drop_goods_deadline_mode=True (tasks/todo.md T8.50): starter 61199/55910/65088 ->
# 59095/56230/65866 and pass 47962/62881/72078 -> 49190/62657/67359 (mixed, within +-7%).
# T8.38 escape guardrail re-checked, not re-recorded. Revert = drop_goods_deadline_mode False.
# Re-recorded a 27th time on 2026-09-20, the user's explicit decision to default
# land_buy_affordability=True (tasks/todo.md T8.52): starter 59095/56230/65866 ->
# 59813/57212/72234 and pass 49190/62657/67359 -> 67546/62552/78380 (five of six up, pass/seed 2
# -0.2%). T8.38 escape guardrail re-checked, not re-recorded. Revert = land_buy_affordability False.
_GOLDEN = {
    ("starter", 1): (59813.0, 4043.0),
    ("starter", 2): (57212.0, 3578.0),
    ("starter", 3): (72234.0, 3581.0),
    ("pass", 1): (67546.0, 3000.0),
    ("pass", 2): (62552.0, 3000.0),
    ("pass", 3): (78380.0, 3000.0),
}


def _run_episode(opponent: str, seed: int):
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": seed},
        debug=False,
    )
    env.run([AGENT_MAIN_PATH, opponent])
    final = env.steps[-1]
    return final[0], final[1]


def test_golden_episodes_reproduce_recorded_final_money():
    mismatches = {}
    for (opponent, seed), expected in _GOLDEN.items():
        our_result, opponent_result = _run_episode(opponent, seed)
        actual = (our_result.reward, opponent_result.reward)
        if actual != expected:
            mismatches[(opponent, seed)] = {"expected": expected, "actual": actual}
        assert our_result.status == "DONE", (opponent, seed, our_result.status)
        assert opponent_result.status == "DONE", (opponent, seed, opponent_result.status)
    assert not mismatches, mismatches


def test_random_opponent_robustness_not_an_exact_number():
    # Invariants that must hold regardless of random_agent's exact
    # (unseeded, non-reproducible) path, rather than a golden number that
    # can't actually be golden here.
    for seed in [1, 2, 3]:
        our_result, opponent_result = _run_episode("random", seed)
        assert our_result.status == "DONE"
        assert opponent_result.status == "DONE"
        assert our_result.reward > 3000  # starting money - the policy must still profit
        # T3.6's ad-hoc 20-seed sweep found random_agent reliably bankrupts
        # itself (margin never under +4886 across 20 runs) - beating it
        # outright, not just being profitable, is the real bar.
        assert our_result.reward > opponent_result.reward


def test_beats_starter_and_random_across_additional_seeds():
    """T3.6's ad-hoc baseline sanity check (tasks/plan.md) - not yet the
    rigorous >=60% win rate SPEC.md's success criteria call for (that
    needs Phase 4's paired-seed harness), but broader than the exact-match
    golden table above: a handful of seeds distinct from _GOLDEN's,
    checking "wins outright" rather than a specific number.

    Full one-off 20-seed sweep (tasks/plan.md T3.6, recorded in that
    commit, not re-run on every test pass - 40 real episodes take ~1
    minute): 20/20 wins vs both starter and random, average margin +1720
    vs starter (min +1336) and +5301 vs random (min +4886). Only 5 seeds
    are re-checked here on every run to keep the suite fast.

    Theoretical flakiness note: random_agent's unseeded RNG means this
    could in principle fail on a given run even at a fixed seed, unlike
    the exact-match golden table above - accepted given how large the
    margin against it was across all 20 sampled seeds (never under
    +4886), consistent with this test's own "ad-hoc, not final-harness
    rigor" framing.
    """
    for seed in (11, 12, 13, 14, 15):
        for opponent in ("starter", "random"):
            our_result, opponent_result = _run_episode(opponent, seed)
            assert our_result.status == "DONE", (opponent, seed)
            assert opponent_result.status == "DONE", (opponent, seed)
            assert our_result.reward > opponent_result.reward, (opponent, seed)


def test_no_animal_escapes_across_the_golden_seeds():
    """T8.37/T8.38 (the user's own concern, 2026-09-18): past conclusions
    about animal husbandry could be silently confounded by undetected
    starvation/escapes, and until this test no golden-episode check ever
    looked - `test_golden_episodes_reproduce_recorded_final_money` only
    compares final money, which an animal that escapes late (T8.37's own
    finding: a last-day escape costs almost nothing) would not visibly
    flag at all.

    Reuses `daily_dashboard.classify_animal_transition` (already unit-
    tested in tests/test_tools_daily_dashboard.py - no new detection
    logic here) against the exact same six canonical (opponent, seed)
    pairs `_GOLDEN` already records money for, diffing every consecutive
    step pair for the whole episode rather than only the final one.

    Confirmed currently true, not assumed: under today's shipped
    defaults (`always_pursue_one_animal=True` since T8.31 - an animal is
    acquired in every one of these six episodes, `test_at_least_one_
    animal_reaches_production...` below covers the pipeline itself),
    zero escapes occur on any of the six. This is a real invariant
    worth protecting, not a tautology - T8.35's own dashboard run found
    a real escape on a *different* seed (100, day 28), and T8.37's own
    measurement found one on seed 105 (self-play, day 29) - animal
    escapes are a real, if seed-dependent, outcome in this game, not
    something that structurally cannot happen. Like `_GOLDEN` itself,
    a future change that causes a real escape on one of these seeds
    should fail this test and require a deliberate look, not update
    silently to a new "golden" escape count - unlike the money table,
    this one has no legitimate reason to ever need updating, since a
    farm having its animal escape is never a improvement to accept.
    """
    escapes = []
    for opponent, seed in _GOLDEN:
        env = make(
            "kaggriculture",
            configuration={"episodeSteps": 720, "seed": seed},
            debug=False,
        )
        env.run([AGENT_MAIN_PATH, opponent])
        steps = env.steps
        for t in range(1, len(steps)):
            prev_tiles = steps[t - 1][0].observation["farms"][0]["tiles"]
            cur_tiles = steps[t][0].observation["farms"][0]["tiles"]
            for y, row in enumerate(prev_tiles):
                for x, prev_tile in enumerate(row):
                    cause = daily_dashboard.classify_animal_transition(prev_tile, cur_tiles[y][x])
                    if cause == "escaped":
                        day = steps[t][0].observation.get("day")
                        escapes.append((opponent, seed, day, prev_tile.get("animal")))
    assert escapes == []


def test_at_least_one_animal_reaches_production_in_a_representative_episode(tmp_path):
    """T6.4's own acceptance criterion (tasks/plan.md): confirms the full
    animal-acquisition pipeline (choose -> BUY_ANIMAL -> BUILD_* ->
    PICKUP -> PLACE -> FEED -> production) actually reaches production in
    a real episode, not just in isolated unit tests.

    Real, not hypothetical: the very first full T6.4 attempt reached
    PLACE but never production at all (verified by direct inspection of
    env.steps) - PLACE's real handler consumes the animal from the
    acting unit's own inventory, not the shed BUY_ANIMAL delivers to, so
    every placed animal just starved and escaped. Fixed via a PICKUP
    step (tasks.py) plus a wheat-sale reservation (market.py) and two
    "don't keep re-buying" guards (decide.py) - see those modules' own
    docstrings for the full story. This test is the regression guard
    against ever silently losing that pipeline again.

    T8.3m correction: `animal_net_of_cost=True` (now the shipped default
    - see kagg.policy.decide's own comment for the measured story) makes
    the pipeline *economically* uncompetitive against crops under normal
    market conditions, confirmed directly - checked across 15 real
    episodes (seeds 100-114, real code, real default params) and found
    zero animal production in every one. That's a real, measured, and
    intentional consequence of finally pricing an animal's true cost, not
    a regression of the *pipeline itself* - so this test now runs with
    `animal_net_of_cost=False` explicitly (via `tuning.write_candidate_
    agent`, not the raw shipped `AGENT_MAIN_PATH`) to keep testing what
    it was built to test: that the full choose -> BUY_ANIMAL -> BUILD_*
    -> PICKUP -> PLACE -> FEED -> production pipeline still works end to
    end when an animal IS pursued, independent of whether today's
    accepted economics happen to pursue one.
    """
    from kagg.policy.params import DEFAULT_PARAMS

    agent_path = tuning.write_candidate_agent(
        dict(DEFAULT_PARAMS, animal_net_of_cost=False), str(tmp_path)
    )
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": 1},
        debug=False,
    )
    env.run([agent_path, "pass"])
    reached_production = any(
        step[0]["observation"]["private"].get("shed", {}).get(product, 0) > 0
        for step in env.steps
        for product in ("MILK", "WOOL", "EGG")
    )
    assert reached_production
