# SPEC: Kaggriculture agent

## Objective

Build an agent for the Kaggle simulation competition
[Kaggriculture](https://www.kaggle.com/competitions/kaggriculture) (host: Kaggle, sponsor: Google
LLC; prize pool $50,000 = 10 × $5,000). Two players each run a 10×10 farm across a 720-turn
season (24 turns/day × 30 days); whoever has more money in the bank at the end wins. Our agent
must consistently beat the field to land in the top 10 of the final Bradley–Terry leaderboard.

**Approach:** a hand-written economic planner (not RL — see "Why not RL" below) whose behavior is
governed by a tunable parameter vector, refined through self-play on a local arena. Correctness of
the planner's internal model of the game is checked against the real, open-source rules
(`kaggle_environments/envs/kaggriculture/kaggriculture.py`) rather than assumed.

**Success criteria:**
- Agent survives 720 turns against arbitrary opponents without ever crashing or exceeding the
  turn/episode time budget (see `SPEC-agent.md`) — a technical loss is never acceptable.
- Measured (not assumed) win rate ≥ 60% against each of: `starter` baseline, the public
  `yhay81/shop-router-0909` notebook, and a snapshot of our own previous-best agent, under the
  paired-seed arena protocol in `SPEC-harness.md`.
- Final submission is made and confirmed active before the September 30, 2026 deadline.

**Timeline:** entry deadline September 23, 2026 (must accept rules / Join before this date); final
submission September 30, 2026; leaderboard finalized after ~2 weeks of catch-up games (~mid
October).

## Why not RL

Kaggle's episode runner is not the constraint — it runs the full `gcr.io/kaggle-images/python:v163`
image (numpy, torch included) and allows submissions up to 20 GB, so inference of a small trained
model would run in microseconds against the turn budget. The real constraint is training cost
relative to what we have: no GPU, CPU-only, and roughly three weeks until the final submission
deadline. Competition forum threads with concrete numbers:

- [Thread 740022](https://www.kaggle.com/competitions/kaggriculture/discussion/740022): end-to-end
  RL on an RTX 3090, 350M environment steps (<10% of the author's planned curriculum), and the
  trained agent *still* trails a static heuristic agent (~90K vs 122K final money).
- [Thread 740792](https://www.kaggle.com/competitions/kaggriculture/discussion/740792): flat PPO
  learns mechanics but "does not form a coherent economy across a full match"; the thread's own
  negative results (see below) further undercut naive approaches.

The one ML-flavored technique that fits our budget and is planned as a later `tuning` milestone is
**search-generated value targets**: from a real game state, branch the (real or self-implemented)
simulator across a handful of complete strategic alternatives, and train a lightweight selector on
the outcomes. This needs no GPU and no RL loop — see `SPEC-tuning.md`.

## Capability map

| id | Responsibility | Depends on | Ships in submission |
|---|---|---|---|
| `harness` | Run episodes against `kaggle_environments` directly (no rewritten simulator — see below), the paired-seed evaluation protocol, seed blocks incl. a held-out block, town-shop-reroll detection, Wilson-interval win rates, per-turn timing profiler | `diskguard` | no |
| `gamelib` | Pure economic model used by the agent at runtime: price curve, harvest/schedule forecasting, tile-value estimation, distances, shed accounting. Verified by property tests against the real `kaggriculture.py` | — | **yes** |
| `agent` | Submission contract: `main.py` exposing `agent(obs)`, observation parsing, action assembly/validation, a time-budget guard, a blanket `try/except` fallback | `gamelib` | **yes** |
| `policy` | Decision logic: daily strategic layer (portfolio, land, hiring), per-turn task layer (task list + greedy unit assignment), per-turn market layer (sell thresholds, ≤10 orders/turn) | `agent` | **yes** |
| `tuning` | Parameter vector, coordinate-ascent search, opponent league, regression gate; stage 2 is search-generated value targets | `harness`, `policy`, `diskguard` | no |
| `ops` | Kaggle MCP: bundle `main.py` into `submission.tar.gz`, submit, poll status, pull episodes/replays/logs, pull the daily top-episodes dataset, monitor the competition forum | `agent`, `diskguard` | no |
| `diskguard` | Application-level disk budget (2.5 TB cap on this project's total footprint, since the shared volume offers no filesystem quota inside this container): usage accounting, oldest-first eviction of re-downloadable data, hard refusal rather than silent overrun — see `SPEC-diskguard.md` | — | no |

Build order: `harness` ∥ `gamelib` ∥ `diskguard` → `agent` → `policy` → (`tuning` ∥ `ops`).

**Note on `fastsim`:** the capability map originally reserved an id for a from-scratch rewrite of
the rules, in case the stock `kaggle_environments` episode was too slow to drive a coordinate-ascent
search or a large arena. Measured: ~1.3–1.4s per 720-turn episode on this machine. A search sweep of
~20 parameters × 5 values × 100 paired seeds (~20,000 episodes) costs roughly 2 hours on 4 CPUs, or
well under an hour once the container's CPU quota is raised (see "Environment" below). That is fast
enough — `fastsim` is not built. `harness` and `tuning` call `kaggle_environments.make(...)`
directly. Revisit only if profiling during `tuning` shows the arena is actually the bottleneck.

**Boundary that's easy to violate:** `gamelib`, `agent`, and `policy` ship inside the submission
bundle, so they depend on the standard library only — never `kaggle_environments`, never a network
call, never a file outside the bundle (see "Rule compliance" below). `harness`, `tuning`, `ops`, and
`diskguard` are dev-only tooling and are free to depend on `kaggle_environments`, `kaggle`,
`pytest`, etc.

## Economic analysis

**Referenced by name throughout `kagg.policy`'s comments (e.g. "premium goods look great until
you check market depth") since Phase 7-8, but never actually written down until Phase 8's T8.3j -
recorded now from the competition's own Overview page (kaggle.com/competitions/kaggriculture, "The
Price Function" section), not reverse-engineered from `kaggriculture.py` alone. The two sources
agree exactly on every number that matters (`MARKET_PARAMS`), but the Overview page adds real
design intent (`T`'s calibration, the "premium" classification, per-shape strategic implications)
that the source code's bare data tables don't state.**

### The price curve, restated precisely

```
price(inv) = base + sign * amp * f(|inv - I0|)
  sign = +1  if inv < I0   (scarcity -> price up)
  sign = -1  if inv > I0   (glut     -> price down)
  amp  = target * base / f(T)        (derived, not stored)
  f    in { linear, sq, sqrt, log, log10, hinge }
```

Floored at $1, rounded to nearest dollar. Every resource starts at `I0 = 10,000` (deliberately far
above any realistic single-game production volume, so it stays positive all game). `T` is **not an
arbitrary tuning knob** - it's the production capacity of a single 5x5 field over a 24-day window at
optimal watering with no fertilizer (animal totals pre-discounted 30% for wheat-feed overhead and
one day of build time). The 24-day window is a calibration horizon, not the 30-day season - the
opening days are setup-heavy and yield little. Practically: **`T` is a real, meaningful "how much of
this good is a lot" reference**, not just a curve-fitting parameter - a heuristic bound worth reusing
directly in planning (e.g. "how many tiles of X can I commit to before I'm producing more than one
field's worth" is already a T-relative question, not something to rediscover by trial and error).

`hinge` (only shape whose closed form depends on `T`, not just `x`): `u = x/T`, evaluates to
`u + 8*max(0, u-1)^2`. Below `T` it's linear in `u` (price barely moves - "stays near base under
ordinary demand"); above `T` the quadratic term takes over and price climbs *steeply*. `f(T) = 1` by
construction, so `target` keeps the same meaning it has for every other shape: **`target` means
"moving `T` units past `I0` shifts the price by `target * base`"** - a directly readable statement
of how much one full field's worth of surplus/shortfall is worth in dollars, per resource, per side.

Because `linear`'s amplitude already normalizes to `x/T` - exactly `hinge`'s below-knee branch -
CARROT/TOMATO/EGG's scarcity-side prices from `I0` down to `I0-T` are **identical** to what a plain
`linear` curve at the same `below_target` would give; the two curves only diverge *past* the knee.
Tomato and egg's `below_target` (0.40 each) is inherited unchanged from the `linear` curve `hinge`
replaced there - the redesign only added the steep post-knee acceleration, it didn't retune the
gentle part.

### Per-resource table (from the Overview page directly - `P(I0-T)`/`P(I0+T)`/`P(I0+2T)` are worked
examples, not something this codebase currently computes anywhere)

| Resource | Base | T | Below func | Below target | Above func | Above target | P(I0-T) | P(I0+T) | P(I0+2T) |
|---|---|---|---|---|---|---|---|---|---|
| Wheat | 25 | 400 | sqrt | 0.80 | log | 0.20 | $45 | $20 | $19 |
| Carrot | 35 | 450 | hinge | 1.00 | sqrt | 0.70 | $70 | $10 | $1 |
| Tomato | 60 | 200 | hinge | 0.40 | sqrt | 0.60 | $84 | $24 | $9 |
| Strawberry | 120 | 100 | sqrt | 0.70 | linear | 1.60 | $204 | $1 | $1 |
| Melon | 250 | 300 | log | 0.20 | sq | 3.60 | $300 | $1 | $1 |
| Egg | 50 | 332 | hinge | 0.40 | log | 0.20 | $70 | $40 | $39 |
| Milk | 160 | 122 | sqrt | 0.60 | linear | 1.60 | $256 | $1 | $1 |
| Wool | 200 | 105 | log | 0.20 | sq | 3.20 | $240 | $1 | $1 |
| Fertilizer | 100 | 200 | linear | 0.40 | linear | 0.40 | $140 | $60 | $20 |

**Every one of the 9 products has its own distinct scarcity/glut pairing - not just two broad
groups.** Recorded per-product, not glossed over, since the user's own point stands: each pairing is
a real, potentially exploitable asymmetry, not merely decoration on the two headline patterns below.

| Resource | Scarcity side (below `I0`) | Glut side (above `I0`) | What this means in practice |
|---|---|---|---|
| **Wheat** | `sqrt`@0.80 - meaningfully sharp: $45 at exactly `I0-T`, +80% over base | `log`@0.20 - very forgiving: still $19 at `I0+2T`, barely below base | "Panics on scarcity, absorbs gluts" (Overview's own phrase) - safe to overproduce in bulk, costly to let run out (feed-stock implications - see the WHEAT-for-feed lead below) |
| **Carrot** | `hinge`@1.00 - gentle below `T` (identical to a plain `linear`@1.00 curve there), then steep past it | `sqrt`@0.70 - moderate, crashes to $1 by `I0+2T` | The clearest `hinge` case: a real deficit *beyond* `T` is disproportionately rewarded versus the same deficit at `T` or under |
| **Tomato** | `hinge`@0.40 - same below-knee-then-steep shape, milder amplitude | `sqrt`@0.60 - moderate | Same `hinge` opportunity as carrot, smaller magnitude (matches its smaller `T`=200, so a real deficit is a smaller absolute quantity to reach) |
| **Strawberry** | `sqrt`@0.70 - strong: $204 at `I0-T`, +70% over base | `linear`@1.60 - already **$1 at exactly `I0+T`**, not just "eventually" | Premium: rewards genuine scarcity well, punishes even one field's worth of glut completely |
| **Melon** | `log`@0.20 - very weak: barely above base even at real scarcity | `sq`@3.60 - already **$1 at exactly `I0+T`**, the steepest above-target of all 9 | "Barely reacts to scarcity, crashes hard on overproduction" (Overview's own phrase) - all the risk is on the sell side, none of the upside on the buy side |
| **Egg** | `hinge`@0.40 - same shape as tomato's, keeps the `linear` curve's target it replaced | `log`@0.20 - very forgiving, still $39 at `I0+2T` | Mirrors wheat's forgiving-glut profile on the sell side, but with carrot/tomato's steep-past-`T` upside on the buy side - arguably the most one-sidedly favorable pairing of the 9 |
| **Milk** | `sqrt`@0.60 - meaningfully strong: $256 at `I0-T`, +60% over base | `linear`@1.60 - **$1 at exactly `I0+T`** | Premium, but unlike melon/wool actually rewards real scarcity too - the one premium good worth chasing on *both* sides, not just avoiding on the sell side |
| **Wool** | `log`@0.20 - very weak, mirrors melon | `sq`@3.20 - **$1 at exactly `I0+T`** | "Mirrors melon at a smaller scale" (Overview's own phrase) - same all-risk-on-the-sell-side shape, smaller `T`=105 so it takes fewer units to trigger |
| **Fertilizer** | `linear`@0.40 | `linear`@0.40 | The only symmetric pairing of the 9 - equally forgiving (or punishing) on both sides, matching its NA "premium" classification |

Two patterns this table makes concrete enough to act on, both only *partially* reflected in code
today:

- **Premium goods (base > $100: strawberry, melon, milk, wool) use `above_target > 1`, and the
  table shows exactly how blunt that already is**: all four are floored at $1 already at `I0+T` -
  not "eventually," not "a modest glut," but *exactly one field's own season of overproduction*.
  This is `kagg.policy.market.PREMIUM_GOODS`'s own justification (drip-selling) and
  T8.3f/T8.3g/T8.3h's whole self-impact/opponent-awareness investigation, but the drip cap is
  reactive damage control, not a plan built around the curve shape itself - MILK is the one
  exception worth separate handling (it rewards real scarcity, unlike the other three, which don't).
- **`hinge`-shaped scarcity (carrot, tomato, egg)**: price stays *near base* under ordinary demand
  and only climbs *sharply* once demand runs past `T` - a fundamentally different opportunity shape
  than the smooth `sqrt`/`log` scarcity curves every other product uses. This is the one genuinely
  **unexploited** lever this analysis surfaces: nothing in `kagg.policy` currently distinguishes "a
  hinge product is approaching its `T` deficit knee" from any other scarcity signal - `price()` is
  called generically everywhere (T8.3f/T8.3i's models included), with no shape-aware logic at all.
  A real, concrete future feature: detect (from `market_inventory` trending toward `I0 - T` for
  CARROT/TOMATO/EGG specifically - e.g. via town/shop consumption already exceeding what any
  visible producer, us or the opponent, appears to be supplying) that one of these three is heading
  into its steep-climb zone *before* the price has fully caught up, and preferentially plant it
  while the payoff is disproportionate to the still-modest current price. Recorded here as a
  concrete idea, not built - see "Not planned yet" in `tasks/todo.md`.

### Open, related ideas recorded from user discussion (T8.3g-T8.3j), not yet implemented

- **Wheat is a special case already touching two of this project's own findings at once.** Feeding
  an animal consumes 1 WHEAT/day from the farmer's own inventory (a private-state operation, no
  market effect) - but *restocking* that WHEAT via `BUY_PRODUCT` **does** reduce the shared
  `market["inventory"]["WHEAT"]` by 1 per unit bought (verified directly in `kaggriculture.py`'s
  `_commit_unit`), which raises WHEAT's own price exactly like a `SELL` order lowers it. Two real,
  currently un-modeled implications: (1) **growing our own feed wheat instead of buying it avoids
  this self-inflicted price pressure entirely** - a genuine cost-avoidance lever `rank_portfolio`
  doesn't currently value at all when scoring WHEAT-as-a-crop; (2) **the opponent feeds their own
  animals too**, via the same `BUY_PRODUCT` (or their own wheat harvest) against the *same* shared
  market - a second, distinct kind of opponent-driven price effect from the T8.3g/T8.3h one (which
  was about opponent *crop* tiles pushing supply up; this one is about opponent *animal feeding*
  pushing WHEAT demand up, tightening supply instead).
- **Animal count is currently capped at one-per-type by a hard rule** (`decide.py`: "never pursue a
  second instance of an animal type we already have placed and alive"), not by price awareness -
  so unconstrained WOOL/MILK/EGG overproduction from stacking animals is a structural
  non-issue *today*, independent of T8.3f's crops-only self-impact scope. That cap is explicitly
  provisional ("revisit once multiple hands make tending more than one worthwhile") and animal
  escape from missed feeding (`consecutive_unfed >= 2`) is a real but currently low-probability risk
  at n=1 animal (FEED is the highest task priority). Both stop being dormant the moment T8.4-T8.7
  hiring lifts the one-animal cap - at that point, an animal-product analog of T8.3f's self-impact
  (bounded by *some* real horizon - e.g. remaining season days, not an unbounded lifetime total)
  becomes a real, not merely theoretical, gap. Flagged in `tasks/todo.md`'s "Not planned yet" for
  re-evaluation alongside the other hiring-dependent re-checks already recorded there.

## Environment

- Container: 12 CPUs / 32 GB (raised from an initial 4 CPUs / 16 GB via `docker-compose.yml`,
  applied from the host) — code must not hardcode either number, read core count at runtime for
  parallelism (`os.cpu_count()`).
- No GPU on the host. This directly informs "Why not RL" above.
- Python 3.12, `venv` at `/root/kaggriculture/.venv` (outside this repo — see "Project structure").
- Competition Data (downloaded replays, the daily top-episodes dataset, arena logs) lives at
  `/root/kaggriculture/data/`, outside this repo, path configurable via `KAGG_DATA_DIR` (default
  `../data` relative to the repo root) — see "Rule compliance".
- **Disk budget: 2.5 TB cap on this project's total footprint.** The underlying volume is shared
  across other, unrelated projects on the same host and offers no filesystem-level quota mechanism
  reachable from inside this container (checked: `ext4` without `prjquota`, no `xfs_quota`/
  `setquota`/`repquota`, no loop devices). Enforced instead by `diskguard` (`tools/diskguard.py`,
  see `SPEC-diskguard.md`): every write in `ops`/`harness`/`tuning` that could grow disk usage
  calls `ensure_budget()` first, which evicts the oldest downloaded replays/episodes (always
  re-fetchable from Kaggle) before ever refusing a write outright — it never touches `data/arena/`
  (tuning history) or this repo.

## Commands

Until `tools/` and `tests/` are implemented (tracked in the build plan, not yet written), these are
the intended invocations — filled in for real once each script exists:

```bash
# Dev environment (already created, one level above this repo)
/root/kaggriculture/.venv/bin/pip install -r requirements-dev.txt

# Tests
/root/kaggriculture/.venv/bin/pytest repo/tests -q

# Arena: N paired seeds against a named opponent, honoring the harness protocol in SPEC-harness.md
/root/kaggriculture/.venv/bin/python repo/tools/arena.py --opponent starter --seeds 100 --jobs auto

# Build the submission bundle (main.py + gamelib + policy + params -> tar.gz)
/root/kaggriculture/.venv/bin/python repo/tools/build_submission.py --out build/submission.tar.gz

# Submit (5/day limit, resets 00:00 UTC calendar day — see Boundaries and
# SPEC-ops.md): agent-mediated via the kaggle-mcp MCP server's
# start_competition_submission_upload -> submit_to_competition, not a
# standalone CLI invocation — see SPEC-ops.md "Submission workflow".
```

## Project structure

```
/root/kaggriculture/          workspace root, NOT a git repo
├── .venv/                    Python virtualenv (dev tooling only)
├── data/                     Competition Data — never enters this repo, see Boundaries
│   ├── replays/
│   ├── episodes/             daily top-episodes dataset
│   └── arena/                arena run logs and tuning history
├── scratch/                  throwaway scripts, not tracked, not part of the deliverable
└── repo/                     THIS repository (git root)
    ├── LICENSE                CC BY 4.0
    ├── README.md
    ├── SPEC.md                this file
    ├── SPEC-{harness,gamelib,agent,policy,tuning,ops}.md
    ├── requirements-dev.txt
    ├── params/                dev-only config, never ships (e.g. seed_blocks.json's
    │                          tuning/holdout seed lists) — distinct from src/kagg/params/
    │                          below, which does ship; conflating the two would risk a
    │                          future build_submission.py accidentally bundling dev
    │                          config into the submission
    ├── src/kagg/
    │   ├── gamelib/           ships in submission
    │   ├── policy/            ships in submission
    │   ├── params/            tuned parameter files (JSON), ships in submission —
    │   │                      lives *inside* kagg/ on purpose (see "Correction" below):
    │   │                      dev and bundle layouts must be identical, not related by
    │   │                      a reorganizing copy step that only "works" after bundling
    │   └── agent_main.py      ships in submission, becomes main.py in the bundle
    ├── tools/                 harness, tuning, ops scripts — dev only
    ├── tests/
    └── build/                 generated submission.tar.gz (gitignored)
```

**Correction (found during T3.4, before any loader code was written):** an earlier revision put
`params/` at the repo root, sibling to `src/`, while `SPEC-ops.md`'s bundling step copies it into
`build/kagg/params/` — nested inside the package folder. That's the exact same class of bug T0.3
found and fixed for `__file__`: a path relationship that only holds after a reorganizing copy step,
untestable in the dev tree as it stood. `params/` moved inside `src/kagg/` so the loader (living in
`kagg/policy/`, a normally-imported submodule with a working `__file__` — see `SPEC-agent.md`'s own
correction) resolves the *same* relative path in dev and in the built bundle, by construction, not
by coincidence.

## Code style

- Comments, docstrings, identifiers: English only, regardless of conversation language (project
  and global convention).
- Python 3.12, type hints on public functions in `gamelib`/`policy`/`agent` (these ship and must
  stay readable without the author present).
- `gamelib`/`agent`/`policy`: standard library only. No third-party imports, no
  `kaggle_environments` import — that boundary is load-bearing (see Capability map and Rule
  compliance).
- Prefer plain dicts/tuples matching the observation schema over introducing a parallel class
  hierarchy — the observation format is fixed by the environment and documented in
  `kaggriculture.json`/`README.md` (see `SPEC-gamelib.md`); wrapping it loses nothing and adds
  translation bugs.
- Example — an action-building helper follows the existing `starter_agent` idiom from the
  environment's own reference agent (`kaggle_environments/envs/kaggriculture/kaggriculture.py`):

  ```python
  def wheat_loop_action(farm: dict, private: dict, day: int) -> list:
      """Buy/plant/water/harvest one wheat tile. Returns a farmer op list."""
      seeds = private.get("seeds", {})
      if seeds.get("WHEAT", 0) == 0 and farm["money"] >= CROPS["WHEAT"]["seed"]:
          return ["PASS"]  # market order handles the buy; farmer waits one turn
      ...
  ```

## Testing strategy

`pytest`, run from `/root/kaggriculture/.venv/bin/pytest repo/tests -q`. Layers, cheapest first:

1. **Property tests** — `gamelib`'s price curve, harvest schedule, and tile-value functions
   produce the same numbers as the real `kaggriculture.py` (`market_price`, `_hire_cost`,
   `_daily_refresh_*`) on randomized inventories/day counts. This is the primary correctness gate
   for `gamelib`, since it ships without ever importing the real rules module.
2. **Golden episodes** — a handful of fixed seeds with recorded final-money outcomes; any change
   that moves these numbers needs a deliberate re-record, not a silent pass.
3. **Arena regression** — see `SPEC-harness.md`: paired seeds, held-out block, town-shop-reroll
   split, Wilson interval. This is the gate before every submission, not just before merging code.
4. **Time-budget test** — a full 720-turn episode run with per-turn timing asserted against the
   budget in `SPEC-agent.md`, both p100-per-turn and cumulative overage.
5. **Fuzzing** — malformed/partial observations fed to `agent()` must never raise; asserts the
   `try/except PASS` fallback actually engages.
6. **Bundle audit** — static check of the built `submission.tar.gz`: no `socket`/`urllib`/
   `requests` imports, no `open()` calls outside the bundle directory. Enforces Official Rules
   §2.11 (no ingress/egress) mechanically rather than by promise. Runs as part of
   `tools/build_submission.py`, not just as a test.
7. **Disk budget** — `tests/test_diskguard.py` (implemented, 7 tests): eviction order, the
   never-touch-`data/arena`-or-`repo` invariant, and the hard-refuse-rather-than-overrun behavior
   of `ensure_budget()`. See `SPEC-diskguard.md`.

## Boundaries

**Always:**
- Run the arena regression (layer 3 above) before every submission, not just before merging code.
- Keep `gamelib`/`agent`/`policy` to the standard library only.
- Call `diskguard.ensure_budget()` before any write in `ops`/`harness`/`tuning` that could grow
  disk usage (dataset/replay downloads, arena logs) — see `SPEC-diskguard.md`.
- `agent()` never raises and never touches the network or a path outside its own bundle directory
  during an episode (Official Rules §2.11 — see "Rule compliance").
- Comments and identifiers in English, regardless of conversation language.

**Ask first:**
- Spending a submission (5/day, only the latest 2 are scored — see `SPEC-ops.md`).
- Any publication on Kaggle itself (notebooks, forum posts) — permitted by the rules, but a
  deliberate act, not a side effect of tooling.
- Adding a dependency to the bundled code (`gamelib`/`agent`/`policy`) — the stdlib-only boundary
  is load-bearing for both the time budget and Official Rules §2.11.
- Granting repository access to anyone outside an official Kaggle team merge (Official Rules
  §2.5.d — private sharing of Competition Code is permitted only within a registered Team).

**Never:**
- Commit the Kaggle API token, or any other secret, anywhere under `repo/`.
- Submit code that has not been run through the local arena regression.
- Publish the agent's code before the competition deadline.
- Exceed 5 submissions per day.
- Place Competition Data (downloaded replays, the daily episodes dataset) inside `repo/` —
  Official Rules §2.4.b prohibits redistributing it, and physical separation (see "Rule
  compliance") is the actual control, not a promise.
- Have `agent()` pull in any information from outside its bundle, or send anything out, during an
  episode (Official Rules §2.11).
- Manually operate the agent during a real competition episode (by analogy with Official Rules
  §3.4.b's prohibition on hand-labeling/human prediction of evaluation data) — local debugging
  runs are not competition episodes and are unaffected.

## Rule compliance

Full Official (competition-specific) Rules and Foundational Rules have been read in full; the
items below are the ones that actually constrain code or process. Everything else (governing law,
taxes, publicity, right-to-cancel, etc.) is standard Kaggle boilerplate with no bearing on this
project.

- **§2.11 No Ingress or Egress** — "During the evaluation of an episode your Submission may not
  pull in or use any information external to the Submission and Environment and may not send any
  information out." Stronger than "stdlib only": also forbids reading config from outside the
  bundle at runtime and any outbound logging. Enforced mechanically by the bundle audit test
  above, not just by code review.
- **§2.5 / §2.8 Winner License & Obligations** — a winner must license the submission and its
  source under CC BY 4.0 and provide a reproducible repository with a methodology writeup. Covered
  by this repo's `LICENSE`, this `SPEC.md`, and the `KAGG_DATA_DIR`-relative paths that let someone
  else reproduce results without our exact directory layout.
- **§2.4 Competition Data / Data Security** — no redistribution of Competition Data (this
  includes downloaded replays and the daily top-episodes dataset). Enforced structurally: Data
  lives at `/root/kaggriculture/data/`, one level above this repo's git root, so it cannot enter a
  commit even by accident (verified: `git -C /root/kaggriculture status` reports "not a git
  repository").
- **§2.5.d / §3.6.a Private Sharing** — Competition Code may be privately shared only within an
  officially merged Kaggle Team; public sharing is allowed but only via Kaggle's own forum/notebooks
  (§3.6.b), not third-party hosting. Not currently relevant (team of one) but binds any future
  collaborator: access via official team merge, not ad-hoc repo grants.
- **§3.4.b Hand Labeling / Human Prediction** — by analogy, no manual control of the agent during a
  real competition episode; only the submitted code decides moves.
- **§2.6 External Data and Tools** — any external data/tool used to build (not run, per §2.11) the
  agent must be reasonably accessible to all competitors at minimal cost. A standard LLM API
  subscription clears this bar; nothing licensed above the prize amount is in scope.
- **§2.7 Eligibility** — Google/Kaggle employees can enter but cannot win prizes; not our situation.
- **Evaluation / no Private Leaderboard** — final ranking comes from a single Bradley–Terry
  tournament run on episodes played after the entry deadline, specifically to avoid rewarding
  "hot streaks"; there is no held-out private test set to worry about leaking into (`SPEC-tuning.md`
  accounts for this in how it reads win rate).

Not competition-rules-related but worth recording: the forum's pinned "Beware of scammers" thread
warns about phishing emails impersonating Kaggle admins asking for source code — unrelated to our
architecture; the response is simply not to reply and to report to `support@kaggle.com`.
