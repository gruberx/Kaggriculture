"""One tile, one product, 30 days: costs, tile-servicing action counts, revenue, profit.

The user's request (2026-09-21): for every product, assume a single tile is used only for that product
in continuous production for 30 days (days 0..29), no fertilizer used on plants, harvest only when the
product is at its maximum (fully ripe / animal at its `max_held` cap), fertilizer from animals counted
as side income, and all prices held at their starting values (no price walk).

Everything about timing comes from the real engine's own functions (kaggle_environments'
kaggriculture.py: `_apply_unit_action`, `_decay_plants`, `_daily_refresh_plants`,
`_daily_refresh_animals`), not from hand arithmetic: a single-crop cycle is brute-forced over watering
schedules and the cheapest schedule reaching the highest yield at the earliest harvest day is kept.

Not counted as actions: BUY_SEED / BUY_ANIMAL / BUY_PRODUCT / SELL orders, PICKUP, carrying, walking.
Not part of the committed test suite - a reference-generation script.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import kaggle_environments.envs.kaggriculture.kaggriculture as K  # noqa: E402
from kagg.gamelib.constants import ANIMALS, CROPS, MARKET_PARAMS  # noqa: E402

DAYS = 30
TPD = 24
PRICE = {p: MARKET_PARAMS[p]["base"] for p in MARKET_PARAMS}  # starting price = base at inventory I0


def _fresh():
    # A 1x1 farm: the tile-servicing rules do not depend on the rest of the board (shed-adjacency
    # only matters for PICKUP/DROP, which are not counted here).
    farm = {"money": 10**9, "tiles": [[None]], "farmer": [0, 0], "hands": [], "hires_today": 0}
    return farm, K._new_private()


def _act(farm, private, day, action):
    K._apply_unit_action(farm, private, 0, action, 10, day, TPD, 100)


def _end_of_hour(farm, day, hour):
    step = day * TPD + hour
    K._decay_plants(farm, step)
    if hour == TPD - 1:
        K._daily_refresh_plants(farm, day, TPD)
        K._daily_refresh_animals(farm, day)


def _tile(farm):
    return farm["tiles"][0][0]


def _run_day(farm, day, private, water):
    """Hour 1: optional WATER; then the rest of the day's steps (decay ticks + midnight refresh)."""
    for hour in range(TPD):
        if hour == 1 and water:
            _act(farm, private, day, ["WATER"])
        _end_of_hour(farm, day, hour)


def best_crop_cycle(crop, max_day=18, target_day=None):
    """Search every survivable watering schedule with the real engine rules.

    Ranking: highest yield, then earliest harvest day, then fewest waterings. With `target_day` only a
    harvest on exactly that day counts (the unfinished last cycle harvested on the final day).
    """
    import copy

    best = [None]

    def visit(day, farm, private, waters):
        for water in (True, False):
            f, pr = copy.deepcopy(farm), copy.deepcopy(private)
            w = waters + ((day,) if water else ())
            if water:
                _act(f, pr, day, ["WATER"])
            probe, ppr = copy.deepcopy(f), copy.deepcopy(pr)
            _act(probe, ppr, day, ["HARVEST"])  # harvest is allowed on the day, after that day's watering
            units = ppr["inventories"][0].get(crop, 0)
            if units > 0 and (target_day is None or day == target_day):
                key = (-units, day, len(w))
                if best[0] is None or key < best[0][0]:
                    best[0] = (key, units, day, w)
            for hour in range(TPD):
                _end_of_hour(f, day, hour)
            tile = _tile(f)
            if day < (max_day if target_day is None else target_day) and isinstance(tile, dict) and tile.get("kind") == "PLANT":
                visit(day + 1, f, pr, w)

    farm, private = _fresh()
    private["seeds"][crop] = 1
    _act(farm, private, 0, ["PLANT", crop])
    visit(0, farm, private, ())
    if best[0] is None:
        return 0, target_day, ()
    _, units, h, w = best[0]
    return units, h, w


FERT_COST = 20  # the user's assumption: one unit of fertilizer costs 20


def _tile_key(tile):
    return tuple(sorted(tile.items()))


def best_crop_cycle_fert(crop, fert_cost=FERT_COST, max_day=18, multi_harvest=True, objective="rate"):
    """Best watering + FERTILIZE (+ intermediate harvests) schedule for one plant, by profit per cycle day.

    Dynamic programming over days with the real engine rules. A state is (tile dict, units already
    harvested); for each state only the Pareto-best (fertilizers, waterings, harvests) counts are kept.
    FERTILIZE (active on the day and the next two) is applied before WATER on the same day. On any day a
    final harvest ends the cycle: profit = units * price - seed - fert_cost * fertilizers, rate = profit /
    that day. An ongoing plant (tomato, strawberry) holds at most `max_yield` units at once, so with
    `multi_harvest` it may also be harvested in the middle of the cycle and keep producing.
    Ranking: highest rate, then fewest actions. With objective="units": most product first, then rate, then
    fewest actions (the maximum a plant can yield with fertilizer).
    """
    import copy

    price, seed, ongoing = PRICE[crop], CROPS[crop]["seed"], CROPS[crop]["ongoing"]
    farm, private = _fresh()
    private["seeds"][crop] = 1
    _act(farm, private, 0, ["PLANT", crop])
    t0 = _tile(farm)
    frontier = {(_tile_key(t0), 0): (t0, 0, [(0, 0, 0, ())])}
    best = None

    def _farm(tile, fert):
        f = {"money": 10**9, "tiles": [[copy.deepcopy(tile)]], "farmer": [0, 0], "hands": [], "hires_today": 0}
        pr = K._new_private()
        pr["inventories"][0]["FERTILIZER"] = 1 if fert else 0
        return f, pr

    def _add(nxt, tile, taken, cand):
        entry = nxt.setdefault((_tile_key(tile), taken), (tile, taken, []))
        lst = entry[2]
        if any(o[0] <= cand[0] and o[1] <= cand[1] and o[2] <= cand[2] for o in lst):
            return
        lst[:] = [o for o in lst if not (cand[0] <= o[0] and cand[1] <= o[1] and cand[2] <= o[2])] + [cand]

    for day in range(max_day + 1):
        nxt = {}
        for tile, taken, pareto in frontier.values():
            for fert in (0, 1):
                for water in (0, 1):
                    f, pr = _farm(tile, fert)
                    if fert:
                        _act(f, pr, day, ["FERTILIZE"])
                    if water:
                        _act(f, pr, day, ["WATER"])
                    probe, ppr = copy.deepcopy(f), copy.deepcopy(pr)
                    _act(probe, ppr, day, ["HARVEST"])
                    units = ppr["inventories"][0].get(crop, 0)
                    for nf, nw, nh, sched in pareto:
                        tag = sched + (((day, "F"),) if fert else ()) + (((day, "W"),) if water else ())
                        if units > 0 and day >= 1:
                            total = taken + units
                            profit = total * price - seed - fert_cost * (nf + fert)
                            actions = 1 + (nw + water) + (nf + fert) + (nh + 1) + (1 if ongoing else 0)
                            key = (-profit / day, actions) if objective == "rate" else (-total, -profit / day, actions)
                            if best is None or key < best[0]:
                                best = (key, total, day, nf + fert, nw + water, nh + 1, tag + ((day, "H"),), profit)
                    variants = [(f, pr, taken, 0, ())]
                    if ongoing and multi_harvest and units > 0 and day >= 1:
                        f2, pr2 = copy.deepcopy(f), copy.deepcopy(pr)
                        _act(f2, pr2, day, ["HARVEST"])
                        variants.append((f2, pr2, taken + pr2["inventories"][0].get(crop, 0), 1, ((day, "H"),)))
                    for fv, pv, tk, dh, htag in variants:
                        for hour in range(TPD):
                            _end_of_hour(fv, day, hour)
                        t2 = _tile(fv)
                        if day < max_day and isinstance(t2, dict) and t2.get("kind") == "PLANT":
                            for nf, nw, nh, sched in pareto:
                                tag = sched + (((day, "F"),) if fert else ()) + (((day, "W"),) if water else ()) + htag
                                _add(nxt, t2, tk, (nf + fert, nw + water, nh + dh, tag))
        frontier = nxt
    _, units, h, ferts, waters, harvests, sched, profit = best
    return {"units": units, "days": h, "ferts": ferts, "waters": waters, "harvests": harvests, "schedule": sched,
            "profit": profit, "fert_days": tuple(d for d, k in sched if k == "F"),
            "water_days": tuple(d for d, k in sched if k == "W"), "harvest_days": tuple(d for d, k in sched if k == "H")}


def crop_report(crop):
    cd = CROPS[crop]
    units, h, water_days = best_crop_cycle(crop)
    cycles = (DAYS - 1) // h  # cycle k is planted on day k*h and harvested on day (k+1)*h <= 29
    rest = (DAYS - 1) - cycles * h  # days left after the last full harvest
    # The unfinished last cycle is planted only if what it holds on the final day (collected and sold
    # then) is worth more than its seed.
    p_units, _, p_waters = best_crop_cycle(crop, target_day=rest) if rest >= 1 else (0, rest, ())
    partial = p_units * PRICE[crop] > cd["seed"]
    n_plant = cycles + (1 if partial else 0)
    digs = (n_plant - 1) if cd["ongoing"] else 0  # an ongoing plant is not cleared by HARVEST
    n_water = cycles * len(water_days) + (len(p_waters) if partial else 0)
    n_units = cycles * units + (p_units if partial else 0)
    per_cycle = units * PRICE[crop] - cd["seed"]
    return {
        "name": crop, "kind": "crop", "cycle_days": h, "cycles": cycles, "units_per_cycle": units,
        "water_days": water_days, "partial_units": p_units if partial else 0, "cost_seed": n_plant * cd["seed"],
        "cost_animal": 0, "cost_feed": 0, "care": 0, "plant": n_plant, "water": n_water, "build": 0, "feed": 0,
        "dig": digs, "harvest": n_plant, "collect": 0, "units": n_units, "product": crop,
        "product_value": n_units * PRICE[crop], "fertilizer_units": 0, "fertilizer_value": 0,
        "ideal_per_day": per_cycle / h,
    }


def _animal_run(animal, days=DAYS, collect_leftover=True, care=True, harvest_at=None):
    ad = ANIMALS[animal]
    farm, private = _fresh()
    inv = private["inventories"][0]
    counts = dict(build=0, place=0, feed=0, collect=0, harvest=0, care=0)
    fert = units = 0
    first_full = None
    leftover = 0
    last_cap_day = None
    for day in range(days):
        for hour in range(TPD):
            if day == 0 and hour == 0:
                _act(farm, private, day, ["BUILD_COOP" if ad["structure"] == "COOP" else "BUILD_PASTURE"])
                counts["build"] += 1
            if day == 0 and hour == 1:
                inv[animal] = 1
                _act(farm, private, day, ["PLACE", animal]); counts["place"] += 1
            tile = _tile(farm)
            if hour == 2 and isinstance(tile, dict) and "animal" in tile:
                if care and day <= days - 2:
                    # CARE only counts on a day the animal is also fed, and is paid out at the next
                    # production event; on the last day it could not be collected any more.
                    inv["WHEAT"] = inv.get("WHEAT", 0) + 1
                    _act(farm, private, day, ["FEED"]); counts["feed"] += 1
                    _act(farm, private, day, ["CARE"]); counts["care"] += 1
                elif tile["consecutive_unfed"] >= 1 and day < days - 1:
                    # feed only when the second missed day would make the animal escape before the end
                    inv["WHEAT"] = inv.get("WHEAT", 0) + 1
                    _act(farm, private, day, ["FEED"]); counts["feed"] += 1
                if tile["fertilizer_available"]:
                    _act(farm, private, day, ["COLLECT_FERTILIZER"]); counts["collect"] += 1
                if tile["yield_units"] >= (harvest_at or ad["max_held"]):  # default: only at the accumulation cap
                    _act(farm, private, day, ["HARVEST"]); counts["harvest"] += 1
                    last_cap_day = day
                    if first_full is None:
                        first_full = day
                if day == days - 1 and collect_leftover and tile["yield_units"] > 0:
                    leftover = tile["yield_units"]  # collected and sold on the final day
                    _act(farm, private, day, ["HARVEST"]); counts["harvest"] += 1
            _end_of_hour(farm, day, hour)
    units = inv.get(ad["product"], 0)
    fert = inv.get("FERTILIZER", 0)
    tile = _tile(farm)
    escaped = not (isinstance(tile, dict) and "animal" in tile)
    return {
        "name": animal, "kind": "animal", "cycle_days": None, "cycles": counts["harvest"],
        "units_per_cycle": ad["max_held"], "water_days": (), "partial_units": leftover, "cost_seed": 0,
        "cost_animal": ad["cost"], "cost_feed": counts["feed"] * PRICE["WHEAT"], "plant": 0, "water": 0,
        "build": counts["build"] + counts["place"], "feed": counts["feed"], "care": counts["care"], "dig": 0,
        "harvest": counts["harvest"], "collect": counts["collect"], "units": units, "product": ad["product"],
        "product_value": units * PRICE[ad["product"]], "fertilizer_units": fert,
        "fertilizer_value": fert * PRICE["FERTILIZER"], "leftover_units": leftover, "first_full": first_full,
        "escaped": escaped, "last_cap_day": last_cap_day, "days": days,
    }


def animal_report(animal, days=DAYS, collect_leftover=True, care=True):
    """Harvest as late as possible without losing production.

    Harvesting strictly at the `max_held` cap wastes output when one production interval with CARE adds
    more than the room left (a sheep adds 4 wool per interval against a cap of 6), so the harvest
    threshold is picked per animal: most profit first, then fewest actions.
    """
    runs = []
    for at in range(1, ANIMALS[animal]["max_held"] + 1):
        r = _animal_run(animal, days, collect_leftover, care, harvest_at=at)
        _, _, profit, actions = summarize(r)
        runs.append(((-profit, actions), at, r))
    _, at, best = min(runs, key=lambda x: x[0])
    best["harvest_at"] = at
    return best


def animal_ideal_per_day(animal):
    """Profit per day if production ran past day 29 until the in-progress cycle completes.

    The horizon is the first day count >= 30 whose last day is a harvest at the accumulation cap
    (days counted like the 30-day window: purchase day 0 .. last harvest day).
    """
    for days in range(DAYS, 120):
        r = animal_report(animal, days=days, collect_leftover=False)
        if r["last_cap_day"] == days - 1:
            _, _, profit, _ = summarize(r)
            return profit / days, days
    raise RuntimeError(animal)


def summarize(r):
    cost = r["cost_seed"] + r["cost_animal"] + r["cost_feed"]
    revenue = r["product_value"] + r["fertilizer_value"]
    actions = r["plant"] + r["water"] + r["build"] + r["feed"] + r["care"] + r["dig"] + r["harvest"] + r["collect"]
    return cost, revenue, revenue - cost, actions


def crop_cycle_report(crop):
    """One life of one plant: planting to harvest (an ongoing plant is also dug out to free the tile)."""
    cd = CROPS[crop]
    units, h, water_days = best_crop_cycle(crop)
    dig = 1 if cd["ongoing"] else 0
    cost = cd["seed"]
    revenue = units * PRICE[crop]
    actions = 1 + len(water_days) + dig + 1
    return {
        "name": crop, "cycle_days": h, "cost_seed": cost, "cost_feed": 0, "plant": 1, "water": len(water_days),
        "build": 0, "feed": 0, "care": 0, "dig": dig, "harvest": 1, "collect": 0, "actions": actions,
        "units": units, "product_value": revenue, "fertilizer_value": 0, "profit": revenue - cost,
    }


def crop_fert_cycle_report(crop, objective="rate"):
    """One plant life with the most profitable FERTILIZE + WATER schedule (cost of one fertilizer = 20)."""
    cd = CROPS[crop]
    r = best_crop_cycle_fert(crop, objective=objective)
    dig = 1 if cd["ongoing"] else 0
    return {
        "name": crop, "cycle_days": r["days"], "cost_seed": cd["seed"], "cost_fert": FERT_COST * r["ferts"],
        "plant": 1, "water": r["waters"], "fert": r["ferts"], "dig": dig, "harvest": r["harvests"],
        "actions": 1 + r["waters"] + r["ferts"] + dig + r["harvests"], "units": r["units"],
        "product_value": r["units"] * PRICE[crop], "profit": r["profit"], "fert_days": r["fert_days"],
        "water_days": r["water_days"], "harvest_days": r["harvest_days"],
    }


def main_fert(objective="rate"):
    print(f"[objective: {objective}]")
    print("product|cycle_days|cost_seed|cost_fert|plant|water|fertilize|dig|harvest|actions|units|product_value|"
          "profit|profit/action|profit/day per cycle|fertilize on day|water on days|harvest on days")
    for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON"):
        r = crop_fert_cycle_report(c, objective)
        print(f"{r['name']}|{r['cycle_days']}|{r['cost_seed']}|{r['cost_fert']}|{r['plant']}|{r['water']}|{r['fert']}|"
              f"{r['dig']}|{r['harvest']}|{r['actions']}|{r['units']}|{r['product_value']}|{r['profit']}|"
              f"{r['profit'] / r['actions']:.1f}|{r['profit'] / r['cycle_days']:.1f}|{r['fert_days']}|{r['water_days']}|{r['harvest_days']}")


def main():
    """Per-life table: plants = one planting-to-harvest cycle; animals = a 30-day cycle."""
    rows = [crop_cycle_report(c) for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")]
    for a in ("GOOSE", "COW", "SHEEP"):
        r = animal_report(a)
        cost, revenue, profit, actions = summarize(r)
        rows.append({
            "name": a, "cycle_days": DAYS, "cost_seed": r["cost_animal"], "cost_feed": r["cost_feed"],
            "plant": 0, "water": 0, "build": r["build"], "feed": r["feed"], "care": r["care"], "dig": 0,
            "harvest": r["harvest"], "collect": r["collect"], "actions": actions, "units": r["units"],
            "product_value": r["product_value"], "fertilizer_value": r["fertilizer_value"], "profit": profit,
        })
    print("product|cycle_days|cost_seed+animal|cost_feed|cost_total|plant|water|build+place|feed|care|dig|harvest|"
          "collect_fert|actions|units|product_value|fert_value|profit|profit/action|profit/day per cycle")
    for r in rows:
        total = r["cost_seed"] + r["cost_feed"]
        print(f"{r['name']}|{r['cycle_days']}|{r['cost_seed']}|{r['cost_feed']}|{total}|{r['plant']}|{r['water']}|"
              f"{r['build']}|{r['feed']}|{r['care']}|{r['dig']}|{r['harvest']}|{r['collect']}|{r['actions']}|"
              f"{r['units']}|{r['product_value']}|{r['fertilizer_value']}|{r['profit']}|"
              f"{r['profit'] / r['actions']:.1f}|{r['profit'] / r['cycle_days']:.1f}")


if __name__ == "__main__":
    main()
    print()
    main_fert()
    print()
    main_fert("units")
