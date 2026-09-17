"""T8.34: widen workload_forecast_free_tile_weight's sweep to actually
break hiring's pin-to-floor problem, before any further land-gate work.

Discovered this session while designing T8.33's "labor-aware land gate"
follow-up (user's own choice, 2026-09-17): under shipped defaults, hand
count is pinned at min_hires_per_day=2 for the entire season, confirmed
empirically across 15 tuning seeds (max_hands=2 on every one, solo play
vs "pass"). Root cause, confirmed by direct computation of hires_per_day
itself (not just reading the docstring's claim): T8.32 Stage 2's own
swept range for workload_forecast_free_tile_weight, [0.1, 0.25, 0.5,
1.0], NEVER crosses the point where the forecast's raw target exceeds
the floor - hand-computed with representative mid-game tile counts (20
crop tiles, 1 animal tile, days_remaining=15), the target only starts
moving at weight~2 and needs weight~5-10 to reach meaningful levels
(saturating at max_hires_per_day=8 once free_tiles is large, e.g. right
after a new quadrant opens). This fully explains T8.32 Stage 2's "flat,
no benefit" result - the swept range was structurally incapable of ever
changing hires_per_day's output, so of course every value performed
identically to weight=0.

This script does two things per candidate, not just win rate - the
lesson from T8.33's own flat-sweep surprise is to check the mechanism
directly alongside the aggregate, not only after a suspicious result:

  1. A direct hand-count diagnostic: solo play (vs "pass") on a handful
     of seeds, reporting max hand count reached - confirms whether the
     floor is actually broken, independent of whether that translates
     into a win-rate improvement.
  2. The standard self-play win-rate sweep against the checked-in
     baseline (weight=0.0, i.e. today's shipped behavior) on the 50
     tuning seeds.

Range: [1, 2, 5, 10, 20] - below the calibrated inflection point (weight
~1 or less) intentionally included as a negative control (should still
show max_hands=2, same as baseline), then crossing into the range where
the target computation says hiring should actually respond.

If a candidate here both breaks the pin AND wins, it's also worth
retesting jointly with T8.32/T8.33's own previously-rejected land
loosening (land_purchase_threshold_money=10000,
land_buy_max_free_tile_fraction=0.2) - since that combination was
rejected specifically because "extra hands had nowhere new to work"
(T8.32's Stage 1 docstring) and "hiring never reacts to free/potential
land" (T8.32 Stage 1/Stage 2's own diagnosis) - if this task actually
fixes that reaction, the original comprehensive hypothesis was never
properly tested with a working hiring mechanism. Built as a second
stage below, gated on Stage 1 actually finding a working weight.

Not part of the committed test suite - a one-off tuning run.

**Prediction stated up front** (T8.3b): the pin-breaking mechanism
itself is not in doubt - it's arithmetic, verified directly against
hires_per_day's own formula before writing this script. What's genuinely
uncertain is whether MORE hands (Fibonacci-priced, reset daily) pays for
itself: the boost is inherently spiky (free_tiles shrinks toward 0 as a
newly-opened quadrant gets planted, so the elevated target decays back
to the floor within days, not sustained), and hiring ahead of confirmed
need is exactly the kind of spend-ahead-of-need pattern this project's
other margin/buffer mechanisms have found only helps in a narrow range,
not unconditionally. A null result here (hands scale but win rate
doesn't improve) would be genuinely informative, not a failure to route
around - it would mean the floor-pin isn't actually the bottleneck
standing between this codebase and more quadrants, and the $15000 land
threshold's role as a labor-readiness proxy (T8.33's own finding) is
correct as shipped for a different reason than under-capitalization.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t834_workdir"
os.makedirs(WORKDIR, exist_ok=True)

blocks = harness.load_seed_blocks()
WORKING_SEEDS = list(blocks.tuning_seeds)
HAND_CHECK_SEEDS = WORKING_SEEDS[:10]  # cheap diagnostic subset, solo play

LARGE_SEEDS = list(range(900, 1100))

_baseline_agent_cache: dict[str, str] = {}


def _baseline_agent() -> str:
    if "path" not in _baseline_agent_cache:
        _baseline_agent_cache["path"] = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
    return _baseline_agent_cache["path"]


def _even_baseline(n: int) -> harness.BlockResult:
    return harness.BlockResult(
        n=n, wins_a=n // 2, wins_b=n - n // 2, ties=0,
        win_rate_a=0.5, wilson_interval_a=harness.wilson_interval(n // 2, n), paired_results=(),
    )


def max_hand_count(agent_path: str, seeds: list[int]) -> int:
    """Solo play vs "pass" - a mechanism check (does the forecast ever
    call for more hands), not a competitive measurement, so "pass" is
    fine here (unlike T8.33's land-purchase timing, this only asks
    whether hires_per_day's own output ever exceeds the floor)."""
    peak = 0
    for seed in seeds:
        env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
        env.run([agent_path, "pass"])
        for s in env.steps:
            farm = s[0].observation["farms"][0]
            peak = max(peak, len(farm.get("hands", [])))
    return peak


def evaluate(params: dict, seeds: list[int]) -> harness.BlockResult:
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    return harness.run_block(agent_path, _baseline_agent(), seeds, jobs=None)


print("=== T8.34 Stage 1: workload_forecast_free_tile_weight, widened range ===")
print("(baseline = checked-in DEFAULT_PARAMS, weight=0.0; land gate untouched)")

WEIGHTS = [1, 2, 5, 10, 20]
results: dict[float, harness.BlockResult] = {}

for weight in WEIGHTS:
    params = dict(DEFAULT_PARAMS, workload_forecast_free_tile_weight=weight)
    agent_path = tuning.write_candidate_agent(params, WORKDIR)
    peak_hands = max_hand_count(agent_path, HAND_CHECK_SEEDS)
    block = harness.run_block(agent_path, _baseline_agent(), WORKING_SEEDS, jobs=None)
    results[weight] = block
    accepted = tuning.accept_candidate(block, _even_baseline(block.n))
    print(
        f"  weight={weight:>4}: max_hands(10 seeds)={peak_hands}  "
        f"win_rate={block.win_rate_a:.3f} ({block.wins_a}W/{block.wins_b}L/{block.ties}T) "
        f"interval={block.wilson_interval_a} accept_candidate={accepted}",
        flush=True,
    )

best_weight = max(results, key=lambda w: results[w].win_rate_a)
best_block = results[best_weight]
print(f"\nBest weight by working win_rate: {best_weight} (win_rate={best_block.win_rate_a:.3f})")

if not tuning.accept_candidate(best_block, _even_baseline(best_block.n)):
    print("Best weight does not clear accept_candidate on the working block. "
          "Stopping here - Stage 1 result is null, no Stage 2 joint test.")
else:
    print(f"\n=== Confirmation: weight={best_weight} on extended "
          f"{len(LARGE_SEEDS)}-seed holdout ({LARGE_SEEDS[0]}-{LARGE_SEEDS[-1]}) ===")
    best_params = dict(DEFAULT_PARAMS, workload_forecast_free_tile_weight=best_weight)
    confirm_block = evaluate(best_params, LARGE_SEEDS)
    n = confirm_block.n
    print(
        f"  confirm: win_rate={confirm_block.win_rate_a:.3f} "
        f"({confirm_block.wins_a}W/{confirm_block.wins_b}L/{confirm_block.ties}T) "
        f"interval={confirm_block.wilson_interval_a}",
        flush=True,
    )
    print(f"  even-odds baseline interval at n={n}: {_even_baseline(n).wilson_interval_a}")
    stage1_accepted = tuning.accept_candidate(confirm_block, _even_baseline(n))
    print(f"  accept_candidate (vs even-odds at n={n}): {stage1_accepted}", flush=True)

    print(f"\n=== Stage 2: weight={best_weight} jointly with T8.32/T8.33's own "
          f"previously-rejected land loosening (10000, 0.2) ===")
    joint_params = dict(
        DEFAULT_PARAMS,
        workload_forecast_free_tile_weight=best_weight,
        land_purchase_threshold_money=10000,
        land_buy_max_free_tile_fraction=0.2,
    )
    joint_block = evaluate(joint_params, WORKING_SEEDS)
    print(
        f"  joint working: win_rate={joint_block.win_rate_a:.3f} "
        f"({joint_block.wins_a}W/{joint_block.wins_b}L/{joint_block.ties}T) "
        f"interval={joint_block.wilson_interval_a} "
        f"accept_candidate={tuning.accept_candidate(joint_block, _even_baseline(joint_block.n))}",
        flush=True,
    )
    if tuning.accept_candidate(joint_block, _even_baseline(joint_block.n)):
        joint_confirm = evaluate(joint_params, LARGE_SEEDS)
        n2 = joint_confirm.n
        print(
            f"  joint confirm (n={n2}): win_rate={joint_confirm.win_rate_a:.3f} "
            f"({joint_confirm.wins_a}W/{joint_confirm.wins_b}L/{joint_confirm.ties}T) "
            f"interval={joint_confirm.wilson_interval_a} "
            f"accept_candidate={tuning.accept_candidate(joint_confirm, _even_baseline(n2))}",
            flush=True,
        )
