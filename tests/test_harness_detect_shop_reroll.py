"""Tests for tools/harness.detect_shop_reroll - see SPEC-harness.md
requirement 3 and tasks/plan.md T4.3.

The town shop unlock sequence is town["unlocked_shops"] (verified by
direct inspection of a real episode's env.toJSON() output): a list that
only ever grows, one entry appended per in-game day at end-of-day refresh
(kaggriculture.py's town-shop-draw, `rng.choice(sorted(SHOPS))`, drawn
with replacement so the same shop can repeat) - shared identically
between both players' observations at a given step (verified: player 0's
and player 1's `observation["town"]` are equal at the same step).

Fixtures below build a minimal synthetic replay JSON (only the
`steps[-1][*]["observation"]["town"]["unlocked_shops"]` path
detect_shop_reroll actually reads) rather than capturing a real episode -
more robust to unrelated schema changes elsewhere in a real replay, and
self-documents exactly which field matters.
"""

import json
import os

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness  # noqa: E402


def _write_replay_fixture(path, unlocked_shops):
    replay = {
        "steps": [
            [
                {"observation": {"town": {"unlocked_shops": unlocked_shops}}},
                {"observation": {"town": {"unlocked_shops": unlocked_shops}}},
            ]
        ]
    }
    with open(path, "w") as f:
        json.dump(replay, f)


def test_detect_shop_reroll_false_when_sequences_match(tmp_path):
    replay_path = str(tmp_path / "replay.json")
    _write_replay_fixture(replay_path, ["FARMERS_MARKET", "BAKERY"])
    live_town_log = ["FARMERS_MARKET", "BAKERY"]
    assert harness.detect_shop_reroll(replay_path, live_town_log) is False


def test_detect_shop_reroll_true_when_a_later_entry_diverges(tmp_path):
    # A deliberately perturbed unlock sequence - SPEC-harness.md Testing:
    # "checked against a replay fixture with a deliberately perturbed
    # unlock sequence."
    replay_path = str(tmp_path / "replay.json")
    _write_replay_fixture(replay_path, ["FARMERS_MARKET", "BAKERY"])
    live_town_log = ["FARMERS_MARKET", "YARN_STORE"]
    assert harness.detect_shop_reroll(replay_path, live_town_log) is True


def test_detect_shop_reroll_true_when_first_entry_diverges(tmp_path):
    replay_path = str(tmp_path / "replay.json")
    _write_replay_fixture(replay_path, ["FARMERS_MARKET"])
    live_town_log = ["BAKERY"]
    assert harness.detect_shop_reroll(replay_path, live_town_log) is True


def test_detect_shop_reroll_only_compares_the_overlapping_prefix(tmp_path):
    # A live run that hasn't reached as many in-game days yet as the
    # recorded replay shouldn't be flagged just for being shorter - only
    # an actual mismatch in the shared prefix counts as a reroll.
    replay_path = str(tmp_path / "replay.json")
    _write_replay_fixture(replay_path, ["FARMERS_MARKET", "BAKERY", "YARN_STORE"])
    live_town_log = ["FARMERS_MARKET"]
    assert harness.detect_shop_reroll(replay_path, live_town_log) is False
