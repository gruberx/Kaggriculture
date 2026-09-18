"""T8.39: measure feed_pickup_unpinned - any free unit (not just the
farmer) can PICKUP wheat and FEED an animal - against today's shipped
baseline.

Two stages:

  Stage A: feed_pickup_unpinned alone, at the shipped
  max_animals_per_type=1, on the 50 tuning seeds; if it clears
  accept_candidate, confirm on the 200-seed extended holdout.

  Stage B (only on a Stage A accept): jointly with max_animals_per_type=2
  - the explicit, named T8.25 follow-up ("labor-gating" - see tasks.py's
  own _PINNED_UNIT_INDEX docstring) - a genuinely open question given
  T8.22/T8.25/T8.26/T8.27 all rejected max_animals_per_type>=2 before
  this fix existed.

Not part of the committed test suite - a one-off tuning run.

**Prediction stated up front** (T8.3b): small positive or neutral at
max_animals_per_type=1 - the mechanism only pays off on the days the
farmer is genuinely saturated *and* an animal goes unfed as a result, a
minority of days with a single animal and hires_per_day=1 already giving
some slack. A large win would itself be suspicious and demand a trace,
not a celebration (T8.33's own lesson) - see tools/trace_t839.py for the
mechanism-level check this script's win rate alone can't provide. Stage
B is a real open question, not assumed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t839_workdir"
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


print("=== T8.39 Stage A: feed_pickup_unpinned alone, max_animals_per_type=1 (shipped) ===")
candidate_params = dict(DEFAULT_PARAMS, feed_pickup_unpinned=True)
working_block = evaluate(candidate_params, WORKING_SEEDS)
working_accepted = tuning.accept_candidate(working_block, _even_baseline(working_block.n))
print(
    f"  working: win_rate={working_block.win_rate_a:.3f} "
    f"({working_block.wins_a}W/{working_block.wins_b}L/{working_block.ties}T) "
    f"interval={working_block.wilson_interval_a} accept_candidate={working_accepted}",
    flush=True,
)

if not working_accepted:
    print("\nDoes not clear accept_candidate on the working block. Stopping here - null result.")
else:
    print(f"\n=== Confirmation: feed_pickup_unpinned=True on extended {len(LARGE_SEEDS)}-seed holdout "
          f"({LARGE_SEEDS[0]}-{LARGE_SEEDS[-1]}) ===")
    confirm_block = evaluate(candidate_params, LARGE_SEEDS)
    n = confirm_block.n
    stage_a_accepted = tuning.accept_candidate(confirm_block, _even_baseline(n))
    print(
        f"  confirm: win_rate={confirm_block.win_rate_a:.3f} "
        f"({confirm_block.wins_a}W/{confirm_block.wins_b}L/{confirm_block.ties}T) "
        f"interval={confirm_block.wilson_interval_a} accept_candidate={stage_a_accepted}",
        flush=True,
    )

    if stage_a_accepted:
        print("\n=== Stage B: feed_pickup_unpinned=True jointly with max_animals_per_type=2 ===")
        joint_params = dict(DEFAULT_PARAMS, feed_pickup_unpinned=True, max_animals_per_type=2)
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
