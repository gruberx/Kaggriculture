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
    # T8.1: "SHED" (shed-anchored placement) is implemented and tested but
    # not yet arena-accepted as the default - see kagg.policy.decide's
    # _DEFAULT_INVESTMENT_ANCHOR comment for the measured story.
    "investment_anchor": "UNIT",
    # T8.9: fixes a real bug (an animal ranking #1 forever can otherwise
    # block crop planting for the rest of the game) but measured to lose
    # in isolation - see kagg.policy.decide._top_crop_choice's docstring.
    "plant_while_pursuing_animal": False,
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
