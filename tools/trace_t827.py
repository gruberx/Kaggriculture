"""T8.27 trace: measure_t827.py's Stage 2 was a real, decisive surprise -
the corrected (scaling_only) forecast made the combined animal+crop case
much WORSE than T8.25 alone (cap=3: 22%/24% here vs T8.25-alone's own
40%/44%, even worse than T8.26's original miscounted forecast's 38%/42%),
even though Stage 1 (crop-only) confirmed the diagnosis and reversed
completely (92%/98%). This traces hand count at the *start* of each day
(hour==0) to find out whether the corrected proactive forecast is now
under-hiring relative to the existing reactive path, and why.

Suspected cause (to confirm or refute here, not assumed): the T8.27 plan's
own scaling_only design excluded FEED **and** CARE **and**
COLLECT_FERTILIZER from the animal-side forecast, reasoning they're all
"coverage, not backlog" like WATER/FEED. But `decide.py`'s own
`_ROUTINE_RECURRING_OPS` (the reactive path's actual, already-accepted
exclusion set) only contains WATER and FEED - CARE and COLLECT_FERTILIZER
tasks DO still count toward `pending_task_count`'s backlog in the shipped,
accepted `dynamic_hiring` path. If that's right, the reactive path is
already hiring *for* CARE/COLLECT_FERTILIZER load in a farm running
`animal_care_aware`/`animal_fertilizer_income_aware` (both True in the
FULL_STACK combo), while the T8.27 proactive forecast silently drops that
same load - a real, previously-unstated asymmetry between the two paths,
not a bug in the exclusion logic itself.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t827_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 900

T825_ALONE = dict(
    DEFAULT_PARAMS,
    animal_care_aware=True,
    animal_fertilizer_income_aware=True,
    parallel_animal_acquisition=True,
    wheat_urgency_reserve=3,
    max_animals_per_type=3,
)
T827_FULL_STACK = dict(T825_ALONE, workload_forecast_hiring_aware=True)


def animal_tiles(farm):
    return [t for row in farm["tiles"] for t in row if isinstance(t, dict) and "animal" in t]


def trace(agent_path: str, label: str) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=False)
    env.run([agent_path, "pass"])
    steps = env.steps

    # Hands reset to zero at hour==0 and the HIRE actions issued that same
    # turn only take effect for the *next* observation - so hour==1 is the
    # first point each day where the actual post-hire hand count is
    # visible (matches T8.16(d)'s own trace convention).
    hands_at_hour1 = []
    for s in steps:
        obs = s[0].observation
        farm = obs["farms"][0]
        if obs.get("hour") == 1:
            hands_at_hour1.append((obs.get("day"), len(farm.get("hands", []))))

    final_farm = steps[-1][0].observation["farms"][0]
    final_animals = animal_tiles(final_farm)
    max_unfed_seen = max(
        (a.get("consecutive_unfed", 0) for s in steps for a in animal_tiles(s[0].observation["farms"][0])),
        default=0,
    )
    escaped_count = 0  # animals present at some point but gone by episode end due to escape, approximated
    max_animals_seen = max(
        (len(animal_tiles(s[0].observation["farms"][0])) for s in steps), default=0
    )

    print(f"=== {label} (seed {SEED}) ===")
    print(f"  final money: {final_farm['money']}")
    print(f"  hand count at each day's hour 1 (post-hire): {hands_at_hour1}")
    print(f"  max animal-tiles ever seen: {max_animals_seen}, final animal-tiles: {len(final_animals)}")
    print(f"  max consecutive_unfed ever observed on any animal tile: {max_unfed_seen}")
    print()


t825_agent = tuning.write_candidate_agent(T825_ALONE, WORKDIR)
t827_agent = tuning.write_candidate_agent(T827_FULL_STACK, WORKDIR)

trace(t825_agent, "T8.25 alone (reactive dynamic_hiring, cap=3)")
trace(t827_agent, "T8.27 (proactive scaling_only forecast, cap=3)")
