"""Tests for tools/harness.run_paired - see SPEC-harness.md and
tasks/plan.md T4.1.

Follows tests/test_diskguard.py's sys.path convention (tools/ isn't a
package, it's dev-only tooling that never ships - see SPEC-harness.md
"Boundaries specific to this module").
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness  # noqa: E402

AGENT_MAIN_PATH = os.path.join(os.path.dirname(__file__), "..", "src", "kagg", "agent_main.py")


def test_two_copies_of_pass_tie_on_every_seed():
    # SPEC-harness.md Testing: "run_paired against two copies of pass:
    # result must be a tie on every seed (symmetric matchup, deterministic
    # given a seed)."
    for seed in (1, 2, 3):
        result = harness.run_paired("pass", "pass", seed)
        assert result.winner == "tie", seed
        assert result.a_total_money == result.b_total_money


def test_starter_beats_random_regardless_of_seat():
    # SPEC-harness.md Testing: confirms seat-pairing doesn't silently
    # favor one side - starter must win as both "a" and "b".
    result_a = harness.run_paired("starter", "random", seed=1)
    assert result_a.winner == "a"
    result_b = harness.run_paired("random", "starter", seed=1)
    assert result_b.winner == "b"


def test_result_carries_both_raw_episode_records():
    result = harness.run_paired("pass", "pass", seed=1)
    assert len(result.episodes) == 2
