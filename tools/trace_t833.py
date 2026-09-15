"""T8.33 Stage 1 trace: seed 100, threshold=0 vs. the checked-in baseline
(threshold=15000), played as a real paired match (shared market, real
opponent) rather than solo vs. "pass".

Written because the sweep (tools/measure_t833.py) found every threshold
value in [0, 1000, ..., 10000] producing the *exact same* result (6W/44L/
0T on the 50 tuning seeds) - flat enough to demand a direct look before
trusting it (T8.3b: trace seed 900/100 before trusting a win rate).

A first attempt traced solo play against "pass" (trace_t832.py's own
pattern) and found *no* divergence at all between threshold=0 and 15000
on 20 scanned seeds - misleading for this specific parameter, because
money in solo play blows past both thresholds early (seed 900: $20k by
day 12) before either one can matter. The real divergence only shows up
in competitive paired play, where the shared market and a real opponent
change the money trajectory enough for the lower threshold to actually
fire sooner. Confirmed this isn't a harness artifact first: the baseline
agent played against a literal copy of itself produces 20/20 ties
(perfect determinism - see tasks/todo.md's T8.33 entry) - so the non-tie
results genuinely come from the swept parameter, not from a hidden
harness confound.

Traces the two farms directly from the *same* shared episode (not two
separate single-agent runs), which is what actually exposes the
mechanism: threshold=0 buys its 2nd quadrant while still under-
capitalized, without hands to work it, and ends up worse off than
waiting.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t833_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 100


def trace_paired(first: str, first_label: str, second: str, second_label: str, seed: int) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([first, second])
    steps = env.steps

    print(f"=== seed {seed}: player0={first_label}  player1={second_label} ===")
    print("  day: [p0]hands plant animal money quad  | [p1]hands plant animal money quad")
    for s in steps:
        obs = s[0].observation
        if obs.get("hour") != 1:
            continue
        day = obs.get("day")
        cells = []
        for i in (0, 1):
            farm = obs["farms"][i]
            hands = len(farm.get("hands", []))
            n_plant = sum(
                1 for row in farm["tiles"] for t in row
                if isinstance(t, dict) and t.get("kind") == "PLANT"
            )
            n_animal = sum(
                1 for row in farm["tiles"] for t in row
                if isinstance(t, dict) and "animal" in t
            )
            n_quadrants = len(farm.get("unlocked_quadrants", []))
            cells.append(f"{hands} {n_plant:>3} {n_animal} {farm['money']:>8.0f} {n_quadrants}")
        print(f"    day {day:>2}: {cells[0]}   |   {cells[1]}")

    final = steps[-1]
    print(f"  final money: p0={final[0].reward}  p1={final[1].reward}")
    print()


baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
threshold0_agent = tuning.write_candidate_agent(
    dict(DEFAULT_PARAMS, land_purchase_threshold_money=0), WORKDIR
)

trace_paired(threshold0_agent, "threshold=0", baseline_agent, "baseline (threshold=15000)", SEED)
