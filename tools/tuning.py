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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diskguard  # noqa: E402
from harness import BlockResult  # noqa: E402

_ACCEPTED_RUNS_LOG_RELATIVE_PATH = os.path.join("data", "arena", "accepted_runs.jsonl")


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
