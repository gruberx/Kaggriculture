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
- [x] T7.3 — Opponent panel (starter/random/previous-best snapshot) + eval-only params override.
      Deviated from the plan's tentative env-var hook: found a real caching hazard (a wrapper
      that `import kagg.agent_main` would get that import cached process-wide, silently reusing
      the first candidate's params for a second one compared in the same process — exactly the
      "candidate vs previous-best" case). Fixed by copying `agent_main.py`'s real source with its
      params-load line patched, never importing it as a module — full fidelity, no shared state.
- [x] T7.4 — Ran the sweep (hiring-count question first). Found a real methodological bug along
      the way: blending win rate across starter/random (near a 100% ceiling for any reasonable
      policy) with self-play against the baseline dilutes the signal so heavily that a candidate
      which *loses* to baseline head-to-head (0.34) can still look like an improvement on the
      blended aggregate (0.78 vs 0.667) — see `strategy.py`'s `_DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY`
      comment. Pure self-play against baseline is the real signal. Result: `hires_per_day` stays 0
      (every value >0 tried lost consistently, 0.03-0.17 win rate — confirms the forum's own
      "hiring has ~zero/negative marginal value" finding). **Accepted**: `land_purchase_threshold_money`
      5000 → 10000 — 50/50 wins on both the working block and the held-out block (95% Wilson
      interval [0.929, 1.0] each). A second bug found while writing the reusable sweep script
      (`tools/run_hiring_sweep.py`) — a hand-typed degenerate `(0.0, 0.0)` Wilson interval for the
      baseline-vs-itself case spuriously let `coordinate_ascent` walk to a bad `hires_per_day=3` —
      was correctly caught and rejected by the held-out gate itself (no bad change reached
      `params/policy.json`), then fixed in the script. Golden episodes re-recorded (real
      improvement across every seed, e.g. pass/seed1: 8078 → 12309). Fresh `ops` submission: ask
      the user first (T5.3's same ask-first discipline applies to every submission, not just the
      first).
- [x] **Checkpoint 7** — `SPEC-tuning.md` Testing section passes; 1 accepted held-out-gated
      `params/policy.json` update exists (`land_purchase_threshold_money` 5000 → 10000). 217/217
      full suite. Commit.

## Phase 8 — movement, land gating, and making labor actually work

Real submission `56184182` scores ~9,400-13,600 vs the field's 76,000-102,000 (~8x gap). User
observations from watching real replays, all confirmed against code + real env source: (1) land
bought while free tiles remain — `should_buy_land` never checks occupancy; (2) work runs in a line
away from the shed, not a compact sweep — `tasks.py`'s sort never uses distance, and `_closest_pos`
anchors placement to the farmer's *current* position, not the shed; the env teleports the farmer to
spawn and dumps all inventory to the shed every day, so travel-from-shed is repaid daily; (3) no
extra staff hired — `hires_per_day=0` was set by T7.4's sweep, but that sweep ran against code where
a hand taking the wheat PICKUP starves animals forever (per-unit inventory, `decide.py` only reads
`inventories[0]`) and expansion is capped at 1 task/turn so hands have nothing to do. Hiring is
economically near-free (one-time `fib(n)` cost, no wage, ~$360 for 5 units all season) so this is
likely the single largest lever. **Blocker found while planning**: code-vs-code self-play is
currently impossible (editable install always wins the import over any bundle/snapshot on
`sys.path` — verified directly), so a measurement instrument (T8.0) must land first. Full story,
verified line numbers, and the design rationale: `/root/.claude/plans/partitioned-puzzling-blossom.md`.

- [x] T8.0 — Code-snapshot opponent. Added `tools/tuning.py::write_code_snapshot_agent` (copies
      `gamelib/`, `policy/`, `params/policy.json`, `__init__.py` under a unique `kagg_snap_<uuid>`
      package name and rewrites every `from kagg.` import to match - verified this is the *only*
      import spelling in `src/`) and `snapshot_agent_from_git_ref` (same, from a `git archive` of a
      given ref). Confirmed the blocker was real: a naive same-name copy is silently ignored
      because `kagg` is editable-installed onto `sys.path` at interpreter startup, ahead of where
      `kaggle_environments`'s loader appends a raw agent file's own directory - verified directly
      (`sys.path` order: `[...python stdlib..., site-packages, .../repo/src]`, then the loader's
      `sys.path.append(exec_dir)` lands *after* that). A RED test using the naive approach would
      have silently run the live `decide()` instead of a sentinel stub; the package rename fixes it,
      confirmed by 4 new tests including one loading two independently-sentineled snapshots in one
      process (the exact "candidate vs previous-best in one multiprocessing worker" shape) and one
      confirming a snapshot of unmodified code ties the live agent exactly, 0 wins either side.
      Also fixed the identical blind spot in `tools/build_submission.py`'s smoke test: it ran
      in-process, so it *always* resolved `kagg` to the live dev tree regardless of what the bundle
      actually shipped - a bundle missing its entire `kagg/` package still reported a false pass.
      Reproduced with a real RED test (bundle = `main.py` only, no `kagg/`, old code said `ok=True`)
      and fixed by running the smoke episode in an isolated subprocess that strips the editable
      `src/` entry from `sys.path` and asserts the resolved `kagg.__file__` is actually under the
      bundle's own directory. 222/222 full suite (5 new tests), compileall clean.
- [x] T8.1 — Shed-anchored investment placement. Added `gamelib.farm.shed_distance`, a
      `_compact_position` placement key in `tasks.py`, and `params["investment_anchor"]`
      (`"SHED"`/`"UNIT"`). Found and fixed a real bug in the implementation itself: an early version
      used a `(distance, pos)` tie-break for BOTH anchors, but `"UNIT"` is meant to reproduce
      `_closest_pos`'s exact old behavior (first-in-scan-order among ties) - the new tuple tie-break
      silently changed 2/6 golden episodes even with the old anchor selected. Caught by re-verifying
      golden reproduction under `anchor="UNIT"` before trusting the SHED-vs-UNIT comparison; fixed by
      having `"UNIT"` delegate to `_closest_pos` verbatim instead of reimplementing it.
      **Major deviation from the plan, found by measuring rather than assumed away**: a real direct
      self-play block (SHED vs UNIT, 50 working seeds) showed SHED *losing* 13/50 (Wilson
      [0.159, 0.396]). Traced (turn-by-turn action-count diagnostic, not guessed) to a real,
      pre-existing bug SHED's efficiency gains amplified: `_top_investment_choice` returns one
      overall pick, so an animal that's already fully placed and simply producing can keep ranking
      #1 forever (`rank_portfolio` has no notion of ownership) - `plant_crop` stayed `None` the whole
      time, and one representative episode spent 47/719 turns on PASS once this triggered. This is
      exactly the gap the plan's own T8.9 (originally scheduled for Stage B) describes - pulled
      forward and fixed now (`_top_crop_choice` reintroduced as an independent second signal
      alongside `_top_investment_choice`; `BUY_SEED`/`BUY_ANIMAL` decoupled from an `elif` into two
      independent `if`s; new `params["plant_while_pursuing_animal"]`). With that fix, SHED+T8.9
      *won* the working block decisively (0.72, Wilson [0.583, 0.825]) - but did **not** survive the
      held-out block (0.56, Wilson [0.423, 0.689], formally **rejected** by `tuning.accept_candidate`
      against an even-odds baseline) - SPEC-tuning.md's regression gate doing exactly its job.
      Measured T8.9 in isolation too (UNIT anchor, no placement change): also a real loss on its own
      (0.26 working / 0.46 holdout) despite fixing a genuine, demonstrated defect - the working
      hypothesis (not fully confirmed) is that the extra seed purchase competes for cash against a
      more valuable animal purchase. **Decision**: both `investment_anchor="SHED"` and
      `plant_while_pursuing_animal=True` are real, fully tested capabilities, shipped as opt-in
      params defaulting to today's exact behavior (`"UNIT"` / `False`) - not flipped as the default
      on working-block evidence alone, matching this project's core discipline. Shipped agent
      behavior is unchanged (golden table reproduces bit-identical, no re-record needed). Revisit
      after T8.2 (distance-aware assignment), which may be what the combination is actually waiting
      on - noted in decide.py's own comments. 234/234 full suite, compileall clean.
- [x] T8.2 — Distance-aware, tier-local task assignment. `build_task_list`'s final sort changed to
      `(priority, pos)` (deterministic, unit-independent); `assign_units` rewritten as tier-by-tier
      greedy nearest-match, tie-break `(distance, task.pos, unit_index)`. Stability under
      `decide()`'s statelessness proved in the plan file (a unit's assigned task remains a minimizer
      as it steps toward it) and confirmed by a real test that steps units 12 times and checks the
      assignment never flips mid-walk. **The single biggest accepted change of Phase 8 so far**:
      direct self-play against the pre-T8.2 snapshot won 49/50 on the working block and 48/50 on the
      held-out block (95% Wilson [0.895, 0.996] and [0.865, 0.989]) - formally accepted by
      `tuning.accept_candidate` against an even-odds baseline on both. Golden table re-recorded (4/6
      seeds improved substantially, e.g. pass/seed2: 10299 → 19168; 2/6 dipped slightly - consistent
      with a large-majority, not unanimous, win).
      **Resolved T8.1's open question, and the answer was the opposite of the hypothesis**: re-tested
      `investment_anchor="SHED"` + `plant_while_pursuing_animal=True` on top of T8.2 expecting them to
      finally pay off - instead they now *lose decisively* (working 0.28, holdout 0.18). T8.2's
      distance-aware servicing already keeps the farmer on the nearest urgent tile regardless of the
      plot's shape, so T8.1's shed-anchored placement and T8.2's smart servicing overlap rather than
      compose. Both toggles stay off by default (documented in decide.py's own comments); this
      question is now closed, not deferred. 237/237 full suite, compileall clean.
- [ ] T8.3 — Land purchase gating (`should_buy_land` gains occupancy-aware gates, both defaulting
      to today's ungated behavior; swept values are explicitly provisional, pending Stage B).
- [ ] **Checkpoint 8A** — suite green, golden table re-recorded, bundle built + submitted, real
      episode scores recorded.
- [ ] T8.4 — `Task.unit_index` + inventory pinning (wheat/animal PICKUP, FEED, PLACE pinned to
      unit 0; pinned-first rule in `assign_units`; diagnostic episodes with `hires_per_day=4`
      forced, checking the pipeline actually reaches production).
- [ ] T8.5 — HIRE order priority (`hires + sells + tail`, buys slot-reserved but emitted after
      sells to avoid seeing pre-sale money).
- [ ] T8.6 — Parallel planting + batched seed purchase, bounded by `seeds_on_hand` (atomic PLANT
      validation — load-bearing), `max_plants_per_unit` (real watering-capacity guard), and
      `max_plant_tasks_per_turn`. Must be bit-identical to today at `hires_per_day=0`.
- [ ] T8.7 — Re-run the hiring sweep (direct self-play only, no panel blending). Prediction stated
      up front: if `hires_per_day=0` still wins after T8.4/T8.6, the bottleneck isn't labor —
      that's the most informative possible negative result here.
- [ ] T8.8 — Re-sweep land (`land_purchase_threshold_money` and T8.3's gates) now that labor works
      — the Phase 7 value was fit to a 1-unit farm and is likely stale.
- [x] T8.9 — Pulled forward into T8.1 above (found to be tightly coupled to it, not a separable
      stretch goal after all). Decouples plant-crop choice from animal-acquisition choice via
      `params["plant_while_pursuing_animal"]`; shipped as opt-in, not the default - see T8.1's entry
      for the full measured story.
- [ ] **Checkpoint 8B** — suite green, bundle built + submitted, real episode scores recorded.

## Not planned yet (see plan.md)

`fastsim` (no evidence the arena is the bottleneck) and `tuning` Stage 2 (search-generated value
targets — gated behind a Stage-1 baseline that doesn't exist yet).
