"""Paired-seat evaluation harness - see SPEC-harness.md and tasks/plan.md
Phase 4.

Dev-only: never ships in the submission bundle (SPEC-harness.md
"Boundaries specific to this module" - may depend on kaggle_environments,
multiprocessing, pytest). agent_a/agent_b are whatever
kaggle_environments.make(...).run([...]) accepts as agent identifiers: a
file path (e.g. src/kagg/agent_main.py) or a built-in name ("pass",
"starter", "random").

Implements only T4.1 (run_paired) so far - run_block, detect_shop_reroll,
and the seed-blocks config land in later tasks.
"""

from __future__ import annotations

import json
import math
import multiprocessing
import os
from dataclasses import dataclass

from kaggle_environments import make

_DEFAULT_EPISODE_STEPS = 720
_WILSON_Z_95 = 1.96
_JOBS_RESERVE = 2
_CGROUP_CPU_MAX_PATH = "/sys/fs/cgroup/cpu.max"


@dataclass(frozen=True)
class PairedResult:
    """One seed, played twice with seats swapped, collapsed to a single
    verdict per SPEC-harness.md requirement 1 (paired seats) - a raw list
    of per-game outcomes would double-count seat advantage as sample size.

    `winner` is "a", "b", or "tie" based on each agent's *summed* money
    across both seatings, not a 2-0/1-1/0-2 game-count vote - a decisive
    win in one seat should be able to outweigh a narrow loss in the other,
    matching how SPEC-harness.md frames it ("which side came out ahead in
    total money-across-both-seatings").
    """

    seed: int
    winner: str
    a_total_money: float
    b_total_money: float
    episodes: tuple[object, object]


def _play(first: str, second: str, seed: int, episode_steps: int):
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": episode_steps, "seed": seed},
        debug=False,
    )
    env.run([first, second])
    final = env.steps[-1]
    return final[0].reward, final[1].reward, final


def run_paired(agent_a, agent_b, seed: int, episode_steps: int = _DEFAULT_EPISODE_STEPS) -> PairedResult:
    """Play `seed` twice - a as player 0 then a as player 1 - and collapse
    into one PairedResult. See SPEC-harness.md "Interface"."""
    a0_money, b0_money, episode_1 = _play(agent_a, agent_b, seed, episode_steps)
    b1_money, a1_money, episode_2 = _play(agent_b, agent_a, seed, episode_steps)

    a_total = a0_money + a1_money
    b_total = b0_money + b1_money
    if a_total > b_total:
        winner = "a"
    elif b_total > a_total:
        winner = "b"
    else:
        winner = "tie"

    return PairedResult(
        seed=seed,
        winner=winner,
        a_total_money=a_total,
        b_total_money=b_total,
        episodes=(episode_1, episode_2),
    )


def _run_paired_star(args) -> PairedResult:
    # multiprocessing.Pool.map needs a top-level, picklable callable - a
    # closure or lambda over run_paired's args can't be pickled.
    agent_a, agent_b, seed, episode_steps = args
    return run_paired(agent_a, agent_b, seed, episode_steps)


def _effective_cpu_count() -> int:
    """The number of CPUs actually available to this process, not the
    host's total core count.

    os.cpu_count() reports the *host's* cores even inside a cgroup-limited
    container - verified empirically in this project's own dev container:
    os.cpu_count() reports 32 while /sys/fs/cgroup/cpu.max's quota/period
    caps this process at far fewer effective cores. Spawning jobs sized to
    the host's count would massively over-subscribe the real CPU budget.
    Same class of bug as __file__ under kaggle_environments' loader
    (SPEC-agent.md) and the params/ bundling path (SPEC-ops.md): a value
    that's only correct outside the sandbox it actually runs in.

    Falls back to os.cpu_count() when cgroup v2's cpu.max isn't present
    (e.g. cgroup v1, non-Linux, or an unlimited "max" quota) - there is no
    better signal available in that case.
    """
    try:
        with open(_CGROUP_CPU_MAX_PATH) as f:
            quota_str, period_str = f.read().split()
        if quota_str == "max":
            raise ValueError("no quota set")
        quota, period = int(quota_str), int(period_str)
        return max(1, quota // period)
    except (OSError, ValueError):
        return os.cpu_count() or 1


def _default_jobs() -> int:
    """SPEC-harness.md: 'jobs=auto defaulting to os.cpu_count() - 2... never
    hardcode a job count or assume a specific core count.' Corrected here
    to read the effective (cgroup-aware) CPU count rather than
    os.cpu_count() directly - see _effective_cpu_count()'s docstring."""
    return max(1, _effective_cpu_count() - _JOBS_RESERVE)


@dataclass(frozen=True)
class BlockResult:
    """Aggregate outcome of run_paired across a block of seeds, per
    SPEC-harness.md requirement 2 (a held-out seed block needs a real
    interval, not just a point estimate, to be trusted)."""

    n: int
    wins_a: int
    wins_b: int
    ties: int
    win_rate_a: float
    wilson_interval_a: tuple[float, float]
    paired_results: tuple[PairedResult, ...]


def wilson_interval(k: int, n: int, z: float = _WILSON_Z_95) -> tuple[float, float]:
    """Wilson score interval for k successes out of n trials. Closed-form
    (Wilson 1927) - see SPEC-harness.md Testing: checked against an
    independently-derived closed-form example, not just "runs without
    error"."""
    phat = k / n
    z2 = z * z
    denom = 1 + z2 / n
    center = phat + z2 / (2 * n)
    adj = z * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n))
    return ((center - adj) / denom, (center + adj) / denom)


def run_block(
    agent_a,
    agent_b,
    seeds: list[int],
    jobs: int | None = None,
    episode_steps: int = _DEFAULT_EPISODE_STEPS,
) -> BlockResult:
    """run_paired for every seed, parallelized across `jobs` worker
    processes (default: _default_jobs(), never a hardcoded core count -
    see SPEC-harness.md "Performance"). Returns win/loss/tie counts and a
    Wilson score interval on agent_a's win rate."""
    if jobs is None:
        jobs = _default_jobs()

    tasks = [(agent_a, agent_b, seed, episode_steps) for seed in seeds]
    if jobs == 1:
        results = [_run_paired_star(t) for t in tasks]
    else:
        with multiprocessing.Pool(processes=jobs) as pool:
            results = pool.map(_run_paired_star, tasks)

    n = len(results)
    wins_a = sum(1 for r in results if r.winner == "a")
    wins_b = sum(1 for r in results if r.winner == "b")
    ties = n - wins_a - wins_b
    win_rate_a = wins_a / n

    return BlockResult(
        n=n,
        wins_a=wins_a,
        wins_b=wins_b,
        ties=ties,
        win_rate_a=win_rate_a,
        wilson_interval_a=wilson_interval(wins_a, n),
        paired_results=tuple(results),
    )


def _recorded_town_shop_sequence(replay_path: str) -> list[str]:
    """The full town shop unlock sequence recorded in a saved episode
    replay (env.toJSON()-shaped: {"steps": [[{"observation": {...}}, ...],
    ...]}).

    town["unlocked_shops"] only ever grows (verified by direct inspection
    of a real episode: kaggriculture.py's end-of-day town-shop draw
    appends one entry per in-game day, with replacement, so the same shop
    can repeat), and is shared identically between both players'
    observations at a given step (also verified directly) - so the last
    step's player-0 observation already holds the complete sequence.
    """
    with open(replay_path) as f:
        replay = json.load(f)
    last_step = replay["steps"][-1]
    return last_step[0]["observation"]["town"].get("unlocked_shops", [])


def detect_shop_reroll(replay_path: str, live_town_log: list[str]) -> bool:
    """True if the live run's town shop unlock sequence has diverged from
    the recorded replay's - see SPEC-harness.md requirement 3 (our own
    moves change which tiles are empty when, perturbing the shared RNG
    stream that also draws town shop unlocks, which can reroll the
    sequence relative to a recorded baseline).

    Only used when the opponent side is a recorded replay rather than a
    second live agent (SPEC-harness.md's own framing) - comparing two live
    agents has no separate "recorded" sequence to diverge from.

    Compares only the overlapping prefix: a live run that hasn't reached
    as many in-game days yet as the replay isn't a reroll, just an
    in-progress comparison - only an actual mismatch within what both
    sides have reached counts.
    """
    recorded = _recorded_town_shop_sequence(replay_path)
    overlap = min(len(recorded), len(live_town_log))
    return recorded[:overlap] != list(live_town_log[:overlap])
