"""Kaggriculture submission entry point.

Ships as `main.py` in the Kaggle submission bundle (see SPEC-ops.md
"Submission bundling").

IMPORTANT, verified empirically against kaggle_environments' own loader
(`kaggle_environments/agent.py: get_last_callable`), not assumed from docs:
a file-path agent's source is `exec(compile(source, path, "exec"), {})`'d
into a **fresh globals dict** - not imported as a real module. Two
consequences that shaped this file:

1. `__file__` is never defined here - `exec()` does not set it, regardless
   of the real `path` passed to `compile()`. Referencing `__file__` at
   module level raises NameError and crashes agent construction outright
   (confirmed: this exact mistake in an earlier revision made every turn
   silently fall back to the environment's own default action, with
   debug=False swallowing the traceback). Any future code that needs to
   locate a sibling file (e.g. Phase 3's `params/policy.json`) must live in
   a normally-imported submodule (`kagg.policy`, `kagg.gamelib`) and use
   *that* module's own `__file__`, never this one's.
2. The loader appends this file's own directory to `sys.path` **only for
   the duration of that one `exec()` call**, and only on the *first* turn
   (the resulting `agent` callable is cached after that - see
   `callable_agent` in the same source file). So sibling-package imports
   (`import kagg...`) must happen at *module top level*, executed while
   that directory is still on `sys.path` - never lazily inside a function
   called on later turns, when it has already been popped back off. This
   is why the import below is not deferred into `_decide()`.

In the actual bundle, `main.py` (this file) sits next to a `kagg/` folder
(gamelib/policy) built by `build_submission.py`, so no manual `sys.path`
edit is needed at all: the loader's own auto-append already makes
`kagg.policy` resolve during that first exec. Locally, `kagg` is
pip-installed (editable), so the same top-level import resolves via
site-packages instead - either way, no path manipulation belongs here.
"""

from __future__ import annotations

import copy
import time

from kagg.policy.decide import decide
from kagg.policy.params import load_params

# Loaded once here, at module top level, not inside _decide() - both
# because it must happen while the loader's auto-appended sys.path entry
# is still active (see this module's own point 2 above) and because
# SPEC-policy.md requires it: params/policy.json is "loaded once at agent
# construction, not per turn."
_PARAMS = load_params()

# Returned on any failure. A module-level dict would be a shared mutable
# object every caller could accidentally corrupt - see _safe_default().
SAFE_DEFAULT_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}

# Hard ceiling per SPEC-agent.md "Time budget": a circuit breaker for
# pathological cases, not a budget to spend routinely (target is <=50ms).
# Measured with time.perf_counter() around the whole _decide() call.
_TURN_TIME_CEILING_SECONDS = 0.400

# The most recent action that finished *within* the ceiling - used as a
# fallback when a computation takes too long to trust, even though it
# didn't raise (SPEC-agent.md: "a stale-but-valid action beats a
# timeout"). Starts as the safe default so the very first turn already has
# a sane fallback before anything has succeeded yet. This is a distinct
# failure mode from an outright exception (see agent()'s docstring) -
# an exception still gets the plain safe default, not this cache.
_last_good_action = {"farmer": ["PASS"], "hands": [], "market": []}


def _safe_default() -> dict:
    """A fresh copy of SAFE_DEFAULT_ACTION - never the shared instance."""
    return {"farmer": ["PASS"], "hands": [], "market": []}


def _decide(obs: dict) -> dict:
    """Decision logic - the full three-layer policy (SPEC-policy.md),
    wired in at T3.5. Kept as its own function so agent()'s
    fault-tolerance wrapper never has to change shape as the real logic
    grows.
    """
    return decide(obs, _PARAMS)


def agent(obs: dict) -> dict:
    """Kaggriculture agent entry point - see SPEC-agent.md "Contract".

    Never raises: any exception here is a technical loss (SPEC.md
    Boundaries - "a technical loss is never acceptable"), so every failure
    mode collapses to the same safe default the environment itself treats
    an invalid action as a no-op for (AGENTS.md: "Invalid actions are
    silent no-ops"). Do not remove or narrow this try/except to see a
    real stack trace during development - use the golden-episode/fuzz
    tests locally instead, where exceptions are allowed to propagate
    (SPEC-agent.md "Boundaries specific to this module"). This only guards
    *per-turn* failures on a constructed agent - it cannot and does not
    need to guard a broken top-level import, which is caught long before
    a real match by the test suite and the bundle-audit smoke test, not by
    this try/except (see the module docstring above).

    Separately, a computation that *succeeds* but takes too long is a
    different failure mode (SPEC-agent.md "Time budget"): Python has no
    clean way to preempt an already-running synchronous call, so this
    can't reduce the wall-clock cost already paid on the slow turn itself
    - what it protects is *trust*, not time. A decision that took this
    long is no longer assumed to be reasoning correctly under pressure, so
    it's discarded in favor of the last one that finished fast enough to
    trust, rather than acted on.
    """
    global _last_good_action
    start = time.perf_counter()
    try:
        action = _decide(obs)
    except Exception:
        return _safe_default()
    elapsed = time.perf_counter() - start
    if elapsed > _TURN_TIME_CEILING_SECONDS:
        return copy.deepcopy(_last_good_action)
    _last_good_action = copy.deepcopy(action)
    return action
