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
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diskguard  # noqa: E402
import harness  # noqa: E402
from harness import BlockResult  # noqa: E402

_ACCEPTED_RUNS_LOG_RELATIVE_PATH = os.path.join("data", "arena", "accepted_runs.jsonl")

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_AGENT_MAIN_PATH = os.path.join(_REPO_ROOT, "src", "kagg", "agent_main.py")
_REAL_SRC_KAGG_DIR = os.path.join(_REPO_ROOT, "src", "kagg")
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


def _rewrite_kagg_imports(path: str, pkg: str) -> None:
    """Rewrite every `from kagg.` import in `path` to `from {pkg}.` in
    place. A plain substring replace is total and safe here: every
    kagg-internal import in src/ is of the single form `from kagg.<sub>
    import ...` (verified by grep across the whole package - no bare
    `import kagg`), so there is no other spelling to miss."""
    with open(path) as f:
        source = f.read()
    rewritten = source.replace("from kagg.", f"from {pkg}.")
    if rewritten != source:
        with open(path, "w") as f:
            f.write(rewritten)


def write_code_snapshot_agent(src_kagg_dir: str, workdir: str, params: dict | None = None) -> str:
    """Write a standalone agent file running a *copy* of `src_kagg_dir`'s
    code, importable under a unique package name so it cannot resolve to
    the live, editable-installed `kagg` package - the T8.0 measurement
    blocker.

    Verified directly before writing this function, not assumed: `kagg`
    is editable-installed via a `.pth` file that puts `src/` on
    `sys.path` at interpreter startup (i.e. near the *front* of
    sys.path), while kaggle_environments' loader
    (`kaggle_environments/agent.py`) only `sys.path.append(exec_dir)`s a
    raw agent file's own directory for the duration of loading it - at
    the *end* of sys.path. So `import kagg` inside any agent file always
    finds the live dev-tree package first, regardless of what a same-
    named copy sits next to that agent file on disk. `write_candidate_agent`
    (above) sidesteps this by never copying the package at all - it only
    patches one line in a copy of agent_main.py and imports
    `kagg.policy.params.load_params`, a pure function with no per-
    candidate state, so letting it resolve to the live package is
    harmless. A *code* snapshot has no such luxury: the whole point is to
    run different code, so the package itself must not collide.

    Renaming the package is the only fix that is safe regardless of how
    many snapshots (or a snapshot alongside the live agent_main.py) end
    up loaded in the same process - including inside one
    multiprocessing.Pool worker, exactly how harness.run_block executes
    both sides of a self-play match.
    """
    pkg = f"kagg_snap_{uuid.uuid4().hex[:12]}"
    pkg_dir = os.path.join(workdir, pkg)
    os.makedirs(pkg_dir, exist_ok=True)

    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copy2(os.path.join(src_kagg_dir, "__init__.py"), os.path.join(pkg_dir, "__init__.py"))
    shutil.copytree(os.path.join(src_kagg_dir, "gamelib"), os.path.join(pkg_dir, "gamelib"), ignore=ignore)
    shutil.copytree(os.path.join(src_kagg_dir, "policy"), os.path.join(pkg_dir, "policy"), ignore=ignore)
    params_dir = os.path.join(pkg_dir, "params")
    os.makedirs(params_dir)
    shutil.copy2(
        os.path.join(src_kagg_dir, "params", "policy.json"), os.path.join(params_dir, "policy.json")
    )
    # T8.68/T8.69: cycle_economics.py's per-crop cost/schedule table -
    # without this, a code snapshot's use_cycle_economics_ranking (now
    # the shipped default) silently degrades to every crop scoring 0.0
    # (_load_plant_shapes finds no file, falls back to {}) while the live
    # side computes real scores - found via a real, reproducible 3-0
    # sweep in test_snapshot_of_the_real_code_ties_the_live_agent_exactly
    # once that default flipped. Mirrors tools/build_submission.py's own
    # matching fix for the same gap in the Kaggle bundle.
    shutil.copy2(
        os.path.join(src_kagg_dir, "params", "tile_economics.json"),
        os.path.join(params_dir, "tile_economics.json"),
    )

    for dirpath, _dirnames, filenames in os.walk(pkg_dir):
        for name in filenames:
            if name.endswith(".py"):
                _rewrite_kagg_imports(os.path.join(dirpath, name), pkg)

    with open(os.path.join(src_kagg_dir, "agent_main.py")) as f:
        main_source = f.read()
    main_source = main_source.replace("from kagg.", f"from {pkg}.")

    if params is not None:
        occurrences = main_source.count(_PARAMS_LOAD_LINE)
        if occurrences != 1:
            raise RuntimeError(
                f"expected exactly one {_PARAMS_LOAD_LINE!r} line in "
                f"{src_kagg_dir}/agent_main.py, found {occurrences} - "
                "agent_main.py may have changed shape; update write_code_snapshot_agent to match"
            )
        params_path = os.path.join(workdir, f"snapshot_params_{pkg}.json")
        with open(params_path, "w") as f:
            json.dump(params, f)
        main_source = main_source.replace(_PARAMS_LOAD_LINE, f"_PARAMS = load_params({params_path!r})")

    main_path = os.path.join(workdir, f"main_{pkg}.py")
    with open(main_path, "w") as f:
        f.write(main_source)
    return main_path


def snapshot_agent_from_git_ref(
    ref: str, workdir: str, params: dict | None = None, repo_root: str = _REPO_ROOT
) -> str:
    """write_code_snapshot_agent, but sourced from `src/kagg` as it stood
    at git ref `ref` instead of the current working tree - for comparing
    a candidate against a specific previous commit (the checked-in
    baseline at HEAD, a tagged release, etc.) rather than uncommitted
    working-tree state."""
    extract_dir = os.path.join(workdir, f"git_src_{uuid.uuid4().hex[:12]}")
    os.makedirs(extract_dir, exist_ok=True)
    archive = subprocess.run(
        ["git", "archive", ref, "src/kagg"], cwd=repo_root, check=True, capture_output=True,
    )
    subprocess.run(["tar", "-x"], input=archive.stdout, cwd=extract_dir, check=True)
    return write_code_snapshot_agent(os.path.join(extract_dir, "src", "kagg"), workdir, params=params)


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


def evaluate_against_panel(
    agent_path: str,
    panel: list,
    seeds: list[int],
    workdir: str,
    jobs: int | None = None,
) -> BlockResult:
    """Run `agent_path` (a real or write_candidate_agent-generated agent
    file) against every opponent in `panel` on `seeds`, and combine the
    results into one aggregate BlockResult - SPEC-tuning.md: "the best
    Wilson-interval-adjusted win rate against a fixed opponent panel" is
    one combined score, not a separate number per opponent. Uses
    `harness.run_block` (module-level call, not a direct import) so
    callers/tests can monkeypatch `harness.run_block` itself.
    """
    total_n = total_wins_a = total_wins_b = total_ties = 0
    all_paired_results: list = []
    for opponent in panel:
        opponent_path = resolve_opponent(opponent, workdir)
        block = harness.run_block(agent_path, opponent_path, seeds, jobs=jobs)
        total_n += block.n
        total_wins_a += block.wins_a
        total_wins_b += block.wins_b
        total_ties += block.ties
        all_paired_results.extend(block.paired_results)
    return BlockResult(
        n=total_n,
        wins_a=total_wins_a,
        wins_b=total_wins_b,
        ties=total_ties,
        win_rate_a=total_wins_a / total_n,
        wilson_interval_a=harness.wilson_interval(total_wins_a, total_n),
        paired_results=tuple(all_paired_results),
    )
