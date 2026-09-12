# Implementation plan: gamelib → agent → policy → harness

Written per [`agent-skills:planning-and-task-breakdown`](../SPEC.md). Covers the path from the
current empty `src/kagg/` skeleton to a policy that has a *measured* baseline win rate against
`starter`/`random` under a trustworthy evaluation protocol. `tuning` and `ops` (needed before the
first real Kaggle submission) are deliberately **not** broken into tasks yet — see "What's not
planned yet" at the end; planning them now would mean guessing at numbers (which hiring-count
range is worth sweeping, how big a seed block, etc.) that Phase 3/4 will actually produce.

`diskguard` is already built and committed (`fb44ae9`) — not covered here.

## Dependency graph

```
constants.py (CROPS, ANIMALS, MARKET_PARAMS, SHOPS, LAND_PRICES, ...)
        │
        ▼
   gamelib/*  ──────────────────────────────────┐
        │                                        │
        ▼                                        │
  agent_main.py (contract, time budget,          │
  fault tolerance)                               │
        │                                        │
        ▼                                        │
   policy/*  (strategic / task / market layers) ─┘  (policy calls gamelib directly too,
        │                                            not only through agent)
        ▼
 tools/harness.py  (evaluates whatever agent_main.py + policy currently do —
                     no code dependency the other direction; harness can be
                     built with plain "starter"/"random" before policy exists,
                     but its main payoff starts once there's a real policy)
```

`gamelib` has zero internal dependencies (only stdlib + the constants it owns). `agent` depends on
`gamelib`. `policy` depends on `gamelib` (calls `price()`, `forecast_*()`, `tile_distance()`
directly) and is *called by* `agent_main.py`, not the other way around. `harness` depends on
nothing in `src/kagg/` — it drives whatever file you point it at, including built-in `"starter"`/
`"random"` — so it could technically be built first, but there's nothing of ours worth evaluating
with it until Phase 0 exists.

## Vertical slicing rationale

Phase 0 deliberately touches all three shipping modules (`gamelib`, `agent`, `policy`) at once,
each with only the single slice needed to play one real crop loop end to end — not "build all of
gamelib" as a horizontal layer before anything else exists. This mirrors `AGENTS.md`'s own
`starter_agent` (carrot loop) reference example and gives a real, submittable (if crude) agent
after Phase 0 alone — a genuine walking skeleton, not a stub. Every phase after that *widens* the
already-working vertical path rather than starting a new one.

---

## Phase 0 — Walking skeleton

**Goal:** one real crop loop (buy → plant → water → harvest → sell) running through
`kaggle_environments` end to end, beating the `"pass"` baseline. Proves the plumbing — Kaggle's
file-loading contract, `sys.path`, the observation/action shapes — before any real economics.

- **T0.1 — `gamelib/constants.py` + `gamelib/market.py: price()`, `shape()`**
  Files: `src/kagg/gamelib/constants.py`, `src/kagg/gamelib/market.py`.
  Copy `CROPS`, `ANIMALS`, `MARKET_PARAMS`, `PRICE_FLOOR`, `HINGE_GAIN` verbatim from
  `kaggriculture.py` (see `SPEC-gamelib.md` for the exact source lines). Implement `shape(func, x,
  T)` and `price(item, inventory, params=None)` per `SPEC-gamelib.md`'s "Key subtleties" — nearest-
  int rounding, `PRICE_FLOOR` clamp, explicit inventory argument (no assumed buy/sell direction).
  - **Acceptance:** `price("WHEAT", 10000)` returns `25` (base price at `I0`); `price("WHEAT", 0)`
    returns an int, not a float.
  - **Verify:** `python -c "from kagg.gamelib.market import price; assert price('WHEAT', 10000) == 25"`

- **T0.2 — `agent_main.py` skeleton**
  Files: `src/kagg/agent_main.py`.
  `agent(obs) -> dict` with a top-level `try/except Exception` returning
  `{"farmer": ["PASS"], "hands": [], "market": []}` on any error (`SPEC-agent.md` "Fault
  tolerance"). Path-safe import of `kagg.gamelib` relative to `os.path.dirname(__file__)` (Kaggle
  unpacks bundles at `/kaggle_simulations/agent/` — see `SPEC-agent.md` "Contract").
  - **Acceptance:** calling `agent({})` (empty/garbage observation) returns the safe-default shape
    without raising.
  - **Verify:** a one-off script importing `agent_main.agent` and calling it with `{}`, `None`-ish
    partial dicts, etc.

- **T0.3 — Wheat-loop policy, wired into `agent_main.py`**
  Files: `src/kagg/policy/` (a single function is enough for this phase — full three-layer
  structure is Phase 3), `src/kagg/agent_main.py`.
  Port `AGENTS.md`'s wheat-loop example, but replace its hardcoded sell decision with
  `gamelib.market.price()` so the vertical slice actually exercises T0.1's function rather than
  duplicating the constant.
  - **Acceptance:** a full 720-turn local episode (`kaggle_environments.make("kaggriculture",
    configuration={"episodeSteps": 720, "seed": 1}).run(["src/kagg/agent_main.py", "pass"])`)
    completes without exception, and our side's final money exceeds `"pass"`'s (i.e. > 3000).
  - **Verify:** run the episode above, print `[(i, s.reward) for i, s in enumerate(env.steps[-1])]`,
    assert our index's reward > 3000.

**Checkpoint 0:** commit. This is the first genuinely submittable agent (crude, but real) —
worth noting as a candidate for an early throwaway Kaggle submission just to confirm the bundle
format and Kaggle's runner behave as documented, once `ops`/`build_submission.py` exist later.

---

## Phase 1 — `gamelib` complete

**Goal:** every function in `SPEC-gamelib.md`'s table implemented and property-tested against the
real `kaggriculture.py` as the oracle (imported only from `repo/tests/`, never from `gamelib`
itself).

- **T1.1 — `hire_cost(n_already_today, mult)`**
  Mirrors `_hire_cost` (`kaggriculture.py:698`).
  - **Verify:** property test — matches `_hire_cost()` for `n_already_today in range(0, 20)`.

- **T1.2 — `watering_bonus_window(crop)` + `forecast_one_time_yield(crop, watered_days,
  fertilized)`**
  Mirrors the `WATER`/`FERTILIZE` handlers (`kaggriculture.py:431-482`). Get the off-by-one right:
  window start is `ceil(max_yield_day / 2)`, inclusive of `max_yield_day` itself.
  - **Verify:** property test — plant a crop in a scratch `_new_farm`, drive a randomized
    watering/fertilizing schedule through the real `_apply_unit_action`, compare final
    `yield_units` to the forecast for the same schedule.

- **T1.3 — `forecast_ongoing_schedule(crop, planted_day)` + `forecast_animal_schedule(animal,
  placed_day)`**
  Mirrors `_daily_refresh_plants`/`_daily_refresh_animals` (`kaggriculture.py:769`, `:805`). Must
  return a **finite** list — tomato caps at 4 scheduled yields, strawberry at 4.
  - **Verify:** property test — drive the real refresh functions for 30 simulated days, compare
    day-indexed yield bumps.

- **T1.4 — `decay_step(max_lifespan_step, step)`**
  Mirrors `_decay_plants` (`kaggriculture.py:752`).
  - **Verify:** property test against `_decay_plants`.

- **T1.5 — `shed_room(shed, capacity)`**
  Mirrors `_drop_inventories_to_shed` (`kaggriculture.py:843`).
  - **Verify:** property test against a scratch shed filled to a randomized level.

- **T1.6 — `tile_distance(a, b)` + `land_price(n_unlocked_extra)`**
  New helper (Manhattan distance) + mirrors `_do_buy_land` (`kaggriculture.py:712`).
  - **Verify:** unit tests (no oracle needed) — symmetry, zero-on-identity, opposite-corner
    distances on a 10×10 board; `land_price` returns `None` once all three quadrants are bought.

- **T1.7 — Boundary enforcement test**
  An `ast`-based scan of every file under `src/kagg/gamelib/` asserting no `import
  kaggle_environments` anywhere (`SPEC-gamelib.md` "Boundaries specific to this module").
  - **Verify:** the scan itself is the test; must fail loudly if the import ever creeps in.

**Checkpoint 1:** `pytest repo/tests -k gamelib` all green. Commit. `gamelib` is now feature-complete
per its spec and is the correctness foundation everything else stands on.

---

## Phase 2 — `agent` hardening

**Goal:** the submission contract fully matches `SPEC-agent.md` — not just the T0.2 skeleton's
bare try/except, but the actual time budget and fault-tolerance guarantees.

- **T2.1 — Time-budget guard**
  `time.perf_counter()` around the whole `agent()` body; 400ms hard ceiling; on ceiling breach,
  return the last cached full plan's next action rather than a partial computation. Strategic
  replanning gated to `obs["hour"] == 0` (or amortized — see `SPEC-agent.md`).
  - **Verify:** unit test that forces a slow path (e.g. a monkeypatched policy call that sleeps)
    and asserts the cached-plan fallback engages within the ceiling.

- **T2.2 — Fault-tolerance fuzzing**
  Feed `agent()` observations with missing keys, wrong types, an out-of-range `player` index, and
  a `farms` list shorter than expected.
  - **Verify:** every case returns the safe-default shape without raising.

- **T2.3 — Full-episode timing test**
  Run a complete 720-turn episode, record per-turn duration.
  - **Acceptance:** p100 per-turn latency under the 400ms ceiling; cumulative overage well under
    the 60s pool (target <10s total, per `SPEC-agent.md`).
  - **Verify:** the timing test itself, run against `agent_main.py` as it stands after Phase 0/1
    (wheat-loop policy) — this test gets re-run, not rewritten, once Phase 3 replaces the policy.

- **T2.4 — Golden-episode fixture**
  Record final money for `agent_main.py` vs `"starter"`/`"random"` on a handful of fixed seeds.
  - **Verify:** re-running those seeds reproduces the recorded numbers exactly; any future change
    that moves them needs a deliberate re-record (`SPEC.md` testing strategy, layer 2).

**Checkpoint 2:** `agent` fully matches `SPEC-agent.md`. Commit. Note in the commit message that the
golden episodes recorded here are against the *Phase 0 wheat-loop* policy — expected to change
substantially (and be re-recorded) once Phase 3 lands.

---

## Phase 3 — `policy` complete (three layers)

**Goal:** replace Phase 0's single-crop wheat loop with the full strategic/task/market structure
from `SPEC-policy.md`, covering all 5 crops and 3 animals.

- **T3.1 — Strategic layer**
  Portfolio allocation across all crops/animals ranked by marginal revenue at the farm's own
  *projected sale volume* (via `gamelib.price()`), not base price. Land-purchase threshold and
  `hires_per_day` as **named parameters in `params/policy.json`**, not hardcoded numbers — this is
  the single most important rule in `SPEC-policy.md`, given the hiring-count question is an open,
  forum-contradicted hypothesis (see `SPEC.md`'s economic analysis) that only the arena can settle.
  - **Verify:** unit test — given a synthetic farm + market snapshot, the chosen allocation matches
    a hand-computed expected marginal-revenue ranking.

- **T3.2 — Task layer**
  Prioritized task list (`WATER`, `HARVEST`, `FEED`, `PLANT`, `COLLECT_FERTILIZER`, `DIG`) +
  greedy farmer/hand assignment via `gamelib.tile_distance`. Priority: prevent-loss (about to hit
  `consecutive_unwatered`/`consecutive_unfed == 2`) > harvest-value > plant-new-tile > maintenance.
  - **Verify:** unit test — a farm with a tile one turn from weeding and a tile ready to harvest;
    assert the prevent-loss action is picked first.

- **T3.3 — Market layer**
  Sell thresholds at a tunable margin over cost basis; drip-selling for premium goods (milk, wool,
  melon, strawberry) across multiple turns rather than a single dump order; `BUY_PRODUCT` limited
  to `WHEAT`/`FERTILIZER`; ≤10 orders/turn enforced.
  - **Verify:** unit test — construct a shed with more than 10 sellable lots, assert the emitted
    market-order list never exceeds 10; assert no `BUY_PRODUCT` order for any item other than
    `WHEAT`/`FERTILIZER` is ever emitted.

- **T3.4 — `params/policy.json` schema + loader**
  Loaded once at agent construction time, not per turn (time budget).
  - **Verify:** loading a missing/malformed file falls back to hardcoded defaults rather than
    crashing agent construction — construction-time failure is not covered by `agent()`'s own
    per-turn `try/except`, so this needs its own guard.

- **T3.5 — Replace Phase 0's wheat loop**
  Wire T3.1–T3.3 into `agent_main.py` in place of the temporary single-crop policy.
  - **Verify:** re-run T0.3's episode check — still completes 720 turns without exception, still
    beats `"pass"`.

- **T3.6 — Ad-hoc baseline measurement**
  Before `harness` exists (Phase 4), get a rough number: run ~20 seeds of the new policy vs
  `"starter"` and vs `"random"` directly through `kaggle_environments` (no paired-seat/held-out
  rigor yet — that's what Phase 4 is for). This is *not* the trustworthy number `SPEC.md`'s success
  criteria refer to; it's a sanity check that Phase 3 is a real improvement over Phase 0 before
  investing in Phase 4's more expensive protocol.
  - **Verify:** win rate against `"random"` is unambiguously high (agent should never lose to
    `"random"` — if it does, something in T3.1–T3.3 is broken, not just under-tuned).

**Checkpoint 3:** commit. Record the T3.6 rough numbers in the commit message (not in `repo/` as a
tracked artifact — this is exactly the kind of ad-hoc arena output that belongs in `data/arena/`
once that convention is actually in use, but a one-off pre-harness sanity check doesn't need its
own logging infrastructure yet).

---

## Phase 4 — `harness`

**Goal:** the paired-seat / held-out / shop-reroll-aware evaluation protocol from
`SPEC-harness.md`, so Phase 3's policy gets a number worth trusting.

- **T4.1 — `run_paired(agent_a, agent_b, seed, episode_steps=720)`**
  Plays `seed` twice (swapped seats), collapses to one `PairedResult`.
  - **Verify:** two copies of `"pass"` → tie on every seed (symmetric, deterministic).

- **T4.2 — `run_block(agent_a, agent_b, seeds, jobs=None)`**
  Parallel `run_paired` across `jobs` worker processes (`os.cpu_count()`-derived default — never
  hardcoded). Wilson score interval on the aggregate win rate, not just a point estimate.
  - **Verify:** Wilson interval matches a known closed-form example (e.g. 60/100 → a specific
    published interval); `"starter"` vs `"random"` — `starter` wins regardless of seat, confirming
    seat-pairing doesn't silently favor one side.

- **T4.3 — `detect_shop_reroll(replay_path, live_town_log)`**
  Compares recorded vs. live town-shop-unlock sequence.
  - **Verify:** checked against a replay fixture with a deliberately perturbed unlock sequence.

- **T4.4 — `params/seed_blocks.json`**
  `tuning_seeds` + `holdout_seeds`, checked into the repo (not gitignored — reproducibility needs
  the exact seeds on record).
  - **Verify:** the file exists, is loaded by `run_block`'s callers, and the two seed sets are
    disjoint.

- **T4.5 — `tools/arena.py` CLI**
  Matches `SPEC.md`'s documented invocation: `--opponent`, `--seeds`, `--jobs auto`. A `--holdout`
  flag that is off by default and requires an explicit, logged invocation
  (`diskguard.ensure_budget()` before the write) — per `SPEC-harness.md`'s boundary against peeking.
  - **Verify:** `tools/arena.py --opponent starter --seeds 20 --jobs auto` runs and prints a win
    rate + Wilson interval on the *working* seed block by default; `--holdout` requires the extra
    flag and is logged.

**Checkpoint 4:** all of `SPEC-harness.md`'s Testing section passes. Re-run Phase 3's T3.6 baseline
through the *real* harness (working block only — do not touch `--holdout` yet) to get the number
that actually matters. Commit.

---

## Phase 5–7: follow-up planning pass (ops → policy capability → tuning)

Written after Phase 4 landed (Checkpoint 4: 50/50 paired wins vs `starter`/`random` on the full
tuning block) and re-grounded directly against the codebase and `kaggriculture.py` before writing
any task below — see each task's own citations. Two things drove re-scoping past the original
"tuning + ops" placeholder below: (1) `SPEC.md`'s own forum citations put strong/RL agents at
~90-122K final money against our measured ~5.4-7.0K — a gap tuning alone (measured ceiling: hiring
alone is worth +27%) cannot plausibly close, traced to a real implementation gap (animal
acquisition was never built, even though `strategy.rank_portfolio()` already ranks animals
correctly and COW/SHEEP beat every crop but MELON at base pricing); (2) the submission bundle path
has never been exercised against real Kaggle with 19 days left before the deadline, and a weak
submission proving the path today is worth more than a stronger one arriving too late to fix a
loader surprise. Full reasoning: see the plan file referenced in the corresponding commits.

`tuning`'s Stage 2 (search-generated value targets, `SPEC-tuning.md`) is deliberately **not**
broken into tasks — its own spec text gates it behind a checked-in Stage-1 baseline that beats
`starter`/`random`, which doesn't exist yet, and it's an open-ended research task that doesn't fit
the remaining runway once Phase 5/6 land. Revisit only if Stage 1 finishes early.

## Phase 5 — `ops`: prove the bundle path, get a baseline live

**Goal:** the current agent, exactly as it stands today, packaged and submitted for real —
deliberately *not* gated on Phase 6/7 (`ops` has zero code dependency on `policy`'s internals
beyond whatever it currently does).

- **T5.1 — `tools/build_submission.py`: bundle, audit, smoke-test**
  Copies `agent_main.py`→`build/main.py`, `gamelib/`/`policy/`→`build/kagg/{gamelib,policy}/`
  (with their existing `__init__.py`s), `src/kagg/params/policy.json`→`build/kagg/params/`. Does
  **not** copy `params/seed_blocks.json` — confirmed by grep only `tools/harness.py` reads it,
  `policy/params.py` never does (resolves `SPEC-ops.md`'s own open conditional on this). Runs the
  bundle audit (reuse `_kaggle_environments_imports` from `tests/test_gamelib_boundary.py` against
  the *built* tree — covers `agent_main.py` too, not just `gamelib`/`policy`) — **fails the build,
  not a warning**, on any violation — then a real smoke episode
  (`kaggle_environments.make(...).run(["build/main.py", "random"])` must reach `DONE`/`DONE`), then
  `tar -czf build/submission.tar.gz -C build main.py kagg` (`main.py` at tar root, matching
  `AGENTS.md` — already confirmed reproducible by hand: a from-scratch bundle assembled in a
  scratch dir with no dev-tree `sys.path` tricks ran a real episode to completion).
  - **Verify:** the script produces `build/submission.tar.gz`; extracting and smoke-testing it
    independently reaches `DONE`/`DONE`; a deliberately reintroduced `kaggle_environments` import
    in a scratch copy of a shipped file makes the script exit nonzero with no tarball produced.

- **T5.2 — Submission workflow script + `--no-submit` dry run**
  `start_competition_submission_upload` → PUT bytes to the returned URL → `submit_to_competition`
  → poll `get_competition_submission` (`SPEC-ops.md`'s exact sequence). Logs every attempted
  submission (message, timestamp, `policy` git commit, arena win-rate that justified it) to
  `data/arena/submissions.jsonl` *before* the API call — exempt from `diskguard.ensure_budget()`
  per `SPEC-ops.md` (kilobyte-scale, not one of the disk-hungry paths `diskguard` exists for).
  `--no-submit` stops after the upload step.
  - **Verify:** `--no-submit` completes an upload and logs would-be-submission details without
    ever calling `submit_to_competition`; the log schema is asserted by a test.

- **T5.3 — First real submission (ask-first, human-approved at execution time)**
  Not a coding task. **Must pause for an explicit, real-time go-ahead immediately before the
  `submit_to_competition` call** regardless of single-task/`auto` build mode — a scarce (5/day,
  2 scored), hard-to-reverse resource per `SPEC.md`/`SPEC-ops.md`'s "ask first" boundary.
  - **Verify:** `list_submission_episodes` shows a scored episode; `submissions.jsonl` has a
    matching entry logged before the call.

**Checkpoint 5:** `build/submission.tar.gz` builds clean and passes its own audit/smoke test; the
first real Kaggle submission is live and confirmed scored; commit (note the submission id/
description in the commit message).

## Phase 6 — `policy`: close the animal-acquisition gap

**Goal:** the farm can choose an animal, not just a crop, as its top investment, buy it, build the
matching structure, place it, and collect its production — the largest measured lever available.

- **T6.1 — Unified investment choice (`decide.py`)**
  Replace `_top_crop_choice`'s `if name not in CROPS: continue` filter with a choice over
  `rank_portfolio()`'s full crop-and-animal ranking, generalizing `_crop_has_time_to_mature`'s
  season-fit check to animals via `gamelib.growth.forecast_animal_schedule` (same "first
  production before `season_length_days`" logic already used for ongoing crops).
  - **Verify:** a market state with crop prices depressed enough that an animal outranks every
    crop (base `MARKET_I0` pricing alone isn't enough — MELON already beats every animal there) picks
    the animal; an animal too close to season-end is skipped, mirroring
    `test_top_crop_choice_returns_none_once_nothing_can_mature`.

- **T6.2 — Acquisition pipeline (`tasks.py`)**
  Extend `build_task_list()`'s `plant_crop` parameter into a general "desired investment" concept.
  Design decision: structure-building does not wait on already owning the animal (build
  proactively so the structure and the `BUY_ANIMAL` order complete in parallel across turns);
  `PLACE` fires once both a held animal and a matching empty structure exist. At most one of
  `{PLANT, BUILD_COOP, BUILD_PASTURE, PLACE}` per call, same invariant `PLANT` already has.
  `action_for_unit` needs `BUILD_COOP`/`BUILD_PASTURE` (no target beyond standing on the tile) and
  `PLACE` (`["PLACE", animal]`).
  - **Verify:** empty tile + desired animal + no matching structure → `BUILD_*` task; matching
    empty structure + animal held in shed → `PLACE` task; neither condition → neither task.

- **T6.3 — `BUY_ANIMAL` market order (`decide.py`)**
  Mirrors the existing `BUY_SEED` block: desired investment is an animal not yet held, money
  allows, `gamelib.shed.shed_room()` confirms capacity → emit `["BUY_ANIMAL", animal, 1]` (verified
  the real handler only reads the item, same as `BUY_SEED`).
  - **Verify:** order emitted when conditions hold; shed full → no order, no error.

- **T6.4 — Real-episode integration and re-measurement**
  Run a real full episode and confirm, empirically, an animal gets bought, its structure built,
  placed, and produces revenue within a season (this multi-turn pipeline is exactly the kind of
  thing that can silently deadlock or land one day too late — the same class of bug T3.5 found
  with melon timing). Document whatever's found precisely and fix in place. Re-run Checkpoint-5-
  style measurement (`tools/arena.py --opponent starter --seeds 50 --jobs auto`, then `random`)
  and record before/after numbers in the commit message.
  - **Verify:** a golden/invariant test confirms at least one animal reaches production in a
    representative episode; the baseline numbers hold or improve — a regression must be explained.

- **T6.5 — Fix the documented `BUY_SEED` gap (`decide.py`)**
  Don't emit `BUY_SEED` when there's no empty tile to plant it on (flagged in `decide.py`'s own
  docstring since T3.5).
  - **Verify:** fully-occupied farm, no seed on hand → no `BUY_SEED` order.

- **T6.6 — Extend the `kaggle_environments`-import boundary check to `policy/`**
  Closes a real gap: `tests/test_gamelib_boundary.py` only ever scanned `gamelib/`, though this
  session's own commit messages claimed `policy/` was covered too (it wasn't — `policy/` in fact
  contains no such import today, but the *test* never checked).
  - **Verify:** generalized test scans `gamelib/` and `policy/` (ideally `agent_main.py` too); a
    synthetic violation planted in a scratch copy of a `policy/` file is caught.

**Checkpoint 6:** full suite green; `tools/arena.py` re-measurement vs `starter`/`random` on the
full tuning block recorded in the commit message; commit.

## Phase 7 — `tuning`: Stage 1 only (coordinate ascent + regression gate)

**Goal:** turn `policy`'s named-but-unset parameters (now including whatever Phase 6 introduces)
into numbers backed by the arena, never accepting a change the held-out block doesn't confirm.

- **T7.1 — Regression gate (`tools/tuning.py`)**
  Compares a candidate's held-out-block `BlockResult` against the checked-in baseline's, accepting
  only if the win rate improves outside Wilson interval overlap. Logs the decision's full
  configuration to `data/arena/` — **does** call `diskguard.ensure_budget()` first (unlike T5.2's
  submission log — this write accumulates over a full tuning run, per `SPEC-tuning.md`).
  - **Verify:** `SPEC-tuning.md`'s own Testing section exactly — a synthetic "worse" candidate
    rejected; a synthetic "clearly better" one (e.g. an always-passing opponent) accepted.

- **T7.2 — Coordinate-ascent loop (`tools/tuning.py`)**
  Sweeps one parameter (or a correlated group — `hires_per_day` + `land_purchase_threshold_money`
  per `SPEC-policy.md`'s hiring note) over a small grid via `harness.run_block` on the **working**
  block only, keeping the best Wilson-adjusted win rate, iterating until no change improves beyond
  noise.
  - **Verify:** tested on a toy 2-parameter synthetic objective with a known optimum before ever
    touching the real (expensive) arena, per `SPEC-tuning.md`.

- **T7.3 — Opponent panel (`tools/tuning.py`)**
  Panel: `starter`, `random`, previous-best `policy` snapshot. Open design point: `agent_main.py`
  loads `params/policy.json` unconditionally at import with no override — recommend a narrow
  eval-only env-var hook (e.g. `KAGG_POLICY_PARAMS_PATH`, read once at import, never used by the
  shipped bundle) over a temp-copy-per-candidate approach. `yhay81/shop-router-0909` joins once
  `ops` downloads it (not blocking Stage 1's start).
  - **Verify:** `run_block` can compare two parameter sets for the same `agent_main.py` codebase
    without mutating the checked-in `params/policy.json`.

- **T7.4 — Run the sweep, prioritizing the hiring-count question first**
  An ongoing activity, not a one-shot task — `SPEC-tuning.md` names hiring-count first priority
  since it gates a large fraction of the rest of the parameter space, and this session's own
  measurement already shows signal (0→3 hires: +27% against `"pass"`). Each accepted change is its
  own described commit (never squashed into "tuning wip") and triggers a fresh `ops` submission.
  - **Verify:** at least one parameter change accepted through the T7.1 gate on the held-out block,
    before/after held-out numbers in the commit message.

**Checkpoint 7:** `SPEC-tuning.md`'s Testing section passes; at least one accepted, held-out-gated
`params/policy.json` update exists; commit.

## What's still not planned

- **`fastsim`** — not built per `SPEC.md`'s own decision (measured episode speed makes it
  unnecessary); no task exists for it and none should be added unless `tuning`'s actual sweep
  proves the arena is the bottleneck.
- **`tuning` Stage 2** (search-generated value targets) — see above; gated behind a Stage-1
  baseline that doesn't exist yet.
