"""T8.32 Stage 2: measure workload_forecast_free_tile_weight, the new
land-aware hiring forecast term (see strategy.hires_per_day's own
docstring addendum and _DEFAULT_WORKLOAD_FORECAST_FREE_TILE_WEIGHT's
comment for the mechanism).

Two sweeps, both against the checked-in baseline (plain DEFAULT_PARAMS -
Stage 1's own promising (10000, 0.2, 4) combination was NOT accepted as
the shipped default, so the baseline here is unchanged from before
T8.32):

  Stage A: the new weight alone, land gate/hiring floor untouched. Tests
  whether proactively hiring ahead of *currently* free tiles (even under
  the existing strict land gate - free tiles still exist from land
  bought earlier and not yet fully planted, or simply from the 25-tile
  NW quadrant before it fills) helps on its own.

  Stage B: the new weight combined with Stage 1's own measured-but-not-
  accepted land+hiring values (land_purchase_threshold_money=10000,
  land_buy_max_free_tile_fraction=0.2, min_hires_per_day=4) - the
  genuinely "comprehensive" combination the user asked for (land opens
  sooner AND hiring both reacts to placed tiles and anticipates free
  ones). Stage 1 alone scored a real 64% held-out that didn't clear the
  acceptance bar; if adding land-awareness to the forecast pushes the
  same combination decisively over that bar, that's the accepted result
  for this task. If not, both stay honestly recorded as an unaccepted-
  but-real direction, same as Stage 1 itself.

Not part of the committed test suite - a one-off tuning run.

**Prediction stated up front** (T8.3b): plausible but genuinely
uncertain - this is new spend-ahead-of-need (hiring cost paid before the
tiles it justifies are actually planted), which this project's own
hire_buffer_fraction/margin-style mechanisms have generally found only
pays off within a narrow range, not unconditionally. Stage B is the more
promising bet given Stage 1's own already-measured 64% starting point,
but Stage A alone tests the mechanism cleanly in isolation first.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t832b_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HOLDOUT_SEEDS = list(blocks.holdout_seeds)

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

STAGE1_LAND_HIRING = dict(
    land_purchase_threshold_money=10000,
    land_buy_max_free_tile_fraction=0.2,
    min_hires_per_day=4,
)

WEIGHTS = [0.1, 0.25, 0.5, 1.0]


def run_sweep(label: str, base_extra: dict) -> None:
    print(f"=== {label} ===")
    for w in WEIGHTS:
        params = dict(DEFAULT_PARAMS, **base_extra, workload_forecast_free_tile_weight=w)
        print(f"--- weight={w} ---")
        candidate_agent = tuning.write_candidate_agent(params, WORKDIR)
        working_block = harness.run_block(candidate_agent, baseline_agent, WORKING_SEEDS, jobs=None)
        print(
            f"  working: win_rate={working_block.win_rate_a:.3f} "
            f"({working_block.wins_a}W/{working_block.wins_b}L/{working_block.ties}T) "
            f"interval={working_block.wilson_interval_a}",
            flush=True,
        )
        holdout_block = harness.run_block(candidate_agent, baseline_agent, HOLDOUT_SEEDS, jobs=None)
        print(
            f"  holdout: win_rate={holdout_block.win_rate_a:.3f} "
            f"({holdout_block.wins_a}W/{holdout_block.wins_b}L/{holdout_block.ties}T) "
            f"interval={holdout_block.wilson_interval_a}",
            flush=True,
        )
        n = holdout_block.n
        even_baseline = harness.BlockResult(
            n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
            win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
        )
        accepted = tuning.accept_candidate(holdout_block, even_baseline)
        print(f"  accept_candidate (vs even-odds at n={n}): {accepted}", flush=True)
    print()


run_sweep("Stage A: free_tile_weight alone (shipped land gate/hiring floor)", {})
run_sweep("Stage B: free_tile_weight + Stage 1's own (10000, 0.2, 4)", STAGE1_LAND_HIRING)
