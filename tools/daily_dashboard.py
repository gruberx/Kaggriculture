"""Daily development dashboard - reusable diagnostic infrastructure, not
a one-off trace_t83N.py. See tasks/todo.md's T8.35 entry for the full
context: the user's own request for per-day visibility into crop/animal
loss, hand count, quadrant openings, cash flow, purchase affordability,
and whether sale prices are being driven to the floor - none of which
any prior trace script surfaced.

The real engine (kaggle_environments.envs.kaggriculture.kaggriculture,
the installed package - src/kagg/gamelib/ only mirrors constants and a
few forecast helpers) has no event log anywhere (no "log"/"events" key,
`info` is always `{}`), so every event this module reports is
reconstructed by diffing two consecutive step snapshots against the
engine's own end-of-day rules:

- Crop drought death (_daily_refresh_plants, kaggriculture.py:769-785):
  a PLANT tile with `consecutive_unwatered >= 2` (i.e. still unwatered
  today, having already missed yesterday) becomes `{"kind": "WEED"}`.
  Early warning: `consecutive_unwatered == 1` means it dies tonight
  unless watered before end-of-day.
- Crop lifespan decay (_decay_plants, kaggriculture.py:752-766, same
  WEED result, different cause): reuses this repo's own
  kagg.gamelib.decay.decay_step, already tested elsewhere - not
  reimplemented here.
- Animal escape (_daily_refresh_animals, kaggriculture.py:805-833): an
  animal tile with `consecutive_unfed >= 2` becomes a bare
  `{"kind": "COOP"/"PASTURE"}` (no "animal" key, no flag). Early
  warning: `consecutive_unfed == 1`.
- A third, harmless WEED source (_spawn_weeds, ambient `None -> WEED`)
  is excluded by requiring the *previous* tile to be a real PLANT dict.

Purchase affordability has no failure flag either - _commit_unit
silently `return False`s on insufficient cash. But env.steps[t][i].action
records the actual submitted order, aligned with the observation it
produced, so diffing the right private/farm counter before vs. after
against the requested quantity gives an exact, engine-truth "requested
N, filled M" signal - no need to reimplement decide()'s own policy
logic. For BUY_LAND specifically, land_gate_status below calls the real
strategy.should_buy_land directly, reusing it rather than re-deriving
its two gates.

Price-floor detection uses obs["market"]["prices"]/["inventory"]
directly (already in the observation, no derivation needed) plus a real
engine quirk worth surfacing: a sale only grows market inventory when
price > 1 (kaggriculture.py:653-661) - once a product's price is pinned
at $1, further selling stops moving inventory at all, so
`price == 1 AND inventory unchanged` is the precise signature of
dumping into a dead floor, not just "price is low today."

One schema note found while building this: obs["private"]["seeds"] is a
*sibling* of "farms", not inside farm[i] - and unlike the shared
farms/market/town keys (only ever valid via steps[t][0].observation),
"private" is per-player and must be read as steps[t][i].observation
["private"] for player i's own data.

Not part of the committed self-play regression suite (like
tools/harness.py/tools/tuning.py, this is dev-only tooling that never
ships), but IS committed, reusable infrastructure with real tests
(tests/test_tools_daily_dashboard.py) - unlike the disposable
trace_t83N.py one-offs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.gamelib import decay  # noqa: E402
from kagg.gamelib.constants import ANIMALS, PRICE_FLOOR, PRODUCTS  # noqa: E402
from kagg.gamelib.farm import land_price  # noqa: E402
from kagg.policy import strategy  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

_DEFAULT_EPISODE_STEPS = 720
_DEFAULT_SEED = 900


# --- pure detection functions (unit-tested, no kaggle_environments dep) ---


def classify_plant_transition(prev_tile, cur_tile, prev_step: int) -> str | None:
    """"drought_death" | "decay_death" | None for one tile's transition
    from `prev_tile` (at turn `prev_step`) to `cur_tile` (at `prev_step
    + 1`). See this module's own docstring for the two real-engine rules
    this mirrors. Drought is checked first since it is a day-boundary-
    only event; decay is checked second since it can fire at any turn -
    by construction of the real engine only one cause can be true for
    any single real transition, so the order doesn't matter in practice,
    but drought first keeps the common case cheap."""
    if not (isinstance(prev_tile, dict) and prev_tile.get("kind") == "PLANT"):
        return None
    if cur_tile != {"kind": "WEED"}:
        return None
    unwatered = not prev_tile.get("watered_today", False) and prev_tile.get("consecutive_unwatered", 0) >= 1
    if unwatered:
        return "drought_death"
    if decay.decay_step(prev_tile.get("max_lifespan_step", -1), prev_step) and prev_tile.get("yield_units", 0) <= 1:
        return "decay_death"
    return None


def classify_animal_transition(prev_tile, cur_tile) -> str | None:
    """"escaped" | None for one tile's transition. Escape only ever
    turns a populated animal tile into its own bare structure - checked
    exactly, not just "kind changed", so a tile that was never an animal
    tile never reports an escape."""
    if not (isinstance(prev_tile, dict) and "animal" in prev_tile):
        return None
    structure = ANIMALS[prev_tile["animal"]]["structure"]
    if not (isinstance(cur_tile, dict) and cur_tile.get("kind") == structure and "animal" not in cur_tile):
        return None
    if not prev_tile.get("fed_today", False) and prev_tile.get("consecutive_unfed", 0) >= 1:
        return "escaped"
    return None


def plant_risk(tile) -> int:
    """consecutive_unwatered for a PLANT tile, 0 otherwise - a same-day
    early-warning count (>=1 means it dies tonight unless watered)."""
    if isinstance(tile, dict) and tile.get("kind") == "PLANT":
        return tile.get("consecutive_unwatered", 0)
    return 0


def animal_risk(tile) -> int:
    """consecutive_unfed for an animal tile, 0 otherwise."""
    if isinstance(tile, dict) and "animal" in tile:
        return tile.get("consecutive_unfed", 0)
    return 0


def is_price_floor_pinned(prev_prices, cur_prices, prev_inventory, cur_inventory, product: str) -> bool:
    """True if `product`'s price was already at PRICE_FLOOR and still is,
    AND inventory didn't move either - the real engine's own signature of
    "selling into a dead floor" (a sale only grows inventory when
    price > 1, kaggriculture.py:653-661), not just "price is low"."""
    if prev_prices.get(product) != PRICE_FLOOR or cur_prices.get(product) != PRICE_FLOOR:
        return False
    return cur_inventory.get(product) == prev_inventory.get(product)


def track_daily_min_price(day_min: dict, day: int, prices: dict) -> None:
    """Update `day_min` (day -> [price, product]) in place with the
    cheapest product/price seen so far this day, across every product in
    `prices`. Call once per turn with that turn's obs["market"]["prices"]
    - since a day's headline row is printed the moment `hour==1` (early
    in the day), the caller must run this over the *whole* episode in a
    first pass before printing any row, not incrementally alongside it,
    or a day's minimum would be read back before most of that day's
    turns - and their price movement - have even happened yet."""
    for product, price in prices.items():
        cur = day_min.get(day)
        if cur is None or price < cur[0]:
            day_min[day] = [price, product]


def order_fill(order: list, prev_private: dict, cur_private: dict, prev_farm: dict, cur_farm: dict):
    """(op, requested, filled) for one submitted market order, by diffing
    the exact counter the real engine actually updates for that order
    type. `prev_private`/`cur_private` must be the acting player's own
    steps[t][i].observation["private"] (per-player, not the shared
    farms/market/town keys); `prev_farm`/`cur_farm` are that same
    player's steps[t][0].observation["farms"][i] (shared, so always
    valid via index 0).

    Caveat, stated rather than hidden: BUY_SEED's "filled" is a lower
    bound if a PLANT action consumed seeds the same turn - unit actions
    run before market processing (kaggriculture.py:935-941), so a same-
    turn plant already reduced `prev_private`'s count before the buy is
    even quoted. Rare in practice (most turns don't both plant and buy
    the same crop), not corrected for here.
    """
    op = order[0]
    if op == "BUY_SEED":
        crop, qty = order[1], int(order[2])
        filled = cur_private["seeds"].get(crop, 0) - prev_private["seeds"].get(crop, 0)
        return op, qty, max(0, filled)
    if op == "BUY_ANIMAL":
        animal = order[1]
        qty = int(order[2]) if len(order) > 2 else 1
        filled = cur_private["shed"].get(animal, 0) - prev_private["shed"].get(animal, 0)
        return op, qty, max(0, filled)
    if op == "BUY_PRODUCT":
        item, qty = order[1], int(order[2])
        filled = cur_private["shed"].get(item, 0) - prev_private["shed"].get(item, 0)
        return op, qty, max(0, filled)
    if op == "BUY_LAND":
        filled = len(cur_farm.get("unlocked_quadrants", [])) - len(prev_farm.get("unlocked_quadrants", []))
        return op, 1, max(0, filled)
    if op == "HIRE":
        filled = cur_farm.get("hires_today", 0) - prev_farm.get("hires_today", 0)
        return op, 1, max(0, filled)
    return op, 0, 0


def land_gate_status(
    money: float,
    n_unlocked_extra: int,
    params: dict,
    free_tiles: int | None = None,
    unlocked_tiles: int | None = None,
    nearest_free_shed_distance: int | None = None,
) -> str:
    """"done" | "blocked: money" | "blocked: occupancy" | "ready" -
    reuses the real strategy.should_buy_land for the actual verdict,
    only adding the money-vs-occupancy breakdown it doesn't itself
    report (both gates collapse to one bool there, by design - see its
    own docstring)."""
    cost = land_price(n_unlocked_extra)
    if cost is None:
        return "done"
    threshold = params.get("land_purchase_threshold_money", strategy._DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY)
    if money < cost + threshold:
        return "blocked: money"
    if strategy.should_buy_land(money, n_unlocked_extra, params, free_tiles, unlocked_tiles, nearest_free_shed_distance):
        return "ready"
    return "blocked: occupancy"


# --- episode runner ---------------------------------------------------


def _scan_tiles(farm: dict) -> dict:
    n_plant = n_animal = 0
    for row in farm["tiles"]:
        for t in row:
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                n_plant += 1
            elif isinstance(t, dict) and "animal" in t:
                n_animal += 1
    return {"plant": n_plant, "animal": n_animal}


def run_dashboard(
    agent_path: str,
    opponent_path: str,
    seed: int,
    episode_steps: int = _DEFAULT_EPISODE_STEPS,
) -> None:
    env = make("kaggriculture", configuration={"episodeSteps": episode_steps, "seed": seed}, debug=False)
    env.run([agent_path, opponent_path])
    steps = env.steps

    # First pass: each day's minimum sale price, over the *whole* episode -
    # must run before any headline row is printed, since a day's row is
    # printed at hour==1 (1-2 turns into that day), long before most of
    # that day's own price movement has happened yet (see
    # track_daily_min_price's own docstring).
    day_min_price: dict[int, list] = {}
    for s in steps:
        obs0 = s[0].observation
        track_daily_min_price(day_min_price, obs0.get("day"), obs0["market"]["prices"])

    events = []  # list of (day, text)
    print(f"=== daily dashboard: seed {seed} ===")
    print("  day | hands | quad | money    | plant | animal | seeds_held | wheat_shed | floor_prices | day_min_price")

    turns_per_day = 24
    for t in range(1, len(steps)):
        prev_obs0 = steps[t - 1][0].observation
        cur_obs0 = steps[t][0].observation
        day = cur_obs0.get("day")
        hour = cur_obs0.get("hour")

        prev_farm = prev_obs0["farms"][0]
        cur_farm = cur_obs0["farms"][0]
        prev_private = steps[t - 1][0].observation["private"]
        cur_private = steps[t][0].observation["private"]

        # Tile-level transitions, every turn (decay can fire mid-day).
        prev_tiles, cur_tiles = prev_farm["tiles"], cur_farm["tiles"]
        for y, row in enumerate(prev_tiles):
            for x, prev_tile in enumerate(row):
                cur_tile = cur_tiles[y][x]
                cause = classify_plant_transition(prev_tile, cur_tile, prev_step=t - 1)
                if cause:
                    crop = prev_tile.get("crop", "?")
                    events.append((day, f"CROP DEATH ({cause}) {crop} at ({x},{y})"))
                    continue
                escape = classify_animal_transition(prev_tile, cur_tile)
                if escape:
                    events.append((day, f"ANIMAL ESCAPED {prev_tile.get('animal', '?')} at ({x},{y})"))

        # Order fills, from the action that produced this step.
        for order in steps[t][0].action.get("market", []) if steps[t][0].action else []:
            op, requested, filled = order_fill(order, prev_private, cur_private, prev_farm, cur_farm)
            if filled < requested:
                events.append((day, f"ORDER PARTIAL {op} requested={requested} filled={filled}"))

        # Land gate status change (report only on the turn it becomes ready/bought/done).
        n_unlocked_extra = len(cur_farm.get("unlocked_quadrants", ["NW"])) - 1
        prev_n_unlocked_extra = len(prev_farm.get("unlocked_quadrants", ["NW"])) - 1
        if n_unlocked_extra != prev_n_unlocked_extra:
            events.append((day, f"LAND bought - now {n_unlocked_extra + 1} quadrant(s)"))

        # Price-floor crossings.
        prev_prices, cur_prices = prev_obs0["market"]["prices"], cur_obs0["market"]["prices"]
        prev_inv, cur_inv = prev_obs0["market"]["inventory"], cur_obs0["market"]["inventory"]
        for product in PRODUCTS:
            was_floor = prev_prices.get(product) == PRICE_FLOOR
            is_floor = cur_prices.get(product) == PRICE_FLOOR
            if is_floor and not was_floor:
                events.append((day, f"{product} hit price floor (${PRICE_FLOOR})"))

        # Headline row once per day.
        if hour == 1:
            counts = _scan_tiles(cur_farm)
            seeds_held = sum(cur_private.get("seeds", {}).values())
            wheat_shed = cur_private.get("shed", {}).get("WHEAT", 0)
            n_floor = sum(1 for p in PRODUCTS if cur_prices.get(p) == PRICE_FLOOR)
            floor_note = f"{n_floor} at floor" if n_floor else "-"
            min_price, min_product = day_min_price.get(day, [None, None])
            min_note = f"{min_product} ${min_price}" if min_price is not None else "-"
            print(
                f"  {day:>3} | {len(cur_farm.get('hands', [])):>5} | {n_unlocked_extra + 1:>4} | "
                f"{cur_farm['money']:>8.0f} | {counts['plant']:>5} | {counts['animal']:>6} | "
                f"{seeds_held:>10} | {wheat_shed:>10} | {floor_note:>12} | {min_note}"
            )

    print("\n=== events ===")
    for day, text in events:
        print(f"  day {day:>2}: {text}")
    if not events:
        print("  (none)")

    final_farm = steps[-1][0].observation["farms"][0]
    print(f"\nfinal money: {final_farm['money']}")


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params-json", default=None, help="JSON file of overrides merged onto DEFAULT_PARAMS")
    parser.add_argument("--agent", default=None, help="literal agent path/name, takes precedence over --params-json")
    parser.add_argument("--opponent", default="pass")
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--episode-steps", type=int, default=_DEFAULT_EPISODE_STEPS)
    parser.add_argument("--workdir", default="/tmp/kagg_daily_dashboard_workdir")
    args = parser.parse_args()

    os.makedirs(args.workdir, exist_ok=True)
    if args.agent:
        agent_path = args.agent
    else:
        params = dict(DEFAULT_PARAMS)
        if args.params_json:
            with open(args.params_json) as f:
                params.update(json.load(f))
        agent_path = tuning.write_candidate_agent(params, args.workdir)

    run_dashboard(agent_path, args.opponent, args.seed, args.episode_steps)


if __name__ == "__main__":
    _main()
