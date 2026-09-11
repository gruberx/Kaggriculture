"""Enforces SPEC-gamelib.md's "Boundaries specific to this module": no file
under src/kagg/gamelib/ may import kaggle_environments - gamelib ships in
the submission bundle and Official Rules SS2.11 forbids anything beyond
the standard library there (see SPEC.md "Rule compliance").

Promoted from an ad-hoc AST scan run by hand after every gamelib task
(T0.1-T1.6) into a real test, so it runs with the rest of the suite
instead of relying on someone remembering to check.
"""

import ast
import pathlib

_GAMELIB_ROOT = pathlib.Path(__file__).parent.parent / "src" / "kagg" / "gamelib"


def _kaggle_environments_imports(source: str) -> list[str]:
    """Dotted module names of any real `import`/`from ... import`
    statement in `source` naming kaggle_environments - never a plain text
    match, which would also flag a comment or docstring mentioning it
    (exactly the false positive an ad-hoc `grep` produced during T0.1)."""
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "kaggle_environments":
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] == "kaggle_environments":
                found.append(node.module)
    return found


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
