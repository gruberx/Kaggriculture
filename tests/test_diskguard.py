"""Tests for tools/diskguard.py - see SPEC-diskguard.md.

Every test builds a synthetic project tree under tmp_path and monkeypatches
BUDGET_BYTES/SOFT_RATIO to small values, rather than touching the real
project root or writing gigabytes of test data.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import diskguard  # noqa: E402


def _write(path: str, size: int, mtime: float | None = None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _make_tree(root) -> None:
    for sub in ("data/replays", "data/episodes", "data/arena", "repo"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)


def test_usage_bytes_matches_actual_sizes(tmp_path):
    _make_tree(tmp_path)
    _write(str(tmp_path / "data/replays/a.json"), 100)
    _write(str(tmp_path / "data/arena/log.jsonl"), 50)
    _write(str(tmp_path / "repo/README.md"), 10)

    assert diskguard.usage_bytes(str(tmp_path)) == 160


def test_ensure_budget_is_noop_under_soft_threshold(tmp_path, monkeypatch):
    _make_tree(tmp_path)
    _write(str(tmp_path / "data/replays/a.json"), 100)
    monkeypatch.setattr(diskguard, "BUDGET_BYTES", 10_000)
    monkeypatch.setattr(diskguard, "SOFT_RATIO", 0.9)

    result = diskguard.ensure_budget(root=str(tmp_path))

    assert result.freed_bytes == 0
    assert result.evicted_paths == []
    assert os.path.exists(tmp_path / "data/replays/a.json")


def test_ensure_budget_evicts_oldest_evictable_files_first(tmp_path, monkeypatch):
    _make_tree(tmp_path)
    now = time.time()
    # Oldest replay first, newest last - eviction must remove oldest first
    # and stop as soon as it's back under the soft threshold.
    _write(str(tmp_path / "data/replays/old.json"), 40, mtime=now - 300)
    _write(str(tmp_path / "data/episodes/mid.json"), 40, mtime=now - 200)
    _write(str(tmp_path / "data/replays/new.json"), 40, mtime=now - 100)
    _write(str(tmp_path / "data/arena/history.jsonl"), 10)
    _write(str(tmp_path / "repo/README.md"), 10)

    # Total = 140 bytes. Soft cap = int(115 * 0.9) = 103: evicting just the
    # oldest file (40 bytes) brings usage to 100, already under the cap, so
    # eviction must stop there rather than also removing mid.json.
    monkeypatch.setattr(diskguard, "BUDGET_BYTES", 115)
    monkeypatch.setattr(diskguard, "SOFT_RATIO", 0.9)  # soft cap = 103

    result = diskguard.ensure_budget(root=str(tmp_path))

    assert result.freed_bytes == 40
    assert result.evicted_paths == [str(tmp_path / "data/replays/old.json")]
    assert not os.path.exists(tmp_path / "data/replays/old.json")
    assert os.path.exists(tmp_path / "data/episodes/mid.json")
    assert os.path.exists(tmp_path / "data/replays/new.json")
    # PROTECTED paths are never touched, even though they were candidates
    # by mtime if eviction had (incorrectly) considered them.
    assert os.path.exists(tmp_path / "data/arena/history.jsonl")
    assert os.path.exists(tmp_path / "repo/README.md")


def test_ensure_budget_never_evicts_protected_paths(tmp_path, monkeypatch):
    _make_tree(tmp_path)
    # Nothing evictable at all - everything lives in PROTECTED paths.
    _write(str(tmp_path / "data/arena/history.jsonl"), 100)
    _write(str(tmp_path / "repo/README.md"), 100)

    monkeypatch.setattr(diskguard, "BUDGET_BYTES", 50)
    monkeypatch.setattr(diskguard, "SOFT_RATIO", 0.9)

    with pytest.raises(diskguard.DiskBudgetExceeded):
        diskguard.ensure_budget(root=str(tmp_path))

    # The exception must not have been the result of deleting anything.
    assert os.path.exists(tmp_path / "data/arena/history.jsonl")
    assert os.path.exists(tmp_path / "repo/README.md")


def test_ensure_budget_raises_when_still_over_after_evicting_everything(
    tmp_path, monkeypatch
):
    _make_tree(tmp_path)
    _write(str(tmp_path / "data/replays/a.json"), 40)
    _write(str(tmp_path / "data/arena/history.jsonl"), 100)  # protected, large

    monkeypatch.setattr(diskguard, "BUDGET_BYTES", 50)
    monkeypatch.setattr(diskguard, "SOFT_RATIO", 0.9)

    with pytest.raises(diskguard.DiskBudgetExceeded):
        diskguard.ensure_budget(root=str(tmp_path))

    # Everything evictable was still removed even though it wasn't enough -
    # ensure_budget doesn't leave evictable files behind just because the
    # hard cap couldn't be met.
    assert not os.path.exists(tmp_path / "data/replays/a.json")
    assert os.path.exists(tmp_path / "data/arena/history.jsonl")


def test_ensure_budget_accounts_for_need_bytes(tmp_path, monkeypatch):
    _make_tree(tmp_path)
    monkeypatch.setattr(diskguard, "BUDGET_BYTES", 100)
    monkeypatch.setattr(diskguard, "SOFT_RATIO", 0.9)  # soft cap = 90

    # Empty tree, but a caller announcing a large incoming download should
    # still trigger eviction/failure based on projected, not current, usage.
    with pytest.raises(diskguard.DiskBudgetExceeded):
        diskguard.ensure_budget(need_bytes=200, root=str(tmp_path))


def test_project_root_honors_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGG_PROJECT_ROOT", str(tmp_path))
    assert diskguard._project_root() == str(tmp_path)
