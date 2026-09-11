# SPEC: `harness`

Part of the [capability map](SPEC.md#capability-map). Depends on: `diskguard` (guards the
held-out-invocation log below). Dev-only, does not ship.

## Objective

Give every other module (`tuning` most directly, but also ad-hoc comparisons during `policy`
development) a way to answer "did this change make the agent better?" that isn't fooled by the
two measurement traps the competition forum has already documented. Getting this wrong wastes the
one resource we can't buy back before September 30: time.

## The three requirements (non-negotiable, from forum evidence)

Source: [thread 740792](https://www.kaggle.com/competitions/kaggriculture/discussion/740792),
reply by Syed Asad Ali. These are requirements, not suggestions — every comparison the harness
produces must satisfy all three or it doesn't get trusted.

1. **Paired seats.** Every seed is played twice — once as player 0, once as player 1 — and the
   pair is collapsed into a single result *before* any statistic is computed on it. A raw list of
   per-game outcomes double-counts seat advantage as sample size.
2. **A held-out seed block.** A fixed, disjoint block of seeds that no tuning decision ever looks
   at while iterating. The author measured the same change score +2,301 on one "fresh" seed block
   and −1,259 on another, purely from having selected on the first. `tuning` may burn through the
   working block freely; only the held-out block's number goes into a go/no-go decision.
3. **Town-shop-reroll detection.** `_spawn_weeds` (`kaggriculture.py:836`) draws one RNG value per
   empty tile *on both farms* every end-of-day refresh, and town shop unlocks are drawn from the
   same `random.Random` stream (see `_initialize`/town setup). Our own moves change which tiles are
   empty when, which perturbs later RNG draws, which can reroll the town shop sequence relative to
   a recorded baseline game. When comparing live play against a *recorded* replay/opponent
   (rather than two live agents), split results into "shop sequence preserved" vs "shop sequence
   rerolled" and report both — collapsing them hides which number is real. Reported effect from the
   forum: 78% win rate in rerolled games vs. 40% in preserved ones against the top 10; only the
   40% was trustworthy for that author's actual matchup.

## Interface

```python
# tools/harness.py
def run_paired(agent_a, agent_b, seed: int, episode_steps: int = 720) -> PairedResult:
    """Play `seed` twice (a as player 0, then a as player 1) via
    kaggle_environments.make("kaggriculture", ...).run([...]), and collapse
    the pair into one PairedResult: which side (a/b/tie) came out ahead in
    total money-across-both-seatings, plus both raw episode records."""

def run_block(agent_a, agent_b, seeds: list[int], jobs: int | None = None) -> BlockResult:
    """run_paired for every seed, parallelized across `jobs` worker processes
    (default: os.cpu_count() - reserve, see SPEC.md Environment — never a
    hardcoded core count). Returns win/loss/tie counts and a Wilson score
    interval on the win rate, not just a point estimate."""

def detect_shop_reroll(replay_path: str, live_town_log: list[str]) -> bool:
    """Compare the recorded episode's town shop unlock sequence against the
    live run's; used only when the opponent side is a recorded replay rather
    than a second live agent."""
```

`SeedBlocks` is a small config object (`tuning_seeds`, `holdout_seeds`) checked into
`params/seed_blocks.json` (not `.gitignore`d — reproducibility requires the exact seeds used) so
that "which seeds are held out" is itself version-controlled, not tribal knowledge.

## Performance

Stock `kaggle_environments.make("kaggriculture").run(...)` measured at ~1.3–1.4s per 720-turn
episode on this machine (see `SPEC.md` "Why `fastsim` isn't built"). `run_block` parallelizes
across processes (the environment interpreter is not thread-safe / releases no GIL benefit worth
counting on); with `jobs=auto` defaulting to `os.cpu_count() - 2`, a 100-seed paired block (200
episodes) costs well under 2 minutes at 4 CPUs and proportionally less once the container's CPU
quota is raised. Never hardcode a job count or assume a specific core count — read it at runtime.

## Testing

- `run_paired` against two copies of `"pass"`: result must be a tie on every seed (symmetric
  matchup, deterministic given a seed).
- `run_paired` against `"starter"` vs `"random"`: `starter` must win regardless of which seat it's
  assigned, confirming seat-pairing doesn't silently favor one side.
- Wilson interval computation checked against a known closed-form example (e.g. 60/100 wins → a
  specific published interval), not just "runs without error."
- `detect_shop_reroll` checked against a replay fixture with a deliberately perturbed town-unlock
  sequence.

## Boundaries specific to this module

- Dev-only: may depend on `kaggle_environments`, `multiprocessing`, `pytest`.
- Never let a `tuning` decision read the held-out block's result before the decision is made —
  enforce this with a CLI flag (`--holdout`) that is off by default and requires an explicit,
  logged invocation (via `diskguard.ensure_budget()` before the write, like every `data/arena/`
  write — see `SPEC-diskguard.md`), so "did we peek" is answerable from `data/arena/` logs later.
