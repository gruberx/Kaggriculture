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

Re-recorded again for T6.3 (BUY_ANIMAL wired in) - a much bigger story
than a simple re-baseline: adding animal investment exposed a real,
previously-latent bug in tasks.py's HARVEST-task logic
(kaggriculture.py's _new_plant() sets a one-time crop's yield_units to 1
*immediately* at planting, before it's actually harvestable - a
freshly-planted crop's doomed-to-fail HARVEST attempt outranked
PLANT/BUILD_*/PLACE's priority, so the single farmer got stuck
perpetually re-attempting it for the crop's entire maturation period).
Harmless before T6.2 (nothing else productive to do with that time
anyway); costly once BUILD_PASTURE became available and had to wait on
it (measured: 5274 -> 3932, a ~1342 regression). Fixed in
tasks._is_actually_harvestable() - and the fix alone (independent of
animals) unlocked a much larger, genuine improvement, since the farmer
was losing productive time on *every* one-time-crop planting all game,
not just the one that happened to coincide with an animal purchase.

Re-recorded a third time for T6.4 (real-episode integration): the T6.3
numbers above turned out to reflect a policy that could never actually
produce anything from an animal at all. Direct inspection of a real
episode found PLACE's real handler consumes the animal from the acting
unit's *own inventory*, never the shed BUY_ANIMAL delivers to - every
placed animal just sat un-placeable (or, once a PICKUP step was added,
placed but then starved: FEED has the identical inventory-vs-shed gap
for WHEAT, and the wheat buy/sell arbitrage's own SELL order emptied
the shed before a PICKUP for feeding could ever complete). Fixed with a
PICKUP task (tasks.py), a WHEAT sell-reservation once any animal exists
(market.py), and two "don't keep re-buying" guards in decide.py (finish
a stuck, already-bought animal before starting anything new; never buy
a second instance of an animal type already placed and alive - a real
episode trace found 21 BUY_ANIMAL orders against only 18 PLACEs before
these fixes). All three fixes together, not any one
alone, were needed before every seed showed a genuine improvement over
T6.3 (e.g. pass/seed1: 5510 -> 8078).

Re-recorded a fourth time for T7.4 (Stage 1's first real accepted
parameter change, not a bug fix this time): land_purchase_threshold_money
raised 5000 -> 10000. Found via a real, previously unnoticed
methodological pitfall in tuning's own opponent-panel design - blending
win rate across starter/random (both near a 100% win-rate ceiling
against basically any reasonable policy) with self-play against the
checked-in baseline dilutes the signal so heavily that a candidate
which actually *loses* to the baseline in direct self-play (measured:
0.34 win rate head-to-head) can still look like an improvement on the
blended aggregate (0.78 vs 0.667) - see kagg.policy.strategy's own
_DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY comment for the full story.
Direct self-play against the previous-best snapshot (not the blended
panel score) is what actually found this real change: 50/50 wins on
both the working block and the held-out block (95% Wilson interval
[0.929, 1.0] on each) - a genuinely accepted, held-out-gated result,
not an ad-hoc measurement.

Re-recorded a fifth time for T8.2 (distance-aware, tier-local task
servicing - tasks/plan.md): `assign_units` used to process same-priority
tasks in row-major scan order (a stable sort on priority alone never used
distance), so a single unit could be sent to the farthest same-tier task
first even while standing on a nearer one. Rewritten as tier-by-tier
greedy nearest-match, proved stable under decide()'s statelessness (see
tasks.assign_units's own docstring for the argument). This was the
biggest single accepted change of Phase 8 so far, dwarfing T8.1's
placement fix: direct self-play against the pre-T8.2 snapshot won 49/50
on the working block and 48/50 on the held-out block (95% Wilson interval
[0.895, 0.996] and [0.865, 0.989] respectively) - formally accepted by
tuning.accept_candidate against an even-odds baseline on both. Notably,
this also *reversed* T8.1's open question: investment_anchor="SHED" +
plant_while_pursuing_animal=True (T8.1/T8.9's opt-in fixes, still not the
default) were re-tested on top of T8.2 on the hypothesis that T8.2 was
what they were "waiting on" - instead they now *lose decisively*
(working 0.28, holdout 0.18) to the plain UNIT/False default. T8.2's
distance-aware servicing already keeps the farmer on the nearest urgent
tile regardless of the plot's shape, so T8.1's shed-anchored placement
and T8.2's smart servicing overlap rather than compose - see
kagg.policy.decide's _DEFAULT_INVESTMENT_ANCHOR comment for the full
story. Both toggles remain off by default.

Re-recorded a sixth time for T8.3 (land purchase gating - tasks/plan.md,
the user's own observed defect: land bought while plenty of free tiles
remained). `should_buy_land` gained an occupancy-aware gate
(`land_buy_max_free_tile_fraction`), and unlike T8.1/T8.9 this one was
swept and accepted immediately, not shipped opt-in: every tested value
(0.6, 0.4, 0.25, 0.1) beat the ungated default 50/50 on the working
block, confirmed 50/50 again on the held-out block for the accepted
value (0.25) - formally accepted by tuning.accept_candidate against an
even-odds baseline on both. Traced directly, not just trusted: with the
gate on, BUY_LAND stops firing almost entirely in real episodes and the
farm stays on the 25-tile NW quadrant - confirms a single farmer cannot
productively work even one full quadrant (one investment task per turn,
one farmer to service it), so every dollar spent unlocking more land was
pure waste. By far the largest single golden-table jump recorded so far
(e.g. starter/seed2: 18821 [T8.2's number] -> 25726, +37%).
Explicitly provisional (fit to a 1-unit farm) - must be re-swept once
labor works (T8.8).

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
# Recorded against the T8.3 policy (land purchase gated on occupancy,
# accepted at land_buy_max_free_tile_fraction=0.25), reproduced twice
# before being hardcoded here. Not yet the rigorous >=60% win rate
# SPEC.md's success criteria call for (that needs Phase 4's paired-seed
# harness, not three ad-hoc seeds), but a real improvement worth locking
# in - all 6 seeds improved substantially this time (e.g. starter/seed2:
# 18821 -> 25726), consistent with the 50/50-on-both-blocks self-play
# result this was accepted on.
_GOLDEN = {
    ("starter", 1): (18242.0, 3421.0),
    ("starter", 2): (25726.0, 3569.0),
    ("starter", 3): (21629.0, 3639.0),
    ("pass", 1): (17970.0, 3000.0),
    ("pass", 2): (25702.0, 3000.0),
    ("pass", 3): (21637.0, 3000.0),
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


def test_at_least_one_animal_reaches_production_in_a_representative_episode():
    """T6.4's own acceptance criterion (tasks/plan.md): confirms the full
    animal-acquisition pipeline (choose -> BUY_ANIMAL -> BUILD_* ->
    PICKUP -> PLACE -> FEED -> production) actually reaches production in
    a real episode, not just in isolated unit tests.

    Real, not hypothetical: the very first full T6.4 attempt reached
    PLACE but never production at all (verified by direct inspection of
    env.steps) - PLACE's real handler consumes the animal from the
    acting unit's own inventory, not the shed BUY_ANIMAL delivers to, so
    every placed animal just starved and escaped. Fixed via a PICKUP
    step (tasks.py) plus a wheat-sale reservation (market.py) and two
    "don't keep re-buying" guards (decide.py) - see those modules' own
    docstrings for the full story. This test is the regression guard
    against ever silently losing that pipeline again.
    """
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 720, "seed": 1},
        debug=False,
    )
    env.run([AGENT_MAIN_PATH, "pass"])
    reached_production = any(
        step[0]["observation"]["private"].get("shed", {}).get(product, 0) > 0
        for step in env.steps
        for product in ("MILK", "WOOL", "EGG")
    )
    assert reached_production
