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
