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


def main():
    rows = [crop_report(c) for c in ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON")]
    rows += [animal_report(a) for a in ("GOOSE", "COW", "SHEEP")]
    print("product|cycle_days|cost_seed+animal|cost_feed|plant|water|build+place|feed|care|dig|harvest|collect_fert|actions|"
          "units|product_value|fert_value|profit|profit/day|profit/action|ideal/day(horizon)|final-day units")
    for r in rows:
        cost, revenue, profit, actions = summarize(r)
        if r["kind"] == "crop":
            ideal = f"{r['ideal_per_day']:.1f}"
        else:
            v, d = animal_ideal_per_day(r["name"])
            ideal = f"{v:.1f} ({d} d)"
        print(f"{r['name']}|{r['cycle_days']}|{r['cost_seed'] + r['cost_animal']}|{r['cost_feed']}|"
              f"{r['plant']}|{r['water']}|{r['build']}|{r['feed']}|{r['care']}|{r['dig']}|{r['harvest']}|{r['collect']}|{actions}|"
              f"{r['units']}|{r['product_value']}|{r['fertilizer_value']}|{profit}|{profit / DAYS:.1f}|"
              f"{profit / actions:.1f}|{ideal}|{r['partial_units']}")


if __name__ == "__main__":
    main()
