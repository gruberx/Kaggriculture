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

from kagg.policy.wheat_loop import wheat_loop_action

# Returned on any failure. A module-level dict would be a shared mutable
# object every caller could accidentally corrupt - see _safe_default().
SAFE_DEFAULT_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}


def _safe_default() -> dict:
    """A fresh copy of SAFE_DEFAULT_ACTION - never the shared instance."""
    return {"farmer": ["PASS"], "hands": [], "market": []}


def _decide(obs: dict) -> dict:
    """Decision logic - currently the Phase 0 single-crop wheat loop
    (tasks/plan.md T0.3). Phase 3 replaces this with the full three-layer
    policy (SPEC-policy.md). Kept as its own function so agent()'s
    fault-tolerance wrapper never has to change shape as the real logic
    grows.
    """
    return wheat_loop_action(obs)


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
    """
    try:
        return _decide(obs)
    except Exception:
        return _safe_default()
