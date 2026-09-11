"""Kaggriculture submission entry point.

Ships as `main.py` in the Kaggle submission bundle (see SPEC-ops.md
"Submission bundling"). On Kaggle, files are unpacked to
`/kaggle_simulations/agent/` (SPEC-agent.md "Contract"), so imports must
resolve relative to this file's own directory, never an assumed working
directory - hence the sys.path fixup below rather than a bare
`import kagg.gamelib`.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    # In the Kaggle bundle, main.py (this file) sits next to a `kagg/`
    # folder containing gamelib/policy - adding this file's own directory
    # makes `import kagg....` resolve there. In dev, `kagg` is already
    # pip-installed (editable), so this is a harmless no-op duplicate.
    sys.path.insert(0, _HERE)

# Returned on any failure. A module-level dict would be a shared mutable
# object every caller could accidentally corrupt - see _safe_default().
SAFE_DEFAULT_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}


def _safe_default() -> dict:
    """A fresh copy of SAFE_DEFAULT_ACTION - never the shared instance."""
    return {"farmer": ["PASS"], "hands": [], "market": []}


def _decide(obs: dict) -> dict:
    """Placeholder decision logic - always PASS.

    T0.3 replaces this with a call into a real (if minimal) policy; Phase 3
    replaces that with the full three-layer policy (SPEC-policy.md). Kept
    as its own function so agent()'s fault-tolerance wrapper never has to
    change shape as the real logic grows.
    """
    return _safe_default()


def agent(obs: dict) -> dict:
    """Kaggriculture agent entry point - see SPEC-agent.md "Contract".

    Never raises: any exception here is a technical loss (SPEC.md
    Boundaries - "a technical loss is never acceptable"), so every failure
    mode collapses to the same safe default the environment itself treats
    an invalid action as a no-op for (AGENTS.md: "Invalid actions are
    silent no-ops"). Do not remove or narrow this try/except to see a
    real stack trace during development - use the golden-episode/fuzz
    tests locally instead, where exceptions are allowed to propagate
    (SPEC-agent.md "Boundaries specific to this module").
    """
    try:
        return _decide(obs)
    except Exception:
        return _safe_default()
