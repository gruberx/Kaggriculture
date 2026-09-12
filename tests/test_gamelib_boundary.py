"""Enforces SPEC-gamelib.md's "Boundaries specific to this module": no file
under src/kagg/gamelib/ may import kaggle_environments - gamelib ships in
the submission bundle and Official Rules SS2.11 forbids anything beyond
the standard library there (see SPEC.md "Rule compliance").

Promoted from an ad-hoc AST scan run by hand after every gamelib task
(T0.1-T1.6) into a real test, so it runs with the rest of the suite
instead of relying on someone remembering to check.

The AST walk itself now lives in tools/boundary_check.py (extracted
during T5.1) so tools/build_submission.py's bundle audit can reuse it
instead of drifting apart from this test's own copy. Scope note (not yet
addressed here - see tasks/plan.md T6.6): this test still only scans
gamelib/, not policy/ or agent_main.py, even though both ship too.
"""

import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from boundary_check import kaggle_environments_imports as _kaggle_environments_imports  # noqa: E402

_GAMELIB_ROOT = pathlib.Path(__file__).parent.parent / "src" / "kagg" / "gamelib"


def test_no_gamelib_file_imports_kaggle_environments():
    violations = {
        str(path): found
        for path in _GAMELIB_ROOT.rglob("*.py")
        if (found := _kaggle_environments_imports(path.read_text()))
    }
    assert not violations, violations


def test_detector_actually_catches_a_real_import():
    # Guards the guard: a future refactor of the AST walk above that
    # silently stops detecting anything would otherwise make the test
    # above pass for the wrong reason (nothing left to find, rather than
    # nothing left to violate).
    assert _kaggle_environments_imports("import kaggle_environments\n") == [
        "kaggle_environments"
    ]
    # `ast.ImportFrom.module` is only the part before `import` - the
    # imported name itself ("kaggriculture") lives in `node.names`, not
    # appended to `module`.
    assert _kaggle_environments_imports(
        "from kaggle_environments.envs.kaggriculture import kaggriculture\n"
    ) == ["kaggle_environments.envs.kaggriculture"]


def test_detector_ignores_docstring_mentions():
    # The T0.1 false positive this test exists to not repeat: a docstring
    # referencing kaggle_environments as text is not an import.
    source = '"""Mirrors kaggle_environments/envs/kaggriculture/kaggriculture.py."""\n'
    assert _kaggle_environments_imports(source) == []
