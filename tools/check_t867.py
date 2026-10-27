"""T8.67: run the animal opening on a few seeds and report escapes, herd size per day, the first
productions and the cash curve. Not part of the committed test suite."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_dashboard  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd67c")
os.makedirs(W, exist_ok=True)


def run(seed, opponent="starter", **over):
    path = tuning.write_candidate_agent(dict(DEFAULT_PARAMS, animal_opening=True, **over), W)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([path, opponent])
    steps = env.steps
    escapes = []
    for t in range(1, len(steps)):
        prev = steps[t - 1][0].observation["farms"][0]["tiles"]
        cur = steps[t][0].observation["farms"][0]["tiles"]
        for y, row in enumerate(prev):
            for x, pt in enumerate(row):
                cause = daily_dashboard.classify_animal_transition(pt, cur[y][x])
                if cause is not None and "escape" in str(cause).lower():
                    o = steps[t][0].observation
                    escapes.append((o["day"], o["hour"], (x, y), pt.get("animal") if isinstance(pt, dict) else None))
    per_day = {}
    for st in steps:
        o = st[0].observation
        f = o["farms"][0]
        if o["hour"] == 0:
            n = sum(1 for r in f["tiles"] for t in r if isinstance(t, dict) and "animal" in t)
            per_day[o["day"]] = (n, int(f["money"]), 1 + len(f["hands"]), len(f["unlocked_quadrants"]))
    return steps[-1][0].reward, escapes, per_day


if __name__ == "__main__":
    for seed in [int(a) for a in sys.argv[1:]] or [100]:
        reward, escapes, per_day = run(seed)
        print(f"seed {seed}: reward {reward:.0f} escapes {escapes}")
        print("  day: (animals, money, units@0, quadrants)", {d: v for d, v in per_day.items() if d % 3 == 0 or d < 4})
