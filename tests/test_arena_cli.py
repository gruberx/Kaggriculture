"""Tests for tools/arena.py - see SPEC.md's documented invocation,
SPEC-harness.md's --holdout boundary, and tasks/plan.md T4.5.

Most tests here monkeypatch harness.run_block/load_seed_blocks (and, for
the --holdout tests, diskguard.ensure_budget + the data/arena/ log
location via KAGG_PROJECT_ROOT, diskguard's own override mechanism) to
stay fast and deterministic - CLI wiring and the holdout-logging
boundary are what's under test here, not run_block's own correctness
(already covered by tests/test_harness_run_block.py). One small real
end-to-end run (2 seeds vs "pass") is included for genuine confidence
that the pieces are wired together correctly, not just individually
mocked correctly.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import arena  # noqa: E402
import diskguard  # noqa: E402
import harness  # noqa: E402


def _fake_block_result(seeds, jobs):
    return harness.BlockResult(
        n=len(seeds),
        wins_a=len(seeds),
        wins_b=0,
        ties=0,
        win_rate_a=1.0,
        wilson_interval_a=(0.8, 1.0),
        paired_results=(),
    )


def test_default_invocation_uses_tuning_block_and_prints_win_rate(monkeypatch, capsys):
    calls = {}

    def fake_run_block(agent_a, agent_b, seeds, jobs=None):
        calls["agent_a"] = agent_a
        calls["agent_b"] = agent_b
        calls["seeds"] = list(seeds)
        calls["jobs"] = jobs
        return _fake_block_result(seeds, jobs)

    monkeypatch.setattr(harness, "run_block", fake_run_block)
    monkeypatch.setattr(
        harness,
        "load_seed_blocks",
        lambda: harness.SeedBlocks(tuning_seeds=(1, 2, 3, 4), holdout_seeds=(900, 901)),
    )

    exit_code = arena.main(["--opponent", "starter", "--seeds", "2", "--jobs", "auto"])

    assert exit_code == 0
    assert calls["agent_b"] == "starter"
    assert calls["seeds"] == [1, 2]  # first 2 of the *tuning* block, not holdout
    assert calls["jobs"] is None  # "auto" -> None, resolved by run_block itself

    out = capsys.readouterr().out
    assert "win rate" in out.lower()
    assert "0.8" in out and "1.0" in out  # the Wilson interval bounds


def test_jobs_explicit_int_is_passed_through(monkeypatch):
    calls = {}

    def fake_run_block(agent_a, agent_b, seeds, jobs=None):
        calls["jobs"] = jobs
        return _fake_block_result(seeds, jobs)

    monkeypatch.setattr(harness, "run_block", fake_run_block)
    monkeypatch.setattr(
        harness, "load_seed_blocks", lambda: harness.SeedBlocks(tuning_seeds=(1, 2), holdout_seeds=(900,))
    )

    arena.main(["--opponent", "starter", "--seeds", "2", "--jobs", "3"])
    assert calls["jobs"] == 3


def test_holdout_flag_uses_holdout_block_and_logs_the_invocation(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("KAGG_PROJECT_ROOT", str(tmp_path))

    def fake_run_block(agent_a, agent_b, seeds, jobs=None):
        return _fake_block_result(seeds, jobs)

    monkeypatch.setattr(harness, "run_block", fake_run_block)
    monkeypatch.setattr(
        harness,
        "load_seed_blocks",
        lambda: harness.SeedBlocks(tuning_seeds=(1, 2, 3), holdout_seeds=(900, 901)),
    )

    ensure_budget_calls = []
    real_ensure_budget = diskguard.ensure_budget

    def spying_ensure_budget(*a, **kw):
        ensure_budget_calls.append((a, kw))
        return real_ensure_budget(*a, **kw)

    monkeypatch.setattr(diskguard, "ensure_budget", spying_ensure_budget)

    arena.main(["--opponent", "starter", "--seeds", "2", "--holdout"])

    assert len(ensure_budget_calls) == 1  # logged via ensure_budget() before the write

    log_path = tmp_path / "data" / "arena" / "holdout_invocations.jsonl"
    assert log_path.is_file()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["opponent"] == "starter"
    assert entries[0]["seeds"] == [900, 901]  # holdout block, not tuning


def test_without_holdout_flag_never_writes_to_data_arena(monkeypatch, tmp_path):
    monkeypatch.setenv("KAGG_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(
        harness, "run_block", lambda agent_a, agent_b, seeds, jobs=None: _fake_block_result(seeds, jobs)
    )
    monkeypatch.setattr(
        harness, "load_seed_blocks", lambda: harness.SeedBlocks(tuning_seeds=(1, 2), holdout_seeds=(900,))
    )

    arena.main(["--opponent", "starter", "--seeds", "2"])

    assert not (tmp_path / "data" / "arena").exists()


def test_real_end_to_end_small_run_against_pass():
    exit_code = arena.main(["--opponent", "pass", "--seeds", "1", "--jobs", "1"])
    assert exit_code == 0
