"""Tests for tools/build_submission.py - see SPEC-ops.md "Submission
bundling" and tasks/plan.md T5.1.

Uses the real src/kagg tree for most tests (genuine confidence that the
actual shipped code bundles and runs cleanly, not just a synthetic
stand-in) except where a test needs to *inject* a violation, which
copies the real tree into a scratch dir first rather than ever touching
checked-in source.
"""

import os
import shutil
import sys
import tarfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import build_submission  # noqa: E402

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
_REAL_SRC_KAGG = os.path.join(_REPO_ROOT, "src", "kagg")
_SMOKE_TEST_STEPS = 48  # short episode - enough to catch import/path errors, not a full 720-turn run


def test_copy_bundle_produces_the_expected_layout(tmp_path):
    build_dir = str(tmp_path / "build")
    build_submission.copy_bundle(_REAL_SRC_KAGG, build_dir)

    assert os.path.isfile(os.path.join(build_dir, "main.py"))
    assert os.path.isfile(os.path.join(build_dir, "kagg", "__init__.py"))
    assert os.path.isfile(os.path.join(build_dir, "kagg", "gamelib", "__init__.py"))
    assert os.path.isfile(os.path.join(build_dir, "kagg", "policy", "__init__.py"))
    assert os.path.isfile(os.path.join(build_dir, "kagg", "params", "policy.json"))
    # Never bundled: harness's dev-only seed block config isn't under
    # src/kagg/params/ at all (it's the repo-root params/), so this also
    # locks in that copy_bundle never reaches outside src_kagg_dir.
    assert not os.path.exists(os.path.join(build_dir, "kagg", "params", "seed_blocks.json"))


def test_copy_bundle_excludes_pycache(tmp_path):
    build_dir = str(tmp_path / "build")
    build_submission.copy_bundle(_REAL_SRC_KAGG, build_dir)
    for dirpath, dirnames, filenames in os.walk(build_dir):
        assert "__pycache__" not in dirnames
        assert not any(name.endswith(".pyc") for name in filenames)


def test_audit_bundle_is_clean_on_the_real_repo_tree(tmp_path):
    build_dir = str(tmp_path / "build")
    build_submission.copy_bundle(_REAL_SRC_KAGG, build_dir)
    assert build_submission.audit_bundle(build_dir) == []


def test_audit_bundle_detects_a_planted_violation(tmp_path):
    build_dir = str(tmp_path / "build")
    build_submission.copy_bundle(_REAL_SRC_KAGG, build_dir)
    victim = os.path.join(build_dir, "kagg", "gamelib", "constants.py")
    with open(victim, "a") as f:
        f.write("\nimport kaggle_environments\n")

    violations = build_submission.audit_bundle(build_dir)

    assert violations
    assert any("constants.py" in v for v in violations)


def test_smoke_test_passes_for_the_real_bundle(tmp_path):
    build_dir = str(tmp_path / "build")
    build_submission.copy_bundle(_REAL_SRC_KAGG, build_dir)
    ok, detail = build_submission.smoke_test(
        os.path.join(build_dir, "main.py"), episode_steps=_SMOKE_TEST_STEPS
    )
    assert ok, detail


def test_smoke_test_fails_when_the_bundle_is_missing_kagg_even_though_the_dev_tree_has_it(tmp_path):
    """Regression test for a real, previously unnoticed ops gap (T8.0):
    `kagg` is editable-installed, putting src/ on sys.path at interpreter
    startup - *ahead of* kaggle_environments' own loader, which only
    `sys.path.append(exec_dir)`s a raw agent file's directory (appended,
    so it always loses that race). An in-process smoke test therefore
    always finds the live dev-tree kagg package first, regardless of
    what's actually sitting next to the bundle's main.py on disk - so a
    bundle entirely missing its kagg/ package still "passed" by silently
    falling back to the live tree. Reproduced here by copying only
    main.py, deliberately not kagg/: the fixed smoke_test must fail, not
    silently succeed.
    """
    build_dir = str(tmp_path / "build")
    os.makedirs(build_dir)
    shutil.copy2(os.path.join(_REAL_SRC_KAGG, "agent_main.py"), os.path.join(build_dir, "main.py"))
    # Deliberately no kagg/ directory copied.

    ok, detail = build_submission.smoke_test(
        os.path.join(build_dir, "main.py"), episode_steps=_SMOKE_TEST_STEPS
    )

    assert not ok, (
        "smoke_test must fail for a bundle missing its kagg/ package, "
        f"not silently fall back to the dev tree (detail={detail!r})"
    )


def test_build_creates_a_tarball_with_main_py_at_the_root(tmp_path):
    build_dir = str(tmp_path / "build")
    out_path = str(tmp_path / "submission.tar.gz")

    exit_code = build_submission.build(
        src_kagg_dir=_REAL_SRC_KAGG,
        build_dir=build_dir,
        out_path=out_path,
        episode_steps=_SMOKE_TEST_STEPS,
    )

    assert exit_code == 0
    assert os.path.isfile(out_path)
    names = tarfile.open(out_path).getnames()
    assert "main.py" in names
    assert "kagg/params/policy.json" in names
    assert "kagg/gamelib/constants.py" in names
    assert not any(n.endswith("seed_blocks.json") for n in names)


def test_extracted_bundle_runs_independently_of_the_dev_tree(tmp_path):
    # The real acceptance criterion: a fresh directory, no dev-tree
    # sys.path, extracted straight from the tarball.
    build_dir = str(tmp_path / "build")
    out_path = str(tmp_path / "submission.tar.gz")
    build_submission.build(
        src_kagg_dir=_REAL_SRC_KAGG,
        build_dir=build_dir,
        out_path=out_path,
        episode_steps=_SMOKE_TEST_STEPS,
    )

    extract_dir = str(tmp_path / "extracted")
    os.makedirs(extract_dir)
    with tarfile.open(out_path) as tf:
        tf.extractall(extract_dir, filter="data")

    ok, detail = build_submission.smoke_test(
        os.path.join(extract_dir, "main.py"), episode_steps=_SMOKE_TEST_STEPS
    )
    assert ok, detail


def test_build_fails_and_produces_no_tarball_when_the_bundle_has_a_violation(tmp_path):
    scratch_src = str(tmp_path / "scratch_src_kagg")
    # Build a scratch src/kagg tree (copy_bundle's *source* layout, not its
    # output) with a planted violation, so the violation is caught before
    # any real repo file is ever touched.
    import shutil

    shutil.copytree(_REAL_SRC_KAGG, scratch_src, ignore=shutil.ignore_patterns("__pycache__"))
    with open(os.path.join(scratch_src, "policy", "decide.py"), "a") as f:
        f.write("\nimport kaggle_environments\n")

    build_dir = str(tmp_path / "build")
    out_path = str(tmp_path / "submission.tar.gz")
    exit_code = build_submission.build(
        src_kagg_dir=scratch_src, build_dir=build_dir, out_path=out_path, episode_steps=_SMOKE_TEST_STEPS
    )

    assert exit_code != 0
    assert not os.path.exists(out_path)
