"""Statistical study of real top-leaderboard Kaggriculture replays - see
tasks/todo.md's T8.40 entry for the full context: the user watched top-10
leaderboard replays and observed a pattern our own self-play-only
conclusions (hires_per_day=1, max_animals_per_type=1, both measured only
in 1-2-quadrant self-play against pass/starter) never tested against -
top players hire many workers and hold many animals from day 1, expand
aggressively through ~day 10, then bank profit. This module is the
reusable tool that turns real downloaded replay JSON (see tasks/todo.md's
T8.40 "fetch procedure") into a small, durable, structured extract that
can answer that question with real numbers instead of an impression, and
be revisited more than once without re-fetching.

Mirrors tools/daily_dashboard.py's own convention: pure dict-in functions,
real unit tests (tests/test_tools_top_replay_stats.py), no oracle needed
for anything that mirrors an already-tested rule (classify_plant_transition
/classify_animal_transition, order_fill - imported from daily_dashboard
directly, not reimplemented).

Real-schema facts this module was built against (found while parsing a
real downloaded episode, not assumed - see tasks/todo.md's T8.40 "Facts
that change the plan's premises"):

- A replay's top-level dict has the standard kaggle_environments episode
  keys (configuration/info/rewards/steps/...). `steps[t][i]` is itself a
  plain dict with "action"/"observation"/"reward"/"status" keys -
  kaggle_environments.utils.Struct (what env.steps holds locally) is a
  dict subclass, so every function here also runs unmodified on live
  env.steps from tools/harness.py (see self_play_records below).
- Turn index t == day * TURNS_PER_DAY + hour exactly (confirmed: t=24 is
  day 1/hour 0). steps[t][i]["action"] is the action that produced
  steps[t]'s observation from steps[t-1]'s - there is no "previous state"
  for t==0, so any diff-based function must skip t==0.
- configuration["seed"] is None in real downloaded replays - the real
  seed lives at info["seed"]. info["TeamNames"]/info["EpisodeId"] are the
  real team-name/id fields (not top-level "id", which is a UUID).
- farms[i]["hands"]/["farmer"] are board *positions* ([x, y]), not
  inventories - unit inventories live at private["inventories"][u] (index
  0 = farmer, 1.. = hands in the same order as farms[i]["hands"]).
  farms[i]["hands"] resets to [] at the start of every day (re-hired daily
  - len(hands) == hires_today all day), so a single hour-0 sample always
  undercounts; sample at MID_DAY_HOUR (or take the day's max) instead.
- Tiles are not always dicts: a locked quadrant's tile is the bare string
  "LOCKED", empty soil is bare None. Every tile-scanning function guards
  with isinstance(tile, dict), same idiom daily_dashboard.py already uses.
  Populated tile "kind" values seen: PLANT, WEED, COOP, PASTURE - an
  animal tile carries an "animal" key; a COOP/PASTURE tile without one is
  a bare (empty) structure, counted separately from real animal occupancy.
- private["seeds"]/["shed"] are per-player (steps[t][i]["observation"]
  ["private"], never via index 0) - "shed" holds both sellable products
  and live animal counts (BUY_ANIMAL deposits into shed, same as
  BUY_PRODUCT) in one dict, matching daily_dashboard.order_fill's own
  BUY_ANIMAL branch.
- town["unlocked_shops"] and market["prices"]/["inventory"] are global -
  shared by both players, only ever valid via steps[t][0]["observation"].
  In the one episode sampled so far, shops unlocked on an exact
  configuration["townShopUnlockInterval"]-day schedule (3, in that
  episode) - shop_schedule_invariant below tests this as a falsifiable
  hypothesis across a real batch, not an assumption from n=1.
- Market order entries can be the empty list [] in real actions (a
  submitted-but-empty market slot) - every order-list walk must skip
  falsy/short entries or raise IndexError (hit twice while verifying this
  module against a real episode).
- A turn can submit several HIRE orders at once (5, seen in a real
  replay) - order_fill's per-order diff would double-count fib-scaled
  hire cost if called once per HIRE order, since it diffs the same
  before/after farm counters each time. cash_flow_for_day costs HIRE and
  BUY_LAND from a single per-turn counter diff instead, and only calls
  order_fill per order for the types that don't exhibit this (BUY_SEED/
  BUY_ANIMAL/BUY_PRODUCT/SELL).
- Feed-WHEAT vs sale-WHEAT is not distinguishable from tile state alone
  (a WHEAT PLANT tile carries no destination marker) - wheat_flow reports
  a flow balance (FEED actions, bought/sold quantities, shed level),
  never a guessed split.

Deliberate granularity limit: episode_record is a *daily* summary, not a
turn-by-turn log - a 720-turn full action log per episode would balloon
the durable extract back toward the raw replay's own ~33MB size. If a
genuinely turn-level question comes up later, the fallback is re-parsing
the one still-cheap-to-refetch raw episode (data/episodes/), not
redesigning this extract.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_dashboard  # noqa: E402
from kagg.gamelib import labor  # noqa: E402
from kagg.gamelib.constants import ANIMALS, CROPS, MAX_SHOP_INSTANCES, PRODUCTS, SHOPS  # noqa: E402,F401
from kagg.gamelib.farm import land_price  # noqa: E402

TURNS_PER_DAY = 24
MID_DAY_HOUR = 12

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_AGENT_MAIN_PATH = os.path.join(_REPO_ROOT, "src", "kagg", "agent_main.py")
_DEFAULT_EPISODES_DIR = os.path.join(_REPO_ROOT, "..", "data", "episodes")
_DEFAULT_RECORDS_DIR = os.path.join(_REPO_ROOT, "..", "data", "top_replay_records")


# --- board/tile counting -----------------------------------------------


def count_tiles(farm: dict) -> dict:
    """Per-type tile census for one farm's `tiles` grid - guards the two
    non-dict tile values a real board can carry ("LOCKED", None)."""
    plants: dict[str, int] = {}
    animals: dict[str, int] = {}
    structures: dict[str, int] = {}
    weeds = empty = locked = 0
    for row in farm.get("tiles", []):
        for tile in row:
            if tile is None:
                empty += 1
            elif tile == "LOCKED":
                locked += 1
            elif not isinstance(tile, dict):
                continue  # unrecognized scalar - ignore rather than crash
            elif tile.get("kind") == "PLANT":
                crop = tile.get("crop", "?")
                plants[crop] = plants.get(crop, 0) + 1
            elif "animal" in tile:
                animal = tile["animal"]
                animals[animal] = animals.get(animal, 0) + 1
            elif tile.get("kind") == "WEED":
                weeds += 1
            else:
                # bare structure (COOP/PASTURE with no "animal" key - built
                # but empty, or emptied by an escape earlier this episode)
                kind = tile.get("kind", "?")
                structures[kind] = structures.get(kind, 0) + 1
    return {
        "plants": plants,
        "animals": animals,
        "structures": structures,
        "weeds": weeds,
        "empty": empty,
        "locked": locked,
        "plants_total": sum(plants.values()),
        "animals_total": sum(animals.values()),
    }


def day_turns(n_steps: int, day: int, turns_per_day: int = TURNS_PER_DAY) -> range:
    """Turn indices belonging to `day`, clipped to [0, n_steps) - empty for
    a day entirely beyond the episode's actual length."""
    start = min(day * turns_per_day, n_steps)
    end = min(start + turns_per_day, n_steps)
    return range(start, end)


# --- per-day, per-team summaries ----------------------------------------


def hands_for_day(steps, day: int, team: int, at_hour: int = MID_DAY_HOUR, turns_per_day: int = TURNS_PER_DAY) -> dict:
    """{"hands_max", "hands_at_mid_day", "hires_today"} - hands resets to
    [] every day (re-hired daily), so hands_max (the day's peak, catching
    a late hire an hour-0 or even mid-day sample could still miss) is the
    headline number, not a single-hour count."""
    turns = day_turns(len(steps), day, turns_per_day)
    if not turns:
        return {"hands_max": 0, "hands_at_mid_day": 0, "hires_today": 0}
    hands_max = 0
    hires_today = 0
    for t in turns:
        farm = steps[t][0]["observation"]["farms"][team]
        hands_max = max(hands_max, len(farm.get("hands", [])))
        hires_today = max(hires_today, farm.get("hires_today", 0))
    mid_turn = min(day * turns_per_day + at_hour, turns[-1])
    hands_mid = len(steps[mid_turn][0]["observation"]["farms"][team].get("hands", []))
    return {"hands_max": hands_max, "hands_at_mid_day": hands_mid, "hires_today": hires_today}


def money_for_day(steps, day: int, team: int, turns_per_day: int = TURNS_PER_DAY) -> dict:
    """{"open", "close", "min", "max"} - min exposes an early-investment
    trough a single mid-day sample would hide entirely."""
    turns = day_turns(len(steps), day, turns_per_day)
    if not turns:
        return {"open": 0.0, "close": 0.0, "min": 0.0, "max": 0.0}
    values = [steps[t][0]["observation"]["farms"][team]["money"] for t in turns]
    return {"open": values[0], "close": values[-1], "min": min(values), "max": max(values)}


def board_for_day(steps, day: int, team: int, at_hour: int = MID_DAY_HOUR, turns_per_day: int = TURNS_PER_DAY) -> dict:
    """count_tiles() at one hour (a stock, not a daily event) plus the
    unlocked-quadrant list at that same moment."""
    turns = day_turns(len(steps), day, turns_per_day)
    if not turns:
        return {
            "plants": {}, "animals": {}, "structures": {}, "weeds": 0, "empty": 0, "locked": 0,
            "plants_total": 0, "animals_total": 0, "n_quadrants": 0, "quadrants": [],
        }
    t = min(day * turns_per_day + at_hour, turns[-1])
    farm = steps[t][0]["observation"]["farms"][team]
    counts = count_tiles(farm)
    quadrants = list(farm.get("unlocked_quadrants", ["NW"]))
    counts["n_quadrants"] = len(quadrants)
    counts["quadrants"] = quadrants
    return counts


def action_counts(steps, day: int, team: int, turns_per_day: int = TURNS_PER_DAY) -> dict:
    """Per-op tallies for farmer/hands/market, keyed generically by
    whatever op string actually appears - not a pre-enumerated allowlist,
    so a real top player using something our own shipped defaults never
    touch (FERTILIZE/CARE/COLLECT_FERTILIZER/BUILD_COOP/BUILD_PASTURE/DIG,
    all seen in a real replay) is captured automatically. Market entries
    are further split by op into {"count", "quantity"} where the order
    carries a quantity (order[2], when present) - HIRE/BUY_LAND carry
    none, so their "quantity" is just their count. Falsy/short market
    entries ([]) are skipped, matching a real quirk of submitted actions.

    Also returns {"farmer_pass_fraction", "hands_pass_fraction"} - a
    labor-*saturation* signal distinct from labor *count*: if a top
    player's hands rarely PASS while ours often do at hires_per_day=1,
    that's direct evidence more hands would find work, not just that they
    have more hands.
    """
    turns = day_turns(len(steps), day, turns_per_day)
    farmer_ops: dict[str, int] = {}
    hands_ops: dict[str, int] = {}
    market_ops: dict[str, dict] = {}
    farmer_turns = farmer_passes = 0
    hands_turns = hands_passes = 0
    for t in turns:
        action = steps[t][team]["action"]
        if not action:
            continue
        farmer_action = action.get("farmer")
        if farmer_action:
            op = farmer_action[0]
            farmer_ops[op] = farmer_ops.get(op, 0) + 1
            farmer_turns += 1
            if op == "PASS":
                farmer_passes += 1
        for hand_action in action.get("hands", []):
            if not hand_action:
                continue
            op = hand_action[0]
            hands_ops[op] = hands_ops.get(op, 0) + 1
            hands_turns += 1
            if op == "PASS":
                hands_passes += 1
        for order in action.get("market", []):
            if not order:
                continue
            op = order[0]
            entry = market_ops.setdefault(op, {"count": 0, "quantity": 0})
            entry["count"] += 1
            entry["quantity"] += int(order[2]) if len(order) > 2 else 1
    return {
        "farmer": farmer_ops,
        "hands": hands_ops,
        "market": market_ops,
        "farmer_pass_fraction": (farmer_passes / farmer_turns) if farmer_turns else 0.0,
        "hands_pass_fraction": (hands_passes / hands_turns) if hands_turns else 0.0,
    }


def wheat_flow(steps, day: int, team: int, turns_per_day: int = TURNS_PER_DAY) -> dict:
    """{"feed_actions", "wheat_bought", "wheat_sold", "wheat_shed_open",
    "wheat_shed_close", "wheat_plant_tiles"} - the honest substitute for
    the undecidable feed-vs-sale WHEAT split (see module docstring): a
    flow balance instead of a guessed attribution."""
    turns = day_turns(len(steps), day, turns_per_day)
    if not turns:
        return {
            "feed_actions": 0, "wheat_bought": 0, "wheat_sold": 0,
            "wheat_shed_open": 0, "wheat_shed_close": 0, "wheat_plant_tiles": 0,
        }
    feed_actions = wheat_bought = wheat_sold = 0
    for t in turns:
        action = steps[t][team]["action"]
        if not action:
            continue
        farmer_action = action.get("farmer")
        if farmer_action and farmer_action[0] == "FEED":
            feed_actions += 1
        for hand_action in action.get("hands", []):
            if hand_action and hand_action[0] == "FEED":
                feed_actions += 1
        for order in action.get("market", []):
            if not order:
                continue
            if order[0] == "BUY_PRODUCT" and order[1] == "WHEAT":
                wheat_bought += int(order[2]) if len(order) > 2 else 1
            elif order[0] == "SELL" and order[1] == "WHEAT":
                wheat_sold += int(order[2]) if len(order) > 2 else 1
    wheat_shed_open = steps[turns[0]][team]["observation"]["private"]["shed"].get("WHEAT", 0)
    wheat_shed_close = steps[turns[-1]][team]["observation"]["private"]["shed"].get("WHEAT", 0)
    mid_turn = min(day * turns_per_day + MID_DAY_HOUR, turns[-1])
    farm = steps[mid_turn][0]["observation"]["farms"][team]
    wheat_plant_tiles = 0
    for row in farm.get("tiles", []):
        for tile in row:
            if isinstance(tile, dict) and tile.get("kind") == "PLANT" and tile.get("crop") == "WHEAT":
                wheat_plant_tiles += 1
    return {
        "feed_actions": feed_actions,
        "wheat_bought": wheat_bought,
        "wheat_sold": wheat_sold,
        "wheat_shed_open": wheat_shed_open,
        "wheat_shed_close": wheat_shed_close,
        "wheat_plant_tiles": wheat_plant_tiles,
    }


def cash_flow_for_day(steps, day: int, team: int, turns_per_day: int = TURNS_PER_DAY) -> dict:
    """{"hire_cost", "land_cost", "seed_cost", "animal_cost",
    "wheat_restock_cost", "other_cost", "sell_revenue", "net"} - where a
    day's money actually went, by category, not just money_for_day's
    open/close balance.

    HIRE and BUY_LAND are costed from a single per-turn hires_today/
    unlocked_quadrants diff (a turn can submit several HIRE orders at
    once - order_fill's per-order diff would double-count fib-scaled hire
    cost if called once per order, since prev/cur farm counters are fixed
    for the whole turn). Every other order type is costed per order via
    daily_dashboard.order_fill's own filled-quantity semantics, priced at
    the turn's own prior market price (prev_prices) for market-priced
    goods, or the fixed CROPS/ANIMALS cost for seeds/animals.
    "other_cost" covers any BUY_PRODUCT that isn't WHEAT (e.g. FERTILIZER
    restock) so `net` reconciles exactly against sell_revenue minus every
    named cost - not just the categories with a name."""
    turns = day_turns(len(steps), day, turns_per_day)
    hire_cost = land_cost = seed_cost = animal_cost = 0.0
    wheat_restock_cost = other_cost = sell_revenue = 0.0
    for t in turns:
        if t == 0:
            continue  # no prior state to diff against
        prev_farm = steps[t - 1][0]["observation"]["farms"][team]
        cur_farm = steps[t][0]["observation"]["farms"][team]

        hires_filled = max(0, cur_farm.get("hires_today", 0) - prev_farm.get("hires_today", 0))
        start_n = prev_farm.get("hires_today", 0)
        for i in range(start_n, start_n + hires_filled):
            hire_cost += labor.hire_cost(i)

        prev_quads = prev_farm.get("unlocked_quadrants", ["NW"])
        cur_quads = cur_farm.get("unlocked_quadrants", ["NW"])
        lands_filled = max(0, len(cur_quads) - len(prev_quads))
        n_before = len(prev_quads) - 1
        for i in range(lands_filled):
            price = land_price(n_before + i)
            if price is not None:
                land_cost += price

        action = steps[t][team]["action"]
        if not action:
            continue
        prev_private = steps[t - 1][team]["observation"]["private"]
        cur_private = steps[t][team]["observation"]["private"]
        prev_prices = steps[t - 1][0]["observation"]["market"]["prices"]
        for order in action.get("market", []):
            if not order:
                continue
            op, _requested, filled = daily_dashboard.order_fill(order, prev_private, cur_private, prev_farm, cur_farm)
            if filled <= 0 or op in ("HIRE", "BUY_LAND"):
                continue
            if op == "BUY_SEED":
                seed_cost += filled * CROPS[order[1]]["seed"]
            elif op == "BUY_ANIMAL":
                animal_cost += filled * ANIMALS[order[1]]["cost"]
            elif op == "BUY_PRODUCT":
                price = prev_prices.get(order[1], 0)
                if order[1] == "WHEAT":
                    wheat_restock_cost += filled * price
                else:
                    other_cost += filled * price
            elif op == "SELL":
                sell_revenue += filled * prev_prices.get(order[1], 0)

    net = sell_revenue - hire_cost - land_cost - seed_cost - animal_cost - wheat_restock_cost - other_cost
    return {
        "hire_cost": hire_cost,
        "land_cost": land_cost,
        "seed_cost": seed_cost,
        "animal_cost": animal_cost,
        "wheat_restock_cost": wheat_restock_cost,
        "other_cost": other_cost,
        "sell_revenue": sell_revenue,
        "net": net,
    }


def stock_for_day(steps, day: int, team: int, at_hour: int = MID_DAY_HOUR, turns_per_day: int = TURNS_PER_DAY) -> dict:
    """{"seeds": {crop: n}, "shed": {item: n}} snapshot at one hour - how
    large a buffer top players actually carry (WHEAT-on-hand especially),
    cross-referencing this project's own wheat_urgency_reserve/
    wheat_restock_threshold findings (T8.25/T8.37/T8.39) against real
    strong play. Every known crop/item key is present, zero-filled if the
    real (or a synthetic test) private dict omits it."""
    turns = day_turns(len(steps), day, turns_per_day)
    if not turns:
        t = None
    else:
        t = min(day * turns_per_day + at_hour, turns[-1])
    if t is None:
        private = {}
    else:
        private = steps[t][team]["observation"]["private"]
    seeds = private.get("seeds", {})
    shed = private.get("shed", {})
    return {
        "seeds": {crop: seeds.get(crop, 0) for crop in CROPS},
        "shed": {item: shed.get(item, 0) for item in list(PRODUCTS) + list(ANIMALS)},
    }


# --- per-episode, per-team summaries -------------------------------------


def quadrant_unlock_days(steps, team: int, turns_per_day: int = TURNS_PER_DAY) -> dict:
    """{"NE": day, "SW": day, "SE": day} - missing key means never
    unlocked. NW is always unlocked from turn 0, so it's never reported."""
    seen = {"NW"}
    result: dict[str, int] = {}
    for t in range(len(steps)):
        farm = steps[t][0]["observation"]["farms"][team]
        for q in farm.get("unlocked_quadrants", []):
            if q not in seen:
                seen.add(q)
                result[q] = t // turns_per_day
    return result


def shop_unlock_timeline(steps, turns_per_day: int = TURNS_PER_DAY) -> list:
    """[{"day", "hour", "shop", "index"}] - one entry per newly unlocked
    shop instance, global (read from steps[t][0] only - town is shared).
    Duplicate shop names are expected (drawn with replacement, capped at
    MAX_SHOP_INSTANCES)."""
    events = []
    prev_shops: list = []
    for t in range(len(steps)):
        shops = steps[t][0]["observation"]["town"]["unlocked_shops"]
        if len(shops) > len(prev_shops):
            for idx in range(len(prev_shops), len(shops)):
                events.append({"day": t // turns_per_day, "hour": t % turns_per_day, "shop": shops[idx], "index": idx})
        prev_shops = shops
    return events


def prices_for_day(steps, day: int, turns_per_day: int = TURNS_PER_DAY) -> dict:
    """{product: {"open", "close", "min", "max"}} - market prices are
    global (steps[t][0]'s observation, shared by both sides), read once
    per day, not per team. Pairs with action_counts's BUY_PRODUCT/SELL
    tallies (both sides) to see how combined volume moves price."""
    turns = day_turns(len(steps), day, turns_per_day)
    result: dict[str, dict] = {}
    if not turns:
        return result
    for product in PRODUCTS:
        values = [steps[t][0]["observation"]["market"]["prices"].get(product) for t in turns]
        values = [v for v in values if v is not None]
        if not values:
            continue
        result[product] = {"open": values[0], "close": values[-1], "min": min(values), "max": max(values)}
    return result


def animal_events_for_day(steps, day: int, team: int, turns_per_day: int = TURNS_PER_DAY) -> list:
    """[{"pos", "animal", "cause", "hour"}] - walks every turn transition
    within the day (an escape can happen mid-day, not just at a single
    sampled hour), reusing daily_dashboard.classify_animal_transition
    directly rather than reimplementing it."""
    turns = day_turns(len(steps), day, turns_per_day)
    events = []
    for t in turns:
        if t == 0:
            continue
        prev_tiles = steps[t - 1][0]["observation"]["farms"][team]["tiles"]
        cur_tiles = steps[t][0]["observation"]["farms"][team]["tiles"]
        for y, row in enumerate(prev_tiles):
            for x, prev_tile in enumerate(row):
                cur_tile = cur_tiles[y][x]
                cause = daily_dashboard.classify_animal_transition(prev_tile, cur_tile)
                if cause:
                    events.append({"pos": [x, y], "animal": prev_tile.get("animal", "?"), "cause": cause, "hour": t % turns_per_day})
    return events


def plant_events_for_day(steps, day: int, team: int, turns_per_day: int = TURNS_PER_DAY) -> list:
    """[{"pos", "crop", "cause", "hour"}] - same convention as
    animal_events_for_day, reusing daily_dashboard.classify_plant_transition
    directly for every non-None death cause (drought/decay)."""
    turns = day_turns(len(steps), day, turns_per_day)
    events = []
    for t in turns:
        if t == 0:
            continue
        prev_tiles = steps[t - 1][0]["observation"]["farms"][team]["tiles"]
        cur_tiles = steps[t][0]["observation"]["farms"][team]["tiles"]
        for y, row in enumerate(prev_tiles):
            for x, prev_tile in enumerate(row):
                cur_tile = cur_tiles[y][x]
                cause = daily_dashboard.classify_plant_transition(prev_tile, cur_tile, prev_step=t - 1)
                if cause:
                    events.append({"pos": [x, y], "crop": prev_tile.get("crop", "?"), "cause": cause, "hour": t % turns_per_day})
    return events


def episode_record(ep: dict, at_hour: int = MID_DAY_HOUR, cohort: str = "top", turns_per_day: int = TURNS_PER_DAY) -> dict:
    """The compact per-episode summary everything downstream uses. Caller
    should drop the raw ~33MB episode dict immediately after calling this
    (see iter_episode_records below) - see module docstring's "Deliberate
    granularity limit" for why this is daily, not turn-by-turn."""
    steps = ep["steps"]
    n_steps = len(steps)
    n_teams = len(steps[0])
    n_days = (n_steps + turns_per_day - 1) // turns_per_day

    info = ep.get("info") or {}
    episode_id = info.get("EpisodeId", ep.get("id"))
    seed = info.get("seed")
    if seed is None:
        seed = (ep.get("configuration") or {}).get("seed")
    team_names = info.get("TeamNames") or [f"team_{i}" for i in range(n_teams)]
    rewards = ep.get("rewards")

    timeline = shop_unlock_timeline(steps, turns_per_day)
    prices = [prices_for_day(steps, day, turns_per_day) for day in range(n_days)]

    teams = []
    for team in range(n_teams):
        days = []
        animal_escapes: list = []
        plant_deaths: list = []
        for day in range(n_days):
            row = {"day": day}
            row.update(hands_for_day(steps, day, team, at_hour, turns_per_day))
            row.update(money_for_day(steps, day, team, turns_per_day))
            row["board"] = board_for_day(steps, day, team, at_hour, turns_per_day)
            row["actions"] = action_counts(steps, day, team, turns_per_day)
            row["wheat"] = wheat_flow(steps, day, team, turns_per_day)
            row["cash_flow"] = cash_flow_for_day(steps, day, team, turns_per_day)
            row["stock"] = stock_for_day(steps, day, team, at_hour, turns_per_day)
            days.append(row)
            for e in animal_events_for_day(steps, day, team, turns_per_day):
                e = dict(e, day=day)
                animal_escapes.append(e)
            for e in plant_events_for_day(steps, day, team, turns_per_day):
                e = dict(e, day=day)
                plant_deaths.append(e)
        teams.append({
            "team_name": team_names[team] if team < len(team_names) else f"team_{team}",
            "reward": rewards[team] if rewards and team < len(rewards) else None,
            "quadrant_unlock_days": quadrant_unlock_days(steps, team, turns_per_day),
            "animal_escapes": animal_escapes,
            "plant_deaths": plant_deaths,
            "days": days,
        })

    return {
        "episode_id": episode_id,
        "seed": seed,
        "cohort": cohort,
        "rewards": rewards,
        "team_names": team_names,
        "n_days": n_days,
        "prices": prices,  # list indexed by day - avoids the int-key/str-key JSON round-trip mismatch a {day: ...} dict would hit
        "shop_unlock_days": [e["day"] for e in timeline],
        "shop_unlock_names": [e["shop"] for e in timeline],
        "teams": teams,
    }


# --- aggregation across many records --------------------------------------


def percentile(values: list, q: float) -> float:
    """Nearest-rank percentile (rank = ceil(q * n), 1-indexed) -
    deterministic and exactly testable, unlike statistics.quantiles's
    interpolation."""
    if not values:
        raise ValueError("percentile of an empty list")
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[k]


def _get_dotted(d: dict, field: str):
    cur = d
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def rows(records: list) -> list:
    """Flatten episode_records to one row per (episode, team, day),
    carrying cohort/episode_id/team_name so summarize/compare_cohorts can
    group and filter without re-walking the nested structure."""
    out = []
    for rec in records:
        for team_idx, team in enumerate(rec["teams"]):
            for day_row in team["days"]:
                flat = dict(day_row)
                flat["episode_id"] = rec["episode_id"]
                flat["cohort"] = rec["cohort"]
                flat["team_name"] = team["team_name"]
                flat["team_index"] = team_idx
                out.append(flat)
    return out


def summarize(rows_: list, field: str, cohort: str | None = None) -> dict:
    """{day: {"n", "median", "q1", "q3", "min", "max"}} for `field`
    (dotted, e.g. "board.animals.COW") across `rows_`, optionally
    restricted to one cohort."""
    by_day: dict[int, list] = {}
    for r in rows_:
        if cohort is not None and r.get("cohort") != cohort:
            continue
        v = _get_dotted(r, field)
        if v is None:
            continue
        by_day.setdefault(r["day"], []).append(v)
    result = {}
    for day, values in by_day.items():
        result[day] = {
            "n": len(values),
            "median": percentile(values, 0.5),
            "q1": percentile(values, 0.25),
            "q3": percentile(values, 0.75),
            "min": min(values),
            "max": max(values),
        }
    return result


def compare_cohorts(rows_: list, field: str, cohort_a: str = "top", cohort_b: str = "ours") -> dict:
    """{day: {"a_median", "b_median", "delta", "n_a", "n_b"}} - delta is
    a_median - b_median (None if either side has no data that day)."""
    sum_a = summarize(rows_, field, cohort_a)
    sum_b = summarize(rows_, field, cohort_b)
    result = {}
    for day in sorted(set(sum_a) | set(sum_b)):
        a, b = sum_a.get(day), sum_b.get(day)
        a_median = a["median"] if a else None
        b_median = b["median"] if b else None
        delta = (a_median - b_median) if (a_median is not None and b_median is not None) else None
        result[day] = {"a_median": a_median, "b_median": b_median, "delta": delta, "n_a": a["n"] if a else 0, "n_b": b["n"] if b else 0}
    return result


def shop_schedule_invariant(records: list) -> dict:
    """{"invariant": bool, "sequences": {episode_id: shop_unlock_names}} -
    tests the exogenous-shop-timing hypothesis directly across a real
    batch (identical shop_unlock_names sequence in every episode) instead
    of assuming it from a single sampled episode."""
    sequences = {rec["episode_id"]: rec["shop_unlock_names"] for rec in records}
    unique = {tuple(v) for v in sequences.values()}
    return {"invariant": len(unique) <= 1, "sequences": sequences}


# --- I/O ------------------------------------------------------------------


def load_episode(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def iter_episode_records(paths, at_hour: int = MID_DAY_HOUR, cohort: str = "top"):
    """Generator - never holds two raw ~33MB episode dicts in memory at
    once; each is dropped as soon as its (much smaller) record is built."""
    for path in paths:
        ep = load_episode(path)
        yield episode_record(ep, at_hour=at_hour, cohort=cohort)
        del ep


def save_records(records: list, out_dir: str) -> None:
    """Writes one <episode_id>.json per record plus a combined
    index.jsonl (one record per line) for fast bulk reload - the durable
    structured extract the user asked to keep recoverable across sessions
    without re-fetching. Deliberately outside diskguard.EVICTABLE (which
    only lists data/replays, data/episodes)."""
    os.makedirs(out_dir, exist_ok=True)
    index_path = os.path.join(out_dir, "index.jsonl")
    with open(index_path, "w") as index_f:
        for rec in records:
            rec_path = os.path.join(out_dir, f"{rec['episode_id']}.json")
            with open(rec_path, "w") as f:
                json.dump(rec, f)
            index_f.write(json.dumps(rec) + "\n")


def load_saved_records(dir_or_index: str) -> list:
    """Reloads records written by save_records, from a directory (reads
    its index.jsonl) or an index.jsonl path directly - never touches the
    raw replays, the normal path for re-analysis."""
    index_path = os.path.join(dir_or_index, "index.jsonl") if os.path.isdir(dir_or_index) else dir_or_index
    records = []
    with open(index_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def self_play_records(
    n_seeds: int,
    agent_a: str = _AGENT_MAIN_PATH,
    agent_b: str = _AGENT_MAIN_PATH,
    episode_steps: int = 720,
    seed_start: int = 900,
    at_hour: int = MID_DAY_HOUR,
    cohort: str = "ours",
) -> list:
    """Optional "ours" comparison cohort, played fresh via
    kaggle_environments directly (tools/harness.py's own run_paired only
    keeps each game's *final* step, not the full history this module
    needs). Works unmodified on real env.steps because
    kaggle_environments.utils.Struct is a dict subclass - no second code
    path for "real replay JSON" vs "just-played env.steps".

    agent_b defaults to a mirror of agent_a, not "pass" - episode_record
    tags cohort once per whole episode (both teams), so pairing against a
    do-nothing "pass" bot would silently fold its near-zero stats into
    the "ours" cohort and drag every median down. A real (non-mirror)
    opponent cohort would need its own cohort tag per team, not attempted
    here."""
    from kaggle_environments import make

    records = []
    for i in range(n_seeds):
        seed = seed_start + i
        env = make("kaggriculture", configuration={"episodeSteps": episode_steps, "seed": seed}, debug=False)
        env.run([agent_a, agent_b])
        synthetic_ep = {
            "steps": env.steps,
            "info": {"TeamNames": ["ours", "opponent"], "seed": seed},
            "rewards": [env.steps[-1][0]["reward"], env.steps[-1][1]["reward"]],
        }
        records.append(episode_record(synthetic_ep, at_hour=at_hour, cohort=cohort))
    return records


# --- CLI --------------------------------------------------------------


def _top_types(rows_: list, base_field: str, day: int, cohort: str, n: int = 3) -> list:
    """Median count per type-key under `base_field` (e.g. "board.animals")
    for one day/cohort, sorted descending, top `n` - a small CLI-only
    helper built on the already-tested percentile(), not a separate
    pure-function-with-its-own-tests surface."""
    values: dict[str, list] = {}
    for r in rows_:
        if r.get("cohort") != cohort or r.get("day") != day:
            continue
        sub = _get_dotted(r, base_field) or {}
        for k, v in sub.items():
            values.setdefault(k, []).append(v)
    medians = [(k, percentile(v, 0.5)) for k, v in values.items()]
    medians.sort(key=lambda kv: kv[1], reverse=True)
    return medians[:n]


def _print_report(records: list, fields: list) -> None:
    rows_ = rows(records)
    cohorts = sorted({r["cohort"] for r in rows_})
    days = sorted({r["day"] for r in rows_})

    for cohort in cohorts:
        print(f"\n=== cohort: {cohort} (n episodes counted per day varies with episode length) ===")
        print("  day | hands med[q1-q3] (pass%) | animals (top3) | plants (top3) | money close | cash net | wheat shed | quadrants | n")
        hands_s = summarize(rows_, "hands_max", cohort)
        money_s = summarize(rows_, "close", cohort)
        animals_s = summarize(rows_, "board.animals_total", cohort)
        plants_s = summarize(rows_, "board.plants_total", cohort)
        cash_s = summarize(rows_, "cash_flow.net", cohort)
        wheat_s = summarize(rows_, "stock.shed.WHEAT", cohort)
        quad_s = summarize(rows_, "board.n_quadrants", cohort)
        pass_s = summarize(rows_, "actions.hands_pass_fraction", cohort)
        for day in days:
            if day not in hands_s:
                continue
            h, m = hands_s[day], money_s.get(day, {})
            a, p = animals_s.get(day, {}), plants_s.get(day, {})
            top_a = ", ".join(f"{k}:{v:.0f}" for k, v in _top_types(rows_, "board.animals", day, cohort))
            top_p = ", ".join(f"{k}:{v:.0f}" for k, v in _top_types(rows_, "board.plants", day, cohort))
            cash = cash_s.get(day, {})
            wheat = wheat_s.get(day, {})
            quad = quad_s.get(day, {})
            passf = pass_s.get(day, {})
            print(
                f"  {day:>3} | {h['median']:>4.0f}[{h['q1']:.0f}-{h['q3']:.0f}] "
                f"({passf.get('median', 0) * 100:>4.0f}%) | {a.get('median', 0):>4.0f} ({top_a}) | "
                f"{p.get('median', 0):>4.0f} ({top_p}) | {m.get('median', 0):>10.0f} | "
                f"{cash.get('median', 0):>8.0f} | {wheat.get('median', 0):>6.0f} | {quad.get('median', 0):.1f} | {h['n']}"
            )
        for field in fields:
            fs = summarize(rows_, field, cohort)
            print(f"  -- {field} --")
            for day in days:
                if day in fs:
                    s = fs[day]
                    print(f"     day {day:>3}: median={s['median']:.1f} q1={s['q1']:.1f} q3={s['q3']:.1f} n={s['n']}")

    print("\n=== price fluctuation (per product, across all cohorts/episodes/days) ===")
    price_values: dict[str, list] = {}
    for rec in records:
        for day_prices in rec["prices"]:
            for product, stat in day_prices.items():
                price_values.setdefault(product, []).append(stat["min"])
                price_values.setdefault(product, []).append(stat["max"])
    for product in PRODUCTS:
        vals = price_values.get(product)
        if vals:
            print(f"  {product:>12}: min={min(vals):>6.0f} max={max(vals):>6.0f}")

    print("\n=== animal escapes / plant deaths (per cohort) ===")
    for cohort in cohorts:
        n_escapes = sum(len(t["animal_escapes"]) for rec in records if rec["cohort"] == cohort for t in rec["teams"])
        n_deaths = sum(len(t["plant_deaths"]) for rec in records if rec["cohort"] == cohort for t in rec["teams"])
        n_team_seasons = sum(len(rec["teams"]) for rec in records if rec["cohort"] == cohort)
        print(f"  {cohort:>8}: {n_escapes} escapes, {n_deaths} deaths across {n_team_seasons} team-seasons")

    print("\n=== quadrant unlock day (median, per cohort) ===")
    for cohort in cohorts:
        for quad in ("NE", "SW", "SE"):
            vals = [
                t["quadrant_unlock_days"][quad]
                for rec in records if rec["cohort"] == cohort
                for t in rec["teams"] if quad in t["quadrant_unlock_days"]
            ]
            if vals:
                print(f"  {cohort:>8} {quad}: median day {percentile(vals, 0.5):.1f} (n={len(vals)})")

    verdict = shop_schedule_invariant(records)
    print(f"\n=== shop-schedule invariance: {'CONFIRMED exogenous' if verdict['invariant'] else 'VARIES - not exogenous'} ===")


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes-dir", default=_DEFAULT_EPISODES_DIR, help="recursive glob root for raw replay JSON files")
    parser.add_argument("--episode", action="append", default=[], help="literal path to one raw replay JSON file (repeatable)")
    parser.add_argument("--at-hour", type=int, default=MID_DAY_HOUR)
    parser.add_argument("--self-play", type=int, default=0, help="number of self-play seeds to add as an 'ours' cohort")
    parser.add_argument("--save-records", default=_DEFAULT_RECORDS_DIR, help="directory to write the parsed structured extract to")
    parser.add_argument("--load-records", default=None, help="skip parsing raw replays; reload the structured extract from this directory/index.jsonl instead")
    parser.add_argument("--json", default=None, help="write the full computed rows() to this path")
    parser.add_argument("--fields", default="", help="comma-separated dotted field list to summarize additionally, e.g. board.animals.COW,board.plants.WHEAT")
    args = parser.parse_args()

    if args.load_records:
        records = load_saved_records(args.load_records)
    else:
        paths = list(args.episode)
        if args.episodes_dir and os.path.isdir(args.episodes_dir):
            paths.extend(sorted(glob.glob(os.path.join(args.episodes_dir, "**", "*.json"), recursive=True)))
        records = list(iter_episode_records(paths, at_hour=args.at_hour, cohort="top"))
        if records:
            save_records(records, args.save_records)
            print(f"saved {len(records)} record(s) to {args.save_records}")

    if args.self_play:
        records.extend(self_play_records(args.self_play, at_hour=args.at_hour))

    if not records:
        print("no episode records to report on (no --episode/--episodes-dir match, no --load-records, no --self-play)")
        return

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    _print_report(records, fields)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(rows(records), f, indent=2)
        print(f"\nwrote full rows() to {args.json}")


if __name__ == "__main__":
    _main()
