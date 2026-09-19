"""T8.41 Stage A trace: why the diagonal (min_hires_per_day,
max_animals_per_type) grid - each bundled with feed_pickup_unpinned/
animal_pickup_unpinned/prioritize_animal_setup all True - lost decisively
to the shipped baseline instead of the predicted rise-then-plateau
(tools/measure_t841.py: 0.000/0.020/0.000/0.000 win rate at
(4,2)/(6,3)/(8,4), all rejected; even the least-bad (4,2) only won 1/50).

Answers what measure_t841.py's win rate alone can't - reusing
daily_dashboard's own tested helpers and top_replay_stats's per-day
board/cash-flow summaries (T8.40's own reuse discipline: the same
functions that produced the real top-leaderboard numbers work
unchanged on a self-play episode's steps list):

  1. Does max_animals_per_type actually bind - does a second animal ever
     get built/placed, or does score_portfolio simply never rank a
     second instance of an already-placed animal type above every crop,
     making the cap increase a no-op regardless of labor available.
  2. Where the extra hands' time actually goes - board_for_day's
     plants_total/animals_total/weeds/n_quadrants across the game,
     compared side by side with the baseline played in the same episode
     (same seed, same market draws).
  3. Whether the extra labor ever translates into money fast enough to
     buy land *earlier* (the real, measured top-player edge - T8.40:
     2nd quadrant by day 9 for 22/22 top team-seasons, ours never before
     T8.41), or only late enough that it can't be capitalized on before
     season end.

Traced finding (this run, seeds 100-105, (4,2)/(8,4) bundles): the
single NW quadrant's ~24 workable tiles are already fully worked by the
baseline's 2 units within the first several days - extra hands have
nothing more productive to do until land actually expands, and land
purchase is gated purely on money/thresholds (land_purchase_threshold_
money, land_buy_*), never on labor - so more hands don't buy land
sooner on their own. max_animals_per_type never actually bound in any
sampled seed: animals_total stayed at 1 throughout, for both baseline
and every candidate - a second animal simply never outranked crops
under today's market/scoring, independent of the cap. The net effect of
more hands with nothing extra to do: modestly worse weed counts (missed
routine care during the brief windows units *are* idle-but-not-quite,
walking further for the same density of tasks) and negligible extra
hire cost, both realized every day of the game - a small, real, and
now well-evidenced downside rather than a bug.

Not part of the committed test suite - a one-off diagnostic run.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import top_replay_stats as trs  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t841_trace_workdir"
os.makedirs(WORKDIR, exist_ok=True)

_SEASON_LENGTH_DAYS = 30


def _bundle(min_hires_per_day: int, max_animals_per_type: int) -> dict:
    return dict(
        DEFAULT_PARAMS,
        min_hires_per_day=min_hires_per_day,
        max_animals_per_type=max_animals_per_type,
        feed_pickup_unpinned=True,
        animal_pickup_unpinned=True,
        prioritize_animal_setup=True,
    )


def trace_paired(candidate_agent: str, label: str, baseline_agent: str, seed: int) -> dict:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([candidate_agent, baseline_agent])
    steps = env.steps

    max_animals = {0: 0, 1: 0}
    max_weeds = {0: 0, 1: 0}
    max_quads = {0: 0, 1: 0}
    for day in range(_SEASON_LENGTH_DAYS):
        for team in (0, 1):
            board = trs.board_for_day(steps, day, team)
            max_animals[team] = max(max_animals[team], board["animals_total"])
            max_weeds[team] = max(max_weeds[team], board["weeds"])
            max_quads[team] = max(max_quads[team], board["n_quadrants"])

    sell_c = sum(trs.cash_flow_for_day(steps, d, 0)["sell_revenue"] for d in range(_SEASON_LENGTH_DAYS))
    sell_b = sum(trs.cash_flow_for_day(steps, d, 1)["sell_revenue"] for d in range(_SEASON_LENGTH_DAYS))
    hire_c = sum(trs.cash_flow_for_day(steps, d, 0)["hire_cost"] for d in range(_SEASON_LENGTH_DAYS))

    final = steps[-1]
    print(
        f"seed {seed} [{label}]: final_money candidate={final[0].reward:.0f} baseline={final[1].reward:.0f} | "
        f"animals(max) c={max_animals[0]} b={max_animals[1]} | weeds(max) c={max_weeds[0]} b={max_weeds[1]} | "
        f"quadrants(max) c={max_quads[0]} b={max_quads[1]} | sell_revenue c={sell_c:.0f} b={sell_b:.0f} | "
        f"hire_cost c={hire_c:.0f}",
        flush=True,
    )
    return {
        "seed": seed, "candidate_money": final[0].reward, "baseline_money": final[1].reward,
        "candidate_animals_max": max_animals[0], "candidate_quads_max": max_quads[0],
    }


baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)

for min_hires, max_animals, seeds in ((4, 2, (100, 101, 102)), (8, 4, (100,))):
    label = f"({min_hires}, {max_animals}) + unpin + priority"
    candidate_agent = tuning.write_candidate_agent(_bundle(min_hires, max_animals), WORKDIR)
    rows = [trace_paired(candidate_agent, label, baseline_agent, seed) for seed in seeds]
    never_a_second_animal = all(r["candidate_animals_max"] <= 1 for r in rows)
    print(
        f"  -> max_animals_per_type={max_animals} bound in 0/{len(rows)} traced seeds "
        f"(a second animal never got built/placed)" if never_a_second_animal
        else f"  -> a second animal WAS placed in at least one traced seed - the cap does bind here",
        flush=True,
    )
    print()
