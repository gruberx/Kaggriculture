"""T8.37: resweep wheat_urgency_reserve against today's shipped baseline.

T8.25 Part 2 built and measured this exact param - a targeted override
that ignores WHEAT's $40 price ceiling once wheat-on-hand is critically
low, rather than losing an animal to starvation. It worked, traced
directly: at max_animals_per_type=3, wheat_urgency_reserve=3 moved win
rate 14%/14% -> 40%/44%, and a seed-900 trace showed 5/5 animals
surviving the full season (vs. 0/5 without it), final money +11.5%. It
was kept off (0) because at the time it measured as a net loss at the
shipped max_animals_per_type=1 - "the single animal's buffer already
survives without it" (params.py's own comment).

That premise is now stale, not re-derived from theory but from a fresh
finding this session: T8.25's sweep ran before T8.27's corrected hiring
forecast, T8.29's labor_units fix, and T8.31's always_pursue_one_animal
(which now guarantees the farm holds an animal from day 1 of every
game, not rarely as before). T8.36 (this session, current shipped code,
max_animals_per_type still 1) already traced a real single-animal
escape caused by exactly this price-ceiling mechanism - direct,
already-in-hand evidence that "the buffer already survives" no longer
holds under today's defaults.

Two stages:

  Stage A: wheat_urgency_reserve alone, at the shipped
  max_animals_per_type=1, over [0 (baseline), 2, 3, 5].

  Stage B (only if Stage A finds a real win): the same values jointly
  with max_animals_per_type=2 - T8.31 already guarantees one animal is
  always pursued; this asks whether a *second* is now viable once the
  feed-drought failure mode is closed, without yet touching the larger
  multi-unit-feeding question (a separate, larger task).

Not part of the committed test suite - a one-off tuning run.

**Prediction stated up front** (T8.3b): plausible real win at
max_animals_per_type=1 this time, precisely because the specific
premise that rejected it before (animals rarely held) is what changed,
not a new mechanism being tried blind - wheat_urgency_reserve itself
was already measured to work exactly as intended (5/5 animals survive)
when it gets the chance to fire. Genuinely uncertain in magnitude: T8.31's
own golden-episode regression ("-9.9% on all six fixed seeds") was
attributed to "real ongoing feed cost," but was never checked for
escapes - if some of that regression was actually escaped animals, this
fix could recover more than a first guess suggests. Stage B is a real
open question, not assumed - T8.22/T8.25/T8.26/T8.27 all rejected
max_animals_per_type>=2 even with this exact fix in earlier combinations,
so a plain win here would itself be the interesting, surprising result.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t837_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
LARGE_SEEDS = list(range(900, 1100))

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)


def _even_baseline(n: int) -> harness.BlockResult:
    return harness.BlockResult(
        n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
        win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
    )


def evaluate(params: dict, seeds: list[int]) -> harness.BlockResult:
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    return harness.run_block(agent_path, baseline_agent, seeds, jobs=None)


results: dict[int, harness.BlockResult] = {}

print("=== T8.37 Stage A: wheat_urgency_reserve alone, max_animals_per_type=1 (shipped) ===")
for reserve in [0, 2, 3, 5]:
    params = dict(DEFAULT_PARAMS, wheat_urgency_reserve=reserve)
    block = evaluate(params, WORKING_SEEDS)
    results[reserve] = block
    accepted = tuning.accept_candidate(block, _even_baseline(block.n))
    print(
        f"  reserve={reserve}: win_rate={block.win_rate_a:.3f} "
        f"({block.wins_a}W/{block.wins_b}L/{block.ties}T) "
        f"interval={block.wilson_interval_a} accept_candidate={accepted}",
        flush=True,
    )

best_reserve = max((r for r in results if r != 0), key=lambda r: results[r].win_rate_a, default=None)
best_block = results[best_reserve] if best_reserve is not None else None

if best_block is None or not tuning.accept_candidate(best_block, _even_baseline(best_block.n)):
    print("\nNo reserve value clears accept_candidate on the working block. Stopping here - null result.")
else:
    print(f"\nBest reserve by working win_rate: {best_reserve} (win_rate={best_block.win_rate_a:.3f})")
    print(f"\n=== Confirmation: reserve={best_reserve} on extended {len(LARGE_SEEDS)}-seed holdout "
          f"({LARGE_SEEDS[0]}-{LARGE_SEEDS[-1]}) ===")
    confirm_params = dict(DEFAULT_PARAMS, wheat_urgency_reserve=best_reserve)
    confirm_block = evaluate(confirm_params, LARGE_SEEDS)
    n = confirm_block.n
    print(
        f"  win_rate={confirm_block.win_rate_a:.3f} "
        f"({confirm_block.wins_a}W/{confirm_block.wins_b}L/{confirm_block.ties}T) "
        f"interval={confirm_block.wilson_interval_a}",
        flush=True,
    )
    print(f"  even-odds baseline interval at n={n}: {_even_baseline(n).wilson_interval_a}")
    stage_a_accepted = tuning.accept_candidate(confirm_block, _even_baseline(n))
    print(f"  accept_candidate (vs even-odds at n={n}): {stage_a_accepted}", flush=True)

    if stage_a_accepted:
        print(f"\n=== Stage B: reserve={best_reserve} jointly with max_animals_per_type=2 ===")
        joint_params = dict(
            DEFAULT_PARAMS, wheat_urgency_reserve=best_reserve, max_animals_per_type=2
        )
        joint_block = evaluate(joint_params, WORKING_SEEDS)
        joint_accepted = tuning.accept_candidate(joint_block, _even_baseline(joint_block.n))
        print(
            f"  working: win_rate={joint_block.win_rate_a:.3f} "
            f"({joint_block.wins_a}W/{joint_block.wins_b}L/{joint_block.ties}T) "
            f"interval={joint_block.wilson_interval_a} accept_candidate={joint_accepted}",
            flush=True,
        )
        if joint_accepted:
            joint_confirm = evaluate(joint_params, LARGE_SEEDS)
            n2 = joint_confirm.n
            print(
                f"  confirm (n={n2}): win_rate={joint_confirm.win_rate_a:.3f} "
                f"({joint_confirm.wins_a}W/{joint_confirm.wins_b}L/{joint_confirm.ties}T) "
                f"interval={joint_confirm.wilson_interval_a} "
                f"accept_candidate={tuning.accept_candidate(joint_confirm, _even_baseline(n2))}",
                flush=True,
            )
