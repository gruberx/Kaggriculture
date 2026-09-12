"""Regression gate for accepting a candidate params/policy.json update -
see SPEC-tuning.md "Held-out evaluation and the regression gate" and
tasks/plan.md T7.1.

Dev-only, never ships (SPEC-tuning.md "Boundaries specific to this
module": full freedom to depend on kaggle_environments, numerical
libraries, etc. via harness.py).

This module implements only the gate itself (T7.1) - the coordinate-
ascent search loop (T7.2) and the opponent panel (T7.3) are separate,
later tasks that call into this one, not the other way around.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diskguard  # noqa: E402
from harness import BlockResult  # noqa: E402

_ACCEPTED_RUNS_LOG_RELATIVE_PATH = os.path.join("data", "arena", "accepted_runs.jsonl")

_AGENT_MAIN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "src", "kagg", "agent_main.py"
)
_PARAMS_LOAD_LINE = "_PARAMS = load_params()"


def wilson_intervals_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """True if two Wilson score intervals share any point, endpoints
    included (a shared boundary still counts as "not distinguishable")."""
    a_lo, a_hi = a
    b_lo, b_hi = b
    return a_lo <= b_hi and b_lo <= a_hi


def accept_candidate(candidate_block: BlockResult, baseline_block: BlockResult) -> bool:
    """True if `candidate_block`'s held-out win rate improves on
    `baseline_block`'s outside their Wilson interval overlap.

    SPEC-tuning.md, restating SPEC-harness.md: "the working block's
    number is not sufficient evidence" - a numerically higher win rate
    alone isn't enough if the two intervals still overlap; both this
    module's own docstring and SPEC-tuning.md's Boundaries call this "the
    single most important discipline this module exists to enforce."
    Both `candidate_block` and `baseline_block` must be measured on the
    *same held-out* seed block - this function trusts its caller for
    that, since a BlockResult on its own doesn't record which block it
    came from.
    """
    if candidate_block.win_rate_a <= baseline_block.win_rate_a:
        return False
    return not wilson_intervals_overlap(candidate_block.wilson_interval_a, baseline_block.wilson_interval_a)


def record_accepted_run(
    opponent: str,
    tuning_seeds: list[int],
    holdout_seeds: list[int],
    candidate_block: BlockResult,
    baseline_block: BlockResult,
    policy_git_commit: str,
) -> None:
    """Append the accepted run's full configuration to
    data/arena/accepted_runs.jsonl (outside the repo - Competition-Data-
    adjacent tuning history, not source code) so a later regression can
    be traced back to exactly what was measured and why it was accepted.

    Calls diskguard.ensure_budget() first - unlike tools/submit.py's
    kilobyte-scale submissions.jsonl (exempt per SPEC-ops.md), this write
    accumulates over a full tuning run and is itself PROTECTED from
    eviction (SPEC-diskguard.md), so it's worth catching a runaway budget
    here per SPEC-tuning.md's own instruction.
    """
    diskguard.ensure_budget()
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "opponent": opponent,
        "tuning_seeds": list(tuning_seeds),
        "holdout_seeds": list(holdout_seeds),
        "candidate_win_rate": candidate_block.win_rate_a,
        "candidate_wilson_interval": list(candidate_block.wilson_interval_a),
        "baseline_win_rate": baseline_block.win_rate_a,
        "baseline_wilson_interval": list(baseline_block.wilson_interval_a),
        "policy_git_commit": policy_git_commit,
    }
    log_path = os.path.join(diskguard._project_root(), _ACCEPTED_RUNS_LOG_RELATIVE_PATH)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


_DEFAULT_MAX_PASSES = 10


def coordinate_ascent(
    param_grid: dict[tuple, list[tuple]],
    evaluate,
    initial_params: dict,
    max_passes: int = _DEFAULT_MAX_PASSES,
) -> dict:
    """Stage 1 coordinate ascent (SPEC-tuning.md): for each entry in
    `param_grid`, hold every other parameter fixed and sweep the given
    candidate values, keeping whichever wins outright over the current
    best via `accept_candidate` - a real, non-noise improvement (Wilson
    interval overlap doesn't count), not merely a higher point estimate.
    Repeats full passes over every grid entry until one changes nothing
    ("no parameter change improves the working-block win rate beyond
    noise") or `max_passes` is reached (a safety cap against oscillation
    or never converging, not something SPEC-tuning.md itself specifies).

    `param_grid` keys are tuples of one or more parameter names - a
    single name for an independent sweep, several for a correlated group
    swept jointly (SPEC-tuning.md: "hires_per_day and land_purchase_
    threshold are suspected to interact... and should be swept jointly
    rather than independently"). Each value is a list of same-length
    tuples, one candidate combination per grid point.

    `evaluate(params: dict)` must return something with `.win_rate_a` and
    `.wilson_interval_a` - a `harness.BlockResult` in real use (T7.4), or
    any compatible object in a test (see SPEC-tuning.md's own
    requirement: "tested on a toy 2-parameter objective with a known
    optimum... before being trusted on the real (expensive) arena").
    Parameters not named in any `param_grid` entry are carried through
    from `initial_params` untouched.
    """
    current = dict(initial_params)
    for _ in range(max_passes):
        changed = False
        for names, candidates in param_grid.items():
            current_values = tuple(current[name] for name in names)
            best_values = current_values
            best_result = evaluate(current)
            for candidate_values in candidates:
                if candidate_values == current_values:
                    continue
                trial = dict(current)
                trial.update(zip(names, candidate_values))
                trial_result = evaluate(trial)
                if accept_candidate(trial_result, best_result):
                    best_result = trial_result
                    best_values = candidate_values
            if best_values != current_values:
                current.update(zip(names, best_values))
                changed = True
        if not changed:
            break
    return current


def write_candidate_agent(params: dict, workdir: str) -> str:
    """Write a real, standalone agent file into `workdir` that behaves
    exactly like agent_main.py but loads `params` from a scratch JSON
    file instead of the checked-in params/policy.json, and return its
    path - usable directly as an agent path for harness.run_paired/
    run_block, e.g. to compare two parameter sets against each other
    without ever mutating params/policy.json (tasks/plan.md T7.3's own
    Verify criterion).

    Design note - a real deviation from the plan's own tentative
    suggestion (an env-var hook), found and fixed while designing this,
    not assumed safe: kaggle_environments' loader execs each agent's raw
    source into its own fresh globals dict (verified directly in
    kaggle_environments/agent.py: `exec(code_object, env)`, never going
    through sys.modules) - safe on its own. But a wrapper that did
    `import kagg.agent_main` instead of copying its source would have
    that *inner* import cached process-wide by Python's ordinary import
    machinery, silently reusing whichever candidate's params loaded
    first for every other candidate compared in the same process -
    exactly the "candidate vs previous-best snapshot" opponent-panel
    case this module needs, where both sides are our own code with
    different params, potentially both exec'd within one
    multiprocessing.Pool worker. Copying agent_main.py's real source
    (never importing it as a module) sidesteps this entirely: the only
    import in the modified copy is `from kagg.policy.params import
    load_params`, a pure function with no per-candidate state, so
    caching it is harmless regardless of how many candidates run in the
    same process.

    Full fidelity, not a reimplementation: copies agent_main.py's actual
    source (fault-tolerance, time-budget circuit breaker, everything)
    rather than a hand-written approximation, since what SPEC-tuning.md's
    arena needs to measure is what would actually ship.
    """
    with open(_AGENT_MAIN_PATH) as f:
        source = f.read()
    occurrences = source.count(_PARAMS_LOAD_LINE)
    if occurrences != 1:
        raise RuntimeError(
            f"expected exactly one {_PARAMS_LOAD_LINE!r} line in {_AGENT_MAIN_PATH}, "
            f"found {occurrences} - agent_main.py may have changed shape; "
            "update write_candidate_agent to match"
        )

    unique = uuid.uuid4().hex
    params_path = os.path.join(workdir, f"tuning_candidate_params_{unique}.json")
    with open(params_path, "w") as f:
        json.dump(params, f)

    patched_source = source.replace(_PARAMS_LOAD_LINE, f"_PARAMS = load_params({params_path!r})")
    agent_path = os.path.join(workdir, f"tuning_candidate_agent_{unique}.py")
    with open(agent_path, "w") as f:
        f.write(patched_source)
    return agent_path


def resolve_opponent(opponent, workdir: str) -> str:
    """A panel entry (see build_opponent_panel) is either a plain
    built-in name/agent path (used as-is) or a params dict - the
    previous-best snapshot, written via write_candidate_agent so it's
    usable as a real agent path."""
    if isinstance(opponent, dict):
        return write_candidate_agent(opponent, workdir)
    return opponent


def build_opponent_panel(previous_best_params: dict | None = None) -> list:
    """The Stage 1 opponent panel (SPEC-tuning.md): starter, random, and
    the previous-best policy snapshot if one exists yet (None before the
    first accepted params/policy.json update - there's nothing to
    compare against). The public yhay81/shop-router-0909 notebook joins
    once ops downloads it (SPEC-ops.md) - not required to start Stage 1,
    so not modeled here; append it to the returned list once available.
    """
    panel: list = ["starter", "random"]
    if previous_best_params is not None:
        panel.append(previous_best_params)
    return panel
