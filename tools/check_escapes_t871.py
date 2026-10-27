"""T8.71 escape guardrail: test_no_animal_escapes_across_the_golden_seeds,
re-run with crop_pending_supply_aware=True (a temporary, never-recorded
override - see that test's own docstring for why this invariant must
never be re-baselined). Not part of the committed test suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_dashboard  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd871_escape")
os.makedirs(W, exist_ok=True)
AGENT_PATH = tuning.write_candidate_agent(dict(DEFAULT_PARAMS, crop_pending_supply_aware=True), W)

_GOLDEN = [("starter", 1), ("starter", 2), ("starter", 3), ("pass", 1), ("pass", 2), ("pass", 3)]

escapes = []
for opponent, seed in _GOLDEN:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([AGENT_PATH, opponent])
    steps = env.steps
    for t in range(1, len(steps)):
        prev_tiles = steps[t - 1][0].observation["farms"][0]["tiles"]
        cur_tiles = steps[t][0].observation["farms"][0]["tiles"]
        for y, row in enumerate(prev_tiles):
            for x, prev_tile in enumerate(row):
                cause = daily_dashboard.classify_animal_transition(prev_tile, cur_tiles[y][x])
                if cause == "escaped":
                    day = steps[t][0].observation.get("day")
                    escapes.append((opponent, seed, day, prev_tile.get("animal")))
    print(f"{opponent} seed {seed}: final money {steps[-1][0].reward}", flush=True)

print("escapes:", escapes)
sys.exit(1 if escapes else 0)
