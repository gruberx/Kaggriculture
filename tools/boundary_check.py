"""Shared AST-based `kaggle_environments`-import detector.

Extracted from tests/test_gamelib_boundary.py (T1.7) so tools/
build_submission.py's bundle audit (T5.1) and any dev-time boundary test
can share one implementation instead of two AST walks drifting apart.
See SPEC.md "Rule compliance": gamelib/agent/policy ship in the
submission bundle and must never import kaggle_environments.

Dev-only: this module itself is never bundled/shipped.
"""

from __future__ import annotations

import ast


def kaggle_environments_imports(source: str) -> list[str]:
    """Dotted module names of any real `import`/`from ... import`
    statement in `source` naming kaggle_environments - never a plain text
    match, which would also flag a comment or docstring mentioning it."""
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
