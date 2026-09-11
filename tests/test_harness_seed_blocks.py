"""Tests for params/seed_blocks.json + harness.load_seed_blocks - see
SPEC-harness.md requirement 2 (a held-out block no tuning decision may
peek at) and tasks/plan.md T4.4.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import harness  # noqa: E402

SEED_BLOCKS_PATH = os.path.join(os.path.dirname(__file__), "..", "params", "seed_blocks.json")


def test_seed_blocks_file_exists():
    assert os.path.isfile(SEED_BLOCKS_PATH)


def test_load_seed_blocks_returns_nonempty_disjoint_sets():
    blocks = harness.load_seed_blocks()
    assert len(blocks.tuning_seeds) > 0
    assert len(blocks.holdout_seeds) > 0
    assert set(blocks.tuning_seeds).isdisjoint(set(blocks.holdout_seeds))


def test_load_seed_blocks_seeds_are_ints_with_no_internal_duplicates():
    blocks = harness.load_seed_blocks()
    for seeds in (blocks.tuning_seeds, blocks.holdout_seeds):
        assert all(isinstance(s, int) for s in seeds)
        assert len(seeds) == len(set(seeds))


def test_run_block_accepts_loaded_tuning_seeds():
    # SPEC-harness.md T4.4's own verify criterion: "loaded by run_block's
    # callers" - a real (small) integration, not just a loader unit test.
    blocks = harness.load_seed_blocks()
    block = harness.run_block("starter", "random", seeds=blocks.tuning_seeds[:2], jobs=1)
    assert block.n == 2
