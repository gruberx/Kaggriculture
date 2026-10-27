"""Package src/kagg into a Kaggle submission bundle - see SPEC-ops.md
"Submission bundling" and tasks/plan.md T5.1.

    python tools/build_submission.py --out build/submission.tar.gz

Dev-only, never ships itself. The bundle it produces (main.py + kagg/)
must be stdlib-only per SPEC.md "Rule compliance" - the audit step below
enforces that on the *built* tree (catching agent_main.py too, not just
gamelib/policy, since it scans everything actually shipped), failing the
build rather than warning on any violation.

Confirmed by hand before this script existed: a from-scratch bundle
assembled this same way (no dev-tree sys.path tricks) runs a real
kaggle_environments episode to completion - see tasks/plan.md Phase 5's
context section.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_check import kaggle_environments_imports  # noqa: E402

_DEFAULT_SRC_KAGG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "src", "kagg"
)
_DEFAULT_BUILD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build")
_DEFAULT_OUT_PATH = os.path.join(_DEFAULT_BUILD_DIR, "submission.tar.gz")
_DEFAULT_EPISODE_STEPS = 720


def copy_bundle(src_kagg_dir: str, build_dir: str) -> None:
    """Lay out `build_dir` as a Kaggle submission expects: `main.py` at
    the root (from agent_main.py) plus a `kagg/` package with only what
    ships (gamelib/, policy/, params/policy.json, __init__.py) - never
    tests, tools, or the repo-root params/ (seed_blocks.json etc., dev-
    only, confirmed unread by policy at runtime - see SPEC-ops.md)."""
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir)

    shutil.copy2(os.path.join(src_kagg_dir, "agent_main.py"), os.path.join(build_dir, "main.py"))

    kagg_dir = os.path.join(build_dir, "kagg")
    os.makedirs(kagg_dir)
    shutil.copy2(os.path.join(src_kagg_dir, "__init__.py"), os.path.join(kagg_dir, "__init__.py"))

    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(os.path.join(src_kagg_dir, "gamelib"), os.path.join(kagg_dir, "gamelib"), ignore=ignore)
    shutil.copytree(os.path.join(src_kagg_dir, "policy"), os.path.join(kagg_dir, "policy"), ignore=ignore)

    params_dir = os.path.join(kagg_dir, "params")
    os.makedirs(params_dir)
    shutil.copy2(
        os.path.join(src_kagg_dir, "params", "policy.json"), os.path.join(params_dir, "policy.json")
    )
    # T8.68: cycle_economics.py's per-crop cost/schedule table - a static
    # snapshot of tasks/data/tile_economics.json (dev-only, not shipped
    # itself), copied here the same way policy.json is so it actually
    # reaches the built bundle. Regenerate both together via
    # `python tools/tile_economics_30d.py --write` followed by
    # `cp tasks/data/tile_economics.json src/kagg/params/tile_economics.json`
    # if the crop/animal constants they're derived from ever change.
    shutil.copy2(
        os.path.join(src_kagg_dir, "params", "tile_economics.json"),
        os.path.join(params_dir, "tile_economics.json"),
    )


def audit_bundle(build_dir: str) -> list[str]:
    """Every `kaggle_environments` import found anywhere in the built
    tree, described as "<path>: <dotted module>" - empty means clean.
    Scans the *built* output, not the dev src tree, so it also covers
    main.py (agent_main.py's copy), not just gamelib/policy."""
    violations = []
    for dirpath, _dirnames, filenames in os.walk(build_dir):
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path) as f:
                source = f.read()
            for module in kaggle_environments_imports(source):
                violations.append(f"{path}: {module}")
    return violations


def _editable_src_dir() -> str:
    """Absolute path of the editable-installed dev-tree kagg package's
    parent directory (its `src/`) - found via the live import rather
    than hardcoded, so this works in any dev environment, not just this
    one. Used by smoke_test to exclude it from the subprocess's
    sys.path (see that function's docstring for why this matters)."""
    import kagg

    return os.path.dirname(os.path.dirname(os.path.abspath(kagg.__file__)))


_SMOKE_TEST_SCRIPT = """
import json
import os
import sys

sys.path = [p for p in sys.path if os.path.abspath(p) != {editable_src_dir!r}]

from kaggle_environments import make

env = make("kaggriculture", configuration={{"episodeSteps": {episode_steps}, "seed": 1}}, debug=False)
env.run([{main_py_path!r}, "random"])
final = env.steps[-1]

import kagg

print(json.dumps({{
    "statuses": [final[0].status, final[1].status],
    "kagg_file": os.path.abspath(kagg.__file__),
}}))
"""


def smoke_test(main_py_path: str, episode_steps: int = _DEFAULT_EPISODE_STEPS) -> tuple[bool, str]:
    """Run a real episode against the built main.py (against "random",
    matching SPEC-ops.md) to catch import/path errors before they cost a
    submission slot. Returns (ok, detail) - detail explains a failure.

    Runs in a clean subprocess whose sys.path excludes the editable
    dev-tree's src/ directory - a real, previously unnoticed gap found
    while planning T8.0, not a hypothetical: `kagg` is editable-installed
    (a `.pth` file puts src/ on sys.path at interpreter startup, ahead of
    anything kaggle_environments' loader appends later), so an in-process
    smoke test always resolves `import kagg` to the *live* dev-tree
    package regardless of what actually sits next to `main_py_path` on
    disk. That made this smoke test pure theater: a bundle entirely
    missing its kagg/ package still "passed" by silently falling back to
    the dev tree (see this module's own regression test for the
    reproduction). The subprocess strips that one sys.path entry before
    importing anything, and the resolved `kagg.__file__` is checked
    against `main_py_path`'s own directory afterward, so this now
    actually proves the bundle is self-contained.
    """
    bundle_kagg_dir = os.path.join(os.path.dirname(os.path.abspath(main_py_path)), "kagg")
    script = _SMOKE_TEST_SCRIPT.format(
        editable_src_dir=_editable_src_dir(),
        episode_steps=episode_steps,
        main_py_path=os.path.abspath(main_py_path),
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        return False, f"smoke-test subprocess failed:\n{result.stderr[-4000:]}"

    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, f"smoke-test subprocess produced no parseable output:\n{result.stdout}\n{result.stderr}"

    statuses = tuple(payload["statuses"])
    if statuses != ("DONE", "DONE"):
        return False, f"expected (DONE, DONE), got {statuses}"

    kagg_file = payload["kagg_file"]
    if not kagg_file.startswith(bundle_kagg_dir + os.sep):
        return False, (
            f"smoke test ran the wrong kagg package: expected it under {bundle_kagg_dir}, "
            f"got {kagg_file} - the bundle is likely missing kagg/ and silently fell back "
            "to some other package on sys.path"
        )
    return True, ""


def make_tarball(build_dir: str, out_path: str) -> None:
    """`tar -czf out_path -C build_dir main.py kagg` - main.py at the tar
    root, matching AGENTS.md's documented multi-file format."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with tarfile.open(out_path, "w:gz") as tf:
        tf.add(os.path.join(build_dir, "main.py"), arcname="main.py")
        tf.add(os.path.join(build_dir, "kagg"), arcname="kagg")


def build(
    src_kagg_dir: str = _DEFAULT_SRC_KAGG_DIR,
    build_dir: str = _DEFAULT_BUILD_DIR,
    out_path: str = _DEFAULT_OUT_PATH,
    episode_steps: int = _DEFAULT_EPISODE_STEPS,
) -> int:
    """Bundle, audit, smoke-test, then tar - in that order, each step
    gating the next. Returns 0 on success; a nonzero exit and no tarball
    on any failure (SPEC-ops.md: "build fails, does not warn")."""
    copy_bundle(src_kagg_dir, build_dir)

    violations = audit_bundle(build_dir)
    if violations:
        print("Bundle audit FAILED - kaggle_environments import(s) found in the built bundle:")
        for v in violations:
            print(f"  {v}")
        return 1

    ok, detail = smoke_test(os.path.join(build_dir, "main.py"), episode_steps=episode_steps)
    if not ok:
        print(f"Smoke test FAILED: {detail}")
        return 1

    make_tarball(build_dir, out_path)
    print(f"Built {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Kaggriculture submission bundle.")
    parser.add_argument("--out", default=_DEFAULT_OUT_PATH, help="output tarball path")
    args = parser.parse_args(argv)
    return build(out_path=args.out)


if __name__ == "__main__":
    sys.exit(main())
