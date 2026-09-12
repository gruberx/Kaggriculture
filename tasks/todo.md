# Todo: gamelib → agent → policy → harness

Full rationale, acceptance criteria, and verification commands: [`plan.md`](plan.md). `diskguard`
already done (`fb44ae9`) — not listed here. Work top to bottom; each `Checkpoint` is a commit gate.

## Phase 0 — Walking skeleton

- [x] T0.1 — `gamelib/constants.py` + `gamelib/market.py`: `price()`, `shape()`
- [x] T0.2 — `agent_main.py` skeleton: `agent(obs)` with top-level try/except → safe default
- [x] T0.3 — Wheat-loop policy wired into `agent_main.py`, using `gamelib.market.price()`
- [x] **Checkpoint 0** — 720-turn local episode vs `"pass"` completes, our side ends with >$3000
      (measured: 3398 vs 3000). Commit.

## Phase 1 — `gamelib` complete

- [x] T1.1 — `hire_cost()` (+ property test vs `_hire_cost`)
- [x] T1.2 — `watering_bonus_window()` + `forecast_one_time_yield()` (+ property test)
- [x] T1.3 — `forecast_ongoing_schedule()` + `forecast_animal_schedule()` (+ property test)
- [x] T1.4 — `decay_step()` (+ property test)
- [x] T1.5 — `shed_room()` (+ property test)
- [x] T1.6 — `tile_distance()` + `land_price()` (+ unit tests)
- [x] T1.7 — Boundary test: no `kaggle_environments` import anywhere under `src/kagg/gamelib/`
- [x] **Checkpoint 1** — `pytest repo/tests -k gamelib` all green (39/39 full suite). Commit.

## Phase 2 — `agent` hardening

- [x] T2.1 — Time-budget guard (400ms ceiling, cached-plan fallback)
- [x] T2.2 — Fault-tolerance fuzzing (malformed observations never raise)
- [x] T2.3 — Full-episode timing test (measured: p100 0.87ms, cumulative overage 0.0s)
- [x] T2.4 — Golden-episode fixture vs `starter`/`pass` (exact); `random` gets a
      robustness check instead of an exact number (its RNG is unseeded - not
      reproducible even at a fixed episode seed, verified empirically)
- [x] **Checkpoint 2** — `agent` matches `SPEC-agent.md` fully (51/51 full suite). Commit.

## Phase 3 — `policy` complete

- [x] T3.1 — Strategic layer (portfolio, land threshold, `hires_per_day` — all as named params)
- [x] T3.2 — Task layer (prioritized list + greedy assignment via `tile_distance`)
- [x] T3.3 — Market layer (sell thresholds, drip-selling, ≤10 orders/turn, `BUY_PRODUCT` restricted)
- [x] T3.4 — `params/policy.json` schema + loader (with safe fallback on missing/malformed file)
- [x] T3.5 — Replace Phase 0's wheat loop with T3.1–T3.3 in `agent_main.py`
      (found+fixed a real bug during measurement: season-end crop-maturity check)
- [x] T3.6 — Ad-hoc baseline: ~20 seeds vs `starter`/`random` (pre-harness sanity check)
      (measured: 20/20 wins vs both; avg margin +1719.7 vs starter [min +1336.0, max
      +1848.0], +5301.4 vs random [min +4886.0, max +5726.0]; 0 crashes/timeouts)
- [x] **Checkpoint 3** — Commit; note T3.6 numbers in the commit message (114/114 full suite).

## Phase 4 — `harness`

- [x] T4.1 — `run_paired()` (+ pass-vs-pass tie test)
- [x] T4.2 — `run_block()` + Wilson interval (+ closed-form check, seat-invariance test)
- [x] T4.3 — `detect_shop_reroll()` (+ fixture test)
- [x] T4.4 — `params/seed_blocks.json` (`tuning_seeds` / `holdout_seeds`, disjoint, committed)
- [x] T4.5 — `tools/arena.py` CLI (`--opponent`, `--seeds`, `--jobs auto`, gated `--holdout`)
- [x] **Checkpoint 4** — `SPEC-harness.md` Testing section all passes (135/135 full suite);
      re-measured through the real paired-seat harness on the full 50-seed working
      (tuning) block: 50/50 paired wins vs `starter`, 50/50 vs `random` (100 paired
      seeds = 200 episodes each), win rate 1.0000, 95% Wilson interval [0.9286, 1.0000]
      both times. Commit.

## Phase 5 — `ops`: prove the bundle path, get a baseline live

- [x] T5.1 — `tools/build_submission.py`: bundle, audit (reuse gamelib boundary check), smoke-test, tar
- [x] T5.2 — Submission workflow script (`tools/submit.py`) + `--no-submit` dry run + submissions.jsonl log
- [x] T5.3 — First real submission (ask-first, human-approved at execution time)
      (submission ref 56175204, status COMPLETE. Confirmed by observation, not
      assumed: a scored submission keeps playing new public episodes on an
      ongoing basis — no fixed game count, public_score kept moving as more
      completed: 600.0 -> 296.7 -> 250.9 across the first ~20 minutes. All
      public games so far are losses (closest: 6239 vs 16388). Real, first-hand
      confirmation the field is well beyond our current policy — see project
      memory "competitive_gap_first_submission" — strengthens Phase 6's
      priority, doesn't change the plan)
- [x] **Checkpoint 5** — bundle builds/audits/smoke-tests clean; first real submission live and
      scored (ref 56175204). Commit.

## Phase 6 — `policy`: close the animal-acquisition gap

- [x] T6.1 — Unified investment choice: `decide.py`'s crop-only filter → full crop+animal ranking
      (generalize `_crop_has_time_to_mature` to animals via `forecast_animal_schedule`).
      Found+fixed a real regression during implementation: without a crop fallback for the
      not-yet-actionable animal case, a real "starter" episode stalled all planting from day 18
      onward (COW outranked MELON after our own sales), costing ~150-200 money/seed. Added a
      `_top_crop_choice` fallback; golden episodes now match Checkpoint 5 exactly again.
- [x] T6.2 — Acquisition pipeline in `tasks.py`: `BUILD_COOP`/`BUILD_PASTURE`/`PLACE` task generation,
      + fixed the verified movement inefficiency: `build_task_list` now picks the nearest empty
      tile/matching structure to any unit (via `tile_distance`) instead of the first one in
      row-major scan order; `decide()` rewired to pass real unit positions. `LAND_ORDER`-aware
      expansion ordering not done (no unlock-sequence-specific logic needed yet — distance-based
      selection already naturally prefers newly-unlocked land near the shed). Golden episodes
      unchanged (single farmer, default params - the fix mainly saves travel time, which shows up
      more with hands/expanded land; still real infrastructure, not a no-op).
- [x] T6.3 — `BUY_ANIMAL` market order in `decide.py` (mirrors `BUY_SEED`, gated on `shed_room()`).
      Rewired `decide()` to act on an animal top choice directly, removing T6.1's crop-only
      fallback (now dead code, deleted). Found+fixed a much bigger bug while measuring: a freshly
      planted one-time crop's yield_units=1 (set immediately at planting, before it's actually
      harvestable) gave HARVEST undeserved priority over PLANT/BUILD_*/PLACE, perpetually
      monopolizing the single farmer on a doomed no-op for the crop's whole maturation period —
      harmless before T6.2/6.3 added competing investments, costly once BUILD_PASTURE had to wait
      on it (5274→3932 regression, traced and fixed via `tasks._is_actually_harvestable()`). The
      fix alone (independent of animals) unlocked a much larger real improvement across all golden
      seeds (e.g. starter/seed2: 5292→13322) — re-recorded golden episodes accordingly.
- [x] T6.4 — Real-episode integration + re-measurement.
      Found+fixed 3 real bugs that together meant NO animal had ever actually produced
      anything in prior measurements: (1) PLACE/FEED consume from the acting unit's own
      inventory, never the shed BUY_ANIMAL/BUY_PRODUCT deliver to — added a PICKUP task
      (tasks.py) + gamelib.farm.shed_access_tiles(); (2) the wheat buy/sell arbitrage sold
      100% of shed WHEAT every turn, racing against PICKUP for feeding — added a
      wheat_reserve param (market.py); (3) decide() kept re-buying animals forever (a
      shifting top-choice ranking, and no "already have one" check) — a real trace found
      21 BUY_ANIMAL vs only 18 PLACEs — added two guards in decide.py (finish a stuck
      animal before anything new; never buy a second of an already-placed type). All three
      needed together before every golden seed showed a genuine improvement over T6.3
      (e.g. pass/seed1: 5510→8078). Re-recorded golden episodes; added a permanent
      real-episode invariant test confirming production actually happens. Re-measured via
      arena.py: 50/50 vs both starter/random (same as Checkpoint 5 — no regression; the
      real gap is against the Kaggle field, not these weak baselines).
- [x] T6.5 — Fix documented `BUY_SEED` gap: don't buy without an empty tile to plant on
      (also closed the analogous `BUY_ANIMAL` gap in the same pass, one shared tile scan:
      an animal needs an empty tile *or* an existing empty matching structure, not
      necessarily free land). Golden episodes unchanged — 193/193 full suite.
- [x] T6.6 — Extend `kaggle_environments`-import boundary check to `policy/` (+ `agent_main.py`).
      Renamed `tests/test_gamelib_boundary.py` → `tests/test_shipped_boundary.py`; added tests
      proving the file-scan (not just the detector) actually catches a planted violation in a
      scratch copy of `policy/` and of `agent_main.py`.
- [x] **Checkpoint 6** — full suite green (195/195). Arena re-measurement: unchanged since T6.4's
      50/50 vs starter/random (T6.5/T6.6 didn't touch runtime behavior — golden episodes identical,
      no re-run needed). Commit.

## Phase 7 — `tuning`: Stage 1 only (coordinate ascent + regression gate)

- [x] T7.1 — Regression gate (`tools/tuning.py`): held-out Wilson-interval accept/reject, tested
      against a synthetic worse/better candidate (+ a numerically-higher-but-overlapping case)
- [x] T7.2 — Coordinate-ascent loop, tested on a toy 2-parameter objective before the real arena
      (single-param sweeps, a correlated-group sweep, and a fixed-point/no-regression check)
- [ ] T7.3 — Opponent panel (starter/random/previous-best snapshot) + eval-only params override hook
- [ ] T7.4 — Run the sweep (hiring-count question first); each accepted change its own commit +
      fresh `ops` submission
- [ ] **Checkpoint 7** — `SPEC-tuning.md` Testing section passes; ≥1 accepted held-out-gated
      `params/policy.json` update exists. Commit.

## Not planned yet (see plan.md)

`fastsim` (no evidence the arena is the bottleneck) and `tuning` Stage 2 (search-generated value
targets — gated behind a Stage-1 baseline that doesn't exist yet).
