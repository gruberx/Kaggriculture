import sys, os, json
sys.path.insert(0, "tools")
from multiprocessing import Pool
import harness, tuning
from kaggle_environments import make
from kagg.policy.params import DEFAULT_PARAMS as SHIPPED
NEW = dict(SHIPPED, day_plan_harvest_replant_aware=True)
W = os.environ["CLAUDE_JOB_DIR"] + "/tmp/wd5"; os.makedirs(W, exist_ok=True)
VARS = {"shipped": SHIPPED, "replant-aware": NEW}
OLD = json.load(open("/tmp/t846/old_params.json"))
PATH = {k: tuning.write_candidate_agent(v, W) for k, v in VARS.items()}
PATH["old default"] = tuning.write_candidate_agent(OLD, W)
def job(a):
    n, o, s = a
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": s}, debug=False)
    env.run([PATH[n], o if o in ("starter", "pass") else PATH[o]]); return n, o, s, env.steps[-1][0].reward
if __name__ == "__main__":
    seeds = list(range(1, 21))
    with Pool(4) as p: res = p.map(job, [(n, o, s) for n in VARS for o in ("starter", "pass", "old default") for s in seeds])
    m = {(n, o, s): r for n, o, s, r in res}
    for o in ("starter", "pass", "old default"):
        base = [m[("shipped", o, s)] for s in seeds]
        print(f"--- vs {o} ({len(seeds)} seeds), our final money")
        for n in VARS:
            v = [m[(n, o, s)] for s in seeds]; d = [a - b for a, b in zip(v, base)]
            print(f"   {n:14} mean {sum(v)/len(v):>7.0f}  vs shipped: {sum(d)/len(d):>+7.0f} ({100*sum(d)/sum(base):+.1f}%), better on {sum(1 for x in d if x>0)}/{len(d)}", flush=True)
    blocks = harness.load_seed_blocks()
    b = harness.run_block(PATH["replant-aware"], PATH["shipped"], list(blocks.tuning_seeds), jobs=None)
    print(f"\narena replant-aware vs shipped, {b.n} working seeds: {b.wins_a}W/{b.wins_b}L/{b.ties}T win_rate={b.win_rate_a:.3f} interval={b.wilson_interval_a}", flush=True)
    b2 = harness.run_block(PATH["replant-aware"], PATH["old default"], list(blocks.tuning_seeds), jobs=None)
    print(f"arena replant-aware vs OLD default: {b2.wins_a}W/{b2.wins_b}L/{b2.ties}T win_rate={b2.win_rate_a:.3f}", flush=True)
    b3 = harness.run_block(PATH["shipped"], PATH["old default"], list(blocks.tuning_seeds), jobs=None)
    print(f"arena shipped vs OLD default (reference): {b3.wins_a}W/{b3.wins_b}L/{b3.ties}T win_rate={b3.win_rate_a:.3f}", flush=True)
