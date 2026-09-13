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
    "land_purchase_threshold_money": 10000,  # raised from 5000 by T7.4's first accepted sweep result
    "hires_per_day": 0,
    "sell_margin": 0,
    "drip_sell_max_per_turn": 5,
    "wheat_restock_threshold": 5,
    "wheat_restock_qty": 10,
    "wheat_max_buy_price": 40,
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
    # direct self-play immediately after the mechanism landed: every
    # tested value (0.6, 0.4, 0.25, 0.1) beat the ungated default 50/50 on
    # the working block, confirmed 50/50 again on the held-out block for
    # 0.25 - see kagg.policy.strategy.should_buy_land's own docstring for
    # the mechanism and tasks/todo.md's T8.3 entry for the full story.
    # Explicitly provisional: fit to a 1-unit farm (a single farmer
    # cannot productively work even one 25-tile quadrant), so T8.8 must
    # re-sweep once labor actually works.
    "land_buy_max_free_tile_fraction": 0.25,
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
