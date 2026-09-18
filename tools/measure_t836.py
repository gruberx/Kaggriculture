"""T8.36: measure wheat_restock_counts_carried_inventory - the fix for a
daily WHEAT buy/sell churn the user spotted directly in tools/
daily_dashboard.py's new buy/sell price columns.

Root cause, traced turn-by-turn (seed 900 vs starter, tools/
daily_dashboard.py's addendum): tasks._WHEAT_PICKUP_BATCH (10, matching
_WHEAT_FEED_RESERVE by design) pulls the *whole* feed reserve out of the
shed into the farmer's own inventory the instant any animal needs
feeding that day. Almost all of it goes unused (only 1 unit/animal/day
is actually consumed via FEED) and safely returns to the shed at
end-of-day (kaggriculture.py's own _drop_inventories_to_shed) - nothing
is lost there. But market.buy_wheat_order's restock check only ever
looks at the *shed* count at decision time, which PICKUP has already
drained - so it re-buys a fresh batch of WHEAT nearly every single day
even with several spare units already secured in a unit's own
inventory, invisible to the check. The fix: sum shed + every unit's
carried inventory for the restock decision, gated behind a new param
(default False, bit-identical) per SPEC-policy.md's "never raised on
reasoning alone" rule.

Not part of the committed test suite - a one-off tuning run.

**Prediction stated up front** (T8.3b): a real, plausible win, not a
coin flip. Unlike most of this session's other measurements (T8.33,
T8.34 - genuine open questions about the *right* value), this is a
straightforward correctness fix for a traced, concrete waste: money
spent on WHEAT that wasn't actually needed, on a cadence that fired
almost daily once any animal was placed (confirmed directly in a
turn-level trace, not inferred from theory). Real risk that tempers the
prediction: the T8.3l docstring's own history shows a *prior* fix in
this exact area first measured as "near-$0 gain" due to a subtly
invalid comparison, before a corrected measurement found the real,
decisive win underneath - so this prediction could similarly turn out
smaller in practice than the traced mechanism alone suggests, and that
would be worth understanding, not just accepting the number.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t836_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
LARGE_SEEDS = list(range(900, 1100))

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_params = dict(DEFAULT_PARAMS, wheat_restock_counts_carried_inventory=True)
candidate_agent = tuning.write_candidate_agent(candidate_params, WORKDIR)


def _even_baseline(n: int) -> harness.BlockResult:
    return harness.BlockResult(
        n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
        win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
    )


print("=== T8.36: wheat_restock_counts_carried_inventory=True vs. shipped baseline ===")
print(f"--- working block (50 tuning seeds) ---")
working_block = harness.run_block(candidate_agent, baseline_agent, WORKING_SEEDS, jobs=None)
print(
    f"  win_rate={working_block.win_rate_a:.3f} "
    f"({working_block.wins_a}W/{working_block.wins_b}L/{working_block.ties}T) "
    f"interval={working_block.wilson_interval_a} "
    f"accept_candidate={tuning.accept_candidate(working_block, _even_baseline(working_block.n))}",
    flush=True,
)

if not tuning.accept_candidate(working_block, _even_baseline(working_block.n)):
    print("\nDoes not clear accept_candidate on the working block. Stopping here - null result.")
else:
    print(f"\n--- confirmation on extended {len(LARGE_SEEDS)}-seed holdout ({LARGE_SEEDS[0]}-{LARGE_SEEDS[-1]}) ---")
    confirm_block = harness.run_block(candidate_agent, baseline_agent, LARGE_SEEDS, jobs=None)
    n = confirm_block.n
    print(
        f"  win_rate={confirm_block.win_rate_a:.3f} "
        f"({confirm_block.wins_a}W/{confirm_block.wins_b}L/{confirm_block.ties}T) "
        f"interval={confirm_block.wilson_interval_a}",
        flush=True,
    )
    print(f"  even-odds baseline interval at n={n}: {_even_baseline(n).wilson_interval_a}")
    accepted = tuning.accept_candidate(confirm_block, _even_baseline(n))
    print(f"  accept_candidate (vs even-odds at n={n}): {accepted}", flush=True)
