"""Enforces SPEC.md's "Rule compliance": no file that ships in the
submission bundle may import kaggle_environments - gamelib/policy/
agent_main.py must be standard-library-only (Official Rules SS2.11).

Promoted from an ad-hoc AST scan run by hand after every gamelib task
(T0.1-T1.6) into a real test, so it runs with the rest of the suite
instead of relying on someone remembering to check. Widened in T6.6
(tasks/plan.md) to cover policy/ and agent_main.py too, not just
gamelib/ - a real, if small, gap: this session's own commit messages
had claimed "no kaggle_environments import under gamelib/ or policy/"
several times before this test actually checked policy/ at all (it
happened to be true, but the test never verified it).

The AST walk itself lives in tools/boundary_check.py (extracted during
T5.1) so tools/build_submission.py's bundle audit reuses the exact same
logic instead of drifting apart from this test's own copy.
"""

import os
import pathlib
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from boundary_check import kaggle_environments_imports  # noqa: E402

_SRC_KAGG = pathlib.Path(__file__).parent.parent / "src" / "kagg"
_SHIPPED_DIRS = ("gamelib", "policy")
_SHIPPED_FILES = ("agent_main.py",)


def _shipped_files(src_kagg_root: pathlib.Path) -> list[pathlib.Path]:
    files = []
    for d in _SHIPPED_DIRS:
        files.extend((src_kagg_root / d).rglob("*.py"))
    files.extend(src_kagg_root / f for f in _SHIPPED_FILES)
    return files


def _shipped_boundary_violations(src_kagg_root: pathlib.Path) -> dict:
    return {
        str(path): found
        for path in _shipped_files(src_kagg_root)
        if (found := kaggle_environments_imports(path.read_text()))
    }


def test_no_shipped_file_imports_kaggle_environments():
    assert not _shipped_boundary_violations(_SRC_KAGG)


def test_boundary_scan_catches_a_planted_violation_in_policy(tmp_path):
    # Not just the detector function in isolation (that's the next two
    # tests) - the actual file-scan this test suite relies on, exercised
    # against a scratch copy so checked-in source is never touched.
    scratch_root = tmp_path / "kagg"
    shutil.copytree(_SRC_KAGG, scratch_root, ignore=shutil.ignore_patterns("__pycache__"))
    victim = scratch_root / "policy" / "decide.py"
    with open(victim, "a") as f:
        f.write("\nimport kaggle_environments\n")

    violations = _shipped_boundary_violations(scratch_root)

    assert violations
    assert any("decide.py" in path for path in violations)


def test_boundary_scan_catches_a_planted_violation_in_agent_main(tmp_path):
    scratch_root = tmp_path / "kagg"
    shutil.copytree(_SRC_KAGG, scratch_root, ignore=shutil.ignore_patterns("__pycache__"))
    victim = scratch_root / "agent_main.py"
    with open(victim, "a") as f:
        f.write("\nimport kaggle_environments\n")

    violations = _shipped_boundary_violations(scratch_root)

    assert violations
    assert any("agent_main.py" in path for path in violations)


def test_detector_actually_catches_a_real_import():
    # Guards the guard: a future refactor of the AST walk in
    # tools/boundary_check.py that silently stops detecting anything
    # would otherwise make the tests above pass for the wrong reason
    # (nothing left to find, rather than nothing left to violate).
    assert kaggle_environments_imports("import kaggle_environments\n") == [
        "kaggle_environments"
    ]
    # `ast.ImportFrom.module` is only the part before `import` - the
    # imported name itself ("kaggriculture") lives in `node.names`, not
    # appended to `module`.
    assert kaggle_environments_imports(
        "from kaggle_environments.envs.kaggriculture import kaggriculture\n"
    ) == ["kaggle_environments.envs.kaggriculture"]


def test_detector_ignores_docstring_mentions():
    # The T0.1 false positive this test exists to not repeat: a docstring
    # referencing kaggle_environments as text is not an import.
    source = '"""Mirrors kaggle_environments/envs/kaggriculture/kaggriculture.py."""\n'
    assert kaggle_environments_imports(source) == []
