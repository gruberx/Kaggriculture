"""T8.68: for every BUY_SEED/BUY_ANIMAL batch the NEW (cycle_economics)
agent places, find how long it took until every unit of that batch was
actually planted/placed, and why - not enough empty tiles (with the
occupied/free tile counts at purchase time) or not enough workers (with
the total farmer+hands count) - the user's own follow-up after the
TOMATO seed-staleness finding (T8.68's tasks/todo.md entry).

FIFO matching: each BUY_SEED/BUY_ANIMAL order becomes a batch queue entry
for its crop/animal; each PLANT/PLACE action of that type consumes one
unit from the oldest still-open batch. A batch's "delay" is the gap
between its own purchase turn and the turn its very last unit was
consumed - 0 means the whole batch was planted/placed the same turn it
was bought.

Not part of the committed test suite - a one-off diagnostic run.
"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.gamelib.constants import ANIMALS, CROPS  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

WORKDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kagg_t868_delays_workdir"
os.makedirs(WORKDIR, exist_ok=True)
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 1

baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, WORKDIR)
candidate_agent = tuning.write_candidate_agent(
    dict(DEFAULT_PARAMS, use_cycle_economics_ranking=True), WORKDIR
)


def tile_counts(obs):
    tiles = obs["farms"][0]["tiles"]
    total = sum(len(row) for row in tiles)
    free = sum(1 for row in tiles for t in row if t is None)
    return free, total - free, total


def worker_count(obs):
    return 1 + len(obs["farms"][0].get("hands", []))


def turn_index(day, hour, turns_per_day=24):
    return day * turns_per_day + hour


def analyze(agent_path, opponent_path, label):
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED}, debug=False)
    env.run([agent_path, opponent_path])
    steps = env.steps

    pending = {crop: deque() for crop in CROPS}
    pending_animal = {animal: deque() for animal in ANIMALS}
    rows = []

    for step in steps:
        obs = step[0].observation
        act = step[0].action or {}
        day, hour = obs["day"], obs["hour"]
        free, occupied, total = tile_counts(obs)
        workers = worker_count(obs)

        for order in act.get("market", []):
            if order[0] == "BUY_SEED" and order[1] in CROPS:
                pending[order[1]].append(
                    {"day": day, "hour": hour, "qty": order[2], "remaining": order[2],
                     "free": free, "occupied": occupied, "total": total, "workers": workers}
                )
            elif order[0] == "BUY_ANIMAL" and order[1] in ANIMALS:
                pending_animal[order[1]].append(
                    {"day": day, "hour": hour, "qty": order[2], "remaining": order[2],
                     "free": free, "occupied": occupied, "total": total, "workers": workers}
                )

        actions = [act.get("farmer")] + list(act.get("hands", []))
        for a in actions:
            if not a:
                continue
            if a[0] == "PLANT" and pending[a[1]]:
                batch = pending[a[1]][0]
                batch["remaining"] -= 1
                if batch["remaining"] <= 0:
                    pending[a[1]].popleft()
                    _finish(rows, "crop", a[1], batch, day, hour)
            elif a[0] == "PLACE" and pending_animal.get(a[1]):
                batch = pending_animal[a[1]][0]
                batch["remaining"] -= 1
                if batch["remaining"] <= 0:
                    pending_animal[a[1]].popleft()
                    _finish(rows, "animal", a[1], batch, day, hour)

    return rows, env.steps[-1][0].reward


def _finish(rows, kind, name, batch, done_day, done_hour):
    delay_turns = turn_index(done_day, done_hour) - turn_index(batch["day"], batch["hour"])
    if delay_turns <= 0:
        return  # realized the same turn it was bought - nothing to explain
    if batch["free"] < batch["qty"]:
        reason = f"нехватка тайлов (свободно {batch['free']}, занято {batch['occupied']} из {batch['total']})"
    elif batch["workers"] < batch["qty"]:
        reason = f"нехватка рабочих (всего {batch['workers']})"
    else:
        reason = f"другое (тайлов/рабочих хватало: свободно {batch['free']}, рабочих {batch['workers']})"
    rows.append({
        "kind": kind, "name": name, "buy_day": batch["day"], "buy_hour": batch["hour"],
        "qty": batch["qty"], "done_day": done_day, "done_hour": done_hour,
        "delay_turns": delay_turns, "delay_days": round(delay_turns / 24, 1), "reason": reason,
    })


if __name__ == "__main__":
    rows, money = analyze(candidate_agent, baseline_agent, "NEW")
    print(f"=== NEW vs OLD head-to-head, seed {SEED} - final money NEW={money} ===")
    print(f"{'kind':<6} {'name':<10} {'bought':>9} {'qty':>3} {'realized':>9} {'delay':>7} | reason")
    for r in sorted(rows, key=lambda r: (r["buy_day"], r["buy_hour"])):
        bought = f"d{r['buy_day']}h{r['buy_hour']}"
        realized = f"d{r['done_day']}h{r['done_hour']}"
        delay = f"{r['delay_turns']}h/{r['delay_days']}d"
        print(f"{r['kind']:<6} {r['name']:<10} {bought:>9} {r['qty']:>3} {realized:>9} {delay:>7} | {r['reason']}")
    print(f"\n{len(rows)} delayed batches total")
