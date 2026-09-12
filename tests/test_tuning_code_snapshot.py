"""Tests for tools/tuning.py's code-snapshot opponent - see tasks/plan.md
T8.0 and /root/.claude/plans/partitioned-puzzling-blossom.md.

Blocker this closes, verified directly before writing any fix: `kagg` is
editable-installed (a `.pth` file puts `src/` on `sys.path` at interpreter
startup), and `kaggle_environments/agent.py`'s loader only
`sys.path.append(exec_dir)`s a raw agent file's own directory - appended,
so it lands *after* the editable install's entry. `import kagg` inside a
loaded agent therefore always resolves to the live dev-tree package,
never to a same-named copy placed anywhere on disk. Before this module's
fix, a params-only override (`write_candidate_agent`) was safe (it never
copies the package, only patches one line and imports `kagg.policy.params`
- a pure function with no per-candidate state), but any *code* snapshot
used as an opponent would silently run the live code instead of the
snapshot, making a code-vs-code arena block read a meaningless ~50/50 no
matter what actually changed.
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness  # noqa: E402
import tuning  # noqa: E402

from kaggle_environments import make  # noqa: E402

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
_REAL_SRC_KAGG = os.path.join(_REPO_ROOT, "src", "kagg")
_SMOKE_STEPS = 8  # short - enough to observe one recorded action, not a full episode

_SENTINEL_DECIDE_OVERRIDE = """

def decide(obs, params):
    return {{"farmer": ["PASS"], "hands": [], "market": [["{sentinel}"]]}}
"""


def _scratch_src_with_sentinel_decide(tmp_path, name: str, sentinel: str) -> str:
    """A scratch copy of the real src/kagg tree whose decide() is
    replaced by a stub returning a recognizable sentinel market order -
    Python executes a module top-to-bottom, so a second `def decide` at
    the end of the file simply shadows the real one, without needing to
    understand or preserve the original's signature/behavior."""
    scratch = str(tmp_path / name)
    shutil.copytree(_REAL_SRC_KAGG, scratch, ignore=shutil.ignore_patterns("__pycache__"))
    with open(os.path.join(scratch, "policy", "decide.py"), "a") as f:
        f.write(_SENTINEL_DECIDE_OVERRIDE.format(sentinel=sentinel))
    return scratch


def _first_turn_market(agent_path: str) -> list:
    env = make("kaggriculture", configuration={"episodeSteps": _SMOKE_STEPS, "seed": 1}, debug=True)
    env.run([agent_path, "pass"])
    return env.steps[1][0]["action"]["market"]


def test_snapshot_runs_the_snapshot_code_not_the_live_package(tmp_path):
    scratch = _scratch_src_with_sentinel_decide(tmp_path, "scratch_src", "SENTINEL_FROM_SNAPSHOT")

    agent_path = tuning.write_code_snapshot_agent(scratch, str(tmp_path))

    assert _first_turn_market(agent_path) == [["SENTINEL_FROM_SNAPSHOT"]]


def test_two_snapshots_are_independent_in_one_process(tmp_path):
    # The exact hazard write_candidate_agent's own docstring warns an
    # `import kagg.agent_main`-based wrapper would have: two candidates'
    # code compared in the same process, one silently winning the other's
    # module cache. A package-name collision would make both agents below
    # resolve to whichever loaded first.
    scratch_a = _scratch_src_with_sentinel_decide(tmp_path, "scratch_a", "SENTINEL_A")
    scratch_b = _scratch_src_with_sentinel_decide(tmp_path, "scratch_b", "SENTINEL_B")
    agent_a = tuning.write_code_snapshot_agent(scratch_a, str(tmp_path))
    agent_b = tuning.write_code_snapshot_agent(scratch_b, str(tmp_path))

    assert _first_turn_market(agent_a) == [["SENTINEL_A"]]
    assert _first_turn_market(agent_b) == [["SENTINEL_B"]]

    # Both loaded together, in one process, one episode - the real shape
    # a self-play arena block needs.
    env = make("kaggriculture", configuration={"episodeSteps": _SMOKE_STEPS, "seed": 1}, debug=True)
    env.run([agent_a, agent_b])
    assert env.steps[1][0]["action"]["market"] == [["SENTINEL_A"]]
    assert env.steps[1][1]["action"]["market"] == [["SENTINEL_B"]]


def test_snapshot_of_the_real_code_ties_the_live_agent_exactly(tmp_path):
    """Acceptance criterion from the plan: run_block(live, snapshot) on a
    handful of seeds must be an exact tie every time, with identical
    per-seed money in both seatings - a snapshot of unmodified code is a
    faithful copy, not an approximation, so self-play against it has zero
    real signal (any real signal in a later task's measurement must come
    from an actual code difference, not from copying infidelity here)."""
    snapshot_path = tuning.write_code_snapshot_agent(_REAL_SRC_KAGG, str(tmp_path))

    block = harness.run_block(tuning._AGENT_MAIN_PATH, snapshot_path, [100, 101, 102], jobs=2)

    assert block.wins_a == 0
    assert block.wins_b == 0
    assert block.ties == block.n
    for paired in block.paired_results:
        assert paired.a_total_money == paired.b_total_money


def test_snapshot_accepts_a_params_override_like_write_candidate_agent(tmp_path):
    override = {"hires_per_day": 3}

    agent_path = tuning.write_code_snapshot_agent(_REAL_SRC_KAGG, str(tmp_path), params=override)

    # Doesn't crash and produces a runnable agent - the params plumbing is
    # already covered in depth by write_candidate_agent's own tests; this
    # just confirms the snapshot mechanism composes with it.
    env = make("kaggriculture", configuration={"episodeSteps": _SMOKE_STEPS, "seed": 1}, debug=True)
    env.run([agent_path, "pass"])
    assert env.steps[-1][0].status == "DONE"
