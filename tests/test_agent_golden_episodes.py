"""Golden-episode regression fixture - see SPEC.md testing strategy
(layer 2) and tasks/plan.md T2.4.

Records exact final-money outcomes against deterministic opponents on
fixed seeds. Any future change to agent/policy that moves these numbers
needs a deliberate re-record (re-run and update _GOLDEN below), not a
silent pass - that's the entire point of a golden test.

"random" is deliberately excluded from the exact-match table: verified
empirically that kaggle_environments' own random_agent seeds its RNG with
`random.Random()` (no seed) fresh on every call, so even the *same*
episode seed produces a different outcome on our own side from run to run
(our wheat loop reacts to market/town state that random_agent's unseeded
choices perturb - confirmed by running the same seed three times and
observing our final money differ: 3389/3378/3381). A separate robustness
check below covers "random" with invariants instead of an exact number.
"""

import os

from kaggle_environments import make

AGENT_MAIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "kagg", "agent_main.py"
)

# (opponent, seed) -> (our exact final money, opponent's exact final money).
# Recorded against the Phase 0 wheat-loop policy (T0.3), reproduced twice
# before being hardcoded here. Losing to "starter" is not a regression:
# T0.3's only acceptance criterion was beating "pass" (tasks/plan.md
# Checkpoint 0); clearing "starter" is explicitly Phase 3's job
# (SPEC.md success criteria: >=60% win rate vs starter under the real
# harness, not this crude policy).
_GOLDEN = {
    ("starter", 1): (3387.0, 3506.0),
    ("starter", 2): (3391.0, 3528.0),
    ("starter", 3): (3379.0, 3748.0),
    ("pass", 1): (3398.0, 3000.0),
    ("pass", 2): (3322.0, 3000.0),
    ("pass", 3): (3387.0, 3000.0),
}


def _run_episode(opponent: str, seed: int):
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": seed},
        debug=False,
    )
    env.run([AGENT_MAIN_PATH, opponent])
    final = env.steps[-1]
    return final[0], final[1]


def test_golden_episodes_reproduce_recorded_final_money():
    mismatches = {}
    for (opponent, seed), expected in _GOLDEN.items():
        our_result, opponent_result = _run_episode(opponent, seed)
        actual = (our_result.reward, opponent_result.reward)
        if actual != expected:
            mismatches[(opponent, seed)] = {"expected": expected, "actual": actual}
        assert our_result.status == "DONE", (opponent, seed, our_result.status)
        assert opponent_result.status == "DONE", (opponent, seed, opponent_result.status)
    assert not mismatches, mismatches


def test_random_opponent_robustness_not_an_exact_number():
    # Invariants that must hold regardless of random_agent's exact
    # (unseeded, non-reproducible) path, rather than a golden number that
    # can't actually be golden here.
    for seed in [1, 2, 3]:
        our_result, opponent_result = _run_episode("random", seed)
        assert our_result.status == "DONE"
        assert opponent_result.status == "DONE"
        assert our_result.reward > 3000  # starting money - the wheat loop must still profit
