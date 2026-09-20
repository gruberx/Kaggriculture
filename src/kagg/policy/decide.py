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
from kagg.policy.market import buy_wheat_order, bulk_purchase_plan, sell_orders
from kagg.policy.strategy import hires_per_day, rank_portfolio, score_portfolio, should_buy_land
from kagg.policy.tasks import (
    action_for_unit,
    animal_tile_day_actions,
    assign_units,
    build_task_list,
    crop_tile_day_actions,
)

_MAX_MARKET_ORDERS = 10

# Default season length in days (kaggriculture.json's default
# episodeSteps=720 / turnsPerDay=24 = 30). A named, tunable parameter
# rather than a bare literal since a non-default configuration would
# change it - see _crop_has_time_to_mature's own docstring for why this
# exists at all.
_DEFAULT_SEASON_LENGTH_DAYS = 30
# T8.12: real episode configuration value, not exposed in the observation
# at all - same shape as expected_daily_consumption's own turns_per_day
# default (gamelib.market), a named default rather than a silently
# assumed literal.
_DEFAULT_TURNS_PER_DAY = 24
# T8.16(a): recur once per tile/animal per day regardless of labor level
# (a tile needs exactly one WATER, an animal exactly one FEED, whether 1
# or 10 hands exist) - excluded from dynamic_hiring's `pending_task_count`
# signal, which should reflect genuine *marginal* work that scales with
# labor, not a standing backlog that doesn't. See the dynamic_hiring
# rejection comment in kagg.policy.strategy for the traced story this
# fixes.
_ROUTINE_RECURRING_OPS = frozenset({"WATER", "FEED"})

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

# T8.5: matches market.py's own module-private
# _DEFAULT_WHEAT_RESTOCK_THRESHOLD (not imported - underscore-prefixed,
# module-private there) - needed here now that this module calls
# sell_orders directly instead of the combined market_orders wrapper, to
# replicate that wrapper's own belt-and-braces reserve-floor invariant
# (see the market-assembly block's own comment for why). Keep the two in
# sync by hand if either default ever changes.
_DEFAULT_WHEAT_RESTOCK_THRESHOLD = 5

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

# T8.3e (the user's own observed defect): FERTILIZER was only ever
# collected (COLLECT_FERTILIZER) and sold (market.sell_orders, since it's
# a PRODUCT), never applied - the real FERTILIZE handler doubles the
# yield bonus on any day the tile is both watered and fertilizer-active
# (kaggriculture.py's _daily_refresh_plants/WATER handler both gate the
# bonus on `was_watered` first), for the day of application plus the
# following two. Gates both kagg.policy.tasks's new FERTILIZE task and
# market.sell_orders's exclusion of FERTILIZER from routine selling (see
# both modules' own docstrings) - a single flag, so enabling it is a
# clean, fully-isolated change for self-play comparison.
#
# Built, tested, and measured - **not accepted as the default**, a real
# rejection rather than a silent no-op default (mirroring the SHED
# anchor's own history - a plausible-sounding mechanism that still needs
# real evidence): measured a clean, decisive loss in direct self-play at
# *both* tiers tried. At PRIORITY_ROUTINE_CARE (tied with WATER, so
# outranking PRIORITY_PLANT): 0/50 working, 0/50 held-out - every
# non-tied episode a loss. At PRIORITY_MAINTENANCE (this module's
# tasks.py default, below PLANT, same tier as COLLECT_FERTILIZER): still
# 0/4 working-block losses and 0/3 held-out-block losses (fewer episodes
# differed at all, but zero of the ones that did favored fertilizing).
# Traced, not just trusted (seed 117, single seat): the fertilize-enabled
# agent completed *fewer* total COLLECT_FERTILIZER actions over the whole
# game (4 vs 5) than the exact same code with the mechanism off, losing
# more FERTILIZER-sale income than the one real FERTILIZE application it
# managed gained back. Root cause: FERTILIZE and COLLECT_FERTILIZER share
# the same PRIORITY_MAINTENANCE tier, so adding FERTILIZE as a second
# consumer of the farmer's already-scarce lowest-priority turns directly
# dilutes COLLECT_FERTILIZER's own throughput - a real, structural
# tension, not tunable away by priority alone at a single farmer's
# capacity. Kept as a real, arena-checkable alternative (like
# `investment_anchor="SHED"`) rather than deleted outright - worth
# revisiting once T8.6/T8.7 give a second unit real spare capacity for
# opportunistic MAINTENANCE-tier work.
_DEFAULT_USE_FERTILIZER = False

# T8.3f (the user's own observation): gates whether `_crop_tile_counts`'s
# scan result actually reaches `rank_portfolio` (see its own docstring
# and `crop_revenue_per_tile_day`'s for the full self-impact story) or is
# withheld (`None`, rank_portfolio's pre-T8.3f behavior, unchanged) - a
# single flag so the change can be cleanly isolated in self-play, exactly
# like every other behavior lever in this module.
#
# Accepted: a clean, decisive 50/50 win on both the working block (seeds
# 100-149) and the held-out block (seeds 900-949) against the identical
# code with this flag off. Traced, not just trusted (seed 100): the
# self-impact-aware agent planted MELON only 16 times before switching to
# STRAWBERRY for the remaining 7 plantings, ending at $21452; the
# unaware agent kept planting MELON 23 times (crashing its own price)
# plus a few cheap CARROT/WHEAT fallbacks once MELON's actual realized
# price cratered, ending at only $17765 - a real, structural
# diversification effect, exactly the dynamic the user described (a
# single crop's own overproduction craters its price while other goods
# stay high) rather than a marginal tuning gain.
_DEFAULT_CROP_SELF_IMPACT_AWARE = True

# T8.3g: extends T8.3f's self-impact model to also count the opponent's
# already-planted tiles, not just our own - the market is shared, so a
# tile the opponent already has growing pushes the same price down just
# as surely as ours does (see `_combined_crop_tile_counts`'s own
# docstring for why this is fully visible, not a private-data leak).
# Gated separately from `crop_self_impact_aware` (a real, deliberately
# distinct lever, not folded into it) since it's a materially different
# mechanism (reading the opponent's board) that could plausibly help or
# hurt independently of whether self-impact alone already helps.
#
# T8.3g measured full weight (1.0, i.e. an opponent's tile counts exactly
# like one of our own) a clean, total loss: 0/50 on the working block and
# 0/50 on the held-out block, worse than T8.3e's FERTILIZE rejection
# (which at least tied most episodes). Traced (seed 100): the opponent-
# aware agent switched from MELON to STRAWBERRY after only 14 MELON
# plantings, versus the unaware agent's 17 - ending with *less* money
# ($19463 vs $23092) despite diversifying "more correctly" by the model's
# own logic. The underlying idea (a shared market is genuinely affected
# by the opponent's production) is real and confirmed (kaggriculture.py's
# market inventory is one object, not per-player) - the flaw was this
# implementation's crude size estimate: it priced *every* visible
# opponent tile at its full remaining `total_yield`, exactly like T8.3f
# already does for our own tiles, but a tile of ours is only a good
# approximation because our own planting schedule is something we
# directly control and cluster in time; the opponent's tiles carry no
# timing information at all (real age, expected harvest day), so full
# weight overcounts an opponent's tile as fully overlapping with our own
# upcoming harvest regardless of whether their production window has any
# real overlap with ours - double-penalizing shared popular crops into
# premature abandonment.
#
# T8.3h (the user's own proposed refinement) tried a *graduated* weight
# instead of all-or-nothing, on the theory that some partial credit for
# "the opponent probably will eventually sell some of this" might beat
# both extremes. Replaces this all-or-nothing flag entirely (0.0 and 1.0
# reproduce its two settings exactly) - see
# `_DEFAULT_CROP_SELF_IMPACT_OPPONENT_WEIGHT` below for the measured
# result.

# T8.3h: how much weight (0.0-1.0) an opponent's already-planted tile
# gets relative to one of our own (which always counts at full weight,
# unconditionally) - see `_combined_crop_tile_counts`'s own docstring for
# why a graduated weight, not the T8.3g all-or-nothing flag, is the right
# shape for this now.
#
# **Still rejected at every nonzero weight tried** - the graduated shape
# alone doesn't rescue the mechanism; it only softens how badly it loses.
# Swept 0.1/0.25/0.5/0.75/1.0 head-to-head against 0.0 (the working
# block, 50 seeds each):
#   0.10 -> win_rate 0.480 (24W/3L/23 ties), Wilson [0.35, 0.61] -
#           overlaps 0.5, not even a point-estimate win over 0.0
#   0.25 -> win_rate 0.020 (1W/49L)  - decisive loss
#   0.50 -> win_rate 0.200 (10W/40L) - decisive loss
#   0.75 -> win_rate 0.040 (2W/48L)  - decisive loss
#   1.00 -> win_rate 0.000 (0W/50L)  - decisive loss (T8.3g's own result)
# No weight beats 0.0 outright; the best any nonzero weight manages is a
# statistical tie at the smallest value tried (0.1), degrading sharply
# from there - not the clean U-shaped "small weight helps" curve the
# refinement hypothesized. Confirms the real flaw isn't merely *how much*
# weight the opponent's tiles get, but the complete absence of timing
# information in the estimate itself (see the T8.3g paragraph above) -
# even a small, constant discount doesn't compensate for not knowing
# *when* the opponent's tile will actually be sold. A signal-based
# refinement (e.g. only trusting the opponent term when the *observed*
# market price already shows movement unexplained by our own sales, the
# user's own follow-up idea) remains untried and unrejected - it would
# need new information this stateless decide() doesn't currently derive
# (an estimate of "expected price from my own activity alone" to compare
# the real price against), a genuinely bigger lift than this sweep, not
# attempted here.
_DEFAULT_CROP_SELF_IMPACT_OPPONENT_WEIGHT = 0.0

# T8.3i (the user's own follow-up question: is elevated town-shop demand
# already accounted for, or only as a lagging reaction once the price has
# already moved?): before this, purely the latter - `market_inventory`
# already reflects any consumption a shop has *already* caused (the same
# shared object kaggriculture.py's `_town_consume` mutates), but nothing
# in this codebase looked ahead to what a *currently* unlocked shop will
# keep doing for the rest of the game (`obs["town"]["unlocked_shops"]`
# was never read anywhere before this). Gates whether that list actually
# reaches `rank_portfolio` - see `kagg.gamelib.market.
# expected_daily_consumption` and `strategy.rank_portfolio`'s own
# docstrings for the mechanism.
#
# Accepted: a strong, decisive win - 49/50 on the working block (seeds
# 100-149) and 48/50 on the held-out block (seeds 900-949) against the
# identical code with this flag off. Traced (seed 100, 8 shops unlocked
# by season end - PIZZA_SHOP x3, SMOOTHIE_SHOP x2, FARMERS_MARKET x2,
# BRUNCH_SPOT): the shop-aware agent diversified its post-MELON fallback
# into TOMATO and CARROT (both drawn down by the unlocked shops) instead
# of STRAWBERRY (the unaware agent's plain crop-only leader with no shop
# information) - $24078 final vs $21424, a real ~12% gain from knowing
# which goods have elevated demand, not a marginal tuning improvement.
_DEFAULT_CROP_SHOP_DEMAND_AWARE = True

# T8.3k (the user's own observation): time is a scarce, hard-capped
# resource in this game (a fixed 30-day season), so crop profitability
# should be net profit per day spent, not gross revenue per day spent -
# before this, a crop's own seed cost was never subtracted anywhere in
# the ranking, only used separately as an affordability check
# (`money >= seed_cost`, unrelated to whether the purchase is worth it
# relative to another crop). Gates whether `crop_revenue_per_tile_day`
# actually nets out `CROPS[crop]["seed"]` before dividing by `tile_days`
# - see its own docstring for the mechanism.
#
# Accepted, with an honest methodological note this measurement itself
# surfaced: unlike every other T8.3-series flag (which changed the
# outcome of nearly every game), this one only changes the crop-ranking
# *order* in a narrow crossover window - most games tie exactly (30/50
# working, 25/50 held-out), since the gap between top-ranked options is
# usually far larger than any seed-cost difference between them. Among
# the games it *does* decide, though, the edge is real and reproducible:
# 18W/2L on the working block (Wilson interval on the decided subset
# [0.70, 0.97], nowhere near 0.5) and 21W/4L on the held-out block
# ([0.65, 0.94]) - 39W/6L combined. Traced (seed 104): the net-aware
# agent planted MELON 16 times and STRAWBERRY 7, entirely skipping
# CARROT; the gross-revenue agent planted MELON 18, STRAWBERRY 5, and
# CARROT 4 - CARROT's $20 seed cost against its own modest per-tile-day
# yield doesn't clear the bar once netted out. $19903 vs $18584 final.
_DEFAULT_CROP_NET_OF_SEED_COST = True

# T8.3l (the user's own observed defect): the agent was buying and
# selling 10 WHEAT every single turn with no animal on the farm and none
# being pursued - traced in a real episode (seed 100): 147 BUY_PRODUCT/
# SELL pairs, steps 1-387, every turn until the price climbed past
# wheat_max_buy_price. Root cause: market.buy_wheat_order restocks
# whenever shed WHEAT falls below wheat_restock_threshold regardless of
# whether there's anything to feed, and market.sell_orders sells
# everything above wheat_reserve (0 until an animal is placed) - the two
# rules fight forever with nothing to break the cycle.
#
# Gates whether feed is only restocked when an animal is actually placed
# or currently the top investment choice - see the wiring below and
# market.buy_wheat_order/market_orders's own docstrings for the
# mechanism (including the belt-and-braces reserve-floor invariant in
# market_orders, which also protects the mechanism if this flag is ever
# turned off).
#
# Correction to this comment's own first draft: the initial prediction
# here was "~$0 real-game gain" - reasoned from the engine's own quoting
# rule (kaggriculture.py quotes BUY_PRODUCT at post-buy inventory
# specifically so a solo round trip nets exactly $0, verified
# numerically) plus a params-flag-toggle self-play measurement. That
# measurement turned out to be invalid: toggling this flag off to build
# a "pre-fix baseline" left market_orders's own reserve-floor invariant
# (see market.py's docstring) still active, since the invariant fires on
# the *feed_needed value*, not on this flag - so the synthetic baseline
# was already accidentally getting most of the real fix, and measured as
# a near-tie against the real candidate.
#
# The correct comparison - this actual code change (write_code_snapshot_
# agent) against the real previously-committed code before it
# (snapshot_agent_from_git_ref("HEAD")), both at their own default
# params, exactly how every other T8.3-series feature in this file was
# measured - found a real, decisive, reproducible win: 49/50 on the
# working block (Wilson [0.895, 0.996]) and 47/50 on the held-out block
# ([0.838, 0.979]), clearing the usual gate cleanly in both directions.
# Per-seed score deltas are not one-sided in magnitude (seed 101: +1445;
# seed 103: -888) - the win comes from a small, consistent edge across
# most seeds and seatings, not one dominant mechanism. The clearest
# proximate cause traced so far: the wasted WHEAT restock (queued ahead
# of BUY_SEED/BUY_ANIMAL in the same turn's market list, and the real
# engine settles a turn's market orders strictly in list order) spends
# money that a same-turn seed or animal purchase needed, occasionally
# delaying it a turn when funds are tight in the early game - consistent
# with, but not yet a complete accounting of, the full measured margin.
# See tasks/todo.md's T8.3l entry for the full story, including the
# invalidated first measurement, corrected in place rather than left
# standing.
_DEFAULT_WHEAT_BUY_ONLY_WHEN_FEED_NEEDED = True

# T8.36 (user's own observed defect, spotted directly from
# tools/daily_dashboard.py's buy/sell price columns: the agent buying
# and selling WHEAT the same day). Traced turn-by-turn (seed 900 vs
# starter): tasks._WHEAT_PICKUP_BATCH (10, matching _WHEAT_FEED_RESERVE
# above by design) pulls the *whole* reserve out of the shed into the
# farmer's own inventory the instant any animal needs feeding that day -
# almost all of it goes unused (only 1 unit/animal/day is actually
# consumed via FEED) and safely returns to the shed at end-of-day
# (kaggriculture.py's own _drop_inventories_to_shed), so nothing is lost
# there. But buy_wheat_order's restock check only ever looks at the
# *shed* count at decision time - which PICKUP has already drained,
# often to near zero, well before end-of-day returns it - so it re-buys
# a fresh batch of WHEAT nearly every single day even with several spare
# units already secured in a unit's own inventory, unseen by the check.
# Confirmed directly: with 1 animal and shed WHEAT restocked to 10 each
# morning, PICKUP took the full 10 immediately, leaving the shed too low
# for buy_wheat_order to recognize the farm was already provisioned for
# the day - triggering another BUY_PRODUCT that same or the next turn.
#
# When set, `wheat_on_hand` (passed to market.buy_wheat_order) sums the
# shed *and* every unit's own carried inventory, not the shed alone - so
# WHEAT that's merely "out for delivery" to an animal this turn no
# longer looks like a shortage. Defaults to False: every existing caller
# keeps today's shed-only behavior unchanged until this is measured and
# accepted (SPEC-policy.md: never raised on reasoning alone).
_DEFAULT_WHEAT_RESTOCK_COUNTS_CARRIED_INVENTORY = False

# T8.3l, found while tracing the wheat ping-pong above: sell_orders was
# subtracting wheat_reserve even during liquidate (T8.3d), stranding the
# feed reserve (~10 WHEAT) unsold once an animal had been placed - dead
# weight per T8.3d's own finding that anything unsold at episode end
# scores exactly zero. There's no future feeding left to protect the
# reserve for once liquidation has begun. See market.sell_orders's own
# docstring for the mechanism; measured alongside the flag above (see
# tasks/todo.md's T8.3l entry).
_DEFAULT_LIQUIDATE_WHEAT_RESERVE = True

# T8.3m (the user's own observation, extending T8.3k's "time is scarce"
# insight to the piece it didn't reach): rank_portfolio had no notion of
# the current day or the remaining season at all - _crop_has_time_to_
# mature/_animal_has_time_to_mature only ever gate whether an option can
# produce *at all* before the season ends, then score whatever survives
# at its full, untruncated lifetime revenue. On day 24 of 30, an ongoing
# crop (TOMATO/STRAWBERRY) that will complete maybe 1 of its capped
# 4-production schedule was still ranked as if all 4 would happen. Gates
# whether `days_remaining` (season_length_days - current_day) actually
# reaches `rank_portfolio`'s crop-side truncation - see
# kagg.policy.strategy._crop_yield_and_tile_days's own docstring for the
# mechanism.
#
# **Measured - a real, decisive rejection, not an acceptance**: 1/44
# (working block) and 2/47 (held-out block) - a near-total loss, unlike
# T8.3k's own "narrow crossover window, most games tie" result. Traced,
# not just trusted (seed 101, direct self-play against the checked-in
# baseline): the season-aware agent correctly stops offering STRAWBERRY/
# TOMATO as `_top_crop_choice`'s fallback late in the season (confirmed
# directly - `_top_crop_choice` returns CARROT instead of STRAWBERRY from
# day 18 onward on this seed), but the freed-up choice doesn't get used
# any better - both agents hit the same pre-existing single-farmer
# capacity limit late-game (seeds for 4-5 different crops sitting unused,
# `n_plant_tiles` shrinking as one-time crops are harvested faster than
# the single farmer - already busy servicing the animal-acquisition
# pipeline - can replant them), but the season-aware agent's narrower
# fallback set gives it *less* diversification to fall back on when that
# congestion hits, with nothing compensating for the loss. A real
# instance of the same class of defect as T8.3e's FERTILIZE rejection - a
# mechanism that is locally "more correct" losing to a genuine,
# already-documented single-farmer capacity constraint. Confirmed the
# result is not confounded with animal_net_of_cost below: A+B track each
# other's win/loss pattern almost exactly (identical Wilson intervals),
# but per-seed money is NOT bit-identical between them (spot-checked
# seeds 101-104) - animal_net_of_cost's own effect dominates the
# trajectory heavily enough that this mechanism's small remaining
# influence never flips an outcome in the sample measured, not evidence
# of a wiring bug.
#
# **Shipped default: False** (rejected, not merely unmeasured) - the
# mechanism stays in the codebase, tested and available, for a future
# re-check once T8.4-T8.7 (Stage B, hired hands) relieve the single-
# farmer congestion this rejection was traced to.
_DEFAULT_RANK_SEASON_AWARE = False

# T8.3m, the animal-side twin: `ANIMALS[animal]["cost"]` was never
# subtracted anywhere in the ranking before this (only used as a
# `money >= cost` affordability check in decide()), and the recurring
# WHEAT feed cost wasn't modeled at all - both previously recorded as
# open gaps in tasks/todo.md (T8.3k's "animal purchase + recurring feed
# cost, net of season-remaining days"). Gates whether
# kagg.policy.strategy.animal_revenue_per_tile_day nets both out over the
# remaining season instead of scoring an unbounded steady-state rate -
# see its own docstring for the mechanism, including how this
# incidentally closes the separately-recorded animal self-impact gap.
# Independently gated from `rank_season_aware` (a materially different
# mechanism - crop schedule truncation vs. animal cost netting) so the
# two can be measured in isolation before any bundled test, per T8.3b's
# own lesson about confounded measurements.
#
# **Measured: the strongest result of the whole T8.3-series investigation
# so far** - 50/50 on the working block (Wilson [0.929, 1.0]) and 49/50
# on the held-out block (Wilson [0.895, 0.996]) against the checked-in
# baseline. Traced (seed 101): with cost netting off, `_top_investment_
# choice` kept picking whichever animal ranked highest on raw steady-
# state rate (COW, then SHEEP, then GOOSE as prices moved) all the way to
# day 25+ of a 30-day season, each pick spending real BUILD_*/PICKUP/
# PLACE turns and cash on an animal that could never earn back its
# purchase cost in the days left - directly measurable once the horizon
# is real: `animal_revenue_per_tile_day("COW", ..., days_remaining=9,
# net_of_cost=True)` scores strictly negative. With cost netting on,
# every animal drops below every crop once too little season remains to
# amortize its purchase + feed cost, freeing the farmer's investment
# turns for crops that can actually still pay off.
_DEFAULT_ANIMAL_NET_OF_COST = True

# T8.3q (the user's own follow-up, prompted by asking for the full animal
# production cycle explained day by day): kaggriculture.py's
# _daily_refresh_animals sets fertilizer_available=True for every placed
# animal that survives the day, regardless of feeding or care - a real,
# always-on revenue stream T8.3m's net-of-cost model never counted.
# Recomputed directly (not estimated): fertilizer income alone
# (~$2,819 over a 30-day COW) dwarfs the animal's own product revenue
# (~$1,645 MILK) - see kagg.policy.strategy.animal_revenue_per_tile_day's
# own docstring for the mechanism. Gates whether the ranking adds this
# term - independently of `animal_net_of_cost` itself (T8.3b's own lesson
# about confounded measurements), even though it only has an effect when
# `animal_net_of_cost` is also on.
#
# **Measured - a real, total, decisive rejection, not a marginal one**:
# 0/50 on the working block and 0/50 on the held-out block against the
# checked-in baseline (Wilson [0.0, 0.071] both times) - every single
# game a loss. Traced (seed 100, action-count diagnostic, not guessed):
# the fertilizer-aware agent pursued and placed a COW (BUILD_PASTURE,
# PICKUP, FEED x27, PLACE) that the unaware baseline never touched at
# all, but the resulting episode shows **zero `COLLECT_FERTILIZER`
# actions the entire game** - the promised ~$2,819 fertilizer revenue the
# ranking priced in never actually gets collected, because
# `COLLECT_FERTILIZER` sits at `tasks.PRIORITY_MAINTENANCE`, the lowest
# tier, and the same single farmer already spends its turns on the animal
# pipeline (BUILD/PICKUP/FEED/PLACE) on top of its existing crop work
# (WATER dropped from 273 to 212 in the same episode, HARVEST/PLANT
# roughly unchanged) - there is nothing left over for MAINTENANCE-tier
# work. The exact same class of defect as T8.3e's FERTILIZE rejection: a
# locally "more correct" economic model choosing a labor-expensive option
# whose promised payoff the single farmer's real turn budget can't
# actually capture. **Shipped default: False** (rejected, not unmeasured)
# - the mechanism stays in the codebase, tested and available, for a
# future re-check once T8.4-T8.7 (Stage B, hired hands) give real spare
# MAINTENANCE-tier capacity - exactly the T8.3p/Stage B argument this
# task's own plan predicted a loss here would make.
_DEFAULT_ANIMAL_FERTILIZER_INCOME_AWARE = False

# T8.3q Part 2: CARE (kaggriculture.py's own "Animal Care" mechanic,
# `_daily_refresh_animals`'s `pending_care_bonus`) is a genuinely new task
# (kagg.policy.tasks's `care_aware` param) plus a new ranking term
# (kagg.policy.strategy.animal_revenue_per_tile_day's own `care_aware`,
# via `_animal_full_care_units`'s exact day-by-day simulation - the
# theoretical ceiling nearly doubles-to-quadruples an animal's raw
# product yield, dwarfing every other T8.3-series lever). Gates whether
# both the task and the ranking are active - deliberately one flag for
# both halves (unlike `use_fertilizer`, which also gates two modules, the
# ranking side here has no meaning without the task side actually
# collecting the bonus it promises, and vice versa - see T8.3q Part 1's
# own fertilizer-income rejection for exactly what happens when a
# ranking promises a payoff the task layer can't actually realize).
#
# **Measured - a real, total, decisive rejection, matching Part 1's own
# result exactly**: 0/50 on the working block and 0/50 on the held-out
# block against the checked-in baseline (Wilson [0.0, 0.071] both times).
# Traced (seed 100, same action-count diagnostic as Part 1): the
# care-aware agent pursued and placed an animal (BUILD_PASTURE x2,
# PICKUP=25, FEED=31, PLACE=2) with WATER dropping from 273 to 226 in the
# same episode, but the episode shows **zero `CARE` actions the entire
# game** - the theoretical yield-doubling bonus the ranking priced in
# never gets collected, for the identical reason Part 1's fertilizer
# income didn't: `CARE` sits at `tasks.PRIORITY_MAINTENANCE`, and the
# same single farmer already spends every available turn on the animal
# pipeline plus its existing crop work, leaving nothing for a second
# MAINTENANCE-tier consumer (`CARE` competes directly with
# `COLLECT_FERTILIZER` at the same tier, on the same tile, for the same
# already-absent spare turns). **Shipped default: False** (rejected, not
# unmeasured) - kept available for the same Stage B re-check as Part 1.
# Confirmed combined with Part 1 too (both flags on at once): 0/50 on
# both self-play blocks, consistent with each mechanism's own individual
# rejection - no confounding, no surprise (unlike T8.3m's Part A/Part B
# split, where the combination masked Part A's own effect).
_DEFAULT_ANIMAL_CARE_AWARE = False

# T8.10, the user's own observation: rank_portfolio's animal side only
# ever estimated town/shop consumption over *one production interval*
# (`rate * a["interval"]`, 1-3 days) - a real, asymmetric gap against the
# crop side's own already-full-horizon `expected_consumption` (T8.3f/
# T8.3i). An animal sells into a market the town drains every single day,
# all season, so a later scheduled unit's real price is far above what a
# flat one-interval offset credits - traced directly on seed 100's real
# shop draw: COW's modeled net rate roughly doubled (T8.3m's flat model
# $46.5/tile-day -> $94.4 with the schedule-day-aware walk, both at
# days_remaining=28), enough to move it from well behind MELON/STRAWBERRY
# to directly competitive with them. See
# kagg.policy.strategy.animal_revenue_per_tile_day's own
# `consumption_horizon_aware` docstring for the mechanism.
#
# **Measured and rejected - a real, decisive, and fully traced result,
# stated up front prediction wrong**: 1/50 working (39 ties), 0/50
# held-out (40 ties) against the checked-in baseline. The prediction ("a
# clear, zero-risk win - a pure formula correction that costs no extra
# farmer turns") was wrong, and understanding *why* mattered more than
# the raw number: a first single-seating trace (seed 901) looked like a
# real loss but turned out to be pure seat-order noise - re-running the
# checked-in baseline against *itself* (identical code both sides)
# reproduced the exact same non-tied money split, proving that seed
# carried zero real signal (`harness.run_paired`'s own seat-swap-and-sum
# already cancels this, which is exactly why the *paired* result, not a
# single seating, is the number that matters).
#
# The real, non-tied holdout seeds (902/908) traced to a genuine
# mechanism, not noise: this flag brings COW's modeled rate close enough
# to STRAWBERRY's that on one seed, ordinary intraday market movement
# made COW edge out STRAWBERRY for exactly 2 turns (day 12, confirmed by
# replaying both param sets against the real trajectory turn-by-turn -
# `_top_investment_choice` agreed on every other turn of the entire
# 720-turn episode). `_top_investment_choice` has no hysteresis - the
# single turn it flipped was enough to fire a real BUY_ANIMAL order, and
# once bought, the existing (correct, deliberate) `stuck_animal` logic
# commits to *finishing* that acquisition (BUILD_PASTURE, repeated
# PICKUP, PLACE, repeated FEED - confirmed in the actual episode) rather
# than abandoning a paid-for animal - diverting real farmer turns from
# STRAWBERRY/MELON tending into a pipeline for an animal the ranking
# itself reverted away from on the very next turn. **Not a flaw in the
# consumption_horizon_aware formula's own accuracy** (the unit tests
# confirm it computes exactly what it claims) - it exposes a real,
# previously-dormant architectural gap: nothing in this codebase requires
# a lead margin or turn-count of sustained ranking before committing
# capital to an irreversible purchase, and animals were simply always
# far enough behind crops (pre-T8.10) that this gap never mattered. A
# concrete lead for later, not built here: gate BUY_ANIMAL on the top
# choice holding for some minimum number of consecutive turns, or on a
# minimum score margin over the runner-up, before committing. Kept
# available (tested, off by default) for that future fix to build on -
# same convention as T8.3q's fertilizer/CARE rejections.
_DEFAULT_ANIMAL_CONSUMPTION_HORIZON_AWARE = False

# T8.24, the user's own follow-up once animal economics started looking
# real: once real feed demand exists, growing WHEAT domestically instead
# of always buying it (market.buy_wheat_order) avoids a real, previously
# unpriced cost - especially under contested demand (an opponent also
# running animals would push WHEAT's own purchase price up via their own
# BUY_PRODUCT orders). See kagg.policy.strategy.wheat_feed_credit_per_
# tile_day for the mechanism (a real make-vs-buy price asymmetry: BUY is
# quoted at post-buy inventory, scarcity pushes it UP; SELL at pre-sell
# inventory, glut pushes it DOWN). Off by default - the exact prior WHEAT
# ranking for every caller that doesn't set it.
_DEFAULT_WHEAT_SELF_SUFFICIENCY_AWARE = False

# T8.14: exactly the "concrete lead for later" T8.10's own rejection
# comment above named - a minimum score margin an animal candidate must
# clear over the best crop before `_top_investment_choice` will return
# it, protecting against the specific, traced failure mode (a razor-thin,
# single-turn lead flipped by ordinary intraday market movement firing a
# real, irreversible BUY_ANIMAL). Default 0.0 (no margin - any animal
# simply ahead of every crop qualifies), reproducing the exact pre-T8.14
# behavior for every caller that doesn't set it. Not yet measured in
# self-play - see `_top_investment_choice`'s own docstring for the
# mechanism.
_DEFAULT_INVESTMENT_COMMIT_MARGIN = 0.0

# T8.11, the user's own observation, traced to a real, decisive bottleneck:
# the real WATER handler only ever adds yield for a one-time crop
# (WHEAT/CARROT/MELON) on ages inside watering_bonus_window(crop) - every
# other day's watering is pure anti-weed insurance, not yield. Before this,
# tasks.py queued WATER at PRIORITY_ROUTINE_CARE every single day
# regardless, outranking PRIORITY_PLANT - traced directly on seed 100: 20
# MELON tiles planted at age 0 (window doesn't open until age 6) burned
# ~140 farmer turns on out-of-window watering over days 3-10 alone, while
# 4 free tiles and 2 MELON seeds already in hand sat completely unplanted
# for those same 8 days (192 unit-turns: 148 WATER, 215 movement, 13
# HARVEST, 0 PLANT) - the exact "labor never reaches PRIORITY_PLANT while
# routine watering saturates it" mechanism behind the idle capital the
# user separately flagged. See kagg.policy.tasks._plant_tile_tasks's own
# `water_bonus_window_aware` docstring for the mechanism and its
# deliberate one-time-crop-only scope (ongoing crops get zero yield from
# watering regardless of age - verified directly in kaggriculture.py, not
# assumed - so they're left untouched). Not yet measured in self-play -
# **Measured and rejected - the named risk (T8.3e's own precedent) came
# true, traced directly, not just trusted**: 7/50 working, 3/50 holdout,
# 0 ties either block (unlike T8.10's mostly-tied result, this mechanism
# fires on nearly every turn, so its effect is never a coin-flip-close
# near-tie - it's a real, consistent behavioral shift, just the wrong
# one). Traced (seed 900, single seat): PLANT count did rise as
# predicted (42 -> 48, +14% - the freed labor genuinely reached PLANT
# more often), but WEED count at episode end more than tripled (4 -> 13)
# and final money fell. Root cause: demoting a *non-urgent* WATER all the
# way to PRIORITY_MAINTENANCE (tied with DIG/COLLECT_FERTILIZER, below
# PLANT) conflates "not yield-productive today" with "not needed today" -
# the real anti-weed rule (2 consecutive misses -> weed) doesn't care
# whether a watering falls inside the bonus window, only whether the
# *previous* day was missed. Once PLANT tasks fill the queue ahead of it
# (exactly the parallel-planting throughput T8.6 built), a demoted
# routine watering can miss two days running before ever reaching MAINTE-
# NANCE priority, converting productive tiles to weed - a real, self-
# inflicted version of the same "promised value the labor budget can't
# safely capture" pattern as T8.3q's fertilizer/CARE rejections, but this
# time the cost lands on the *same* task instead of a competing one. A
# concrete lead for later, not built here: a middle priority tier between
# ROUTINE_CARE and PLANT (not all the way down to MAINTENANCE) might free
# some labor without exposing 2-day misses to PLANT-tier contention - or
# track "turns since last watered" more precisely than the binary urgent/
# routine split already does. Kept available (tested, off by default) for
# that future revision - same convention as every other T8.3/T8.10-series
# rejection.
_DEFAULT_WATER_BONUS_WINDOW_AWARE = False

# T8.22, the user's own request: verified directly against
# kaggriculture.py that BUY_ANIMAL has no same-type limit at all (only
# shed_capacity and money) and PLACE only needs one matching empty
# structure per animal - the "never pursue a second instance of an
# already-placed animal type" rule below (placed_animal_type_counts) was
# entirely this module's own simplification, not a game constraint.
# Prompted by the corrected unit-economics analysis (tools/analyze_unit_
# economics.py): a fully-cared animal beats every crop on raw $/tile-day
# at N=1, and still beats even *contested* MELON at realistic end-game
# shop-consumption scale - real evidence the single-instance cap was
# leaving money on the table, not just a hypothesis. Deliberately a
# simple swept scalar (default 1, bit-identical), not a labor-derived
# formula - matches this project's own established preference
# (land_purchase_threshold_money, hires_per_day, min_hires_per_day were
# all found by sweeping a plain number) - the arena finds the real
# ceiling rather than a formula guessing at per-animal labor cost the
# unit-economics analysis already showed is small and non-linear (shop
# luck dominates over marginal labor cost).
_DEFAULT_MAX_ANIMALS_PER_TYPE = 1

# T8.31, the user's own follow-up after T8.29: decouples animal
# acquisition from _top_investment_choice's single strict top-pick
# ranking, which structurally almost never chooses an animal (MELON
# scores ~119/tile-day at a fresh market vs COW's ~23 - verified directly
# via score_portfolio - and per-crop-scoped self-impact decay means the
# ranking always rotates to a fresh crop type instead of ever being
# forced toward an animal). Stage 0 (tasks/todo.md) measured that
# loosening investment_commit_margin cannot fix this on its own - even
# margin=-0.5 produced zero behavioral change across 400 self-play games.
# When set and the farm has no animal anywhere in any form, the single
# best-scoring animal (via the new _top_animal_choice, scored on its own -
# never compared against the crop ranking) is pursued in parallel with
# whatever crop the normal ranking already picked - see the gating block
# in decide() (right after have_animal_anywhere) for the full mechanism.
# Default False, bit-identical to every pre-T8.31 caller - not yet
# measured in self-play.
_DEFAULT_ALWAYS_PURSUE_ONE_ANIMAL = False

# T8.43, the user's own observation, confirmed as a real mechanism gap
# rather than a ranking-strength question: always_pursue_one_animal's own
# gate below was a one-shot trigger - "not placed_animal_type_counts"
# permanently goes False the instant *any* animal exists anywhere, of any
# type, so max_animals_per_type has never once bound in any measurement
# this project has run (T8.41 traced animals_total stuck at exactly 1 in
# every sampled seed regardless of the cap's value). Generalizes the gate
# from a boolean "at least one, ever" to a count: the mechanism keeps
# firing (still subject to the same "nothing stuck mid-pipeline" check)
# until `sum(placed_animal_type_counts.values()) >=
# always_pursue_animal_target_count`. At the default 1 this is exactly
# `not placed_animal_type_counts` - bit-identical to every pre-T8.43
# caller. Raising it alone would just re-buy unlimited copies of whichever
# single animal type scores highest (recreating T8.22's original
# 18-BUY_ANIMAL-orders bug from this other code path) without max_
# animals_per_type also excluding already-capped types from _top_animal_
# choice's own ranking - see the gating block in decide() for how both
# pieces combine.
#
# **Measured a strong win rate, then REJECTED on a stricter guardrail, not
# on win rate** (tools/measure_t843_stage2.py/trace_t843_stage2.py):
# target_count=3 (all three animal types, cap left at its shipped 1) won
# decisively on self-play - working 86% (43W/7L/0T), holdout 83.5%
# (167W/33L/0T), Wilson [0.777, 0.880] - and traced cleanly (reaches
# GOOSE+SHEEP+COW by day 3 in every traced seed, wins on final money in
# all 5). But test_no_animal_escapes_across_the_golden_seeds (T8.38's own
# never-re-recordable guardrail) then found **30 real animal escapes
# across the 6 golden seeds** at target_count=3 (zero at target_count=1)
# - that guardrail's own explicit rule makes an escape disqualifying
# regardless of win rate, so this was reverted despite the strong number.
# Root cause, verified structurally in code, not just inferred from the
# count: _WHEAT_FEED_RESERVE (10 above) and wheat_restock_threshold/
# wheat_restock_qty (5/10) are all flat constants sized for "at most 1
# animal" (the only case that ever existed before this task) - three
# animals with different feed schedules (GOOSE interval=1, SHEEP
# interval=3, COW interval=2) roughly triple simultaneous feed demand
# with no matching scale-up, causing recurring consecutive_unfed>=2
# escapes, especially before hiring ramps up early game. Kept available
# (tested, default 1 - bit-identical to every pre-T8.43 caller) for a
# future revisit once the feed-supply chain itself scales with animal
# count - a concrete, named next step, not built here.
_DEFAULT_ALWAYS_PURSUE_ANIMAL_TARGET_COUNT = 1

# T8.18: verified directly against kaggriculture.py that PICKUP has no
# structural prerequisite at all - only PLACE genuinely needs both an
# animal in hand and a matching built structure. The shipped serial
# if/elif chain in tasks._new_investment_tasks checks "no structure yet"
# before PICKUP's own readiness, wasting a real, available second labor
# unit (Stage B's now-shipped hires_per_day>=1) that could do BUILD_* and
# PICKUP the same turn. Default False reproduces the exact prior serial
# pipeline - a mechanism change gated the same way as every other
# tunable here, for a clean accept/reject even though the "off" behavior
# is arguably just a latent bug.
_DEFAULT_PARALLEL_ANIMAL_ACQUISITION = False

# T8.39: the user's own concern - the farmer is the *only* unit allowed
# to FEED an animal or PICKUP its wheat (tasks._PINNED_UNIT_INDEX), so a
# busy farmer leaves a needy animal unfed even with a free hand standing
# right next to it. Verified directly against kaggriculture.py: the real
# FEED/PICKUP handlers never check which unit acts - the pin exists
# purely because decide() historically modeled only inventories[0]. When
# on: the WHEAT-holding scan (tasks.build_task_list's own docstring) and
# the aggregate wheat PICKUP both widen from "unit 0 only" to "any unit"
# - a single mechanism, not two independently-gated ones (see that
# docstring for why the WHEAT scan specifically needs gating at all,
# unlike FERTILIZE/PLACE's own always-on multi-unit awareness). The
# *animal* PICKUP/PLACE pipeline stays pinned to the farmer regardless -
# a deliberate scope limit, not covered by this flag (see tasks.
# _new_investment_tasks's own docstring). Default False, bit-identical to
# every pre-T8.39 caller - not yet measured in self-play.
_DEFAULT_FEED_PICKUP_UNPINNED = False

# T8.41: the user's own follow-up - "any action pinned only to the
# farmer is a scaling bottleneck." Grepping every unit_index/
# _PINNED_UNIT_INDEX use in tasks.py found exactly one action T8.39 left
# out of scope: the animal PICKUP (tasks._PINNED_UNIT_INDEX, still
# unconditionally pinned). Mirrors feed_pickup_unpinned's own mechanism
# for that one remaining pipeline - see tasks._new_investment_tasks's
# own docstring. Default False, bit-identical to every pre-T8.41 caller.
_DEFAULT_ANIMAL_PICKUP_UNPINNED = False

# T8.41, the user's own observation: once an animal is bought, preparing
# its place and installing it should outrank ordinary map work, tracked
# for hired hands too, so a "picked up but never placed" animal doesn't
# sit idle in a busy turn. Verified directly, not assumed: BUILD_COOP/
# BUILD_PASTURE/animal-PICKUP/PLACE are all emitted at tasks.PRIORITY_
# PLANT - the same tier as ordinary crop planting - and assign_units
# resolves tiers strictly in order, consuming free_units as it goes, so
# this pipeline gets zero free units whenever tiers 0-2 (PREVENT_LOSS/
# HARVEST/ROUTINE_CARE) already used them all, the expected case on a
# farm busy enough to need extra hands. When on, these tasks are emitted
# at tasks.PRIORITY_ANIMAL_SETUP instead (between HARVEST and ROUTINE_
# CARE) - see that constant's own comment for why it still yields to
# PREVENT_LOSS (an unplaced animal isn't at risk the way a genuine
# prevent-loss target is). Default False, bit-identical to every
# pre-T8.41 caller.
_DEFAULT_PRIORITIZE_ANIMAL_SETUP = False

# T8.43, the user's own observation, confirmed as a real ranking/task-
# layer inconsistency, not just a calibration question: strategy._crop_
# yield_and_tile_days (the layer that decides a one-time crop is worth
# planting) already scores it assuming the *full* watering_bonus_window
# gets watered before harvest (growth.forecast_one_time_yield). But
# tasks._is_actually_harvestable has always proposed HARVEST the instant
# a crop is legally harvestable (current_day - planted_day >= first_
# yield_day), forfeiting that assumed bonus yield entirely for WHEAT/
# CARROT (whose bonus windows start at/after first_yield_day - zero
# bonus days ever realized) while leaving MELON (window mostly precedes
# its own first_yield_day) largely unaffected - see that function's own
# docstring for the full mechanism. When on, a one-time crop instead
# waits for current_day - planted_day >= max_yield_day (the bonus
# window's own end) or yield_units already at max_yield (already
# capped).
#
# **Measured (tools/measure_t843.py): 0.300 win rate (15W/12L/23T, n=50)
# - not a clearing accept_candidate result on its own (mostly ties, since
# WHEAT/CARROT are rarely top-ranked under current play - the mechanism
# doesn't even activate in most games), but 15W/12L (0.556) where it does
# activate, and bit-identical (a tie) whenever it doesn't. Enabled by the
# user's own explicit decision, 2026-09-19: "Включи вторую версию 1 этапа
# по умолчанию. Она не ухудшает ситуацию, но потенциально может улучшить
# если использовать эти культуры" - a deliberate call to ship a
# no-worse/possibly-better mechanism ahead of a full n=200 holdout
# confirmation, not a project-default acceptance verdict.**
_DEFAULT_DEFER_ONE_TIME_HARVEST_TO_MAX_YIELD = True

# T8.44 (day-plan-driven dynamic hiring, the user's own follow-up after
# T8.43 Stage 3's mechanical proof of `workload_forecast_hiring_aware`'s
# own formula's unreachable-past-8 ceiling): the planned-new-work terms
# `kagg.policy.strategy.hires_per_day`'s new `day_plan_hiring_aware`
# branch adds to `maintenance_actions_today` (the tile-scan's own
# real per-tile-today sum, via `kagg.policy.tasks.crop_tile_day_actions`/
# `animal_tile_day_actions`). `day_plan_max_new_tiles_per_day` guards
# against forecasting the *entire* free board getting planted in one day
# (25 - one quadrant, the same unit this session's hand calculations were
# done in); `day_plan_new_tiles_cash_aware` additionally caps the
# planned-new-tiles count by what's actually affordable (seeds already
# held plus what today's money can buy), so a freshly-opened, still-broke
# quadrant doesn't forecast phantom work it can't fund. Both default to
# values that keep the mechanism physically honest once
# `day_plan_hiring_aware` is turned on - see that flag's own comment
# (kagg.policy.strategy) for why the flag itself defaults off.
_DEFAULT_DAY_PLAN_MAX_NEW_TILES_PER_DAY = 25
_DEFAULT_DAY_PLAN_NEW_TILES_CASH_AWARE = True

# T8.44 follow-up: a fresh crop tile's own PLANT+WATER cost, reused for a
# just-dug WEED tile's own near-term follow-up work (see the tile-scan's
# own WEED branch, and `day_plan_weed_replant_aware`'s comment there) -
# duplicated here (not imported from `strategy.py`, which defines the
# identical `day_plan_new_crop_tile_actions` default for its own use in
# the planned-new-work multiplier) purely so this module's own tile scan
# doesn't need a cross-module default import for one shared literal;
# both read the same `"day_plan_new_crop_tile_actions"` params key, so a
# caller who sweeps it gets a consistent value in both places regardless.
_DEFAULT_DAY_PLAN_NEW_CROP_TILE_ACTIONS = 2.0
_DEFAULT_DAY_PLAN_WEED_REPLANT_AWARE = True

# T8.44: a same-day quadrant top-up hire is only worth emitting if enough
# turns remain today for the new hand to be productive - `hire_min_turns_
# left` gates the HIRE-emission loop below on `turns_per_day -
# current_hour >= hire_min_turns_left`, except when `hires_today == 0`
# (a deliberate escape hatch: never leave the farm with zero labor for a
# whole day just because the gate would otherwise block the day's very
# first hire - see the loop's own comment). Default 0 (bit-identical -
# the gate always passes).
_DEFAULT_HIRE_MIN_TURNS_LEFT = 0

# T8.44: independently re-verified line-by-line against this module's own
# order-construction code - `sell_max_orders` already reserves room
# against `len(hires)`, but `tail` (BUY_SEED/BUY_ANIMAL/BUY_LAND/wheat
# restock) has no such reservation, and `market = (hires + sells +
# tail)[:_MAX_MARKET_ORDERS]` puts `hires` first - so a `target_hires`
# above roughly `_MAX_MARKET_ORDERS` would silently drop every `tail`
# order that turn without a dedicated cap. Matches `_MAX_MARKET_ORDERS`
# by default (bit-identical - the shipped `max_hires_per_day=8` already
# never reaches this cap in practice, but `day_plan_hiring_aware` is
# specifically designed to be able to exceed 8 on a burst day).
_DEFAULT_MAX_HIRE_ORDERS_PER_TURN = _MAX_MARKET_ORDERS

# T8.6 (tasks/plan.md): parallel planting + batched seed purchase - lets
# `plant_qty` scale with the real labor force (1 + hires_per_day) instead
# of a hardcoded "one PLANT task per turn" baked in since Phase 3.
# Chosen, per the plan's own design, so labor_units=1 (today's shipped
# hires_per_day=0) reproduces exactly today's behavior:
#   - max_plants_per_unit=100 (the board size - structurally unreachable
#     at labor_units=1, a real but not-yet-binding safety valve against
#     planting more than the labor force can water; a tile weeds at
#     consecutive_unwatered>=2, converting unwaterable excess planting
#     into MAINTENANCE-tier DIG work).
#   - max_plant_tasks_per_turn=8 (a flat per-turn cap, independent of
#     labor_units).
#   - seed_buffer_per_unit=1 (how many seeds of the target crop to try to
#     keep on hand per labor unit, so a burst of parallel planting next
#     turn doesn't stall on a just-in-time single-seed purchase).
#   - seed_cash_reserve=0 (dollars to leave unspent when batch-buying
#     seed - a no-op floor by default).
# None of these four are tuned yet - see kagg.policy.decide's own
# plant_qty/seed-purchase comments for the exact formulas.
_DEFAULT_MAX_PLANTS_PER_UNIT = 100
_DEFAULT_MAX_PLANT_TASKS_PER_TURN = 8
_DEFAULT_SEED_BUFFER_PER_UNIT = 1
_DEFAULT_SEED_CASH_RESERVE = 0

# T8.45 (the user's own request, after a per-hour trace of day 0 showed
# only 21 of 24 planned tiles got planted despite 33 idle unit-turns): the
# T8.6 seed formula above (`labor_units * seed_buffer_per_unit`, ~5 seeds
# at a time) restocks a handful per turn, so by the end of a big planting
# day the farm runs out of physical seeds while hands stand idle - the
# hiring forecast (T8.44) and the seed purchase were two independent
# mechanisms and the second never knew the first's ambition. `bulk_seed_
# purchase` (default False, bit-identical) sizes the purchase from the
# real number of tiles about to be planted instead: `ceil(tiles *
# (1 + bulk_seed_buffer_fraction))` in total across *all* basket crops,
# minus every basket seed already on hand (see `market.bulk_purchase_
# plan`). `bulk_animal_purchase` does the same for animals (target = the
# planned-animal count already computed for the day-plan forecast,
# minus animals already bought and waiting in the shed/inventory;
# `bulk_animal_buffer_fraction` rounds *down*, so a buffer that can't fill
# a whole animal buys nothing extra). `bulk_purchase_max_new_tiles` caps
# how many tiles a single plan covers (one quadrant). `plant_while_
# animal_pending` (default False) lifts the old rule that a bought-but-
# unplaced animal (`stuck_animal`) blocks *all* crop planting and seed
# buying until it is placed - the traced cause of the day-0 morning
# stall (4 hands PASSing for hours 2-3 while one farmer built/picked up/
# placed a single animal).
_DEFAULT_BULK_SEED_PURCHASE = True
_DEFAULT_BULK_SEED_BUFFER_FRACTION = 0.10
_DEFAULT_BULK_ANIMAL_PURCHASE = True
_DEFAULT_BULK_ANIMAL_BUFFER_FRACTION = 0.0
_DEFAULT_BULK_PURCHASE_MAX_NEW_TILES = 25
_DEFAULT_PLANT_WHILE_ANIMAL_PENDING = True
# T8.46 (the user's own idea, after T8.45's trace showed 17 MELON seeds
# bought at price 260 and stranded because the agent's own drip-sale of the
# 89 harvested melons on the shed dragged MELON to ~190 - level with
# STRAWBERRY - eight turns later): the ranking is computed from the market
# *before* this turn's own sale is priced in, and an agent cannot query
# prices mid-turn (`decide()` returns every order at once; the engine
# settles them afterwards and the new prices appear in the *next*
# observation). Two-step fix: when this turn's sale of crop products
# (WHEAT/CARROT/TOMATO/STRAWBERRY/MELON) is at least this many units, send
# no BUY_SEED this turn - the following turn's observation already carries
# the real post-sale prices, and the ranking/bulk plan run on those.
# 0 = off (bit-identical). Meant to be paired with a large
# `drip_sell_max_per_turn` (the sell-everything-at-once half of the idea).
_DEFAULT_DEFER_SEED_PURCHASE_ON_CROP_SALE = 0

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

# T8.19: 1 (the single top-ranked crop) reproduces the exact prior
# behavior for every caller that doesn't set it - see _top_crop_basket's
# own docstring for the mechanism and decide()'s own portfolio_basket_
# size comment for how a value >1 changes new PLANT commitments.
_DEFAULT_PORTFOLIO_BASKET_SIZE = 1


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


def _crop_tile_counts(tiles) -> dict[str, int]:
    """How many PLANT tiles of each crop currently exist on the farm -
    T8.3f's input to `rank_portfolio`'s self-impact pricing (see its own
    docstring): a *new* tile's marginal value must be priced as if the
    farm's existing commitment to that crop already landed, not from a
    pristine market snapshot.
    """
    counts: dict[str, int] = {}
    for row in tiles:
        for tile in row:
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                crop = tile.get("crop")
                counts[crop] = counts.get(crop, 0) + 1
    return counts


def _combined_crop_tile_counts(my_tiles, other_farms, opponent_weight: float = 1.0) -> dict[str, float]:
    """`_crop_tile_counts(my_tiles)`, plus every farm in `other_farms`
    counted at `opponent_weight` (T8.3g extends T8.3f's own-farm-only
    scan to include the opponent; T8.3h makes that weight graduated
    instead of all-or-nothing - see both modules' own history below).

    Verified directly in kaggriculture.py (not assumed): `obs["farms"]`
    is one shared list object, assigned identically to every player's
    observation (`_initialize`/`interpreter` both copy the *same* list,
    never a per-player copy) - so the opponent's tiles (crop, planted
    day, watered status, everything) are exactly as visible as our own.
    Only `private` (shed/seeds) is genuinely per-player and stays out of
    reach. A tile the opponent already has growing pushes the same
    shared market inventory down just as surely as one of our own once
    it's harvested and sold (`kagg.gamelib.market.price` and the real
    market don't distinguish whose SELL order moved the inventory) - so
    ownership wouldn't matter at all, only quantity, *if* we knew exactly
    when the opponent's tile will actually be harvested and sold.

    `opponent_weight` (T8.3h, the user's own proposed refinement) exists
    precisely because we don't: T8.3g measured that treating a visible
    opponent tile as if its full remaining yield stacks directly on top
    of our own (`opponent_weight=1.0`) is a real, decisive net loss (0/50
    both self-play blocks) - traced to premature crop abandonment, since
    an opponent's tile carries no timing information (real age, expected
    harvest day) the way our *own* tiles do (we control our own planting
    schedule, so our own tiles are naturally time-clustered with our next
    one; the opponent's aren't). Our own tiles always count at full
    weight (1.0, unconditionally) - only the opponent's contribution is
    ever discounted.
    """
    combined: dict[str, float] = dict(_crop_tile_counts(my_tiles))
    for farm in other_farms:
        for crop, n in _crop_tile_counts(farm["tiles"]).items():
            combined[crop] = combined.get(crop, 0) + opponent_weight * n
    return combined


def _top_investment_choice(
    market_inventory: dict,
    current_day: int,
    params: dict,
    crop_tile_counts: dict | None = None,
    unlocked_shops: list | None = None,
    net_of_seed_cost: bool = False,
) -> tuple[str, str] | None:
    """The highest-ranked crop-or-animal that still has time to mature
    this season, as `(name, kind)` with `kind` "crop" or "animal". `None`
    if nothing does - late enough in the season, forcing a choice would
    only ever waste capital on something that can't pay off.

    Generalizes the old crop-only `_top_crop_choice` (T3.5) to rank
    animals too (T6.1) - see the module docstring for the real, temporary
    gap this opens until T6.2/T6.3 wire actual animal acquisition into
    tasks.py/market.py.

    `crop_tile_counts` (T8.3f), `unlocked_shops` (T8.3i), and
    `net_of_seed_cost` (T8.3k) are all passed straight through to
    `score_portfolio` - see its own docstring. `rank_season_aware`/
    `animal_net_of_cost`/`animal_fertilizer_income_aware` (T8.3m/T8.3q) are
    read from `params` here (not taken as their own arguments, unlike the
    others) since the first two also govern `days_remaining` itself,
    computed once from the same `season_length_days` this function
    already needs for the maturity checks below.

    `investment_commit_margin` (T8.14, the user's own follow-up after
    T8.10's rejection): an ANIMAL candidate is only ever returned once its
    score clears `best_crop_score * (1 + investment_commit_margin)` -
    otherwise it's skipped (as if it hadn't qualified) and the walk
    continues to the next candidate. Scoped to animals only, matching the
    exact failure T8.10 traced: buying an animal is a real, effectively
    irreversible commitment (`stuck_animal` then finishes acquiring it
    regardless of what the ranking says next turn), while a crop-to-crop
    reordering costs at most one seed purchase - so only the animal side
    needs protection from a razor-thin, single-turn lead that a routine
    intraday market wobble could flip. `best_crop_score` is computed once
    (the highest crop score in the same `score_portfolio` call, regardless
    of maturity - the margin is about *score* separation, not about which
    crop would ultimately be picked) rather than per-animal-candidate,
    since it doesn't change while walking the same ranking. Defaults to
    `0.0` (no margin - any animal that's simply ahead qualifies, exactly
    the pre-T8.14 behavior for every caller that doesn't set it).
    """
    season_length_days = params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS)
    rank_season_aware = params.get("rank_season_aware", _DEFAULT_RANK_SEASON_AWARE)
    animal_net_of_cost = params.get("animal_net_of_cost", _DEFAULT_ANIMAL_NET_OF_COST)
    animal_fertilizer_income_aware = params.get(
        "animal_fertilizer_income_aware", _DEFAULT_ANIMAL_FERTILIZER_INCOME_AWARE
    )
    animal_care_aware = params.get("animal_care_aware", _DEFAULT_ANIMAL_CARE_AWARE)
    animal_consumption_horizon_aware = params.get(
        "animal_consumption_horizon_aware", _DEFAULT_ANIMAL_CONSUMPTION_HORIZON_AWARE
    )
    investment_commit_margin = params.get("investment_commit_margin", _DEFAULT_INVESTMENT_COMMIT_MARGIN)
    days_remaining = season_length_days - current_day if (rank_season_aware or animal_net_of_cost) else None
    scores = score_portfolio(
        market_inventory, crop_tile_counts, unlocked_shops, net_of_seed_cost,
        days_remaining, rank_season_aware, animal_net_of_cost, animal_fertilizer_income_aware,
        animal_care_aware, animal_consumption_horizon_aware,
    )
    best_crop_score = max(scores[c] for c in CROPS)
    for name in sorted(scores, key=scores.__getitem__, reverse=True):
        if name in CROPS:
            if _crop_has_time_to_mature(name, current_day, season_length_days):
                return name, "crop"
        elif name in ANIMALS:
            if scores[name] < best_crop_score * (1 + investment_commit_margin):
                continue
            if _animal_has_time_to_mature(name, current_day, season_length_days):
                return name, "animal"
    return None


def _top_animal_choice(
    market_inventory: dict, current_day: int, params: dict, excluded_types: frozenset[str] = frozenset()
) -> str | None:
    """The highest-scoring animal that still has time to mature this
    season, as a plain animal name - `None` if none does.

    T8.31 Stage 1: unlike `_top_investment_choice`, this ranks animals in
    complete isolation - never compared against `best_crop_score` at
    all. Exists for `always_pursue_one_animal` (see that param's own
    comment and the gating block in `decide()` that uses it), a caller
    that has already decided an animal is wanted regardless of how it
    stacks up against the crop ranking. T8.31 Stage 0 (see
    tasks/todo.md) measured that loosening `investment_commit_margin`
    cannot fix this: even the widest margin tested (-0.5) produced zero
    behavioral change across 400 self-play games, because the real score
    gap to a strong crop like MELON is far too wide (roughly -80% margin
    needed to flip, an economically extreme value) - so the fix decouples
    animal acquisition from the single top-investment ranking entirely
    rather than trying to force that ranking to flip.

    Reads the same `params` entries `_top_investment_choice` reads for
    its own animal branch of `score_portfolio` (`animal_net_of_cost`/
    `animal_fertilizer_income_aware`/`animal_care_aware`/`animal_
    consumption_horizon_aware`/`rank_season_aware`) - identical
    economics, just no crop-score comparison gate. `crop_tile_counts`/
    `unlocked_shops`/`net_of_seed_cost` are irrelevant here (they only
    affect crop scores, which this function never reads) so they're
    passed as `None`/`False` rather than threaded through as arguments.

    `excluded_types` (T8.43): animal names to skip entirely, regardless
    of score - the caller's own `max_animals_per_type`-capped types, once
    `always_pursue_animal_target_count` lets this function be asked for a
    *second* (or later) animal. Without this, raising the target count
    alone would just re-buy unlimited copies of whichever single type
    scores highest (recreating T8.22's original 18-BUY_ANIMAL-orders bug
    from this other code path), never actually diversifying. Empty by
    default, bit-identical to every pre-T8.43 caller.
    """
    season_length_days = params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS)
    rank_season_aware = params.get("rank_season_aware", _DEFAULT_RANK_SEASON_AWARE)
    animal_net_of_cost = params.get("animal_net_of_cost", _DEFAULT_ANIMAL_NET_OF_COST)
    animal_fertilizer_income_aware = params.get(
        "animal_fertilizer_income_aware", _DEFAULT_ANIMAL_FERTILIZER_INCOME_AWARE
    )
    animal_care_aware = params.get("animal_care_aware", _DEFAULT_ANIMAL_CARE_AWARE)
    animal_consumption_horizon_aware = params.get(
        "animal_consumption_horizon_aware", _DEFAULT_ANIMAL_CONSUMPTION_HORIZON_AWARE
    )
    days_remaining = season_length_days - current_day if (rank_season_aware or animal_net_of_cost) else None
    scores = score_portfolio(
        market_inventory, None, None, False,
        days_remaining, rank_season_aware, animal_net_of_cost, animal_fertilizer_income_aware,
        animal_care_aware, animal_consumption_horizon_aware,
    )
    for name in sorted(ANIMALS, key=scores.__getitem__, reverse=True):
        if name in excluded_types:
            continue
        if _animal_has_time_to_mature(name, current_day, season_length_days):
            return name
    return None


def _top_crop_basket(
    market_inventory: dict,
    current_day: int,
    params: dict,
    crop_tile_counts: dict | None = None,
    unlocked_shops: list | None = None,
    net_of_seed_cost: bool = False,
    basket_size: int = 1,
    wheat_feed_units_needed: int = 0,
) -> list[str]:
    """Generalizes `_top_crop_choice` (T8.19, the user's own observation:
    committing every new tile to a single top-ranked product invites a
    double price-crash risk - our own volume plus a plausible independent
    opponent bet on the same good) to return up to `basket_size` distinct
    maturing crop names, in rank order, instead of just the first.

    At `basket_size=1` (the default) this returns exactly what
    `_top_crop_choice` would, as `[name]` or `[]` - see that function's
    own docstring (now a thin wrapper around this one) for the ranking/
    margin details both share. `decide()` uses the result to round-robin
    new PLANT commitments across the basket instead of concentrating them
    in the single top pick - see its own `portfolio_basket_size` comment.

    `wheat_feed_units_needed` (T8.24, the user's own follow-up): passed
    straight through to `rank_portfolio`'s own `wheat_feed_units_needed`
    - see `wheat_feed_credit_per_tile_day`'s own docstring for the
    mechanism. `decide()` computes the real value (0 when no animal is
    placed or pursued, or `wheat_self_sufficiency_aware` is off) - this
    function only needs to read `wheat_self_sufficiency_aware` itself
    from `params` (the same "flag gates whether the number is used at
    all" convention every other animal-awareness flag here follows).
    Defaults to `0`, reproducing the exact prior WHEAT ranking for every
    caller that doesn't pass it, regardless of the flag.
    """
    season_length_days = params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS)
    rank_season_aware = params.get("rank_season_aware", _DEFAULT_RANK_SEASON_AWARE)
    animal_net_of_cost = params.get("animal_net_of_cost", _DEFAULT_ANIMAL_NET_OF_COST)
    animal_fertilizer_income_aware = params.get(
        "animal_fertilizer_income_aware", _DEFAULT_ANIMAL_FERTILIZER_INCOME_AWARE
    )
    animal_care_aware = params.get("animal_care_aware", _DEFAULT_ANIMAL_CARE_AWARE)
    animal_consumption_horizon_aware = params.get(
        "animal_consumption_horizon_aware", _DEFAULT_ANIMAL_CONSUMPTION_HORIZON_AWARE
    )
    wheat_self_sufficiency_aware = params.get(
        "wheat_self_sufficiency_aware", _DEFAULT_WHEAT_SELF_SUFFICIENCY_AWARE
    )
    days_remaining = season_length_days - current_day if (rank_season_aware or animal_net_of_cost) else None
    basket: list[str] = []
    for name in rank_portfolio(
        market_inventory, crop_tile_counts, unlocked_shops, net_of_seed_cost,
        days_remaining, rank_season_aware, animal_net_of_cost, animal_fertilizer_income_aware,
        animal_care_aware, animal_consumption_horizon_aware,
        wheat_self_sufficiency_aware, wheat_feed_units_needed,
    ):
        if name in CROPS and _crop_has_time_to_mature(name, current_day, season_length_days):
            basket.append(name)
            if len(basket) >= basket_size:
                break
    return basket


def _top_crop_choice(
    market_inventory: dict,
    current_day: int,
    params: dict,
    crop_tile_counts: dict | None = None,
    unlocked_shops: list | None = None,
    net_of_seed_cost: bool = False,
) -> str | None:
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

    `rank_season_aware`/`animal_net_of_cost` (T8.3m) are read from
    `params` and passed through exactly like `_top_investment_choice`
    does, for the same reason (this ranks the full portfolio too, even
    though only the crop entries are ever returned) - see that
    function's own comment.

    T8.19: now a thin wrapper around `_top_crop_basket(..., basket_size=
    1)` - a pure refactor, bit-identical output, see that function's own
    docstring for the shared mechanism.
    """
    basket = _top_crop_basket(
        market_inventory, current_day, params, crop_tile_counts, unlocked_shops, net_of_seed_cost,
        basket_size=1,
    )
    return basket[0] if basket else None


def decide(obs: dict, params: dict) -> dict:
    """This turn's full action dict, combining the strategic, task, and
    market layers."""
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    seeds = private.get("seeds", {})
    shed = private.get("shed", {})
    # Moved up from its old spot below the crop-basket call (T8.24): a
    # single trivial dict lookup, no ordering dependency on anything
    # computed in between - needed early now so the WHEAT feed-demand
    # check just below can read it. Index 0 is always the farmer's own
    # inventory - see its own fuller comment at its original use site
    # further down (PLACE/FEED/PICKUP's real handlers, tasks._PINNED_
    # UNIT_INDEX).
    farmer_inventory = (private.get("inventories") or [{}])[0]

    current_day = obs.get("day", 0)
    current_hour = obs.get("hour", 0)
    if params.get("crop_self_impact_aware", _DEFAULT_CROP_SELF_IMPACT_AWARE):
        other_farms = [f for i, f in enumerate(obs["farms"]) if i != player]
        opponent_weight = params.get(
            "crop_self_impact_opponent_weight", _DEFAULT_CROP_SELF_IMPACT_OPPONENT_WEIGHT
        )
        crop_tile_counts = _combined_crop_tile_counts(me["tiles"], other_farms, opponent_weight)
    else:
        crop_tile_counts = None
    unlocked_shops = (
        obs.get("town", {}).get("unlocked_shops", [])
        if params.get("crop_shop_demand_aware", _DEFAULT_CROP_SHOP_DEMAND_AWARE)
        else None
    )
    net_of_seed_cost = params.get("crop_net_of_seed_cost", _DEFAULT_CROP_NET_OF_SEED_COST)
    investment = _top_investment_choice(
        obs["market"]["inventory"], current_day, params, crop_tile_counts, unlocked_shops, net_of_seed_cost
    )
    desired_name, desired_kind = investment if investment is not None else (None, None)
    desired_crop = desired_name if desired_kind == "crop" else None
    desired_animal = desired_name if desired_kind == "animal" else None

    # T8.24, the user's own follow-up: real WHEAT feed-demand signal for
    # _top_crop_basket's own wheat_feed_units_needed, computed here since
    # it needs to exist before that call (below) - deliberately NOT the
    # full six-purpose tile scan further down (placed_animal_type_counts
    # etc.) to avoid reordering that scan's own dependencies; a small,
    # single-purpose check instead. "An animal exists in some form" means
    # any of: this turn's top investment choice is itself an animal
    # (desired_animal, already computed above - pursuit is starting
    # *this* turn even before any tile/shed state reflects it), an
    # animal already bought and awaiting BUILD/PICKUP/PLACE (shed or
    # farmer_inventory), or an animal already placed and alive (a tile
    # with an "animal" key) - matches feed_needed's own later, similar
    # definition as closely as this early a call site allows. One WHEAT
    # unit covers exactly one FEED day (kaggriculture.py's fixed rate),
    # so the full remaining season is the real horizon of feed-days to
    # credit against, uncapped by any single tile's own yield (`wheat_
    # feed_credit_per_tile_day` caps that itself).
    wheat_self_sufficiency_aware = params.get(
        "wheat_self_sufficiency_aware", _DEFAULT_WHEAT_SELF_SUFFICIENCY_AWARE
    )
    if wheat_self_sufficiency_aware:
        has_animal_context = (
            desired_animal is not None
            or any(shed.get(a, 0) > 0 or farmer_inventory.get(a, 0) > 0 for a in ANIMALS)
            or any(
                isinstance(tile, dict) and "animal" in tile
                for row in me["tiles"] for tile in row
            )
        )
        wheat_feed_units_needed = (
            max(0, params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS) - current_day)
            if has_animal_context else 0
        )
    else:
        wheat_feed_units_needed = 0

    # T8.9, opt-in (see _top_crop_choice's own docstring for why this
    # isn't the default despite fixing a real bug): when enabled, the
    # crop(s) to plant/buy-seed-for are the best crop(s) the market
    # supports *regardless* of whether an animal separately ranks first
    # overall. Only re-ranks crops alone when the overall top choice is
    # itself an animal; when it's already a crop, `desired_crop` IS the
    # best crop, so `_top_crop_basket`'s own ranking (crops-only, same
    # score_portfolio call) would find the identical top entry anyway -
    # this just calls it once rather than recomputing.
    #
    # T8.19, the user's own observation: committing every new tile to
    # the single top pick invites a double price-crash risk (our own
    # volume plus a plausible independent opponent bet on the same good)
    # - portfolio_basket_size (default 1, bit-identical) asks for more
    # than one qualifying crop here, round-robined below instead of all
    # going to fallback_crops[0].
    portfolio_basket_size = params.get("portfolio_basket_size", _DEFAULT_PORTFOLIO_BASKET_SIZE)
    if desired_crop is not None or params.get(
        "plant_while_pursuing_animal", _DEFAULT_PLANT_WHILE_PURSUING_ANIMAL
    ):
        fallback_crops = _top_crop_basket(
            obs["market"]["inventory"], current_day, params, crop_tile_counts, unlocked_shops,
            net_of_seed_cost, basket_size=portfolio_basket_size,
            wheat_feed_units_needed=wheat_feed_units_needed,
        )
    else:
        fallback_crops = []
    fallback_crop = fallback_crops[0] if fallback_crops else None
    have_seed = fallback_crop is not None and seeds.get(fallback_crop, 0) > 0
    plant_crop = fallback_crop if have_seed else None
    # farmer_inventory itself is defined up near shed/seeds now (T8.24
    # needed it earlier, before the crop-basket call above) - see that
    # definition's own comment for the indexing convention and why index
    # 0 is correct by construction (tasks._PINNED_UNIT_INDEX).

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
    # T8.44: read here, before the six-purpose tile scan below, instead of
    # after it (their pre-T8.44 location, just before build_task_list) -
    # pure dict-lookup reordering, bit-identical - so the scan can use
    # them to accumulate maintenance_actions_today via crop_tile_day_
    # actions/animal_tile_day_actions (both need use_fertilizer/care_
    # aware/defer_one_time_harvest_to_max_yield to match whatever this
    # episode actually has turned on).
    use_fertilizer = params.get("use_fertilizer", _DEFAULT_USE_FERTILIZER)
    care_aware = params.get("animal_care_aware", _DEFAULT_ANIMAL_CARE_AWARE)
    defer_one_time_harvest_to_max_yield = params.get(
        "defer_one_time_harvest_to_max_yield", _DEFAULT_DEFER_ONE_TIME_HARVEST_TO_MAX_YIELD
    )
    # One scan covers seven questions at once: which animal types are
    # already placed (stuck/already-have-one logic above), whether any
    # empty tile exists at all, which structure kinds already sit empty
    # (T6.5: BUY_SEED/BUY_ANIMAL shouldn't fire with nowhere to use them -
    # a full farm just accumulates unused seeds/animals), how much
    # unlocked land is free and how far the nearest free tile is from the
    # shed (T8.3, should_buy_land's occupancy-aware gates), how many tiles
    # are already committed to a plant - the real denominator plant_
    # budget needs to know how much more planting the current labor force
    # can still take on - (T8.6), and (T8.44) the real total actions
    # every already-placed tile needs *today*, for the day-plan hiring
    # forecast (`maintenance_actions_today`, summed via `crop_tile_day_
    # actions`/`animal_tile_day_actions` - see `kagg.policy.strategy.
    # hires_per_day`'s own `day_plan_hiring_aware` docstring). A WEED tile
    # (a real category this scan never distinguished before T8.44 - it
    # fell through to the bare `unlocked_tiles += 1` below, uncounted
    # beyond that) costs exactly one DIG (`kagg.policy.tasks.build_task_
    # list`'s own WEED handling), counted here too.
    # Computed here, early - `unlocked_quadrants` doesn't depend on the
    # tile scan below - purely to avoid a second, later read for
    # `n_unlocked_extra` (land-purchase gating, further below, which is
    # `len(...) - 1`). A quadrant-count-aware day-plan hiring lookup was
    # tried here too (T8.44 follow-up) and reverted - see `strategy.
    # hires_per_day`'s own docstring/neighbor-constant comment for the
    # measured regression that caused the revert.
    n_quadrants = len(me.get("unlocked_quadrants", ["NW"]))
    # T8.44 follow-up: a real, hand-verified per-tile action cost this
    # session's own trace found missing, not assumed - kaggriculture.py's
    # real DIG handler clears a WEED tile straight to `None` (does NOT
    # restore a plant), so keeping a weeded tile productive needs a
    # follow-up PLANT+WATER right after DIG, not just the DIG itself.
    # Reuses `day_plan_new_crop_tile_actions` (the same PLANT+WATER cost a
    # fresh tile already costs elsewhere in this forecast) rather than a
    # separately-swept constant, since it's the identical follow-up work.
    weed_replant_aware = params.get(
        "day_plan_weed_replant_aware", _DEFAULT_DAY_PLAN_WEED_REPLANT_AWARE
    )
    weed_replant_actions = (
        params.get("day_plan_new_crop_tile_actions", _DEFAULT_DAY_PLAN_NEW_CROP_TILE_ACTIONS)
        if weed_replant_aware
        else 0
    )
    placed_animal_type_counts: dict[str, int] = {}
    free_tiles = 0
    unlocked_tiles = 0
    nearest_free_shed_distance: int | None = None
    empty_structure_kinds: set[str] = set()
    n_plant_tiles = 0
    n_weed_tiles = 0
    maintenance_actions_today = 0
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
                    placed_animal_type_counts[tile["animal"]] = (
                        placed_animal_type_counts.get(tile["animal"], 0) + 1
                    )
                    maintenance_actions_today += animal_tile_day_actions(tile, care_aware=care_aware)
                elif tile.get("kind") in ("COOP", "PASTURE"):
                    empty_structure_kinds.add(tile["kind"])
                elif tile.get("kind") == "PLANT":
                    n_plant_tiles += 1
                    maintenance_actions_today += crop_tile_day_actions(
                        tile,
                        current_day,
                        use_fertilizer=use_fertilizer,
                        defer_one_time_harvest_to_max_yield=defer_one_time_harvest_to_max_yield,
                    )
                elif tile.get("kind") == "WEED":
                    n_weed_tiles += 1
                    # 1 (DIG) + the follow-up PLANT+WATER once it's clear
                    # (weed_replant_actions is 0 when day_plan_weed_
                    # replant_aware is off - bit-identical -1 total).
                    maintenance_actions_today += 1 + weed_replant_actions
    has_empty_tile = free_tiles > 0
    # T8.45: see _DEFAULT_PLANT_WHILE_ANIMAL_PENDING's comment - when on,
    # a bought-but-unplaced animal no longer blocks crop planting/seed
    # buying (the animal pipeline itself is unchanged).
    animal_blocks_planting = stuck_animal is not None and not params.get(
        "plant_while_animal_pending", _DEFAULT_PLANT_WHILE_ANIMAL_PENDING
    )
    if stuck_animal is not None:
        acquisition_animal = stuck_animal
        if animal_blocks_planting:
            plant_crop = None  # finish the paid-for animal before starting a new crop too
    elif (
        desired_animal is not None
        and placed_animal_type_counts.get(desired_animal, 0)
        >= params.get("max_animals_per_type", _DEFAULT_MAX_ANIMALS_PER_TYPE)
    ):
        # A second real bug found the same way: even with the stuck-
        # animal fix above, decide() kept re-buying *another* instance of
        # the same top-ranked animal indefinitely - a live, well-fed,
        # already-producing COW is not "done" in _top_investment_choice's
        # eyes, so it commissioned a second one, then a third, forever.
        # T8.22 (the user's own request): count-based, not a flat "never
        # a second instance" ban - max_animals_per_type (default 1,
        # bit-identical) lets the arena find how many instances of one
        # animal type are actually worth pursuing, rather than assuming
        # the answer is always exactly one. Still stops *something* -
        # unconditionally chasing more copies forever with no cap at all
        # would just recreate the original 18-BUY_ANIMAL-orders bug this
        # gate was built to fix.
        acquisition_animal = None
    else:
        acquisition_animal = desired_animal
    have_animal_anywhere = acquisition_animal is not None and (
        shed.get(acquisition_animal, 0) > 0 or farmer_inventory.get(acquisition_animal, 0) > 0
    )

    # T8.31 Stage 1, the user's own follow-up after T8.29: _top_investment_
    # choice's single strict top-pick structurally almost never chooses an
    # animal (MELON scores ~119/tile-day at a fresh market vs COW's ~23 -
    # verified directly via score_portfolio - and self-impact decay is
    # scoped per-crop, not farm-wide, so the ranking always rotates to a
    # fresh crop type rather than ever being forced toward an animal).
    # Stage 0 (tasks/todo.md) measured that loosening investment_commit_
    # margin cannot fix this - even margin=-0.5 produced zero behavioral
    # change across 400 self-play games, the real score gap is far wider
    # than any plausible margin. always_pursue_one_animal (default False,
    # bit-identical for every caller that doesn't set it) decouples
    # animal acquisition from that ranking entirely instead: once the
    # normal ranking has had its turn above (stuck_animal/max_animals_
    # per_type-gated, exactly as before) and STILL left acquisition_
    # animal at None, and the farm has no animal anywhere in any form
    # (no placed tile of any type, nothing sitting in the shed or
    # farmer_inventory for any animal), pick the single best-scoring
    # animal via _top_animal_choice - scored on its own, never compared
    # against the crop ranking - and pursue it in parallel with whatever
    # plant_crop the crop ranking already picked (mirrors plant_while_
    # pursuing_animal's existing shape in the opposite direction: that
    # flag plants a crop while an animal is the top pick, this one buys
    # an animal while a crop is). have_animal_anywhere stays correctly
    # False below - the gating condition here already confirmed nothing
    # is pending for any animal type, this one included. Once
    # always_pursue_animal_target_count animals exist anywhere, this path
    # stops firing on its own (the gate's own condition goes False) -
    # stuck_animal/max_animals_per_type's existing "finish what's already
    # bought" logic take over exactly as today, unaffected.
    #
    # T8.43: generalizes the "at least one, ever" gate to a count (see
    # _DEFAULT_ALWAYS_PURSUE_ANIMAL_TARGET_COUNT's own comment) - bit-
    # identical at the default target_count=1, where `sum(...) < 1` is
    # exactly `not placed_animal_type_counts`. Types already at max_
    # animals_per_type's own cap are excluded from _top_animal_choice's
    # ranking, so a higher target count diversifies across types instead
    # of re-buying unlimited copies of whichever single type scores
    # highest.
    always_pursue_target_count = params.get(
        "always_pursue_animal_target_count", _DEFAULT_ALWAYS_PURSUE_ANIMAL_TARGET_COUNT
    )
    if (
        params.get("always_pursue_one_animal", _DEFAULT_ALWAYS_PURSUE_ONE_ANIMAL)
        and acquisition_animal is None
        and sum(placed_animal_type_counts.values()) < always_pursue_target_count
        and not any(shed.get(a, 0) > 0 or farmer_inventory.get(a, 0) > 0 for a in ANIMALS)
    ):
        max_animals_per_type = params.get("max_animals_per_type", _DEFAULT_MAX_ANIMALS_PER_TYPE)
        capped_types = frozenset(
            a for a in ANIMALS if placed_animal_type_counts.get(a, 0) >= max_animals_per_type
        )
        always_pursue_choice = _top_animal_choice(
            obs["market"]["inventory"], current_day, params, excluded_types=capped_types
        )
        if always_pursue_choice is not None:
            acquisition_animal = always_pursue_choice

    # T8.44: planned-new-work estimate for the day-plan hiring forecast
    # (`hires_per_day`'s `day_plan_hiring_aware` branch), computed here -
    # right after acquisition_animal/plant_crop are both finalized
    # (stuck_animal/max_animals_per_type/always_pursue_one_animal gating
    # above; the crop-basket fallback further below hasn't run yet, so
    # plant_crop is still a single crop string or None here - verified
    # directly against this function's own control flow, no circularity).
    #
    # T8.44 fix (2026-09-19, the user's own follow-up after seeing a
    # per-day trace of this forecast): uses `fallback_crop` here, not
    # `plant_crop`. `plant_crop` (just above, `fallback_crop if have_seed
    # else None`) stays `None` until a seed is *physically on hand* -
    # `have_seed` - which a fresh BUY_SEED order can't satisfy until next
    # turn (T8.5: market orders settle after this turn's unit actions).
    # `fallback_crop` itself is the ranking layer's already-computed
    # intent (real market prices already factored in via `_top_crop_
    # basket`), available with zero seeds held - gating the forecast on
    # `plant_crop` silently blinded it to that already-known intent on
    # day 0 (or any day starting from zero seed stock of the target
    # crop): traced directly, day 0's forecast said 4 total actions
    # (maintenance=0, new_crop=0) against a real ~46, entirely because
    # `plant_crop` was `None` at that instant. Still respects the same
    # `stuck_animal` gate `plant_crop` itself is nulled by ("finish the
    # paid-for animal before starting a new crop too") - forecasting new
    # planting while mid-acquisition would be wrong for the identical
    # reason.
    plant_crop_intent = fallback_crop if not animal_blocks_planting else None

    # T8.44 second fix (2026-09-19, the user's own explicit request): a
    # real count instead of a hardcoded 0/1 boolean cast - `decide()`
    # still structurally progresses at most one animal-acquisition
    # *pipeline* per turn (BUY->BUILD->PICKUP->PLACE - see parallel_
    # animal_acquisition's own docstring for why), but the *forecast*
    # should staff ahead of the whole intended campaign, not just
    # today's single literal step, so a raised always_pursue_animal_
    # target_count (a starting-portfolio or later expansion tuned to
    # want, say, 5 or 10 animals) doesn't silently understate hiring by
    # the same factor - the exact failure mode the user flagged. Uses
    # the shortfall against that same target (already computed above,
    # `always_pursue_target_count`) - how many more animals are still
    # wanted in total, not yet placed - floored at 1 whenever acquisition_
    # animal is actively set (never *less* than "one pipeline is
    # genuinely in flight right now", including when the ranking-driven
    # path picked one independent of the always_pursue target, e.g.
    # already past that target - see always_pursue_one_animal's own gate
    # above). Bit-identical at the shipped default (always_pursue_
    # animal_target_count=1): shortfall is always exactly 1 whenever
    # acquisition_animal is set, matching the old hardcoded value.
    placed_animal_count = sum(placed_animal_type_counts.values())
    animal_shortfall = max(0, always_pursue_target_count - placed_animal_count)
    planned_new_animals = max(1, animal_shortfall) if acquisition_animal is not None else 0

    # T8.44 third fix (same request): land is a real, shared, finite
    # resource between new crop planting and new animal structures - the
    # pre-fix formula let planned_new_crop_tiles claim every free tile
    # (up to a full 25-tile quadrant) *and* separately planned a new
    # BUILD_COOP/BUILD_PASTURE on "one more" tile, double-booking one
    # tile's worth of capacity (worse, uncapped, once planned_new_animals
    # can be >1). Only the *first* pursued animal's own structure need is
    # actually knowable in advance (its real type, `acquisition_animal`,
    # and whether a matching empty structure already exists,
    # `empty_structure_kinds`); every animal beyond the first (the
    # shortfall's own tail, whose eventual types aren't chosen yet) is
    # conservatively assumed to need a fresh tile each - a safe, honestly
    # documented simplification, not a precise multi-type reservation.
    if acquisition_animal is not None:
        first_animal_needs_new_tile = (
            ANIMALS[acquisition_animal]["structure"] not in empty_structure_kinds
        )
        animals_needing_new_tiles = (
            (1 if first_animal_needs_new_tile else 0) + max(0, planned_new_animals - 1)
        )
    else:
        animals_needing_new_tiles = 0

    planned_new_crop_tiles = 0
    if plant_crop_intent is not None:
        day_plan_max_new_tiles = params.get(
            "day_plan_max_new_tiles_per_day", _DEFAULT_DAY_PLAN_MAX_NEW_TILES_PER_DAY
        )
        land_available_for_crops = max(0, free_tiles - animals_needing_new_tiles)
        cap = min(land_available_for_crops, day_plan_max_new_tiles)
        if params.get("day_plan_new_tiles_cash_aware", _DEFAULT_DAY_PLAN_NEW_TILES_CASH_AWARE):
            seed_cost = CROPS[plant_crop_intent]["seed"]
            seeds_held = seeds.get(plant_crop_intent, 0)
            affordable = int(me["money"] // seed_cost) if seed_cost > 0 else cap
            cap = min(cap, seeds_held + affordable)
        planned_new_crop_tiles = max(0, cap)

    # T8.6: labor_units is 1 (the farmer) plus however many hands the
    # hiring mechanism targets hiring today - the real capacity this
    # turn's planting decision should scale with, not the fixed "one tile
    # per turn" assumption baked in since Phase 3. plant_budget guards
    # against planting more than the labor force can realistically water
    # (a tile weeds at consecutive_unwatered>=2, so unwaterable excess
    # planting converts seed spend into WEEDs that then consume
    # MAINTENANCE-tier actions) - max_plants_per_unit defaults to 100
    # (the board size, structurally unreachable), so it's a real, tunable
    # safety valve, not yet a binding constraint at labor_units=1.
    # max_plant_tasks_per_turn caps how many PLANT tasks one
    # build_task_list call ever proposes, independent of the other three
    # bounds. At the shipped static hires_per_day=1 with dynamic_hiring
    # off, plant_qty collapses to min(seeds_held, free_tiles, 2, ...) -
    # reproducing the pre-T8.6/T8.12 flat behavior.
    #
    # T8.29 fix: this used to be a bare `hires_per_day(params)` call with
    # no runtime arguments at all - `hour`/`animal_tile_counts`/
    # `crop_tile_counts`/`days_remaining`/`money` all omitted. Every one
    # of hires_per_day's real paths (reactive pending_task_count,
    # proactive workload-forecast) needs at least one of those; with none
    # given, both fell straight through to the static fallback (default
    # 1) regardless of dynamic_hiring being on (shipped default since
    # T8.16(d)) or the farm's real hand count/workload - labor_units was
    # hardcoded at 2 every turn of every game, decoupled from the actual
    # hiring mechanism. A live self-play trace (T8.29's own todo.md entry)
    # confirmed the resulting symptom chain directly: hand count pinned
    # at 2 for all 30 days, cash stuck near the $500-1000 floor, a single
    # quadrant most of the game, zero animals ever acquired - this one
    # stale value throttled plant_budget/plant_qty/seed_target (below) to
    # a fictional 2-unit labor force no matter how many hands were really
    # hired. It also retroactively explains T8.28's own rejection of
    # raising min_hires_per_day: extra hands had no extra planting
    # capacity to use, since this throttle never moved.
    #
    # The real, forecast-aware target is computed here instead, using
    # every argument already available this early (right after the
    # six-purpose tile scan above, which produced placed_animal_type_
    # counts/n_plant_tiles): animal_tile_counts=placed_animal_type_counts,
    # crop_tile_counts=_crop_tile_counts(me["tiles"]) (own-tiles-only,
    # matching T8.26's own choice for the identical late call below),
    # hour=current_hour, turns_per_day, money=me["money"],
    # free_tiles=free_tiles (T8.32 Stage 2, harmless at the shipped
    # workload_forecast_free_tile_weight=0.0 default), and
    # days_remaining (hires_per_day_days_remaining, needed again
    # unchanged by the late target_hires call further down). The one
    # input genuinely NOT available this early is pending_task_count -
    # it needs `tasks`, which needs `plant_qty`, which needs
    # `labor_units` itself (a real circular dependency). Under the
    # shipped default (workload_forecast_hiring_aware=True) this is
    # harmless: that branch never reads pending_task_count, so this call
    # returns exactly what the late target_hires call (which does have
    # pending_task_count) would also return. The one honest, narrow gap:
    # a non-default reactive-only configuration
    # (workload_forecast_hiring_aware=False with dynamic_hiring=True)
    # still falls back to the static value here, since its
    # pending_task_count-driven target isn't knowable yet at this point
    # in decide() - a real limitation for that specific combination, not
    # a silent regression from today's shipped behavior for it.
    hires_per_day_days_remaining = max(
        0, params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS) - current_day
    )
    early_target_hires = hires_per_day(
        params, hour=current_hour,
        turns_per_day=params.get("turns_per_day", _DEFAULT_TURNS_PER_DAY), money=me["money"],
        animal_tile_counts=placed_animal_type_counts,
        crop_tile_counts=_crop_tile_counts(me["tiles"]),
        days_remaining=hires_per_day_days_remaining,
        free_tiles=free_tiles,
        maintenance_actions_today=maintenance_actions_today,
        planned_new_crop_tiles=planned_new_crop_tiles,
        planned_new_animals=planned_new_animals,
    )
    labor_units = 1 + early_target_hires
    max_plants_per_unit = params.get("max_plants_per_unit", _DEFAULT_MAX_PLANTS_PER_UNIT)
    plant_budget = max(0, max_plants_per_unit * labor_units - n_plant_tiles)
    max_plant_tasks_per_turn = params.get("max_plant_tasks_per_turn", _DEFAULT_MAX_PLANT_TASKS_PER_TURN)
    plant_qty = (
        min(seeds.get(plant_crop, 0), free_tiles, labor_units, plant_budget, max_plant_tasks_per_turn)
        if plant_crop is not None
        else 0
    )
    # T8.19: portfolio_basket_size > 1 with more than one crop actually
    # qualifying (len(fallback_crops)<=1 leaves the single-crop
    # computation above completely untouched, bit-identical) - round-
    # robins the same total_cap of tiles across the basket in rank
    # order, each crop capped by seeds *currently* held (this turn's
    # BUY_SEED order below arrives next turn, same "only what's on hand
    # plants today" rule the single-crop path already follows). Still
    # gated on stuck_animal (plant_crop/plant_qty above already reflect
    # that - a nulled plant_crop with len(fallback_crops)>1 falls through
    # to the `if basket_seq` check below and resets to None/0 the same
    # way).
    if len(fallback_crops) > 1 and not animal_blocks_planting:
        total_cap = min(free_tiles, labor_units, plant_budget, max_plant_tasks_per_turn)
        remaining = {c: seeds.get(c, 0) for c in fallback_crops}
        basket_seq: list[str] = []
        i = 0
        while len(basket_seq) < total_cap and any(v > 0 for v in remaining.values()):
            c = fallback_crops[i % len(fallback_crops)]
            if remaining[c] > 0:
                basket_seq.append(c)
                remaining[c] -= 1
            i += 1
        plant_crop = basket_seq if basket_seq else None
        plant_qty = len(basket_seq)

    water_bonus_window_aware = params.get("water_bonus_window_aware", _DEFAULT_WATER_BONUS_WINDOW_AWARE)
    parallel_animal_acquisition = params.get(
        "parallel_animal_acquisition", _DEFAULT_PARALLEL_ANIMAL_ACQUISITION
    )
    feed_pickup_unpinned = params.get("feed_pickup_unpinned", _DEFAULT_FEED_PICKUP_UNPINNED)
    animal_pickup_unpinned = params.get("animal_pickup_unpinned", _DEFAULT_ANIMAL_PICKUP_UNPINNED)
    prioritize_animal_setup = params.get("prioritize_animal_setup", _DEFAULT_PRIORITIZE_ANIMAL_SETUP)

    unit_positions = [tuple(me["farmer"])] + [tuple(h) for h in me.get("hands", [])]
    tasks = build_task_list(
        me["tiles"], unit_positions,
        plant_crop=plant_crop, desired_animal=acquisition_animal,
        shed=shed, farmer_inventory=farmer_inventory,
        # T8.39: the real per-unit list (private["inventories"] - index 0
        # the farmer, later indices hands) rather than farmer_inventory
        # alone, so FEED/FERTILIZE can bind to whichever unit actually
        # holds the item once feed_pickup_unpinned lets a hand carry
        # WHEAT too - see build_task_list's own docstring. Bit-identical
        # today: only unit 0 can ever hold WHEAT/FERTILIZER while the
        # wheat PICKUP stays pinned (feed_pickup_unpinned off).
        inventories=private.get("inventories"),
        current_day=current_day,
        anchor=params.get("investment_anchor", _DEFAULT_INVESTMENT_ANCHOR),
        use_fertilizer=use_fertilizer,
        plant_qty=plant_qty,
        care_aware=care_aware,
        water_bonus_window_aware=water_bonus_window_aware,
        parallel_animal_acquisition=parallel_animal_acquisition,
        feed_pickup_unpinned=feed_pickup_unpinned,
        animal_pickup_unpinned=animal_pickup_unpinned,
        prioritize_animal_setup=prioritize_animal_setup,
        defer_one_time_harvest_to_max_yield=defer_one_time_harvest_to_max_yield,
        plant_alongside_animal=params.get(
            "plant_while_animal_pending", _DEFAULT_PLANT_WHILE_ANIMAL_PENDING
        ),
    )
    assignment = assign_units(tasks, unit_positions)

    farmer_action = action_for_unit(unit_positions[0], assignment[0])
    hand_actions = [
        action_for_unit(unit_positions[i], assignment[i])
        for i in range(1, len(unit_positions))
    ]

    # Reserve WHEAT from routine selling once any animal exists on the
    # farm - see market.sell_orders's own docstring for the real deadlock
    # this avoids (found during T6.4: selling everything emptied the shed
    # before a PICKUP for feeding could ever complete, starving a placed
    # COW to escape). Matches tasks._WHEAT_PICKUP_BATCH's batch size, not
    # by import (tasks.py has no dependency on this module) - keep the
    # two in sync by hand if either changes.
    wheat_reserve = _WHEAT_FEED_RESERVE if placed_animal_type_counts else 0

    # T8.3l: feed is only worth restocking when there's an animal placed
    # or currently being pursued (acquisition_animal) - see
    # _DEFAULT_WHEAT_BUY_ONLY_WHEN_FEED_NEEDED's own comment for the real
    # ping-pong this fixes.
    feed_needed = (
        bool(placed_animal_type_counts) or acquisition_animal is not None
        if params.get("wheat_buy_only_when_feed_needed", _DEFAULT_WHEAT_BUY_ONLY_WHEN_FEED_NEEDED)
        else True
    )

    season_length_days = params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS)
    liquidation_days_before_end = params.get(
        "liquidation_days_before_end", _DEFAULT_LIQUIDATION_DAYS_BEFORE_END
    )
    liquidate = current_day >= season_length_days - liquidation_days_before_end
    liquidate_wheat_reserve = params.get(
        "liquidate_wheat_reserve", _DEFAULT_LIQUIDATE_WHEAT_RESERVE
    )

    # T8.5: assembled as `hires + sells + tail`, not "sells first, buys
    # after" (the pre-T8.5 order) - two deliberate properties, both real,
    # measured gaps in the old order, not a style preference:
    #
    # 1. `hires` sits at index 0 and is never truncated by sells crowding
    #    the 10-order cap. A hand hired at hour 1 instead of hour 0 loses
    #    a whole unit-day, and hour 0 - right after the end-of-day
    #    inventory dump - is exactly when the shed is fullest and `sells`
    #    is longest, so "sells first" is precisely the ordering most
    #    likely to starve HIRE of a slot the turn it matters most.
    # 2. `tail` (land/investment/wheat-restock - all real cash-consuming
    #    buys) keeps a reserved slot budget but is still emitted *after*
    #    `sells`, not before: the real interpreter's `_process_market`
    #    walks the turn's order queue index by index, settling each order
    #    against the money the *previous* orders in the list already
    #    changed - a buy placed ahead of a sell would see pre-sale money
    #    and could fail on cash the agent would otherwise have had that
    #    same turn.
    #
    # `hires_per_day` defaults to 0 (SPEC.md's economic analysis: no
    # tuning evidence yet that hiring pays for itself), so this reordering
    # is a no-op by default - `hires` is always empty, and `sells`/`tail`
    # keep exactly today's relative order and content.
    #
    # T8.12 (`dynamic_hiring`, off by default): sized from the task
    # backlog `tasks` already built above, not a second board scan - see
    # `hires_per_day`'s own docstring for the formula. Bit-identical to
    # the plain `hires_per_day(params)` call it replaces whenever
    # `dynamic_hiring` is off (the shipped default) - the extra arguments
    # are simply unused in that case.
    #
    # T8.16(a): pending_task_count excludes `_ROUTINE_RECURRING_OPS`
    # (WATER/FEED) - T8.12's own traced rejection found `len(tasks)`
    # counted these the same as genuine bottleneck work (PLANT/HARVEST/
    # acquisition), over-hiring without a corresponding gain, since a
    # tile needs exactly one WATER/FEED per day *regardless* of how many
    # hands exist - more labor doesn't create more of this work, unlike
    # PLANT/HARVEST, which scale with how many hands are free to act.
    pending_task_count = sum(1 for t in tasks if t.op not in _ROUTINE_RECURRING_OPS)
    # T8.26: real tile-count signals passed unconditionally, same
    # "always give the real signal, let the callee's own flag decide"
    # pattern every other params-gated mechanism in this module follows
    # (e.g. animal_care_aware passed to build_task_list regardless of
    # whether it's on) - hires_per_day's own workload_forecast_hiring_
    # aware flag is what actually gates whether these are used.
    # placed_animal_type_counts is the same six-purpose tile scan's own
    # dict computed above; _crop_tile_counts(me["tiles"]) is deliberately
    # own-tiles-only, NOT the opponent-blended _combined_crop_tile_counts
    # used for the unrelated crop-self-impact mechanism - hiring workload
    # is about our own farm's labor demand, not a market-price signal.
    # hires_per_day_days_remaining was already computed above (T8.29,
    # for the early labor_units call) - reused here unchanged, not
    # recomputed, since current_day hasn't moved between the two calls.
    target_hires = hires_per_day(
        params, pending_task_count=pending_task_count, hour=current_hour,
        turns_per_day=params.get("turns_per_day", _DEFAULT_TURNS_PER_DAY), money=me["money"],
        animal_tile_counts=placed_animal_type_counts,
        crop_tile_counts=_crop_tile_counts(me["tiles"]),
        days_remaining=hires_per_day_days_remaining,
        free_tiles=free_tiles,
        maintenance_actions_today=maintenance_actions_today,
        planned_new_crop_tiles=planned_new_crop_tiles,
        planned_new_animals=planned_new_animals,
    )
    hires_today = me.get("hires_today", 0)
    # T8.44: a same-day (mid-day) top-up hire - e.g. a BUY_LAND settling
    # this same turn jumps free_tiles, and the day-plan forecast above
    # reacts to it automatically (recomputed fresh every call, no new
    # state) - is only worth emitting if enough turns remain today for
    # the new hand to be productive. `hire_min_turns_left` (default 0,
    # bit-identical - the gate always passes) requires `turns_per_day -
    # current_hour >= hire_min_turns_left` before queuing *further* HIRE
    # orders once at least one has already been hired today
    # (`hires_today == 0` is a deliberate escape hatch: never leave the
    # farm with zero labor for a whole day just because the gate would
    # otherwise block the day's very first hire, e.g. one blocked by
    # hire_cash_reserve earlier that same hour - a clear regression risk
    # worse than one slightly-late hire). `max_hire_orders_per_turn`
    # (default matches `_MAX_MARKET_ORDERS`) caps how many HIRE orders
    # this loop queues in one turn - load-bearing once target_hires can
    # exceed roughly 10 (day_plan_hiring_aware's whole point): `hires` is
    # listed first in the final `(hires + sells + tail)[:_MAX_MARKET_
    # ORDERS]` truncation below, so an uncapped burst would silently drop
    # every `tail` order (BUY_SEED/BUY_ANIMAL/BUY_LAND/wheat restock) that
    # turn. A target above the cap simply finishes over the next turn(s),
    # self-correcting via hires_today - no extra state needed.
    hire_min_turns_left = params.get("hire_min_turns_left", _DEFAULT_HIRE_MIN_TURNS_LEFT)
    turns_per_day_val = params.get("turns_per_day", _DEFAULT_TURNS_PER_DAY)
    max_hire_orders_per_turn = params.get(
        "max_hire_orders_per_turn", _DEFAULT_MAX_HIRE_ORDERS_PER_TURN
    )
    hires: list[list] = []
    while hires_today + len(hires) < target_hires and len(hires) < max_hire_orders_per_turn:
        if hires_today > 0 and (turns_per_day_val - current_hour) < hire_min_turns_left:
            break
        hires.append(["HIRE"])

    # T8.46: does this turn's own sale of crop products move the market
    # enough that a seed bought on today's ranking could be stale next turn?
    # Preview the sells (pure function, same inputs as the final call below;
    # only the order-slot cap differs and one order per product never hits it).
    defer_seed_units = params.get(
        "defer_seed_purchase_on_crop_sale", _DEFAULT_DEFER_SEED_PURCHASE_ON_CROP_SALE
    )
    defer_seed_purchase = False
    if defer_seed_units > 0:
        preview_wheat_reserve = wheat_reserve
        if feed_needed and not liquidate:
            preview_wheat_reserve = max(
                wheat_reserve,
                params.get("wheat_restock_threshold", _DEFAULT_WHEAT_RESTOCK_THRESHOLD),
            )
        preview_sells = sell_orders(
            shed, obs["market"]["inventory"], params,
            max_orders=_MAX_MARKET_ORDERS,
            wheat_reserve=preview_wheat_reserve,
            liquidate=liquidate,
            use_fertilizer=use_fertilizer,
            liquidate_wheat_reserve=liquidate_wheat_reserve,
        )
        defer_seed_purchase = (
            sum(o[2] for o in preview_sells if o[1] in CROPS) >= defer_seed_units
        )

    tail: list[list] = []
    # Seed/animal purchase: arrives next turn (market orders resolve
    # after this turn's unit actions) - the PLANT/PLACE task above
    # naturally starts firing once the seed/animal shows up in a future
    # observation, no extra state needed here. No longer mutually
    # exclusive as of T8.9: they used to be, "by construction," when both
    # came from `_top_investment_choice`'s single top pick - but
    # `fallback_crop` is now a genuinely independent second signal (see
    # its own docstring), so both purchases fire whenever both are
    # warranted. Both still gated on `stuck_animal is None` - finish
    # placing what's already bought (see the stuck_animal comment above)
    # before spending on anything else, seed or animal. Also gated on
    # somewhere to actually use the purchase (T6.5): a seed needs an
    # empty tile; an animal needs either an empty tile (to build a fresh
    # structure on) or an existing empty matching structure - it doesn't
    # need free land specifically, just somewhere to eventually stand.
    # T8.6: bought as one batched order up to seed_buffer_per_unit *
    # labor_units seeds - not the old flat "1 if none on hand" - so a
    # burst of parallel PLANT tasks next turn isn't stalled behind a
    # just-in-time single-seed purchase. One market order regardless of
    # quantity (verified: the real interpreter's _parse_order reads
    # order[2] as the full remaining count), which matters for T8.5's
    # slot arithmetic - buying 5 seeds costs exactly the same one `tail`
    # slot as buying 1. At labor_units=1/seed_buffer_per_unit=1 (today's
    # shipped defaults) seed_target=1, so `needed` is nonzero under
    # exactly the same condition the old `not have_seed` gate checked
    # (seeds_held==0) and buys exactly 1 - bit-identical.
    # T8.45: the bulk plans are computed up front (animal first) so the
    # animal's cost is reserved out of the seed budget - `tail` settles in
    # list order against real money, and a big seed order placed ahead of
    # BUY_ANIMAL could otherwise starve it. Both are off by default (the
    # legacy branches below are unchanged, bit-identical).
    bulk_seed_purchase = params.get("bulk_seed_purchase", _DEFAULT_BULK_SEED_PURCHASE)
    bulk_animal_purchase = params.get("bulk_animal_purchase", _DEFAULT_BULK_ANIMAL_PURCHASE)
    bulk_animal_qty = 0
    bulk_animal_cost = 0
    if (
        bulk_animal_purchase
        and acquisition_animal is not None
        and (has_empty_tile or ANIMALS[acquisition_animal]["structure"] in empty_structure_kinds)
    ):
        animal_unit_cost = ANIMALS[acquisition_animal]["cost"]
        animal_held = shed.get(acquisition_animal, 0) + sum(
            inv.get(acquisition_animal, 0) for inv in (private.get("inventories") or [])
        )
        animal_plan = bulk_purchase_plan(
            [acquisition_animal],
            {acquisition_animal: animal_held},
            {acquisition_animal: animal_unit_cost},
            planned_new_animals,
            me["money"],
            buffer_fraction=params.get(
                "bulk_animal_buffer_fraction", _DEFAULT_BULK_ANIMAL_BUFFER_FRACTION
            ),
            round_up=False,
        )
        shed_capacity = params.get("shed_capacity", _DEFAULT_SHED_CAPACITY)
        # Never buy past max_animals_per_type (placed + already waiting in
        # the shed/inventory count against it) - the legacy one-at-a-time
        # path could not exceed it, and stuck_animal would happily place
        # every extra unit bought here regardless of the cap.
        type_room = max(
            0,
            params.get("max_animals_per_type", _DEFAULT_MAX_ANIMALS_PER_TYPE)
            - placed_animal_type_counts.get(acquisition_animal, 0)
            - animal_held,
        )
        bulk_animal_qty = min(
            animal_plan.get(acquisition_animal, 0), shed_room(shed, shed_capacity), type_room
        )
        bulk_animal_cost = bulk_animal_qty * animal_unit_cost

    if not animal_blocks_planting and fallback_crops and has_empty_tile and not defer_seed_purchase:
        if bulk_seed_purchase:
            # Tiles about to be planted: every free tile not reserved for
            # a planned animal's structure (the same land accounting the
            # day-plan forecast uses), capped at one quadrant. All basket
            # crops together add up to this one total.
            tiles_to_plant = min(
                max(0, free_tiles - animals_needing_new_tiles),
                params.get("bulk_purchase_max_new_tiles", _DEFAULT_BULK_PURCHASE_MAX_NEW_TILES),
            )
            seed_budget = max(
                0,
                me["money"] - params.get("seed_cash_reserve", _DEFAULT_SEED_CASH_RESERVE)
                - bulk_animal_cost,
            )
            seed_plan = bulk_purchase_plan(
                list(fallback_crops),
                {c: seeds.get(c, 0) for c in fallback_crops},
                {c: CROPS[c]["seed"] for c in fallback_crops},
                tiles_to_plant,
                seed_budget,
                buffer_fraction=params.get(
                    "bulk_seed_buffer_fraction", _DEFAULT_BULK_SEED_BUFFER_FRACTION
                ),
                round_up=True,
            )
            for crop, qty in seed_plan.items():
                tail.append(["BUY_SEED", crop, qty])
        else:
            # T8.19: loops over the full basket instead of a single crop -
            # at portfolio_basket_size=1 (fallback_crops has at most one
            # entry) this is exactly one iteration, bit-identical to the
            # pre-T8.19 single-crop computation. `spendable` is tracked
            # cumulatively across the loop (not recomputed from me["money"]
            # each time) since the real interpreter settles same-turn orders
            # in queue order, each against the money earlier orders in the
            # same turn already spent (T8.5's own comment above) - computing
            # every basket crop's affordability against the same untouched
            # `me["money"]` would let a later BUY_SEED order overcommit.
            seed_buffer_per_unit = params.get("seed_buffer_per_unit", _DEFAULT_SEED_BUFFER_PER_UNIT)
            seed_target = labor_units * seed_buffer_per_unit
            seed_cash_reserve = params.get("seed_cash_reserve", _DEFAULT_SEED_CASH_RESERVE)
            spendable = max(0, me["money"] - seed_cash_reserve)  # max(0, ...) before // - avoids
            for crop in fallback_crops:  # negative-floor-division surprises
                seed_cost = CROPS[crop]["seed"]
                seeds_held = seeds.get(crop, 0)
                needed = max(0, seed_target - seeds_held)
                if needed <= 0:
                    continue
                affordable = int(spendable // seed_cost)
                buy_qty = min(needed, affordable)
                if buy_qty > 0:
                    tail.append(["BUY_SEED", crop, buy_qty])
                    spendable -= buy_qty * seed_cost
    if bulk_animal_purchase:
        if bulk_animal_qty > 0:
            tail.append(["BUY_ANIMAL", acquisition_animal, bulk_animal_qty])
    elif (
        acquisition_animal is not None
        and not have_animal_anywhere
        and (has_empty_tile or ANIMALS[acquisition_animal]["structure"] in empty_structure_kinds)
    ):
        animal_cost = ANIMALS[acquisition_animal]["cost"]
        shed_capacity = params.get("shed_capacity", _DEFAULT_SHED_CAPACITY)
        if me["money"] >= animal_cost and shed_room(shed, shed_capacity) > 0:
            tail.append(["BUY_ANIMAL", acquisition_animal, 1])

    # Land purchase, per the strategic layer's tunable threshold
    # (SPEC-policy.md "1. Strategic layer") plus T8.3's occupancy gates.
    # One order per turn - if affordable for more than one quadrant at
    # once, the next turn's observation re-evaluates and queues the next
    # purchase then.
    n_unlocked_extra = n_quadrants - 1  # T8.44: n_quadrants computed early, reused here unchanged
    if should_buy_land(
        me["money"], n_unlocked_extra, params,
        free_tiles=free_tiles, unlocked_tiles=unlocked_tiles,
        nearest_free_shed_distance=nearest_free_shed_distance,
    ):
        tail.append(["BUY_LAND"])

    # T8.36: wheat_on_hand for the restock check, optionally widened
    # beyond the shed alone - see _DEFAULT_WHEAT_RESTOCK_COUNTS_CARRIED_
    # INVENTORY's own comment for why the shed-only count is misleading
    # the moment a PICKUP has carried some of it off for feeding.
    wheat_on_hand = shed.get("WHEAT", 0)
    if params.get(
        "wheat_restock_counts_carried_inventory", _DEFAULT_WHEAT_RESTOCK_COUNTS_CARRIED_INVENTORY
    ):
        wheat_on_hand += sum(inv.get("WHEAT", 0) for inv in private.get("inventories", []))
    wheat_order = buy_wheat_order(
        wheat_on_hand, obs["market"]["prices"].get("WHEAT", 0), params, feed_needed=feed_needed
    )
    if wheat_order is not None:
        tail.append(wheat_order)

    # `sells` gets whatever's left after `hires`/`tail` reserve their
    # slots - mirrors market.market_orders's own belt-and-braces reserve-
    # floor invariant (not by import; that function operates on a
    # combined sells+restock list this module no longer builds in one
    # call - see this block's own docstring above for why the restock
    # order moved to `tail` instead): once feed is needed and this isn't
    # a liquidation turn, the *effective* reserve is floored at
    # `wheat_restock_threshold`, so `sell_orders` can never sell WHEAT
    # down to a level `buy_wheat_order` (above) would immediately restock
    # next turn - T8.3l's own fix, preserved here even though the two
    # calls are no longer bundled.
    effective_wheat_reserve = wheat_reserve
    if feed_needed and not liquidate:
        threshold = params.get("wheat_restock_threshold", _DEFAULT_WHEAT_RESTOCK_THRESHOLD)
        effective_wheat_reserve = max(wheat_reserve, threshold)
    sell_max_orders = max(0, _MAX_MARKET_ORDERS - len(hires) - len(tail))
    sells = sell_orders(
        shed,
        obs["market"]["inventory"],
        params,
        max_orders=sell_max_orders,
        wheat_reserve=effective_wheat_reserve,
        liquidate=liquidate,
        use_fertilizer=use_fertilizer,
        liquidate_wheat_reserve=liquidate_wheat_reserve,
    )

    market = (hires + sells + tail)[:_MAX_MARKET_ORDERS]

    return {"farmer": farmer_action, "hands": hand_actions, "market": market[:_MAX_MARKET_ORDERS]}
