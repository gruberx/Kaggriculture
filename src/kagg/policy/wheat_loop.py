"""A single-crop wheat loop - ports AGENTS.md's own reference example.

This is the Phase 0 walking-skeleton policy (tasks/plan.md T0.3): the
smallest real strategy that plants, waters, harvests, and sells one crop,
proving the whole kaggle_environments pipeline works end to end before
Phase 3 replaces it with the full three-layer policy (SPEC-policy.md).
Unlike the reference example, seed cost and the harvest-age threshold come
from gamelib's constants rather than hardcoded numbers, and the sell
decision goes through gamelib.market.price() rather than dumping
unconditionally - a minimal but real use of gamelib, not a duplicate of it.
"""

from __future__ import annotations

from kagg.gamelib.constants import CROPS
from kagg.gamelib.market import price

_CROP = "WHEAT"
_SEED_COST = CROPS[_CROP]["seed"]
_FIRST_YIELD_DAY = CROPS[_CROP]["first_yield_day"]


def wheat_loop_action(obs: dict) -> dict:
    """Buy/plant/water/harvest/sell a single wheat tile. Returns a full
    action dict (see SPEC-agent.md "Contract")."""
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    fx, fy = me["farmer"]
    tile = me["tiles"][fy][fx]

    market = []
    seeds = private.get("seeds", {})
    if seeds.get(_CROP, 0) == 0 and me["money"] >= _SEED_COST:
        market.append(["BUY_SEED", _CROP, 1])

    wheat_in_shed = private.get("shed", {}).get(_CROP, 0)
    if wheat_in_shed > 0:
        # Only sell if it clears the seed cost - a minimal profitability
        # gate that actually calls gamelib.market.price(), rather than
        # dumping unconditionally regardless of what the market is doing.
        current_price = price(_CROP, obs["market"]["inventory"][_CROP])
        if current_price > _SEED_COST:
            market.append(["SELL", _CROP, wheat_in_shed])

    if tile is None and seeds.get(_CROP, 0) > 0:
        return {"farmer": ["PLANT", _CROP], "hands": [], "market": market}
    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        crop_age = obs["day"] - tile["planted_day"]
        if crop_age >= _FIRST_YIELD_DAY:
            return {"farmer": ["HARVEST"], "hands": [], "market": market}
        if not tile["watered_today"]:
            return {"farmer": ["WATER"], "hands": [], "market": market}

    return {"farmer": ["PASS"], "hands": [], "market": market}
