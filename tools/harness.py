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

from dataclasses import dataclass

from kaggle_environments import make

_DEFAULT_EPISODE_STEPS = 720


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
