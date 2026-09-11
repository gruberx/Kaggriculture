"""Golden-episode regression fixture - see SPEC.md testing strategy
(layer 2) and tasks/plan.md T2.4.

Records exact final-money outcomes against deterministic opponents on
fixed seeds. Any future change to agent/policy that moves these numbers
needs a deliberate re-record (re-run and update _GOLDEN below), not a
silent pass - that's the entire point of a golden test.

Re-recorded for T3.5 (full three-layer policy replacing the Phase 0 wheat
loop) - see that commit for the full story: the first T3.5 measurement
showed all three seeds converging to an *identical* 4998.0 regardless of
seed or opponent, traced to a real bug (a melon planted too late in the
season to ever reach harvest eligibility - fixed via
decide._crop_has_time_to_mature()), not accepted as-is. These are the
numbers *after* that fix, and now beat "starter" for the first time
(T2.4's wheat-loop numbers lost to it: 3387-3391 vs 3506-3748).

"random" is deliberately excluded from the exact-match table: verified
empirically that kaggle_environments' own random_agent seeds its RNG with
`random.Random()` (no seed) fresh on every call, so even the *same*
episode seed produces a different outcome on our own side from run to run
(our policy reacts to market/town state that random_agent's unseeded
choices perturb). A separate robustness check below covers "random" with
invariants instead of an exact number.
"""

import os

from kaggle_environments import make

AGENT_MAIN_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "kagg", "agent_main.py"
)

# (opponent, seed) -> (our exact final money, opponent's exact final money).
# Recorded against the T3.5 full three-layer policy, reproduced twice
# before being hardcoded here. This is a real, if crude, win over
# "starter" - not yet the rigorous >=60% win rate SPEC.md's success
# criteria call for (that needs Phase 4's paired-seed harness, not three
# ad-hoc seeds), but a genuine improvement worth locking in as a floor.
_GOLDEN = {
    ("starter", 1): (5274.0, 3506.0),
    ("starter", 2): (5292.0, 3528.0),
    ("starter", 3): (5543.0, 3743.0),
    ("pass", 1): (5288.0, 3000.0),
    ("pass", 2): (5720.0, 3000.0),
    ("pass", 3): (5274.0, 3000.0),
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
        assert our_result.reward > 3000  # starting money - the policy must still profit
        # T3.6's ad-hoc 20-seed sweep found random_agent reliably bankrupts
        # itself (margin never under +4886 across 20 runs) - beating it
        # outright, not just being profitable, is the real bar.
        assert our_result.reward > opponent_result.reward


def test_beats_starter_and_random_across_additional_seeds():
    """T3.6's ad-hoc baseline sanity check (tasks/plan.md) - not yet the
    rigorous >=60% win rate SPEC.md's success criteria call for (that
    needs Phase 4's paired-seed harness), but broader than the exact-match
    golden table above: a handful of seeds distinct from _GOLDEN's,
    checking "wins outright" rather than a specific number.

    Full one-off 20-seed sweep (tasks/plan.md T3.6, recorded in that
    commit, not re-run on every test pass - 40 real episodes take ~1
    minute): 20/20 wins vs both starter and random, average margin +1720
    vs starter (min +1336) and +5301 vs random (min +4886). Only 5 seeds
    are re-checked here on every run to keep the suite fast.

    Theoretical flakiness note: random_agent's unseeded RNG means this
    could in principle fail on a given run even at a fixed seed, unlike
    the exact-match golden table above - accepted given how large the
    margin against it was across all 20 sampled seeds (never under
    +4886), consistent with this test's own "ad-hoc, not final-harness
    rigor" framing.
    """
    for seed in (11, 12, 13, 14, 15):
        for opponent in ("starter", "random"):
            our_result, opponent_result = _run_episode(opponent, seed)
            assert our_result.status == "DONE", (opponent, seed)
            assert opponent_result.status == "DONE", (opponent, seed)
            assert our_result.reward > opponent_result.reward, (opponent, seed)
