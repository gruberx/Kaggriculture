"""T8.70 follow-up (the user's own request): for every seed in both blocks,
how much of what each farm actually SOLD matches what the town's unlocked
shops demand, comparing the M1 candidate (crop_shop_unlock_forecast_aware=
True) against today's shipped baseline - both playing the SAME episode
(paired head-to-head), so both see the exact same shop-unlock schedule.

Reuses daily_dashboard.order_fill (exact SELL-fill accounting, diffing the
real engine's own shed counters) and kagg.gamelib.constants.SHOPS (shop ->
demanded-products mapping) - no new production-tracking logic invented.

Not part of the committed test suite.
"""
import json
import multiprocessing
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daily_dashboard  # noqa: E402
import harness  # noqa: E402
import tuning  # noqa: E402
from kaggle_environments import make  # noqa: E402
from kagg.gamelib.constants import SHOPS  # noqa: E402
from kagg.policy.params import DEFAULT_PARAMS  # noqa: E402

W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "wd870_shopmatch")
os.makedirs(W, exist_ok=True)

_EPISODE_STEPS = 720


def _demanded_products(unlocked_shops: list) -> set:
    demanded = set()
    for shop in unlocked_shops:
        demanded.update(SHOPS.get(shop, []))
    return demanded


def _sold_units_per_product(steps, team: int) -> dict:
    """Total units of each product `team` actually SOLD over the whole
    episode - order_fill's exact SELL-fill accounting (see its own
    docstring: diffs the real engine's own shed counter, not an estimate)."""
    sold: dict[str, int] = {}
    for t in range(1, len(steps)):
        prev_private = steps[t - 1][team].observation["private"]
        cur_private = steps[t][team].observation["private"]
        prev_farm = steps[t - 1][0].observation["farms"][team]
        cur_farm = steps[t][0].observation["farms"][team]
        action = steps[t][team].action
        for order in (action.get("market", []) if action else []):
            if order[0] != "SELL":
                continue
            op, _requested, filled = daily_dashboard.order_fill(order, prev_private, cur_private, prev_farm, cur_farm)
            if filled > 0:
                item = order[1]
                sold[item] = sold.get(item, 0) + filled
    return sold


def _analyze_one(args):
    seed, candidate_agent, baseline_agent = args
    env = make("kaggriculture", configuration={"episodeSteps": _EPISODE_STEPS, "seed": seed}, debug=False)
    env.run([candidate_agent, baseline_agent])
    steps = env.steps
    unlocked_shops = steps[-1][0].observation["town"]["unlocked_shops"]
    demanded = _demanded_products(unlocked_shops)

    result = {"seed": seed, "unlocked_shops": unlocked_shops, "demanded_products": sorted(demanded)}
    for label, team in (("candidate", 0), ("baseline", 1)):
        sold = _sold_units_per_product(steps, team)
        total = sum(sold.values())
        matched = sum(q for p, q in sold.items() if p in demanded)
        top_product = max(sold, key=sold.get) if sold else None
        result[label] = {
            "sold": sold,
            "total_units": total,
            "matched_units": matched,
            "match_ratio": (matched / total) if total else None,
            "top_product": top_product,
            "top_product_matches": (top_product in demanded) if top_product else None,
            "final_money": steps[-1][team].reward,
        }
    return result


_VARIANTS = {
    "m1": {"crop_shop_unlock_forecast_aware": True},
    "m2": {"crop_own_future_supply_aware": True},
    "m1m2": {"crop_shop_unlock_forecast_aware": True, "crop_own_future_supply_aware": True},
}

if __name__ == "__main__":
    variant = sys.argv[1] if len(sys.argv) > 1 else "m1"
    overrides = _VARIANTS[variant]

    blocks = harness.load_seed_blocks()
    seeds = list(blocks.tuning_seeds) + list(blocks.holdout_seeds)

    candidate_agent = tuning.write_candidate_agent(dict(DEFAULT_PARAMS, **overrides), W)
    baseline_agent = tuning.write_candidate_agent(DEFAULT_PARAMS, W)

    jobs = harness._default_jobs()
    print(f"variant: {variant} {overrides}, seeds: {len(seeds)}, jobs: {jobs}", flush=True)
    args = [(s, candidate_agent, baseline_agent) for s in seeds]
    with multiprocessing.Pool(processes=jobs) as pool:
        results = []
        for i, r in enumerate(pool.imap(_analyze_one, args)):
            results.append(r)
            print(f"  [{i + 1}/{len(seeds)}] seed {r['seed']} done", flush=True)

    out_path = os.path.join(W, f"results_{variant}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"wrote {out_path}", flush=True)
