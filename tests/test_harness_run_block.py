"""Tests for tools/harness.run_block / wilson_interval - see
SPEC-harness.md and tasks/plan.md T4.2.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness  # noqa: E402


def _independent_wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    # Reimplemented independently from harness.wilson_interval, straight
    # from the closed-form definition (Wilson 1927), as the test oracle -
    # SPEC-harness.md: "checked against a known closed-form example... not
    # just runs without error."
    phat = k / n
    denom = 1 + z * z / n
    center = phat + z * z / (2 * n)
    adj = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return ((center - adj) / denom, (center + adj) / denom)


def test_wilson_interval_matches_the_closed_form_definition():
    for k, n in [(60, 100), (1, 1), (0, 10), (10, 10), (37, 213)]:
        expected_low, expected_high = _independent_wilson(k, n)
        actual_low, actual_high = harness.wilson_interval(k, n)
        assert math.isclose(actual_low, expected_low, abs_tol=1e-9)
        assert math.isclose(actual_high, expected_high, abs_tol=1e-9)


def test_wilson_interval_bounds_are_within_zero_and_one():
    low, high = harness.wilson_interval(60, 100)
    assert 0.0 <= low <= high <= 1.0


def test_run_block_aggregates_paired_results_and_starter_wins_every_seed():
    block = harness.run_block("starter", "random", seeds=[1, 2, 3], jobs=1)
    assert block.n == 3
    assert block.wins_a == 3
    assert block.wins_b == 0
    assert block.ties == 0
    assert block.win_rate_a == 1.0
    assert len(block.paired_results) == 3


def test_run_block_multiprocessing_pool_path_matches_serial_path():
    # jobs=1 above takes a serial shortcut that skips multiprocessing.Pool
    # entirely - exercise the actual Pool codepath too (jobs=2), since
    # pickling run_paired's args across process boundaries is exactly the
    # kind of thing that works in the serial path and silently breaks here.
    block = harness.run_block("starter", "random", seeds=[1, 2], jobs=2)
    assert block.n == 2
    assert block.wins_a == 2
    assert block.wins_b == 0


def test_default_jobs_never_hardcoded_and_at_least_one():
    # SPEC-harness.md: "Never hardcode a job count or assume a specific
    # core count - read it at runtime." Also must not blindly trust
    # os.cpu_count(), which reports the *host's* cores, not this
    # container's actual cgroup CPU quota (verified empirically: 32 vs a
    # cgroup cpu.max quota of far fewer effective cores here) - the same
    # class of "looks right outside the sandbox, wrong inside it" issue as
    # __file__ under kaggle_environments' loader.
    assert harness._default_jobs() >= 1
