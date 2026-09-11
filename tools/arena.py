"""CLI for tools/harness.run_block - see SPEC.md's documented invocation
and SPEC-harness.md's --holdout boundary, tasks/plan.md T4.5.

    python tools/arena.py --opponent starter --seeds 100 --jobs auto

Dev-only, never ships (SPEC-harness.md "Boundaries specific to this
module").

By default, runs against the *working* (tuning) seed block from
params/seed_blocks.json - the block `tuning` may burn through freely
while iterating (SPEC-harness.md requirement 2). --holdout switches to
the held-out block instead, and every --holdout invocation is logged to
data/arena/holdout_invocations.jsonl (after an diskguard.ensure_budget()
check, like every data/arena/ write) so "did a tuning decision peek at
the held-out number" is answerable later from that log, not tribal
memory - the entire reason SPEC-harness.md requires this to be an
explicit, logged flag rather than a quiet code-path switch.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diskguard  # noqa: E402
import harness  # noqa: E402

AGENT_MAIN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "src", "kagg", "agent_main.py"
)

_HOLDOUT_LOG_RELATIVE_PATH = os.path.join("data", "arena", "holdout_invocations.jsonl")


def _parse_jobs(raw: str) -> int | None:
    if raw == "auto":
        return None
    return int(raw)


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--opponent", required=True, help='e.g. "starter", "random", "pass", or an agent path')
    parser.add_argument("--seeds", type=int, required=True, help="number of seeds to use from the seed block")
    parser.add_argument("--jobs", default="auto", help='worker process count, or "auto" (default)')
    parser.add_argument(
        "--holdout",
        action="store_true",
        help="use the held-out seed block instead of the working (tuning) block; every "
        "invocation is logged to data/arena/holdout_invocations.jsonl",
    )
    return parser.parse_args(argv)


def _log_holdout_invocation(opponent: str, seeds: list[int], block: harness.BlockResult) -> None:
    diskguard.ensure_budget()
    root = diskguard._project_root()
    log_path = os.path.join(root, _HOLDOUT_LOG_RELATIVE_PATH)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "opponent": opponent,
        "seeds": seeds,
        "wins_a": block.wins_a,
        "wins_b": block.wins_b,
        "ties": block.ties,
        "win_rate_a": block.win_rate_a,
        "wilson_interval_a": list(block.wilson_interval_a),
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    jobs = _parse_jobs(args.jobs)

    blocks = harness.load_seed_blocks()
    seed_pool = blocks.holdout_seeds if args.holdout else blocks.tuning_seeds
    seeds = list(seed_pool[: args.seeds])

    block = harness.run_block(AGENT_MAIN_PATH, args.opponent, seeds=seeds, jobs=jobs)

    block_name = "holdout" if args.holdout else "tuning"
    low, high = block.wilson_interval_a
    print(f"Opponent: {args.opponent}")
    print(f"Seed block: {block_name} ({block.n} seeds)")
    print(f"Wins: {block.wins_a}  Losses: {block.wins_b}  Ties: {block.ties}")
    print(f"Win rate (our agent): {block.win_rate_a:.4f}")
    print(f"95% Wilson interval: [{low:.4f}, {high:.4f}]")

    if args.holdout:
        _log_holdout_invocation(args.opponent, seeds, block)
        print(f"Logged to {_HOLDOUT_LOG_RELATIVE_PATH} (holdout invocation).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
