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
    `rank_portfolio` - see its own docstring. `rank_season_aware`/
    `animal_net_of_cost`/`animal_fertilizer_income_aware` (T8.3m/T8.3q) are
    read from `params` here (not taken as their own arguments, unlike the
    others) since the first two also govern `days_remaining` itself,
    computed once from the same `season_length_days` this function
    already needs for the maturity checks below.
    """
    season_length_days = params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS)
    rank_season_aware = params.get("rank_season_aware", _DEFAULT_RANK_SEASON_AWARE)
    animal_net_of_cost = params.get("animal_net_of_cost", _DEFAULT_ANIMAL_NET_OF_COST)
    animal_fertilizer_income_aware = params.get(
        "animal_fertilizer_income_aware", _DEFAULT_ANIMAL_FERTILIZER_INCOME_AWARE
    )
    animal_care_aware = params.get("animal_care_aware", _DEFAULT_ANIMAL_CARE_AWARE)
    days_remaining = season_length_days - current_day if (rank_season_aware or animal_net_of_cost) else None
    for name in rank_portfolio(
        market_inventory, crop_tile_counts, unlocked_shops, net_of_seed_cost,
        days_remaining, rank_season_aware, animal_net_of_cost, animal_fertilizer_income_aware,
        animal_care_aware,
    ):
        if name in CROPS:
            if _crop_has_time_to_mature(name, current_day, season_length_days):
                return name, "crop"
        elif name in ANIMALS:
            if _animal_has_time_to_mature(name, current_day, season_length_days):
                return name, "animal"
    return None


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
    """
    season_length_days = params.get("season_length_days", _DEFAULT_SEASON_LENGTH_DAYS)
    rank_season_aware = params.get("rank_season_aware", _DEFAULT_RANK_SEASON_AWARE)
    animal_net_of_cost = params.get("animal_net_of_cost", _DEFAULT_ANIMAL_NET_OF_COST)
    animal_fertilizer_income_aware = params.get(
        "animal_fertilizer_income_aware", _DEFAULT_ANIMAL_FERTILIZER_INCOME_AWARE
    )
    animal_care_aware = params.get("animal_care_aware", _DEFAULT_ANIMAL_CARE_AWARE)
    days_remaining = season_length_days - current_day if (rank_season_aware or animal_net_of_cost) else None
    for name in rank_portfolio(
        market_inventory, crop_tile_counts, unlocked_shops, net_of_seed_cost,
        days_remaining, rank_season_aware, animal_net_of_cost, animal_fertilizer_income_aware,
        animal_care_aware,
    ):
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
        fallback_crop = _top_crop_choice(
            obs["market"]["inventory"], current_day, params, crop_tile_counts, unlocked_shops, net_of_seed_cost
        )
    else:
        fallback_crop = None
    have_seed = fallback_crop is not None and seeds.get(fallback_crop, 0) > 0
    plant_crop = fallback_crop if have_seed else None
    # Index 0 is always the farmer's own inventory (_farmer_inventory's
    # own indexing convention - hands are index 1+). PLACE/FEED's real
    # handlers consume from here, never the shed directly - see
    # tasks.build_task_list's own docstring for why both are needed.
    # T8.4: reading only index 0 here is correct *by construction*, not
    # merely by convention - tasks.py pins every inventory-resolving op
    # (wheat/animal PICKUP, FEED, PLACE) to unit_index 0, so no other
    # unit's inventory can ever hold the wheat/animal this function reads
    # for. See tasks._PINNED_UNIT_INDEX's own docstring for the full
    # story (the real gap this closes: before T8.4, a hired hand could
    # silently pick up the wheat/animal into inventories[1+], which
    # decide() would then never see again).
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

    use_fertilizer = params.get("use_fertilizer", _DEFAULT_USE_FERTILIZER)
    care_aware = params.get("animal_care_aware", _DEFAULT_ANIMAL_CARE_AWARE)

    unit_positions = [tuple(me["farmer"])] + [tuple(h) for h in me.get("hands", [])]
    tasks = build_task_list(
        me["tiles"], unit_positions,
        plant_crop=plant_crop, desired_animal=acquisition_animal,
        shed=shed, farmer_inventory=farmer_inventory,
        current_day=current_day,
        anchor=params.get("investment_anchor", _DEFAULT_INVESTMENT_ANCHOR),
        use_fertilizer=use_fertilizer,
        care_aware=care_aware,
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
    wheat_reserve = _WHEAT_FEED_RESERVE if placed_animal_types else 0

    # T8.3l: feed is only worth restocking when there's an animal placed
    # or currently being pursued (acquisition_animal) - see
    # _DEFAULT_WHEAT_BUY_ONLY_WHEN_FEED_NEEDED's own comment for the real
    # ping-pong this fixes.
    feed_needed = (
        bool(placed_animal_types) or acquisition_animal is not None
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

    market = market_orders(
        shed,
        obs["market"]["inventory"],
        obs["market"]["prices"],
        wheat_on_hand=shed.get("WHEAT", 0),
        params=params,
        max_orders=_MAX_MARKET_ORDERS,
        wheat_reserve=wheat_reserve,
        liquidate=liquidate,
        use_fertilizer=use_fertilizer,
        liquidate_wheat_reserve=liquidate_wheat_reserve,
        feed_needed=feed_needed,
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
