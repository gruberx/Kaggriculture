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
- [x] T8.3 — Land purchase gating. `should_buy_land` gains two OR'd, occupancy-aware gates
      (`land_buy_max_free_tile_fraction`, `land_buy_min_frontier_distance`), both defaulting to a
      no-op (1.0 / 99) so the mechanism alone is behavior-preserving - golden table unchanged at
      defaults, confirmed. `decide()`'s existing tile scan extended to supply real
      `free_tiles`/`unlocked_tiles`/`nearest_free_shed_distance`.
      **Swept immediately (not deferred) - a decisive result, not a marginal one**: every tested
      `land_buy_max_free_tile_fraction` value (0.6, 0.4, 0.25, 0.1) beat the ungated default **50/50**
      on the working block; confirmed **50/50** again on the held-out block for the chosen value
      (0.25), formally accepted by `tuning.accept_candidate` against an even-odds baseline. Traced the
      mechanism directly (not just trusted the number): with the gate enabled, `BUY_LAND` never fires
      at all in real episodes checked, the farm stays on the 25-tile NW quadrant, and final money
      rises ~34-35% (e.g. seed 100: 18718 -> 25082). Confirms the plan's own reasoning precisely - a
      single farmer cannot productively work even one full 25-tile quadrant (one investment task per
      turn, one farmer to service it), so every dollar spent unlocking more land is pure waste right
      now. **Accepted**: `land_buy_max_free_tile_fraction` 1.0 → 0.25 (explicitly provisional per the
      plan - fit to a 1-unit farm, T8.8 must re-sweep once labor works). `land_buy_min_frontier_distance`
      stays disabled (99) - no evidence yet it's needed once the fraction gate already prevents nearly
      all land purchases. Golden table re-recorded for the accepted value. 242/242 full suite (13 new
      tests total across strategy/decide), compileall clean.
- [x] **Checkpoint 8A** — 248/248 suite green (at the time), golden table re-recorded, bundle built
      and audited clean. Submitted as ref `56186320` (commit `5bd0336`) after explicit user
      go-ahead. Real public episodes: ~8,300-25,700 across 14 games (6 wins / 8 losses).
- [x] T8.3b — Isolated `investment_anchor` and `plant_while_pursuing_animal` on top of T8.2+T8.3,
      prompted directly by the user watching `56186320`'s real replays and reporting the exact two
      symptoms these two disabled toggles were built to fix (animal structures built far from the
      shed at the end of a long line; crop production stopping mid-game once animals appear).
      Re-read the actual measurement history first and found the prior "both stay off" conclusion
      was drawn from a **confounded** test (SHED+fallback tested only as a bundle after T8.2) plus a
      **stale** one (the fallback alone was only ever tested before T8.2/T8.3 existed) - not clean
      evidence against either mechanism on its own. Ran the real, isolated comparisons:
      `investment_anchor="SHED"` alone lost **0/50 on both blocks** - *worse* than the original
      pre-T8.2 result, traced directly (action-count diagnostic) to SHED re-triggering the exact
      "animal ranks #1 forever" bug even harder, since it speeds the animal pipeline up enough to
      lock it in as top choice sooner (one seed: PASS actions jumped to 266/719 turns).
      `plant_while_pursuing_animal=True` alone **won 50/50 on both blocks** - a clean, decisive,
      properly-isolated result the codebase never actually had before. Also checked the combination
      one more time on current code: SHED+True beats doing nothing (0.78/0.80) but loses decisively
      to UNIT+True (0.10/0.02) - traced to SHED trading away crop-tending efficiency for animal-
      tending efficiency, a net loss since crops are still the bigger income source. **Accepted**:
      `plant_while_pursuing_animal` False → **True** (kept in sync across `decide.py`'s module
      constant, `DEFAULT_PARAMS`, and `params/policy.json`). `investment_anchor` stays `"UNIT"` - a
      clean rejection of `"SHED"` now,
      not "unproven." The user's placement/line-shaped-growth observation is confirmed real but
      **not resolved** by the built mechanism - noted honestly as still open (a differently-shaped
      fix, e.g. anchoring animal structures and crop plants independently, is the likely next idea,
      not yet built or scoped). Golden table re-recorded (conditional fix - 2/6 seeds jumped
      substantially where an animal actually locked in as top choice, e.g. starter/seed1: 18242 →
      25204; the rest near-unchanged). 248/248 full suite, compileall clean.
- [x] T8.3c — Designed together with the user in direct response to T8.3b's honest "SHED doesn't
      pay for itself" finding, and to their own follow-up proposal for a better placement rule.
      Traced the actual root cause precisely: `_closest_pos` (what `anchor="UNIT"` delegates to)
      already picks the tile nearest the farmer correctly, but breaks ties among equidistant
      candidates by **row-major scan order** - which has no relationship to the shed and is exactly
      what drove the marching-line pattern. SHED's mistake (T8.1) was replacing the whole primary
      key, not just the tie-break, which is what cost it real travel efficiency.
      **New anchor `"UNIT_TOWARD_SHED"`**: keeps distance-to-farmer as the primary key (identical to
      plain UNIT - provably never a worse detour, since tied candidates share the same
      farmer-distance by construction) and only changes the tie-break to `shed_distance` instead of
      scan order. A user-proposed continuous-coordinate formula (`|4.5-x|+|4.5-y|`) turned out to be
      algebraically identical to the already-implemented `shed_distance` up to an irrelevant +1
      constant - confirmed before writing any code, so no new geometry was needed. Two other
      refinements agreed with the user before implementing: no new state (the user's original design
      used each unit's "last movement direction," which `decide()` deliberately never tracks - a
      turn-number-based stateless rotation was considered and explicitly dropped in favor of a
      simple final `(x,y)` tie-break, since a rotating direction doesn't classify cleanly for a
      *global* argmin the way it does for immediate neighbors); and reused the existing global
      `empty_tiles`/`_compact_position` machinery rather than writing new local ring-expansion
      pathfinding, since nothing in this game blocks movement (units can walk through
      occupied/LOCKED tiles), so a local greedy walk and a global argmin converge to the same result.
      **Measured: 50/50 wins on BOTH self-play blocks** against the previously-shipped default - the
      single cleanest result of this whole investigation. Traced, not just trusted: every seed
      checked did strictly more WATER/PLANT/HARVEST and fewer PASS turns than the old default in the
      same episode (e.g. seed 100: 24862 → 26507 money). **Accepted** as the new
      `investment_anchor` default (kept in sync across `decide.py`'s module constant,
      `DEFAULT_PARAMS`, and `params/policy.json`). Golden table re-recorded - all 6 seeds improved
      this time (e.g. starter/seed3: 21486 → 25422), unlike T8.3b's conditional fix: this is a
      structural travel-efficiency improvement that applies in every game. 251/251 full suite (3 new
      tests), compileall clean, boundary check green.
- [x] T8.3d — The user's own observed defect from watching real Checkpoint 8A replays: shed stock
      still unsold when the episode ends is a total loss, not a deferred sale. Confirmed directly in
      the real `kaggriculture.py` engine (not assumed): the episode's `reward` is final money only
      (`s.reward = float(obs0.farms[...]["money"])`), and there is no auto-liquidation of leftover
      shed inventory anywhere in `interpreter()`. `market.sell_orders`'s margin check and
      `PREMIUM_GOODS` drip cap both exist to protect *future* turns (holding out for a price recovery;
      not crashing tomorrow's price) - neither protection makes sense once there is no future turn
      left to sell into.
      **Fix:** a new `liquidate: bool` parameter threading through `market.sell_orders` →
      `market.market_orders`, set by `decide()` once `current_day >= season_length_days -
      liquidation_days_before_end` (new `params["liquidation_days_before_end"]`, default 2). When
      true, the margin check is skipped entirely (sell at any positive price - `PRICE_FLOOR`
      guarantees > 0) and the drip cap is lifted (full shed count in one order instead of 5/turn).
      **Measured:** 2 (mechanism on) vs 0 (mechanism off, i.e. yesterday's shipped behavior) - **50/50
      on both the working block (seeds 100-149) and the held-out block (seeds 900-949)**, a clean,
      expected win (this is close to free money the old code was leaving on the table). 2 days is also
      mechanically justified on its own: `shedCapacity=100` fully drains in well under a day even at
      a much smaller order size, so 2 days x 24 turns/day is a comfortable buffer, not a number fit to
      the self-play seeds.
      **A real lead found but deliberately NOT chased here:** a follow-up head-to-head sweep over
      `liquidation_days_before_end` in {1, 2, 3, 5, 7, 10, 15, 30} (working block only) found win rate
      keeps climbing the larger the window gets, all the way up to 30 (i.e. the drip cap effectively
      disabled for the *entire* season, not just the end). That is a materially different, unreviewed
      change - the `PREMIUM_GOODS` drip cap turning out not to earn its keep at all under current
      single-farmer conditions, vs. the narrow "liquidate near the end" fix actually asked for here -
      and deserves its own dedicated investigation (candidate: T8.3f or later), not scope creep into
      this task. Golden table unchanged (none of the 6 recorded seeds happened to hit a
      margin-blocked or drip-capped sale in the last 2 days under these exact params). 257/257 full
      suite (7 new tests), compileall clean, boundary check green.
- [x] T8.3e — The user's own observed defect from watching real replays: FERTILIZER was only ever
      collected (`COLLECT_FERTILIZER`) and sold as an ordinary `PRODUCT`, never applied via the real
      `FERTILIZE` action - confirmed directly in `kaggriculture.py`: `FERTILIZE` doubles the yield
      bonus (via `_daily_refresh_plants`/the WATER handler, both gated on `was_watered` - "basic needs
      first") for the day of application plus the following two (`fertilized_until_day = max(existing,
      day+2)`).
      **Built:** a new `FERTILIZE` task in `tasks.py` (fires when the farmer holds ≥1 FERTILIZER and
      the target tile isn't already actively fertilized - gated on `fertilized_until_day < current_day`
      so a second application while one is still active can never be a wasted no-op unit), plus a
      `market.py` change excluding FERTILIZER from the routine sell loop (it exists to be applied, not
      liquidated on sight - `liquidate`, T8.3d, still sells any leftover once there's no time left to
      ever use it). Both gated by one new `params["use_fertilizer"]` flag for a clean, fully-isolated
      self-play comparison.
      **Measured — a real, decisive rejection, not an acceptance**, mirroring the SHED anchor's own
      history (a plausible-sounding mechanism that still needs real evidence): at
      `PRIORITY_ROUTINE_CARE` (tied with WATER, outranking PLANT) it lost 0/50 on the working block and
      0/50 on the held-out block - every non-tied episode a loss. Re-tried at `PRIORITY_MAINTENANCE`
      (same tier as `COLLECT_FERTILIZER`, below PLANT) on the theory that ROUTINE_CARE was crowding out
      higher-value work - still 0/4 and 0/3 losses (fewer episodes differed at all, but zero favored
      fertilizing). **Traced, not just trusted** (seed 117): the fertilize-enabled agent completed
      *fewer* total `COLLECT_FERTILIZER` actions over the whole game (4 vs 5) than the identical code
      with the mechanism off - `FERTILIZE` and `COLLECT_FERTILIZER` share the same `PRIORITY_MAINTENANCE`
      tier, so a second consumer of the farmer's already-scarce lowest-priority turns directly dilutes
      `COLLECT_FERTILIZER`'s own throughput, losing more sale income than the rare successful
      `FERTILIZE` application won back. A real single-farmer capacity limit, not fixable by priority
      tuning alone.
      **Shipped default: `use_fertilizer=False`** (`DEFAULT_PARAMS`, `params/policy.json`,
      `decide.py`'s `_DEFAULT_USE_FERTILIZER`) - the mechanism stays in the codebase, tested and
      available (`use_fertilizer=True`), kept for a future re-check once T8.6/T8.7 give a second unit
      real spare MAINTENANCE-tier capacity, not deleted outright. Golden table unchanged (default
      behavior is bit-identical to before this task). 265/265 full suite (10 new tests), compileall
      clean, boundary check green.
- [x] T8.3f — The user's own proposal (price-aware crop/production diversification) plus a
      clarifying question (can we see the opponent's production?) that surfaced real facts worth
      recording: `obs["farms"]` is one shared list visible identically to both players (tiles, crops,
      animals, money, positions all visible), only `private` (shed/seeds) is per-player - and the
      user's recollection that premium goods react sharper to overproduction is exactly the
      `above_target` coefficients already encoded in `PREMIUM_GOODS` (MELON 3.60, WOOL 3.20 vs WHEAT
      0.20, CARROT/TOMATO 0.60-0.70). Scoped, with the user, to *own* self-impact first (no opponent
      modeling yet).
      **A real mid-implementation pivot, reported honestly rather than shipped quietly:** the first
      version walked a single tile's own future yield against its own price
      (`crop_revenue_per_tile_day`'s per-unit lockstep pricing, mirroring the real engine's SELL
      quoting) - measured this alone is real but numerically negligible (one melon tile's 6-unit run:
      250 -> 250 unchanged), since the market's elasticity scale (`T`) is calibrated to a whole farm's
      output, not one tile's. Reported this finding back to the user, who chose the corrected fix:
      account for how many tiles of a crop are **already planted on the farm** (measured: 20 melon
      tiles already growing crashes even the *next* tile's own average price from 250 to 46; 30 tiles
      crashes it below every other crop's).
      **Built:** `rank_portfolio`/`crop_revenue_per_tile_day` (`strategy.py`) gained a
      `crop_tile_counts`/`already_committed_units` argument; `decide.py` scans the farm's own tiles
      (`_crop_tile_counts`) and feeds the counts through, gated by a new `params["crop_self_impact_aware"]`
      flag for a clean self-play A/B. Scoped to crops only (animals deferred - their lifetime yield is
      intentionally unbounded, so there's no natural total to walk without picking an arbitrary
      horizon). Opponent visibility explicitly deferred too, per the user's own scoping choice - a
      real, documented next step, not forgotten.
      **Measured: 50/50 wins on BOTH self-play blocks** against the mechanism disabled. Traced, not
      just trusted (seed 100): the self-impact-aware agent planted MELON only 16 times before
      switching to STRAWBERRY for its remaining 7 plantings ($21452 final); the old code kept planting
      MELON 23 times (crashing its own realized price) plus cheap CARROT/WHEAT fallbacks once MELON's
      price cratered ($17765 final) - real structural diversification, not a marginal tuning gain.
      **Accepted** as the default (`crop_self_impact_aware=True`). Golden table re-recorded - 4 of 6
      seeds changed (both directions, since this changes *what* gets planted). 272/272 full suite (11
      new tests), compileall clean, boundary check green.
- [x] T8.3g — The user's direct follow-up to T8.3f: extend the same self-impact model to also
      count the OPPONENT's already-planted tiles, not just our own - confirmed feasible first
      (`_combined_crop_tile_counts`'s own docstring): `obs["farms"]` is one shared list object,
      verified directly in `kaggriculture.py` to be assigned identically to both players (only
      `private` shed/seeds are genuinely per-player), so the opponent's crop tiles are exactly as
      visible as our own, at zero extra cost to reuse T8.3f's existing `crop_tile_counts` machinery
      (sum both farms' counts before ranking, no `strategy.py` changes needed at all).
      **Measured — a real, decisive rejection, not an acceptance:** a clean, total loss (0/50 on the
      working block, 0/50 on the held-out block) - worse than T8.3e's FERTILIZE rejection, which at
      least tied most episodes. Traced, not just trusted (seed 100): the opponent-aware agent switched
      from MELON to STRAWBERRY after only 14 MELON plantings (vs the unaware agent's 17), ending with
      *less* money ($19463 vs $23092) despite "diversifying more correctly" by the model's own logic.
      The underlying idea is real (the market genuinely is shared - confirmed directly, not assumed) -
      the flaw is in this implementation's crude size estimate: it prices every visible opponent tile
      at its full remaining `total_yield`, exactly like T8.3f does for our own tiles, but that
      approximation only worked for our own tiles because we directly control our own planting
      schedule (naturally time-clustered); an opponent's tile carries no timing information at all
      (real age or expected harvest day) in this model, so it overcounts an opponent's tile as fully
      overlapping with our own upcoming harvest regardless of real overlap - double-penalizing shared
      popular crops into premature abandonment.
      **Shipped default: opponent contribution ignored** (an all-or-nothing `crop_self_impact_
      include_opponent` flag, superseded in T8.3h below by a graduated weight - see that entry) - the
      mechanism stays in the codebase, tested and available, kept for a real, not-yet-built refinement
      (weighting an opponent's tile by its own forecasted remaining yield/timing instead of a flat
      full `total_yield`) rather than deleted outright. Golden table unchanged (default behavior is
      bit-identical to T8.3f). 276/276 full suite (7 new tests), compileall clean, boundary check
      green.
- [x] T8.3h — The user's own proposed refinement to T8.3g's rejection: instead of an all-or-
      nothing opponent flag, graduate it - discount the opponent's tile-count contribution by a
      continuous `crop_self_impact_opponent_weight` (0.0-1.0), on the theory that partial credit
      for "the opponent probably will eventually sell some of this" might beat both the 0.0 and 1.0
      extremes. The user also asked two grounding questions along the way, both answered directly
      from the code rather than assumed: (1) current market prices ARE already the baseline for
      every forecast (`sell_at_inventory` is the real, current `market_inventory` level; the self-
      impact walk only adds *future*, not-yet-sold production on top of it) - no separate "current
      price" gap existed to close; (2) the crop-switch decision was already a real $-vs-$
      quantitative comparison (`rank_portfolio`'s scores are directly comparable dollar amounts), not
      a naive "opponent planted something -> panic switch" heuristic, and reallocation across the
      farm is already inherently gradual (one new tile decided per planting opportunity, existing
      tiles never uprooted) - T8.3g's problem was mis-calibration of the estimate, not an all-or-
      nothing switching *mechanism*. Also answered two side questions plainly: yes, animal products
      are scored too (`rank_portfolio` includes `animal_revenue_per_tile_day`), but the self-impact
      fix is scoped to crops only (documented gap, same reason as before - unbounded animal
      production has no natural total to walk); and no, the policy does not read `obs["town"]` at
      all currently, so town-shop-driven consumption boosts (`SHOPS` in `kaggriculture.py` - e.g.
      YARN_STORE raises WOOL demand, PET_CAFE raises CARROT demand) are a real, completely unused
      forward-looking signal - flagged as a genuine separate future opportunity, not attempted here.
      **Built:** replaced T8.3g's boolean flag with `_combined_crop_tile_counts(my_tiles,
      other_farms, opponent_weight)` - our own tiles always count at full weight; the opponent's
      count is scaled by `opponent_weight` before being added in.
      **Measured — still a rejection, and an informative one:** swept 0.1/0.25/0.5/0.75/1.0 against
      the 0.0 baseline (working block, 50 seeds each). No weight wins outright: 0.1 -> win_rate 0.480
      (24W/3L/23 ties, Wilson [0.35, 0.61], overlapping 0.5 - not even a point-estimate win); 0.25 ->
      0.020 (1W/49L); 0.5 -> 0.200 (10W/40L); 0.75 -> 0.040 (2W/48L); 1.0 -> 0.000 (0W/50L, T8.3g's own
      result). No clean U-shape where a small weight helps - graduating the discount only softens how
      badly the mechanism loses, it doesn't rescue it, confirming the real flaw is the complete
      absence of *timing* information about the opponent's tiles, not merely the *size* of the
      discount applied to a timing-blind estimate.
      **Shipped default: `crop_self_impact_opponent_weight=0.0`** (unchanged from T8.3f's own
      behavior) - the graduated mechanism stays in the codebase, tested and available at any weight,
      for a genuinely different future refinement: a signal-based approach (only trusting the
      opponent term when the *observed* market price already shows movement unexplained by our own
      activity - the user's own follow-up idea) that this sweep did not attempt, since it needs new
      information this stateless `decide()` doesn't currently derive. Golden table unchanged (default
      behavior is bit-identical to T8.3f/T8.3g). 278/278 full suite (renamed/added tests), compileall
      clean, boundary check green.
- [x] T8.3i — The user's own follow-up question, arising directly from the T8.3g/T8.3h
      discussion: does the agent already account for elevated town-shop demand, or only react once
      the price has already moved? Answered by reading the code, not assuming: purely the latter -
      `market_inventory` already reflects any consumption a shop has *already* caused (the same
      shared object `_town_consume` mutates, and `rank_portfolio` already reads it), but
      `obs["town"]["unlocked_shops"]` was never read anywhere in this codebase before this task, so
      nothing looked ahead to what a *currently* unlocked shop will keep consuming for the rest of
      the game. Also recorded the user's related observation along the way: hiring (T8.4-T8.7) will
      speed up production and should already be handled correctly by T8.3f's self-impact mechanism
      (it counts real current tiles, not planting rate) - flagged in "Not planned yet" below for a
      real re-validation once hiring actually works, not assumed safe without checking.
      **Built:** `SHOPS`/`TOWN_CENTER_PRODUCTS`/`MAX_SHOP_INSTANCES` added to `gamelib/constants.py`
      (oracle-verified byte-for-byte against the real engine, new tests in `test_gamelib_market.py`);
      `gamelib.market.expected_daily_consumption(product, unlocked_shops, ...)` mirrors
      `_town_consume`'s own math (town center's constant per-product draw plus each unlocked shop's
      per-instance draw, doubled for YARN_STORE/PET_CAFE's single-product shops); wired into both
      `crop_revenue_per_tile_day` *and* `animal_revenue_per_tile_day` (unlike T8.3f/g/h's crop-only
      self-impact scope - a consumption estimate needs no bounded lifetime total the way self-impact-
      from-production does, so animal products like WOOL/MILK/EGG are included here) as a negative
      offset to the same starting inventory the self-impact walk already uses. Gated by
      `params["crop_shop_demand_aware"]` for a clean self-play A/B.
      **Measured: a strong, decisive win** - 49/50 on the working block and 48/50 on the held-out
      block, the second-strongest result of the whole investigation (after T8.3c). Traced (seed 100,
      8 shops unlocked by season end - PIZZA_SHOP x3, SMOOTHIE_SHOP x2, FARMERS_MARKET x2,
      BRUNCH_SPOT): the shop-aware agent diversified its post-MELON fallback into TOMATO and CARROT
      (both drawn down by the unlocked shops) instead of STRAWBERRY (the unaware agent's plain
      crop-only leader with no shop information) - $24078 final vs $21424, a real ~12% gain from
      knowing which goods have elevated demand, not a marginal tuning improvement.
      **Accepted** as the default (`crop_shop_demand_aware=True`). Golden table re-recorded - 5 of 6
      seeds changed. 294/294 full suite (new tests across `test_gamelib_market.py`,
      `test_policy_strategy.py`, `test_policy_decide.py`), compileall clean, boundary check green.
- [x] T8.3j — Documentation-only, no code/behavior change: the user asked two grounding
      questions after T8.3i (does self-impact cover animal products; where did the SHOPS table come
      from) that surfaced a real gap - `SPEC.md` had been referencing "the economic analysis" by
      name since Phase 7-8 (e.g. "premium goods look great until you check market depth") but no
      such section actually existed anywhere in the repo. Fetched the competition's own Overview
      page directly (`mcp__kaggle-mcp__list_competition_pages`, not `WebFetch` - the page is a
      client-rendered SPA and returns only a bare title over plain HTTP) and cross-checked it
      against `kaggriculture.py`: every number in `MARKET_PARAMS` matches exactly, but the Overview
      page adds real design intent the source code's bare tables don't state - what `T` actually
      *is* (a full 5x5 field's 24-day production capacity, not an arbitrary curve-fit knob), the
      "premium goods" classification (`above_target > 1`) and why it matters strategically, and
      worked example prices (`P(I0-T)`/`P(I0+T)`/`P(I0+2T)`) per resource.
      **Added a new "Economic analysis" section to `SPEC.md`** (between "Capability map" and
      "Environment") with the full per-resource table and two concrete, unexploited leads recorded
      for later implementation, not built here:
      1. **`hinge`-shaped scarcity (CARROT/TOMATO/EGG)**: price stays near base under ordinary
         demand and only climbs *sharply* once a real deficit passes `T` - a fundamentally
         different opportunity shape than every other product's smooth scarcity curve, and nothing
         in `kagg.policy` currently distinguishes it (`price()` is called shape-agnostically
         everywhere, T8.3f/T8.3i's models included). A real future feature: detect an approaching
         `T`-deficit for one of these three specifically and preferentially plant it before the
         price has fully caught up.
      2. **WHEAT-for-feed cross-pressure**, the user's own follow-up on the "hiring speeds up wool
         production" question: `BUY_PRODUCT` (restocking WHEAT to feed animals) reduces the *shared*
         `market["inventory"]["WHEAT"]` exactly like a `SELL` raises it (verified directly in
         `_commit_unit`) - so (a) growing our own feed wheat instead of buying it avoids a real,
         currently-unvalued self-inflicted price cost, and (b) the opponent feeding *their* animals
         is a second, distinct kind of opponent-driven WHEAT pressure (tightening supply) from
         T8.3g/T8.3h's crop-tile one (adding supply). Also recorded precisely why WOOL/MILK/EGG
         overproduction from stacking animals is a structural non-issue *today* (a hard
         one-animal-per-type cap in `decide.py`, not price awareness) but stops being dormant the
         moment T8.4-T8.7 hiring lifts that cap.
      No tests, no measurement, no default changed - see `SPEC.md`'s new section and the "Not
      planned yet" list below for the concrete ideas to pick up later.
- [x] T8.3k — The user's own observation, arising directly from a question about whether
      buying/planting decisions already weigh cost, labor, and time: they don't - `decide.py` only
      ever used a crop's seed cost / an animal's purchase cost as an *affordability* check
      (`money >= cost`), never subtracted it anywhere in the *ranking* comparing crops/animals
      against each other. The user's own framing: time is a scarce, hard-capped resource in this
      game (a fixed 30-day season), so profitability should be **net profit per day spent**, not
      gross revenue per day spent.
      **Built:** `crop_revenue_per_tile_day` gained a `net_of_seed_cost` argument - when set,
      `CROPS[crop]["seed"]` is subtracted from the total revenue once before dividing by
      `tile_days` (the same per-day-of-scarce-time denominator the user is pointing at, now applied
      to net instead of gross proceeds). Wired through `rank_portfolio`/`decide.py`, gated by
      `params["crop_net_of_seed_cost"]`. Scoped to crops only (documented, not silently ignored):
      netting out an animal's purchase cost needs an amortization horizon this codebase doesn't
      have yet (same unbounded-lifetime problem T8.3f already hit), and there's also a real
      *recurring* feed cost (WHEAT) animals have that this doesn't model at all - left as an open,
      harder problem, cross-referenced to the WHEAT-for-feed lead already recorded in `SPEC.md`.
      **Measured, with an honest methodological finding this run itself surfaced:** unlike every
      other T8.3-series flag (which changed nearly every game's outcome), this one only changes the
      *ranking order* in a narrow crossover window - most games tie exactly (30/50 working block,
      25/50 held-out), since the gap between top-ranked options usually dwarfs any seed-cost
      difference between them. Among the games it *does* decide, the edge is real and reproducible:
      18W/2L on the working block (Wilson interval on the decided subset [0.70, 0.97]) and 21W/4L
      on the held-out block ([0.65, 0.94]) - 39W/6L combined, nowhere near the 0.5 line. Traced (seed
      104): the net-aware agent planted MELON 16 times and STRAWBERRY 7, entirely skipping CARROT;
      the gross-revenue agent planted MELON 18, STRAWBERRY 5, and CARROT 4 - CARROT's $20 seed cost
      against its own modest yield doesn't clear the bar once netted out. $19903 vs $18584 final.
      **Accepted** as the default (`crop_net_of_seed_cost=True`). Golden table re-recorded - only 2
      of 6 seeds changed this time, a smaller footprint than T8.3f/T8.3i, consistent with the
      narrow-crossover-window finding. 300/300 full suite (new tests across `test_policy_strategy.py`
      and `test_policy_decide.py`), compileall clean, boundary check green.
- [x] T8.3l — The user's own observed defect: "our agent looks like it constantly buys and sells 10
      WHEAT." Confirmed and traced in a real episode (seed 100): 147 `BUY_PRODUCT`/`SELL` pairs,
      every single turn from step 1 to 387, stopping only once the price climbed past
      `wheat_max_buy_price`. Root cause - two rules fighting with nothing to break the cycle:
      `buy_wheat_order` restocks whenever shed WHEAT falls below `wheat_restock_threshold`,
      regardless of whether anything needs feeding; `sell_orders` sells everything above
      `wheat_reserve`, which is 0 until an animal is actually placed.
      **Built:** `buy_wheat_order`/`market_orders` gained `feed_needed` (only restock when an animal
      is placed or currently the top investment choice - `decide.py` computes this from
      `placed_animal_types`/`acquisition_animal`, both already tracked there); `market_orders` also
      gained a belt-and-braces invariant that floors the *effective* wheat reserve at
      `wheat_restock_threshold` whenever feed is needed and it isn't a liquidation turn, so
      `sell_orders` can never again sell WHEAT down to a level `buy_wheat_order` immediately restocks
      - protects the fix even if the gate flag is ever disabled. Separately,
      `sell_orders`/`market_orders` gained `liquidate_wheat_reserve` (default on): a second real bug
      found while tracing the first - the feed reserve was being kept off the table even during
      end-of-season liquidation (T8.3d), stranding ~10 WHEAT unsold (worth exactly $0 per T8.3d's own
      finding) once an animal had been placed.
      **A real, invalidated-and-corrected-in-place measurement, worth recording for next time:** a
      first self-play attempt (toggling both new flags off as a synthetic "old" baseline) predicted
      only a near-$0 real-game gain, reasoned from the engine's own quoting rule
      (`kaggriculture.py`: `BUY_PRODUCT` is quoted at post-buy inventory specifically so a round trip
      nets $0 - verified numerically). That measurement was **wrong, not just weak**: disabling the
      gate flag left the new reserve-floor invariant *still active* (it fires on the `feed_needed`
      value, not the flag), so the "baseline" was already getting most of the real fix, and measured
      as a near-tie against the actual candidate - invalid, not merely inconclusive.
      **The correct comparison** - this code change (`write_code_snapshot_agent`) against the real
      previously-committed code (`snapshot_agent_from_git_ref("HEAD")`), exactly how every other
      T8.3-series feature in this project has been measured - found a real, decisive, reproducible
      win: **49/50 on the working block** (Wilson [0.895, 0.996]) and **47/50 on the held-out block**
      ([0.838, 0.979]). Per-seed score deltas are not one-sided in magnitude (seed 101: +1445; seed
      103: -888) - the win is a small, consistent edge across most seeds and seatings, not one
      dominant mechanism. The clearest proximate cause traced: a same-turn WHEAT restock is queued
      ahead of `BUY_SEED`/`BUY_ANIMAL` in the market-order list, and the real engine settles a turn's
      orders strictly in list order - spending money on an unneeded restock can delay a same-turn
      seed/animal purchase when funds are tight early in the game. Not a complete accounting of the
      full measured margin, but consistent with it.
      **Accepted** as the default (`wheat_buy_only_when_feed_needed=True`,
      `liquidate_wheat_reserve=True`). Golden table re-recorded (all 6 seeds changed - the largest
      footprint of any T8.3-series flag, matching the win rate). 310/310 full suite (new tests in
      `test_policy_market.py` and `test_policy_decide.py`), compileall clean, boundary check green. A
      fresh episode trace confirms the ping-pong is gone: seed 100 now shows 7 WHEAT buy/sell pairs
      total (all genuinely feed-related), down from 147.
- [x] T8.3m — Season-remaining-aware ranking (extends T8.3k's "time is scarce" insight to the piece
      it didn't reach): `rank_portfolio` had no notion of the current day or remaining season at
      all - `_crop_has_time_to_mature`/`_animal_has_time_to_mature` only ever gate whether an
      option can produce *at all*, then score whatever survives at its full, untruncated lifetime
      revenue. Two independent mechanisms, measured in isolation per T8.3b's own lesson about
      confounded measurements:
      **Part A (`rank_season_aware`)** truncates an ongoing crop's (TOMATO/STRAWBERRY) scored
      schedule to what actually fits in the remaining season, instead of always pricing the full
      capped schedule. **Measured — a real, decisive rejection**: 1/44 working, 2/47 held-out.
      Traced (seed 101, direct self-play): correctly stops offering STRAWBERRY/TOMATO as
      `_top_crop_choice`'s late-season fallback, but the narrower fallback set gives the farmer
      less to fall back on once it hits the same pre-existing single-farmer congestion both agents
      show late-game (multiple crop seeds sitting unused, `n_plant_tiles` shrinking as harvests
      outpace replanting) - the same class of defect as T8.3e's FERTILIZE rejection. **Shipped
      default: False** (rejected, not unmeasured) - kept available for a re-check once Stage B
      relieves the congestion.
      **Part B (`animal_net_of_cost`)** nets `ANIMALS[animal]["cost"]` and the recurring WHEAT feed
      cost out of an animal's score over the remaining season (reusing
      `forecast_animal_schedule`, the same call `_animal_has_time_to_mature` already makes -
      incidentally closes the separately-recorded animal self-impact gap too), instead of scoring
      an unbounded steady-state rate. **Measured: the strongest result of the whole T8.3-series
      investigation** - 50/50 working (Wilson [0.929, 1.0]), 49/50 held-out (Wilson [0.895,
      0.996]) against the checked-in baseline. Traced (seed 101): with cost off, an animal (COW,
      then SHEEP, then GOOSE as ranks shifted) kept getting commissioned as late as day 25+ of a
      30-day season, unable to earn back its purchase cost in the days left. **Accepted as the
      default** - a real, deliberately-verified major side effect, not an oversight: once true
      cost is priced in, no animal ever tops the ranking at base market prices at any point in the
      season (checked directly across days 0-28), and animal production never occurs across 15
      real episodes checked (seeds 100-114) - the whole T6.1-T6.5 acquisition pipeline is now
      correctly avoided as economically uncompetitive under normal conditions (COW's old fictional
      steady-state rate: 80/tile-day forever; its real net rate over a full 30-day horizon: ~21/day,
      below MELON/STRAWBERRY) rather than pursued reflexively. The pipeline itself is untouched and
      still verified working (`test_at_least_one_animal_reaches_production_in_a_representative_
      episode`, now exercised with `animal_net_of_cost=False` explicitly to keep testing pipeline
      mechanics independent of today's accepted economics). Golden table re-recorded - all 6 seeds
      improved (none decreased), e.g. starter/seed1: 26386 -> 27524. 324/324 full suite (18 new
      tests), compileall clean, boundary check green.
- [x] T8.3q — The user's own follow-up: asked for the full animal production cycle explained day by
      day, then pushed back on T8.3m's implied "animals are worthless" conclusion with a real
      counter-estimate (~11 MILK units over 30 days should net real profit). Investigated by reading
      the official "How to Play" page fresh (`mcp__kaggle-mcp__list_competition_pages`) and
      `kaggriculture.py`'s `_daily_refresh_animals` directly - found the user was right, and the gap
      was real and large: two completely unmodeled revenue streams.
      **Part 1 (fertilizer by-product income)**: every placed animal sets `fertilizer_available=True`
      at the end of every surviving day regardless of feeding/care - recomputed directly, ~$2,819
      over 30 days for one animal, more than its own product revenue. Built as
      `animal_fertilizer_income_aware` (`strategy.py`'s `animal_revenue_per_tile_day`, `rank_
      portfolio`, `decide.py`). **Measured - a real, total, decisive rejection**: 0/50 on both
      self-play blocks against the checked-in baseline, contrary to this task's own stated
      prediction. Traced (seed 100, action-count diagnostic): the fertilizer-aware agent pursued and
      placed an animal the baseline never touched, but the episode shows **zero
      `COLLECT_FERTILIZER` actions the entire game** - the promised revenue never gets collected
      because the task sits at the lowest priority and the single farmer has no spare turns for it
      on top of the animal pipeline plus crop work. The same class of defect as T8.3e's FERTILIZE
      rejection.
      **Part 2 (`CARE`)**: kaggriculture.py's completely unbuilt "Animal Care" mechanic
      (`pending_care_bonus`) banks a yield bonus paid out on the animal's next scheduled production -
      exact day-by-day simulation (mirroring the real mechanic precisely, since the banking is
      genuinely path-dependent - SHEEP's 5-day pre-production banking window hits `max_held` on its
      very first tick) found this roughly doubles (GOOSE) to quadruples (SHEEP) an animal's raw
      product yield over 30 days, the single largest lever found in the whole T8.3 investigation.
      Built as a new `CARE` task (`tasks.py`, `PRIORITY_MAINTENANCE`) + `animal_care_aware`
      ranking term. **Measured - the identical result as Part 1**: 0/50 on both self-play blocks,
      traced to zero `CARE` actions ever firing, for the identical structural reason. Combined
      (both flags together): also 0/50, no confounding.
      **Shipped defaults: both False** (rejected, not unmeasured) - both mechanisms stay in the
      codebase, tested and available, for a re-check once Stage B (hired hands) gives real spare
      MAINTENANCE-tier capacity.
      **Documentation deliverable**: `tools/economic_profitability_table.py` (generates min/max net
      $/tile-day for all 9 products from real code, plus a `days_remaining` sweep showing
      profitability degrades - or cliffs - as season end approaches) feeds a new "Net profitability
      per tile-day" subsection in `SPEC.md`'s Economic analysis, directly answering the user's
      original ask. Key finding: **one-time crops are a step function** (flat until `max_yield_day`
      no longer fits, then impossible - no partial credit), **ongoing crops degrade gradually near
      the cliff**, and **animals without the two rejected mechanisms go net-negative ~10 days before
      the hard maturity cutoff**, not just at it - exactly the user's own COW/MILK example, confirmed
      directly. 345/345 full suite (31 new tests across three commits), compileall clean, boundary
      check green.
- [x] T8.4 — `Task.unit_index` + inventory pinning. Added a trailing `unit_index: int | None = None`
      field to `Task` (positional-construction-safe); pinned wheat `PICKUP`, animal `PICKUP`, `FEED`,
      `PLACE` to unit 0 (`_PINNED_UNIT_INDEX`) - the exact ops `kaggriculture.py` resolves against the
      *acting unit's own* inventory, verified directly. `assign_units` gained a pinned-first rule
      within each tier: a pinned task is matched to its exact unit if free, else dropped for the turn
      (never handed to a nearer hand, which would resolve against the wrong inventory) - preserves
      T8.2's stability argument unchanged for the unpinned remainder (same algorithm, smaller free-unit
      set). Bit-identical at `hires_per_day=0` (golden table unchanged, confirmed) - pinning only
      matters once more than one unit exists.
      **Diagnostic run** (6 episodes, `hires_per_day=4` forced, vs starter): directly falsifies half
      of T7.4's stale "hands have nothing to do" premise - hands are NOT majority-PASS (28-38% PASS
      across all 6 seeds, the rest real WATER/PLANT/HARVEST/movement work). The other half is still
      unresolved as expected: `inventories[0]["WHEAT"]` stayed empty in 5/6 seeds and animal
      production was reached in 0/6 - expected, not a red flag, since `build_task_list` still emits at
      most one new-investment task per turn regardless of hand count (T8.6's job, not T8.4's). 354/354
      full suite (9 new tests), compileall clean, boundary check green.
- [x] T8.5 — HIRE order priority. Market list assembled as `hires + sells + tail` (tail =
      BUY_SEED/BUY_ANIMAL/BUY_LAND/wheat-restock) instead of the old "sells first, HIRE dead last" -
      `HIRE` now sits at index 0, never truncated by sells crowding the 10-order cap (a hand hired at
      hour 1 instead of hour 0 loses a whole unit-day, and hour 0 - right after the end-of-day
      inventory dump - is exactly when `sells` is longest). `tail`'s cash-consuming buys still keep a
      reserved slot budget but are emitted *after* `sells` - the real interpreter's `_process_market`
      settles a turn's orders index by index, so a buy ahead of a sell would see pre-sale money.
      Switched from the combined `market.market_orders()` wrapper to calling `sell_orders`/
      `buy_wheat_order` directly (replicated `market_orders`'s own belt-and-braces reserve-floor
      invariant locally, `market.py` untouched - `sell_orders(max_orders=0)` already returns `[]`
      cleanly, no library change needed). Bit-identical at the shipped `hires_per_day=0` default
      (confirmed - full suite unchanged, golden table unchanged, the strongest form of the plan's own
      "neutral expected" acceptance criterion). 356/356 full suite (2 new tests), compileall clean,
      boundary check green.
- [x] T8.6 — Parallel planting + batched seed purchase. `_new_investment_task` → `_new_investment_
      tasks` (returns a list; the animal pipeline stays singular by design - only planting
      parallelizes). New `_compact_positions` picks up to `plant_qty` distinct tiles by calling the
      existing, already-tested `_compact_position` one at a time (never a reimplementation of its
      selection logic - the exact mistake that historically shifted golden episodes once already).
      `decide()` computes `labor_units = 1 + hires_per_day(params)`, `plant_budget = max(0,
      max_plants_per_unit * labor_units - n_plant_tiles)` (a real structural safeguard against
      planting beyond watering capacity, not a formality - unwaterable excess converts seed spend
      into WEEDs), `plant_qty = min(seeds_held, free_tiles, labor_units, plant_budget,
      max_plant_tasks_per_turn)`. `plant_qty <= seeds_held` is load-bearing - verified directly
      against the real interpreter's own atomic PLANT validation (`kaggriculture.py`: exceeding
      seeds held drops *every* PLANT request for that crop this turn, not just the excess). Seeds
      now bought as one batched `BUY_SEED` order up to `seed_buffer_per_unit * labor_units` (one
      market slot regardless of quantity - `_parse_order` reads `order[2]` as the full count).
      New params (`max_plants_per_unit=100`, `max_plant_tasks_per_turn=8`, `seed_buffer_per_unit=1`,
      `seed_cash_reserve=0`) chosen so `labor_units=1` reproduces today bit-identically - confirmed,
      golden table unchanged, full suite unchanged.
      **Diagnostic, run twice to isolate the real cause of a real, informative negative result**: a
      first pass (default params, `hires_per_day=4` forced) showed real, large crop-side gains
      (PASS fraction dropped further to 15-18%, PLANT/WATER/HARVEST throughput up substantially,
      final money +15-20% over the T8.4-only diagnostic) but animal production still never reached
      in 6/6 seeds - traced, not assumed a bug: a second pass with `animal_net_of_cost=False`
      (steady-state ranking, matching T8.4's own diagnostic intent of testing the *pipeline* rather
      than today's economics) reached real animal production in 3/3 seeds checked
      (`inventories[0]["WHEAT"]` non-empty, MILK/WOOL/EGG all reached). Confirms the pipeline itself
      is now genuinely fixed by T8.4+T8.6 together - the default-params result simply reflects
      T8.3m/T8.3q's already-accepted economics correctly *not* wanting an animal without
      fertilizer/CARE, not a labor or pipeline defect.
      **Monoculture risk flagged, not yet triggered**: `_top_investment_choice` returns one crop, so
      parallel planting at `hires_per_day>0` could in principle plant several of the same crop daily
      and crater its own price - not observable yet at the shipped `hires_per_day=0` default;
      revisit once T8.7 accepts a nonzero value (watch the per-episode price series, not just final
      money - `crop_self_impact_aware`'s existing self-impact walk already partially self-corrects).
      362/362 full suite (10 new tests), compileall clean, boundary check green.
- [x] T8.7 — Re-ran the hiring sweep (`tools/run_hiring_sweep.py`), direct self-play only against
      the checked-in T8.6 baseline, no panel blending (T7.4's own documented pitfall). **Prediction
      stated up front, and it came true decisively**: with T8.4 (inventory pinning) + T8.6 (parallel
      planting) landed, hiring flipped completely - every nonzero `hires_per_day` tried won 96-100%
      working-block win rate (`hires_per_day=1`: 50/50, Wilson [0.929, 1.0]; 2/3/4/8 also hit the
      same 100% ceiling; 6 alone dipped to 96%, likely noise around an already-saturated result) -
      the exact opposite of T7.4's stale 0.03-0.17 finding. A joint sweep of the suspected-correlated
      group `{hires_per_day, max_plants_per_unit, seed_buffer_per_unit}` via `coordinate_ascent`
      found no further improvement beyond `hires_per_day` alone - the geometry-derived defaults for
      the other two don't bind at this labor level.
      **Accepted**: `hires_per_day` 0 → 1, held-out-gated at 50/50 (Wilson [0.929, 1.0]). Deliberately
      the most conservative value among several tied at the measured ceiling (least labor cost for
      the same measured benefit) - not necessarily "uniquely optimal" in a strict sense, since
      `accept_candidate` can never distinguish two candidates both at the 100% ceiling; a genuine,
      well-justified choice all the same. Non-regression check vs starter/random (10 holdout seeds,
      reporting only): 100% win rate, no regression.
      Shed-overflow risk (flagged in the plan as a real possibility at this harvest throughput):
      checked directly across the 3 golden `starter` seeds - shed total peaked at 65/100, never
      reached the cap. Not a live issue at `hires_per_day=1`; revisit if a future sweep raises it
      further.
      Golden table re-recorded - all 6 seeds improved substantially (none decreased), e.g.
      starter/seed1: 27524 → 37258 (+35%). `_DEFAULT_HIRES_PER_DAY`
      (`kagg.policy.strategy`)/`DEFAULT_PARAMS`/`params/policy.json` kept in sync. 362/362 full suite
      (4 pre-existing tests updated for the new default, no new tests - this task changes a value,
      not a mechanism), compileall clean, boundary check green.
- [x] T8.8 — Re-swept land (`tools/run_land_sweep.py`) now that `hires_per_day=1` (T8.7) landed -
      `hires_per_day` itself held fixed, not re-opened, per the task's own scope.
      **Real, held-out-gated result that went the opposite direction the plan's own hypothesis
      expected**: the working assumption was "more labor can work more land, so the gate should
      loosen." Measured instead that going *stricter* wins decisively -
      `land_buy_max_free_tile_fraction` 0.25 → 0.1 (working block 0.90 vs 0.25's own 0.36-0.38;
      held-out 0.84, Wilson [0.715, 0.917]) - every looser value tried (0.4, 0.6, 0.8, 1.0 fully
      ungated) lost outright, 1.0 all the way down to a total 0/50.
      `land_purchase_threshold_money` 10000 → 15000 (swept jointly with the fraction gate via
      `coordinate_ascent`). Traced, not just assumed: two labor units still can't profitably use
      even one 25-tile quadrant - land purchase spends cash that would otherwise buy seeds/animals,
      and a hired hand needs *work* (more investment tasks), not more square footage; land now also
      competes with T8.6's larger batched seed/animal spend for the same cash on top of T8.3's
      original finding. Non-regression check vs starter/random (10 holdout seeds, reporting only):
      100% win rate.
      Golden table re-recorded - 4 of 6 seeds improved, 2 dipped slightly (consistent with a 0.84
      win rate, not a 50/50-both-blocks sweep like T8.3's own original). `_DEFAULT_LAND_PURCHASE_
      THRESHOLD_MONEY`/`_DEFAULT_LAND_BUY_MAX_FREE_TILE_FRACTION` (`kagg.policy.strategy`)/
      `DEFAULT_PARAMS`/`params/policy.json` kept in sync. 362/362 full suite (2 pre-existing tests
      updated for the new defaults), compileall clean, boundary check green.
      Fresh Kaggle submission: ref `56214285` (commit `777e46a`, this task's own land re-sweep,
      user-approved) - supersedes ref `56213981` (T8.4-T8.7 alone, commit `bf6cef3`).
- [x] T8.9 — Pulled forward into T8.1 above (found to be tightly coupled to it, not a separable
      stretch goal after all). Decouples plant-crop choice from animal-acquisition choice via
      `params["plant_while_pursuing_animal"]`; shipped as opt-in, not the default - see T8.1's entry
      for the full measured story.
- [x] **Checkpoint 8B** — suite green (362/362), bundle built and submitted (ref `56214285`, commit
      `777e46a`), real episode scores recorded. **Honest, not just the self-play headline**: real
      public episodes today for T8.3l+T8.3m (ref `56213409`) were 6W/8L across 14 games;
      T8.4-T8.7 (ref `56213981`) was 1W/4L across 5 games (small sample). Our own money did rise as
      self-play predicted (roughly 13k-38k vs the prior ~15-28k range), but the field's own top tier
      scored 75k-117k in the same window - the real competitive gap from `competitive_gap_first_
      submission` memory is confirmed current, not stale (an earlier read this session
      misidentified it as resolved by matching the wrong team - corrected). `public_score` itself
      moved 391.8 -> 375.3 -> 354.3 across the three submissions today; per this project's own
      established finding, a fresh submission's score is volatile for its first ~20 minutes and
      keeps moving as more episodes complete, so this snapshot is not a final verdict - re-check
      before drawing conclusions from it.

## Stage C — season-remaining-aware demand, watering-window awareness, dynamic hiring (2026-09-13)

The user's own three observations after reviewing Stage B: (1) animal ranking should model demand
drained all season, not one production interval; (2) hiring should scale from the real task backlog,
not a flat constant; (3) ~$1000-1150 sits idle early in the season. Investigation traced a fourth,
connecting cause not named by the user but found while tracing (1)-(3) together: WATER is queued at
routine-care priority every day regardless of whether it can add yield, crowding out PLANT exactly
when idle capital and idle tiles coincide (seed 100: 4 free tiles + 2 seeds in hand + $1150 sat
untouched for 8 days while 148 of 192 available unit-turns went to WATER, 0 to PLANT).

- [x] T8.10 — `animal_revenue_per_tile_day` gains `consumption_horizon_aware`/`consumption_rate`:
      prices each scheduled animal-product unit at its own production day's drained market level
      (`price(product, inv - rate*day + k)`) instead of one flat one-production-interval offset -
      mirrors what `crop_revenue_per_tile_day` already does across a crop's full tile-occupancy
      horizon (T8.3f/T8.3i). Traced on seed 100's real shop draw: COW's modeled net rate roughly
      doubled ($46.5 -> $94.4/tile-day at `days_remaining=28`), enough to move it from well behind
      MELON/STRAWBERRY to directly competitive with them.
      **Prediction stated up front: a clear, zero-risk win (pure formula correction, zero extra
      farmer turns). Measured and rejected, prediction wrong**: 1/50 working (39 ties), 0/50 held-out
      (40 ties). Traced, not just trusted: a first single-seating trace (seed 901) looked like a real
      loss but proved to be pure seat-order noise (re-running the checked-in baseline against
      *itself* reproduced the exact same non-tied split) - the real, non-tied holdout seeds
      (902/908) traced to a genuine mechanism instead: this flag brings COW's score close enough to
      STRAWBERRY's that a 2-turn intraday market wobble flipped `_top_investment_choice`'s pick on
      seed 902/day 12 (confirmed turn-by-turn across the whole 720-turn episode: exactly 2 turns
      differed). `_top_investment_choice` has no hysteresis - that one flip fired a real `BUY_ANIMAL`
      order, and the existing (correct, deliberate) `stuck_animal` logic then committed to finishing
      the acquisition (`BUILD_PASTURE`, repeated `PICKUP`/`FEED`, `PLACE` - all confirmed in the
      actual episode), diverting real farmer turns from the crop the ranking reverted to one turn
      later. Not a flaw in the formula's own accuracy (unit-test-verified) - a real, previously-
      dormant architectural gap: nothing gates an irreversible purchase on a lead margin or sustained
      turn count, and animals were simply always far enough behind crops pre-T8.10 for this to never
      matter. **Shipped default: False** (rejected, not unmeasured) - kept available (tested) for a
      concrete follow-up lead this traced: gate `BUY_ANIMAL` on the top choice holding for some
      minimum consecutive turns or score margin before committing.
- [x] T8.11 — `_plant_tile_tasks` gains `water_bonus_window_aware`: demotes a non-urgent WATER on a
      one-time crop (WHEAT/CARROT/MELON) outside `watering_bonus_window(crop)` from `PRIORITY_
      ROUTINE_CARE` to `PRIORITY_MAINTENANCE` - such a watering adds zero yield (verified directly
      against the real WATER handler), only anti-weed insurance. Deliberately scoped to one-time
      crops only: for an *ongoing* crop (TOMATO/STRAWBERRY), watering never adds yield regardless of
      age (verified directly in `kaggriculture.py` - base production fires purely on
      `_daily_refresh_plants`' own schedule, independent of watering), so there is no "bonus window"
      concept to demote against there at all.
      **Prediction: a real, informative win but not risk-free** - explicitly named the same
      FERTILIZE-crowding risk class as T8.3e up front. **Measured and rejected, the named risk came
      true, traced directly**: 7/50 working, 3/50 holdout, 0 ties either block (fires on nearly every
      turn, unlike T8.10's mostly-tied result). Traced (seed 900): PLANT count did rise as predicted
      (42 -> 48, +14%), but WEED count at episode end more than tripled (4 -> 13) and final money
      fell. Root cause: demoting all the way to `PRIORITY_MAINTENANCE` (tied with `DIG`, below
      `PLANT`) conflates "not yield-productive today" with "not needed today" - the real anti-weed
      rule only counts consecutive misses, not the bonus window, and once `PLANT` tasks fill the
      queue ahead of it (T8.6's own parallel-planting throughput), a demoted watering can miss two
      days running before reaching `MAINTENANCE`, converting productive tiles to weed. **Shipped
      default: False** (rejected, not unmeasured) - kept available (tested) for a concrete follow-up
      lead: a middle priority tier between `ROUTINE_CARE` and `PLANT`, not all the way to
      `MAINTENANCE`.
- [x] T8.12 — `hires_per_day` gains a `dynamic_hiring` mode: sizes the hiring target from the task
      backlog `decide()` already built (`ceil(pending_task_count * turns_per_task_estimate /
      max(1, turns_per_day - hour)) - 1`, clipped to `[min_hires_per_day, max_hires_per_day]`), rather
      than a flat constant - the user's own explicit request, with `min_hires_per_day`/
      `hire_cash_reserve` addressing their own follow-up concern (protect the season's limited
      starting capital) as named, swept parameters instead of leaving it implicit.
      **Prediction stated up front, naming the dependency explicitly**: a win only if T8.11 had
      already freed labor first; close to zero (or a small loss) otherwise, since T8.11 was rejected
      and the labor supply this would scale into is still saturated by the same out-of-window
      watering T8.11 tried and failed to free.
      **Measured and rejected, prediction correct**: 2/50 working, 4/50 holdout, 0 ties either block.
      Traced (seed 900): hired up to 5 hands at once (1412 total hand-turns vs the checked-in
      baseline's 690 with 1 hand); PLANT count did rise (45+25=70 vs 20+22=42, +67%), but `PASS`
      appeared 68 times (hands with genuinely nothing to do) and WATER rose even more sharply than
      PLANT (609 vs 437 total) - final money fell (28439 vs 32958). Root cause: `len(tasks)` counts
      every queued action including ones that recur regardless of labor level (routine watering
      chief among them - T8.11's own unresolved target), so the formula reads a large *standing*
      backlog as a large *marginal* one and overshoots the labor level T8.6's own geometry-derived
      caps were tuned against - reproducing T7.4's original "adding workers past real bottlenecks has
      zero marginal value" finding, now for a genuinely different, non-bug reason. **Shipped default:
      `dynamic_hiring=False`** (rejected, not unmeasured) - kept available (tested) for a concrete
      follow-up lead: fix the task-count signal itself (count only PLANT/HARVEST/acquisition tasks,
      or add a real idle-hand penalty) before this can safely scale labor - very plausibly needs
      T8.11's own still-open watering-crowding problem solved first, exactly as predicted.

**Net result of this whole investigation**: all three built mechanisms (T8.10/T8.11/T8.12) were
measured and rejected - a real, honest outcome, not a wasted one. Each rejection is traced to a
concrete, specific mechanism (not noise, not a bug in the new code) and each names a genuine
follow-up lead: T8.10 needs investment-choice hysteresis before a more accurate animal valuation is
safe to act on; T8.11 needs a middle priority tier instead of a full demotion to MAINTENANCE; T8.12
needs a better task-count signal and very plausibly depends on T8.11's fix landing first. The user's
third observation (idle starting capital) was never directly built as its own task - it was correctly
diagnosed as a downstream symptom of the same watering-crowding bottleneck T8.11 targeted, and stays
unresolved for the same reason T8.11 was rejected.

## Stage D — fixing Stage C's three named leads (2026-09-13, same session)

The user's own follow-up after reviewing Stage C's honest rejections: since COW/SHEEP's own
theoretical full-care+fertilizer profitability ($215-275/tile-day, dwarfing every crop) was never
actually disproven - every measurement that would test it was contaminated by a separate,
unrelated architectural bug - fix the three named leads first, then re-test. Investigated and
confirmed directly against `kaggriculture.py`: the game engine imposes no cap at all on animal
count/type (`BUY_ANIMAL`/`BUILD_COOP`/`BUILD_PASTURE`/`PLACE` check only tile state and money/shed
capacity) and `PICKUP` has no structural prerequisite (only `PLACE` needs both an animal in hand and
a built structure) - both the "one animal type" cap and the serial BUILD-then-PICKUP-then-PLACE
pipeline are this codebase's own choices, not game rules (see the full plan at
`.claude/plans/jazzy-jumping-lamport.md` for T8.18/T8.20, not yet built this session).

- [x] T8.14 — `score_portfolio(...)` (new) exposes the raw `{name: score}` dict `rank_portfolio` has
      always computed internally but never returned; `rank_portfolio` becomes a thin sorting wrapper
      over it (bit-identical output, its own RED test locks the relationship down). `_top_investment_
      choice` gains `investment_commit_margin`: an ANIMAL candidate is only returned once its score
      clears `best_crop_score * (1 + investment_commit_margin)` - otherwise skipped, keep walking the
      ranking. Scoped to animals only (crops are cheap to reverse; `BUY_ANIMAL` isn't). Default `0.0`
      (no margin, bit-identical).
      **Measured alone against the checked-in baseline**: 100% ties at every margin tried (0.05,
      0.10, 0.20), both blocks - expected, not informative: under today's default
      (`animal_consumption_horizon_aware=False`), animal scores never come close enough to a crop's
      for the margin to ever bind. **Measured combined with `animal_consumption_horizon_aware`
      (T8.10) instead - the real test, since T8.10's own rejection is exactly what this margin
      targets**: losses dropped from 10/50 (T8.10 alone, working) to 3/50 (margin=0.05) to 0/50
      (margin=0.10 and 0.20); holdout losses dropped from 10/50 to 6/50 to 2/50 (both 0.10 and 0.20).
      **Confirms the diagnosis and the fix work exactly as designed** - the hysteresis bug really was
      the cause, and the margin really suppresses it. Not yet a full accept: `accept_candidate`
      requires beating the baseline, and this combination only neutralizes the harm (ties, not wins) -
      animals still rarely get chosen at all under today's baseline valuation, so removing a bad
      decision doesn't yet create a new good one. `investment_commit_margin` stays at its `0.0`
      default pending T8.17's fuller test (fertilizer/CARE, where the real upside is expected). 393/393
      suite green (7 new tests), compileall clean, boundary check green, bit-identical at defaults.
- [x] T8.15 — `PRIORITY_LOW_VALUE_CARE = 3.5` (new tier, between `PRIORITY_PLANT` and `PRIORITY_
      MAINTENANCE` - `assign_units` already groups tiers via `sorted({t.priority for t in tasks})`,
      any sortable value works). `water_bonus_window_aware`'s out-of-window watering demotes here
      instead of all the way to `PRIORITY_MAINTENANCE` (T8.11's own rejected target).
      **Measured (re-running `tools/measure_t811.py` unchanged - same flag, new mechanism
      underneath)**: 27/50 working (54%), 24/50 holdout (48%) - a huge recovery from T8.11's own
      decisive 7/50 (14%)/3/50 (6%) rejection, confirming the softer tier really does stop the
      weed-conversion cost, but not yet a statistically decisive win either
      (`accept_candidate`: False, wide overlapping intervals). Real progress, not a full accept -
      `water_bonus_window_aware` stays at its `False` default pending further tuning (see below).
- [x] T8.16(a)+(b) — `pending_task_count` (the value `dynamic_hiring` scales hiring from) now excludes
      `_ROUTINE_RECURRING_OPS = {WATER, FEED}` - these recur once per tile/animal per day regardless
      of labor level, so counting them inflated the backlog signal without reflecting genuine
      marginal work (T8.12's own traced root cause). `hires_per_day` gains `hire_buffer_fraction`
      (default `0.0`) - the user's own explicit "5-10% запас" ask - scaling the computed target up
      before clipping to `[min_hires_per_day, max_hires_per_day]`.
      **Measured (counting fix alone, buffer still at 0.0)**: 31/50 working (62%), 24/50 holdout
      (48%) - again a huge recovery from T8.12's own decisive 2/50 (4%)/4/50 (8%) rejection, same
      "real progress, not yet decisive" shape as T8.15. **Measured T8.15+T8.16(a) combined** (testing
      the plan's own predicted dependency - freed labor giving hiring real work to scale into):
      29/50 working (58%), 21/50 holdout (42%) - **contrary to the stated prediction, combining did
      not beat either alone** (holdout actually dipped from 48% to 42%). An honest, informative
      surprise: the two fixes on their own recover from decisive rejection to parity, but don't
      compound into a win yet - `min_hires_per_day`/`max_hires_per_day`/`turns_per_task_estimate`/
      `hire_buffer_fraction` have never actually been swept (T8.16's own plan named this explicitly:
      "not yet actually swept... any earlier sweep would have been contaminated by (a)'s bug
      anyway"). **Movement overhead (T8.16(c))**: deliberately not built as separate code - see the
      plan's own reasoning (the empirical `turns_per_task_estimate` ratio already absorbs it).
      `dynamic_hiring`/`water_bonus_window_aware` both stay at their `False` defaults - T8.16(d)'s
      joint `coordinate_ascent` sweep over the four correlated parameters is the next, not-yet-run
      step this session's evidence points to before either can be fairly judged.
- [x] T8.16(d) — joint `coordinate_ascent` sweep over `{min_hires_per_day, max_hires_per_day,
      turns_per_task_estimate, hire_buffer_fraction}` (SPEC-tuning.md: correlated parameters swept
      together), `dynamic_hiring=True` throughout (`tools/measure_t816d.py`). **Decisive result -
      ACCEPTED as the new shipped default**: raising `min_hires_per_day` from its old flat-constant
      value (1) to 2 took the working-block win rate from T8.16(a)'s own 0.62 to 0.94, while every
      other knob's best value stayed at its untouched starting point - a spare-capacity buffer
      actively hurt at every value tried (0.02), a tighter `turns_per_task_estimate` helped some
      (0.72) but far less than the floor change, a looser one or a higher `max_hires_per_day` both
      hurt. Held-out gate: 49W/1L/0T (98%, Wilson [0.895, 0.996]) against the pre-T8.16(d) checked-in
      baseline - the single most decisive result this whole plan produced. Traced (seed 900,
      `tools/trace_t816d.py`): candidate ends the episode with 8 hands (old default: 1), hand `PASS`
      only 101/1438 turns (~7%, genuinely working), final money 41365 vs 36172 (+14.4%). **Shipped
      default changed**: `dynamic_hiring=true`, `min_hires_per_day=2` (params.py, policy.json,
      strategy.py's `_DEFAULT_DYNAMIC_HIRING`/`_DEFAULT_MIN_HIRES_PER_DAY`). Golden episodes
      re-recorded (`tests/test_agent_golden_episodes.py`) - a real, large jump on every one of the
      six checked-in seeds (e.g. starter/seed1: 38093 -> 45650, +19.8%), matching the self-play
      result exactly, not a regression to chase down. This directly answers the session's opening
      question: the user's own diagnosis (missed watering/feeding is a labor shortage, not proof
      animal economics are bad, and a real day-1 hiring floor was the missing piece) was correct -
      see T8.17 below for the still-open follow-up (does this labor fix alone make COW/SHEEP
      profitable, or is T8.17's own animal-awareness stack also needed).
- [x] T8.17 — re-measure `animal_consumption_horizon_aware`/`animal_fertilizer_income_aware`/
      `animal_care_aware` individually then combined, against the new T8.16(d) baseline
      (`tools/measure_t817.py`) - the actual "are COW/SHEEP genuinely profitable" answer, now that
      the labor floor is fixed. **Run. None accepted - but the story is real and different from
      every earlier attempt, not a repeat of the old architectural-bug contamination**:
      - `animal_consumption_horizon_aware` alone: **0/50 working, 0/50 holdout - every single
        episode lost**, worse than T8.10's original 1/50-0/50 rejection. `investment_commit_margin`
        is still 0.0 by default, so this is very plausibly the same hysteresis-flip pattern T8.14
        was built to fix, now amplified: with real spare labor (T8.16(d)), a mistaken animal
        commitment gets *fully* executed (feeding, placing, tending) instead of being starved by a
        single farmer's limited bandwidth, so a wrong pick costs more, not less, once labor stops
        being the bottleneck. Not yet re-tested combined with a nonzero `investment_commit_margin` -
        a concrete next step if this flag is revisited.
      - `animal_fertilizer_income_aware` alone: 24%/32% (working/holdout) - still a clear loss, but
        materially less decisive than any of its earlier rejections.
      - `animal_care_aware` alone: 48%/56% - the closest any animal-economics flag has come to
        parity all session; Wilson interval [0.42, 0.69] still overlaps 0.5, so correctly not
        accepted, but this is the one genuinely promising lead this task produced.
      - All three combined: 44%/54%, essentially tracking `animal_care_aware` alone (consumption-
        horizon-aware's own strong negative and fertilizer's milder one roughly cancel against
        care's mild positive) - not a clean synergy, not a clean rejection either.
      **The honest answer to the session's opening question**: T8.16(d)'s real labor fix was
      necessary but not sufficient. Once genuine spare labor exists, COW/SHEEP's *execution*
      constraint (a single farmer can't feed+care+collect+harvest) is real and now testable - but at
      least one of the three accuracy improvements (`animal_consumption_horizon_aware`) is actively
      harmful even with labor no longer the bottleneck, and none of the three yet clears the
      held-out bar. `animal_care_aware` alone is the one lead worth returning to (closest to parity,
      real upward movement from every prior measurement) - a future session could try it combined
      with `investment_commit_margin` or on its own with a larger seed sample.
- [x] T8.18 — parallelize the animal-acquisition pipeline. Verified directly against
      `kaggriculture.py`: `PICKUP` has no structural prerequisite at all, only `PLACE` needs both an
      animal in hand and a matching built structure. `tasks._new_investment_tasks`'s animal branch
      gains `parallel_animal_acquisition` (default `False`, bit-identical): when on, `BUILD_*` and
      `PICKUP` both fire the same call whenever they're independently actionable, instead of the old
      first-match-wins chain (up to 3 sequential turns even with 2+ free labor units). RED tests +
      GREEN in `test_policy_tasks.py`; full suite green. **Measured - 100% ties on both blocks**
      (0W/0L/50T working, 0W/0L/50T holdout, `tools/measure_t818.py`, `hires_per_day=2` base against
      the new T8.16(d) default baseline): candidate and baseline produced byte-identical outcomes on
      every one of the 100 seeds tested - not a rejection, a genuine no-op, consistent with the
      mechanism's own stated prediction ("a null result here is plausible... not that the mechanism
      is wrong"). Most likely explanation: with every `animal_*_aware` flag still off by default,
      COW/SHEEP/GOOSE essentially never outrank a crop in `_top_investment_choice` under these
      seeds/this baseline, so `BUY_ANIMAL` (and therefore the parallelized BUILD/PICKUP pipeline)
      never actually fires - T8.17 (below) is the direct test of whether that changes. Kept available
      (tested, off by default) - worth re-measuring once T8.17 makes animal acquisition a real,
      regular occurrence in self-play.
- [x] T8.19 — a small crop basket (`portfolio_basket_size`) instead of always the single top-ranked
      product. Fully wired (`_top_crop_basket`, round-robin `plant_crop`/`plant_qty`, a cumulative-
      spendable multi-crop seed-buying loop in `decide.py`; `tasks.py`'s plant branch accepts a
      per-tile crop-name list). RED+GREEN throughout, full suite green. **Measured and rejected**
      (`tools/measure_t819.py`, against the new T8.16(d) baseline): `portfolio_basket_size=2` ->
      10%/8% (working/holdout), `=3` -> 6%/6% - both decisive, consistent losses. The predicted
      tradeoff resolved against the hedge: spreading tiles into a worse-ranked crop (STRAWBERRY's
      $21.6/tile-day vs MELON's $109) pays a real per-tile cost every episode, while the double-
      price-crash scenario it hedges against apparently doesn't materialize often enough in these
      seeds/this opponent to pay for it - and `crop_self_impact_aware` (already on by default)
      already provides some real reactive protection, so a proactive basket may just be redundant
      with that. Stays off by default (`portfolio_basket_size=1`), kept available (tested).
- [x] T8.21 — close the `animal_care_aware`/`animal_consumption_horizon_aware` no-op gap:
      `_animal_full_care_units` split into `_animal_full_care_schedule` (new per-production-day
      `[(day, units), ...]` breakdown, `_animal_full_care_units` now just its sum - pure refactor,
      bit-identical) so `animal_revenue_per_tile_day` can walk real per-unit production days for the
      combination instead of silently falling back to the flat `expected_consumption` offset.
      RED+GREEN in `test_policy_strategy.py`, full suite green (407/407), compileall/boundary clean.
      **Measured and NOT adopted as a new default** (`tools/measure_t821.py`, against the T8.16(d)
      baseline - neither flag is on by default, so this changes zero shipped behavior regardless):
      `animal_consumption_horizon_aware` alone reproduced T8.17's own 0/50, 0/50 exactly (sanity
      check the refactor didn't leak into the untouched branch). The new `care_aware` +
      `consumption_horizon_aware` combination: **36%/38% (working/holdout) - a real regression from
      `animal_care_aware` alone's 48%/56% (T8.17)**, and all-three-combined fell from 44%/54% to
      34%/38% the same way. Verified this isn't a sign-flip bug: the new walk genuinely raises
      per-animal scores when a shop is drawing consumption (e.g. COW at consumption_rate=3:
      $142->$254/tile-day) exactly as designed - the regression is real economics, not
      miscomputation. The coherent explanation: `animal_consumption_horizon_aware` was *already* a
      decisive standalone rejection (0/50) before this task - its flaw (extrapolating *today's*
      shop-consumption rate as if it held for the animal's *entire* remaining-season horizon,
      systematically overcrediting future units a shop may not even still be drawing on) was simply
      invisible in `animal_care_aware`'s own measurements because the no-op meant the flawed model
      never actually ran in that combination. Closing the gap didn't introduce a new problem - it
      exposed T8.10's already-known one in a context that used to mask it. Kept available (tested,
      both flags default `False`, so this combination only ever fires when a caller explicitly sets
      both) - the real fix, if this is revisited, is `animal_consumption_horizon_aware`'s own
      over-extrapolation (e.g. discounting the assumed rate for how much of the horizon the current
      shop mix can actually be trusted to hold), not `care_aware`'s schedule.
- [x] T8.22 — lift the single-animal-type cap once labor genuinely supports a second. Verified
      directly against `kaggriculture.py`: `BUY_ANIMAL` has no engine-level same-type cap at all
      (only `shed_capacity`/money), and `PLACE` only needs one matching empty structure - the "never
      pursue a second instance" rule was entirely `decide.py`'s own simplification
      (`placed_animal_types`). Changed to a count-based gate: `placed_animal_type_counts: dict[str,
      int]` + new `max_animals_per_type` param (default `1`, bit-identical - reproduces the exact
      prior rule for every caller that doesn't set it). RED+GREEN in `test_policy_decide.py`, full
      suite green (410/410), compileall/boundary clean.
      **Measured and decisively rejected** (`tools/measure_t822.py`, sweeping the cap against the
      T8.16(d) baseline with `animal_care_aware`/`animal_fertilizer_income_aware`/`parallel_animal_
      acquisition=True` - deliberately *without* T8.21's `consumption_horizon_aware` combination,
      which that task's own measurement had already found harmful on its own, to avoid confounding
      the two questions): `max_animals_per_type=2` -> 28%/24% (working/holdout), `=3` -> 14%/14%,
      `=4` -> 2%/4% - a monotonic collapse, each step decisively worse than the last, not noise.
      **Traced** (`tools/trace_t822.py`, seed 900): at cap=2, animal-tile count peaks at 4 mid-
      episode; at cap=4, it peaks at 5 - but in both cases **every single animal is gone by episode
      end** (final count 0). Confirmed directly against `kaggriculture.py`'s own
      `_daily_refresh_animals`: an animal escapes (tile reverts to a bare structure, `"animal"` key
      removed) once `consecutive_unfed >= 2` - the observed "max consecutive_unfed ever seen on a
      surviving tile = 1" is exactly consistent with animals repeatedly reaching 1, then escaping the
      very next missed-feed day before a stored value of 2 could ever be observed. The same
      T8.3q "promised a mechanism the labor budget couldn't execute" failure mode this whole
      animal-economics thread keeps finding - now for N animals instead of one: `min_hires_per_day=2`
      (T8.16(d)) covers one animal's FEED+CARE+COLLECT_FERTILIZER+HARVEST plus crop maintenance, but
      not two or more animals' worth on top of that. Stays off by default (`max_animals_per_type=1`,
      bit-identical), kept available (tested). A concrete lead for later, not built here: gate
      `max_animals_per_type` on real spare labor (e.g. only pursue a second animal once
      `hires_per_day`/`min_hires_per_day` themselves have been raised enough to cover it), rather
      than assuming today's single-animal-tuned labor floor scales for free.
- [x] T8.23 — verify (not assume) that crop+animal coexistence emerges naturally from
      `plant_while_pursuing_animal` (T8.9, on by default) - the user's own diversification
      hypothesis ("melon + milk won't crash one market as hard as melon alone"). Scoped down from
      the plan's own multi-animal framing: T8.22's `max_animals_per_type>1` was decisively rejected
      (above), so the "repeated same-type stacking starves crop planting via `stuck_animal`" risk
      that task's fallback-fix trigger named cannot arise in the shipped default
      (`max_animals_per_type` stays `1`) - traced the scenario that's actually viable instead:
      `animal_care_aware=True` alone (T8.17's closest lead to parity, 48%/56%), otherwise default.
      **Verification only, no code changes** (`tools/trace_t823.py`, seed 900): the candidate holds
      one SHEEP for 718 of 720 turns while planting 15 STRAWBERRY tiles - **identical final crop-tile
      count to the animal-free baseline (15)**, and every PLANT that happened landed during an
      animal-pursuit-or-held turn (66 of them) with zero starvation of animal-free planting
      opportunities (there were none to starve - the animal is held almost the entire episode).
      `plant_while_pursuing_animal`'s independent-signal design works exactly as the plan predicted:
      crop planting proceeds at its normal pace regardless of a concurrent animal purchase/care
      cycle. No fallback fix needed - the fallback plan (narrowing when `stuck_animal` pauses new
      crop commitments) stays a documented option for if/when `max_animals_per_type>1` is ever
      revisited with the labor-gating fix T8.22's own entry names.
- [x] T8.24 — grow WHEAT domestically to avoid the animal-feed BUY-side purchase price, once real
      feed demand exists. New `wheat_feed_credit_per_tile_day` (`strategy.py`): a real make-vs-buy
      price asymmetry `gamelib.market.price` already has (BUY quoted at *post-buy* inventory, rising
      as more is bought; SELL at *pre-sell* inventory, falling as more is sold) that
      `crop_revenue_per_tile_day`'s plain sale-side walk never priced. Splits one WHEAT tile's yield
      into `feed_units` (diverted, credited at the avoided buy price) and the remainder (still sold
      normally) - a pure additive delta on top of the existing WHEAT score, never double-counting a
      unit. Threaded through `score_portfolio`/`rank_portfolio`/`_top_crop_basket` (new
      `wheat_self_sufficiency_aware`/`wheat_feed_units_needed` params, both bit-identical off/`0` by
      default) into `decide()`, which computes real feed demand early (before the crop-ranking calls
      - `farmer_inventory` moved up to support this) from three signals: this turn's top choice is
      itself an animal, an animal already bought and awaiting placement, or one already placed and
      alive. RED+GREEN across `test_policy_strategy.py`/`test_policy_decide.py` (a caught and fixed
      test-authoring mistake along the way: the credit's sign is genuinely state-dependent, not
      always positive - see the corrected test names/comments), full suite green (421/421),
      compileall/boundary clean.
      **Scope note**: the plan deferred this until T8.22 landed (multi-animal feed demand); T8.22 was
      decisively rejected, so this measures the scenario that's actually viable instead - a single
      placed/pursued animal (`animal_care_aware=True`, T8.17's closest lead).
      **Measured - null/inconclusive, not accepted** (`tools/measure_t824.py`): alone (no animal-
      awareness flag) - **100% ties, 0W/0L/50T on both blocks**, an exact no-op, exactly as predicted
      (T8.18 already established animals essentially never get bought under default economics, so the
      flag has nothing to attach to). Combined with `animal_care_aware` - mostly ties again (47/50
      working, 41/50 holdout), with only a handful of decided games in each (3 working, 9 holdout) -
      too few to draw a confident conclusion, though the decided-game ratio (1W/2L, 3W/6L - both
      exactly 1:2) leans slightly negative rather than positive. Consistent with the mechanism's own
      predicted ceiling: WHEAT's market is the deepest/flattest of any product (`T=400`), so one
      tile's feed-diversion delta is real (confirmed directly in unit tests) but numerically small -
      too small to reliably move a 720-turn episode's outcome at this seed count. The plan's own
      contested-demand scenario (an opponent also buying WHEAT for feed, pushing the purchase price
      up further) was **not measured** - an honest scope limit, same as the plan itself anticipated:
      the harness has no way to bias the opponent toward animal purchases. Stays off by default
      (bit-identical), kept available (tested) - a real, working mechanism without yet a self-play
      case that needs it.

- [x] T8.25 — fix the WHEAT feed-restock price ceiling (`wheat_max_buy_price`), a real,
      previously undiscovered bug found while investigating the user's own hiring/burstiness
      questions about T8.22's collapse. **Root cause** (verified directly against
      `kagg.policy.market.buy_wheat_order`): a static, never-swept $40 cap silently blocks *all*
      WHEAT feed restocking once market price drifts past it, with no urgency override - and WHEAT
      price drifts upward for the *entire* season structurally (nobody grows it at scale, T8.24's
      own finding, so town/shop consumption has no supply-side counterweight). Traced (seed 900):
      price crosses $40 around day 25 with 0 animals (harmless), ~day 22 with 1 (buffer barely
      survives), ~day 17 with 4-5 (buffer drains to 0 by day 20 - a 10-day feed drought matching
      T8.22's own escape events, turns 504/528/624, exactly).
      **Part 1** (`market.py`): re-swept `wheat_max_buy_price` itself as a plain scalar (80, 150,
      effectively unbounded) - project precedent (`land_purchase_threshold_money`/`hires_per_day`).
      **Part 2**: new `wheat_urgency_reserve` param - when `wheat_on_hand` is at or below it (and
      `> 0`, i.e. explicitly configured) and `feed_needed`, `buy_wheat_order` ignores the price cap
      entirely for that turn, bounded only by money. RED+GREEN in `test_policy_market.py`, full
      suite green, compileall/boundary clean.
      **Measured** (`tools/measure_t825.py`/`measure_t825b.py`, `tools/trace_t825.py`):
      - **Part 1 alone, unconditionally raising the cap - a real, decisive net LOSS** for the
        `animal_care_aware`-alone (single-animal) scenario: 12%/28% (working/holdout), identical
        across all three values tried (80/150/1,000,000). Traced directly (seeds 900/100): price
        does cross $40 (48-53), but that single animal's shed buffer already survives to episode
        end *without* any restock above $40 - raising the cap just buys the same already-surviving
        buffer back at a worse price, ~$200-300/episode wasted with no escape ever actually at
        risk in that scenario.
      - **Part 2 alone (cap left at 40), the real fix**: `wheat_urgency_reserve=3` found
        **bit-identical in practice** to Part 1's blanket raise in every comparison run (identical
        W/L splits down to the exact count) - the restock-threshold gate (`wheat_on_hand <
        wheat_restock_threshold=5`) means on-hand stock is already at or below the urgency reserve
        by the time a restock is even attempted once price has drifted past $40, so the two designs
        converge. Substantially closes (but does not reverse) T8.22's own decisively-rejected
        `max_animals_per_type` sweep: cap=2 28%/24% -> 36%/26%, **cap=3 14%/14% -> 40%/44%** (the
        closest to parity of any cap tried across either session), cap=4 2%/4% -> 14%/22% - a real,
        large improvement at every cap, not noise, but still a net loss in aggregate self-play.
      - **Seed-900 trace directly confirms the mechanism** (`tools/trace_t825.py`, cap=4): without
        the fix, all 5 animals are gone by episode end (escaped from neglect) and the shed sits at
        a permanent WHEAT zero for the final 263 turns; **with the fix, all 5 animals survive the
        full season**, the zero-stock run drops to 1 turn, and final money is actually *higher*
        than the plain baseline (46101 vs 41365, +11.5%) - the root-cause diagnosis holds up under
        direct inspection, not just aggregate win rate.
      - Both `wheat_max_buy_price` (stays 40) and `wheat_urgency_reserve` (stays 0/off) are **kept
        at their pre-fix defaults** - real, working, decisively-traced mechanisms, but a net loss at
        today's shipped `max_animals_per_type=1` (the same single-animal-buffer-already-survives
        effect Part 1 alone showed) and insufficient alone to reverse the `max_animals_per_type>1`
        rejection even where it helps most. Kept available (tested) for a future combination once
        `max_animals_per_type` itself is revisited.
- [x] T8.26 — proactive, tile-count-derived hiring forecast (the user's own proposed formula),
      built to test whether T8.22's remaining gap (even after T8.25's price fix) is a labor-ramp-lag
      problem: `hires_per_day`'s existing `dynamic_hiring` path sizes today's hiring target from the
      *currently visible* task backlog (`pending_task_count`), which only grows as the day's turns
      reveal more work, instead of a number already known in full at hour 0 from real tile counts.
      Ported `_crop_actions_per_tile_day`/`_animal_actions_per_tile_day` from
      `tools/analyze_unit_economics.py` (this session's own unit-economics analysis, verified
      directly against real WATER/FEED/CARE/HARVEST/FERTILIZE handler semantics) into `strategy.py`
      (the shipped bundle). New `workload_forecast_hiring_aware` param + `animal_tile_counts`/
      `crop_tile_counts`/`days_remaining` args on `hires_per_day()`: when on and both tile-count
      dicts are given, `total_turns = (sum of per-type actions/tile-day x real tile counts) x
      turns_per_task_estimate` (folding in movement/travel overhead once, confirmed with the user
      not to double-count it), divided by the *full* `turns_per_day` (not the shrinking remainder,
      so the target doesn't inflate through the day for the same real tile-derived workload),
      buffered/clipped exactly as the existing path. `decide()` wired to pass real signals
      unconditionally (`placed_animal_type_counts`, own-tiles-only `_crop_tile_counts(me["tiles"])`
      - *not* the opponent-blended `_combined_crop_tile_counts`, and a real `days_remaining`).
      RED+GREEN across `test_policy_strategy.py`/`test_policy_decide.py`, full suite green (432/432),
      compileall/boundary clean.
      **Measured and decisively rejected** (`tools/measure_t826.py`): **Stage 1 (alone, crop-only
      farm, vs the plain T8.16(d) baseline) - 10%/0%, a real, decisive loss**, not noise. Traced to
      reproducing T8.12's own original rejected mistake: the ported per-tile action functions (built
      for `analyze_unit_economics.py`'s isolated "how much labor does one fully-tended tile need"
      question) count routine WATER/FEED/CARE at their full per-day rate, but `pending_task_count`
      (the existing reactive path) deliberately *excludes* exactly these ops - T8.16(a)'s own
      measured fix, for the identical reason: a tile needs exactly one WATER/FEED per day
      *regardless* of labor size, so counting it as scaling demand over-hires without a matching
      gain. **Stage 2** (combined with T8.25's `wheat_urgency_reserve=3` fix + `max_animals_per_
      type` at 3/4) confirmed no rescue either: cap=3 38%/42% (vs T8.25 alone's 40%/44% -
      statistically indistinguishable, marginally worse), cap=4 16%/24% (vs T8.25 alone's 14%/22% -
      likewise indistinguishable) - the proactive forecast adds no measurable benefit on top of
      T8.25's already-real gain, and actively hurts on its own. Stays off by default (`False`,
      already the code's own default - no change needed there). Kept available (tested) for a
      future corrected version that excludes routine per-day-regardless-of-labor ops from the
      forecast, matching `pending_task_count`'s own already-fixed exclusion - not built here.
      **Combined T8.25+T8.26 outcome**: the user's original question ("is limited hiring the main
      reason for poor results?") turned out to have a more fundamental answer underneath it - a
      real price-ceiling bug (T8.25) that was silently causing animal starvation regardless of labor
      supply, which the user's own sharp follow-up question (burstiness/averaging risk) led directly
      to discovering. Fixing it substantially improves (but does not reverse) the animal-economics
      picture; a *proactive* hiring forecast on top, as directly proposed, measured worse, not
      better - the existing reactive `dynamic_hiring` path (T8.16(d)) remains the best-measured
      hiring mechanism. `max_animals_per_type` stays at its T8.22-rejected default of 1.

- [x] T8.27 — corrected workload-forecast hiring: exclude routine coverage ops from T8.26's own
      per-tile forecast, my own recommended next step in response to the user's open "what's next?"
      question (2026-09-14). Diagnosed T8.26's decisive rejection precisely: `_crop_actions_per_
      tile_day`/`_animal_actions_per_tile_day` (ported from `tools/analyze_unit_economics.py`) counted
      routine WATER/FEED/CARE/COLLECT_FERTILIZER at their full per-day rate, while the existing
      reactive path (`pending_task_count`) deliberately excludes the routine crop-side ops
      (`decide.py`'s `_ROUTINE_RECURRING_OPS`, T8.16(a)'s own fix for T8.12's original mistake) -
      T8.26 reproduced that exact mistake one level up, at tile-count granularity. Added a new
      `scaling_only: bool = False` parameter to both functions (default `False` bit-identical for
      every existing caller, including `analyze_unit_economics.py`-parity tests): crops exclude
      `water_actions`, animals exclude `feed_actions`/`care_actions`/`collect_fertilizer_actions`.
      `hires_per_day`'s `workload_forecast_hiring_aware` branch always passes `scaling_only=True` -
      the only caller that wants marginal-hiring-sized demand rather than total labor. RED+GREEN
      across `test_policy_strategy.py` (new `scaling_only` cases + updated hand-computed target),
      full suite green (437/437), compileall/boundary clean.
      **Measured** (`tools/measure_t827.py`, same two-stage structure as T8.26):
      **Stage 1 (this flag alone, against the exact shipped `DEFAULT_PARAMS` baseline) reversed
      T8.26's own rejection completely**: 98% working (49W/1L/0T), 92% holdout (46W/4L/0T), Wilson
      [0.812, 0.968] entirely clear of 50%, `accept_candidate=True`. Confirms the diagnosis was
      correct and sufficient for the crop-only case - not merely plausible. **Accepted and shipped
      as the new default** (`workload_forecast_hiring_aware: True`), since this comparison *is* a
      direct, held-out-gated acceptance test against the shipped baseline, not just a diagnostic
      sanity check. Re-recorded the golden-episode fixture (`test_agent_golden_episodes.py`, sixteenth
      re-record): 5/6 seeds improved (e.g. pass/seed1: 43879 -> 44707, +1.9%), one dipped slightly
      (pass/seed3: 46818 -> 46536, -0.6%) - consistent with a real, non-uniform self-play win.
      **Stage 2** (combined with T8.25's `wheat_urgency_reserve=3` fix + `animal_care_aware`/
      `animal_fertilizer_income_aware`/`parallel_animal_acquisition` + `max_animals_per_type` swept
      2/3/4 - a bundle of mechanisms NOT shipped by default) stayed decisively rejected: 12%/12%
      (cap=2), 24%/22% (cap=3), 16%/24% (cap=4) - all worse than T8.25 alone (cap=3: 40%/44%), and
      cap=3/4 even worse than T8.26's own original miscounted forecast (38%/42%, 16%/24%). A real,
      unexpected surprise given Stage 1's clean reversal - traced directly (`tools/trace_t827.py`,
      seed 900) rather than accepted at face value: hand count at each day's post-hire point (hour 1)
      is nearly identical between T8.25-alone (reactive path) and the T8.27 combo (proactive
      forecast) - both clip to `min_hires_per_day=2` for almost the entire 30-day episode - ruling out
      gross under/over-hiring by volume as the direct cause. The two runs diverge instead in exactly
      *which* days deviate from the floor (T8.25-alone dips to 0-1 hands on days 5-7; T8.27 stays flat
      at 2 throughout) and in how many animal tiles get acquired (3 vs 5) and final money (49155 vs
      41091) - a real, subtle interaction between the forecast's specific day-to-day computed value
      (even when clipped to the same floor most days) and the deterministic policy engine's investment
      timing, not a simple magnitude bug in the `scaling_only` fix itself. Left as a genuinely open
      question for whoever next revisits `max_animals_per_type` (flagged, not chased further here -
      Stage 1's own separately-earned win stands on its own merits per T8.3b's isolation discipline).
      `max_animals_per_type` stays at its T8.22-rejected default of 1; `wheat_urgency_reserve`,
      `animal_care_aware`, `animal_fertilizer_income_aware`, `parallel_animal_acquisition` all stay off.
      **T8.28 correction to the causal story above**: "hand count is nearly identical between the
      two paths" was true but under-investigated at the time - not checked for *why*. A direct
      read-only computation (T8.28) found the shipped `scaling_only=True` forecast's raw pre-clip
      target is 0 at every realistic farm size (25 MELON + 1 COW: `total_turns=8.7`; 50 MELON + 3
      COW: `total_turns=18.4` - both far under the 24-turn denominator), so it is *always* clipped to
      `min_hires_per_day=2`. The Stage-1 accepted default is, in practice, **flat 2 hands/day** - the
      tile-count scaling term this entry describes never actually engages at any farm size tried,
      confirmed directly by T8.28's own seed-900 trace (`tools/trace_t828.py`: `raw_target` never
      exceeds 1 across all 30 days). Stage 1's real, honestly-measured finding is therefore **"flat 2
      hands/day beats the reactive backlog-scaled path (which climbed to 8)"**, not "proactive
      tile-count sizing works" - and this directly explains Stage 2's regression: the reactive path's
      own ability to climb above 2 was helping in the animal-heavy bundle, and this forecast removed
      that headroom outright. The win rates/Wilson intervals recorded above are unaffected by this
      correction - only the causal explanation was wrong. See T8.28's own entry below for the re-sweep
      this finding prompted.

- [x] T8.28 — re-sweep the hiring knobs under the forecast path T8.27 actually shipped, my own
      recommended next step after the user's "what's next?" question (2026-09-14), chosen over
      submitting immediately (user: "Сначала T8.28, потом сабмит"). Prompted by the read-only finding
      recorded in T8.27's own corrected entry above: the shipped `scaling_only=True` forecast's raw
      target is 0 at every realistic farm size, always clipped to `min_hires_per_day=2` - so
      `min_hires_per_day`/`max_hires_per_day`/`turns_per_task_estimate`/`hire_buffer_fraction` (swept
      by T8.16(d) against the now-replaced *reactive* `pending_task_count` formula) had never been
      swept in a regime where the floor is the *only* live term, and the total-work variant
      (`scaling_only=False`, which genuinely scales) had only ever been measured by T8.26 at knobs
      fitted to that same unrelated reactive path.
      Added `workload_forecast_scaling_only: bool` (default `True`, bit-identical to T8.27's shipped,
      previously-hardcoded behavior) as a new named/swept parameter in `strategy.py`/`params.py`/
      `policy.json`, read inside `hires_per_day`'s forecast branch and passed to both per-tile
      functions instead of the hardcoded `scaling_only=True`. RED+GREEN (`test_policy_strategy.py`,
      2 new tests: default-matches-T8.27, and explicit `False` routes through the total-work variant
      and changes the clipped output), full suite green (439/439 incl. golden episodes bit-identical -
      no re-record needed, the new flag's default changes nothing), compileall/boundary clean.
      **Measured** (`tools/measure_t828.py`): joint `coordinate_ascent` sweep over
      `(min_hires_per_day, max_hires_per_day, turns_per_task_estimate, hire_buffer_fraction,
      workload_forecast_scaling_only)` - floors 1/3/4 at `scaling_only=True`, tighter
      `turns_per_task_estimate` (1.0, 0.5) to see if the scaling term could clear the floor at all,
      the total-work variant at 4 knob combinations of its own, one buffer probe. **Every single one
      of the 10 candidates tried lost decisively to the shipped baseline** on the working block
      (win rates 0.00-0.20, all Wilson intervals clear below 0.5) - not close calls. `coordinate_
      ascent`'s own internal search picked `(4, 8, 2.0, 0.0, True)` as its "best" (working-block
      win_rate=0.200, the least-bad of the 10) - but this ranking was contaminated by a measurement
      artifact specific to this task: the search's own starting point (`BASE`) is bit-identical to
      the checked-in baseline (T8.27's shipped default is now `DEFAULT_PARAMS` itself), so the very
      first working-block comparison was a guaranteed-tie mirror match (`win_rate=0.000` by
      construction, not because the baseline is bad) - any real parameter change looks "better" than
      a guaranteed tie by this metric alone, regardless of whether it's actually stronger. The
      held-out gate (a real, direct test against the true checked-in baseline, not the degenerate
      mirror) is what actually decides, and it **decisively rejected** this candidate: 7W/43L/0T
      (14%), Wilson [0.070, 0.262], `accept_candidate=False`. Traced anyway (`tools/trace_t828.py`,
      seed 900, `min_hires_per_day=4` vs the shipped `min_hires_per_day=2`) to see why: the raw
      pre-clip forecast target **never exceeds 1 across all 30 days in either run** - confirming
      directly (not just inferring from the read-only formula check) that the tile-count scaling term
      genuinely never clears any floor from 2 to 4 on this farm's real trajectory, so both runs are
      exactly as flat as the formula predicted, just at different floors (2 vs 4 hands every day).
      Raising the floor to 4 costs real money with no offsetting work to show for it: final money
      42040 (floor 2) vs 36550 (floor 4), -13% on this seed alone - directly explaining the 14%
      held-out loss. **Conclusion, honestly recorded either way as planned**: nothing tried in this
      sweep beats the shipped default beyond noise - `min_hires_per_day=2`,
      `workload_forecast_scaling_only=True` (both unchanged) is a genuine local optimum among every
      alternative tested, including higher/lower floors, a tighter turns-per-task estimate, the
      total-work variant at its own knobs, and a buffer. This closes the open question T8.27's
      correction raised: the tile-count forecast has no measured remaining headroom at this farm
      scale, and flat-`min_hires_per_day` hiring is not a defect to keep chasing - it is the measured
      answer. No parameter changed as a result; `workload_forecast_scaling_only` ships at its
      bit-identical default (`True`) purely so future sweeps have the knob named rather than
      hardcoded. No Kaggle submission in this task (per the user's own chosen order) - the submission
      question returns now that this is settled.

- [x] T8.29 — fix `labor_units`'s stale hiring signal, prompted by the user's own strategic question
      (2026-09-14): "Как думаешь какие дальше шаги предпринять?" - farms almost always run with 1
      farmer + 1 hand, starting cash never fully deploys (floor ~$500-1000, idle even once more comes
      in), only one quadrant ever meaningfully develops, and animals are rare, while top-10 competitor
      games start with 3-5 hands, both crops and animals from day 1, 3-4 quadrants and 6-8 hands
      mid-game, and finish at $120k-140k vs our ~$30-45k. A live self-play trace confirmed the pattern
      exactly (hand count pinned at 2 for all 30 days, farm plateaus at one quadrant most of the game,
      money repeatedly drains to ~$500 and sits there, zero animals ever acquired) and root-caused it
      to `decide.py`'s `labor_units = 1 + hires_per_day(params)` - a **bare call with no runtime
      arguments**. Every real path inside `hires_per_day` (reactive `pending_task_count`, proactive
      workload-forecast) needs at least one of `hour`/`animal_tile_counts`/`crop_tile_counts`/
      `days_remaining`/`money`; with none given, both fell straight through to the static fallback
      (default 1), so `labor_units` was **hardcoded at 2 every turn of every game**, completely
      decoupled from `dynamic_hiring` (shipped default `True` since T8.16(d)) and from the farm's real
      workload - a leftover from Stage B (T8.6), never updated when `dynamic_hiring` shipped. This
      throttled `plant_budget`/`plant_qty`/`seed_target` - every cash-reinvestment throttle - to a
      fictional 2-unit labor force regardless of real hand count, and retroactively explains **T8.28's
      own rejection** of raising `min_hires_per_day` (extra hands had no extra planting capacity to
      use, since this throttle never moved).
      **Fix**: compute the forecast-aware `hires_per_day(...)` call once, early - right after the
      existing six-purpose tile scan (`placed_animal_type_counts`/`n_plant_tiles`), before
      `labor_units` needs it - using every argument genuinely available there:
      `animal_tile_counts=placed_animal_type_counts`, `crop_tile_counts=_crop_tile_counts(me["tiles"])`,
      `hour=current_hour`, `turns_per_day`, `money=me["money"]`, `days_remaining`. `pending_task_count`
      is the one input not available this early (needs `tasks`, which needs `plant_qty`, which needs
      `labor_units` - genuinely circular); harmless under the shipped default
      (`workload_forecast_hiring_aware=True` never reads it), a narrow documented gap only for the
      non-default reactive-only configuration. The existing late `target_hires` call (the actual
      HIRE-queuing loop) is unchanged, now reusing the same `days_remaining` instead of recomputing it.
      RED test added first (`test_decide_labor_units_reflects_the_real_dynamic_hiring_forecast_not_
      the_static_fallback`: 75 already-placed COW tiles forecast 3 hires under the shipped defaults,
      so `labor_units` should be 4, not the bug's fixed 2 - confirmed RED at 2 before the fix, GREEN
      at 4 after). Fixing exposed 4 more tests that pinned `labor_units` via the *static*
      `hires_per_day` param while leaving `dynamic_hiring` at its default-True (now overridden by the
      real forecast) - all fixed by adding `dynamic_hiring=False` explicitly, the same pinning pattern
      one test already used deliberately (`test_policy_decide.py` x3, `test_tuning.py` x1). Full suite
      green (440/440), compileall/boundary clean.
      **Measured** (`tools/measure_t829.py`): a pure code fix, not a new parameter, so measured as the
      current working tree against `tuning.snapshot_agent_from_git_ref("HEAD", ...)` (a real git-archive
      snapshot of the pre-fix checked-in code), both run with bit-identical `DEFAULT_PARAMS`. **Working
      92% (46W/4L/0T), holdout 98% (49W/1L/0T)**, Wilson [0.895, 0.996] - `accept_candidate=True`, a
      decisive, clearly-accepted win. Traced (`tools/trace_t829.py`, seed 900): confirms the mechanism
      directly - `plant_qty` on day 1 jumps from 13 to 19 tiles (the previously-throttled `labor_units`
      genuinely rising once the real forecast is used instead of the bug's fixed 2), the 2nd quadrant
      opens a day earlier (day 14 vs 15). Two honest findings, not glossed over: on this one seed,
      final money is *slightly lower* with the fix (36814 vs 42040) despite the 98% aggregate win -
      single-seed variance fully consistent with a 49/50 result, not a sign the fix is wrong. And hand
      count stays pinned at 2 on this seed even after the fix - not a remaining bug, but the real
      forecast genuinely never clearing `min_hires_per_day=2` for a farm this size (matching T8.28's
      own finding), which is exactly the natural **T8.30 follow-up**: re-sweep the hiring floor now
      that planting capacity genuinely scales with it (it didn't before this fix, which is why T8.28's
      sweep found no headroom - that finding needs revisiting, not re-trusting, now that the throttle
      it measured against no longer exists). Zero animals acquired on either side of the trace -
      confirms the separate, still out-of-scope animal-ranking root cause (`_top_investment_choice`
      structurally favoring crops like MELON over COW even at full tile-count saturation, found but
      deliberately not bundled into this task) remains untouched and is its own future task.
      Golden episodes re-recorded (a real, mixed-but-net-positive move across all six tracked seeds,
      e.g. starter/seed2: 44914 -> 46745 +4.1%; pass/seed1: 44707 -> 44462 -0.5% - consistent with the
      measured aggregate win, not a regression). No Kaggle submission in this task - ask before any
      further one, as always.

- [x] T8.30 — re-sweep the hiring-floor knobs now that `labor_units` genuinely scales (T8.29's own
      named follow-up, user: "Пожалуйста начинай реализацию исправления этих проблем" after T8.29's
      report). T8.28's own sweep of `min_hires_per_day`/`max_hires_per_day`/`turns_per_task_estimate`/
      `hire_buffer_fraction` ran *before* T8.29's fix - every candidate it tried lost because raising
      the floor bought idle hands with no extra planting capacity to use (`labor_units` was hardcoded
      at 2 regardless of real hand count). That finding needed re-testing, not re-trusting, now that
      planting capacity genuinely tracks the real forecast.
      **Measured** (`tools/measure_t830.py`, joint `coordinate_ascent` sweep against the checked-in
      baseline, i.e. plain `DEFAULT_PARAMS` - T8.29's fix is now the shipped default, nothing to
      toggle): floors 3/4/5/6 (above the current 2), tighter `turns_per_task_estimate` (1.5, 1.0), one
      buffer probe (0.1) - 8 candidates total. **Every single one lost decisively** to the shipped
      baseline on the working block (win rates 0.00-0.04, all far below 0.5) - not close calls, and
      *worse* than T8.28's own pre-fix rejection (which found win rates up to 0.20). `coordinate_
      ascent` kept the shipped default `(2, 8, 2.0, 0.0)` as the winner (no candidate ever beat it).
      Held-out gate confirms trivially: candidate == baseline (bit-identical), so all 50 games tied
      (0W/0L/50T), `accept_candidate=False`.
      **Conclusion, honestly recorded as predicted**: this closes the open question, the same way
      T8.28 did before it, just now under the corrected `labor_units`. Raising the hiring floor still
      does not help - not because planting capacity doesn't scale with it anymore (T8.29 fixed that),
      but because the underlying `hires_per_day` forecast itself never asks for more than
      `min_hires_per_day=2` hands at this farm's real scale (T8.28's own seed-900 trace already showed
      the raw pre-clip forecast target never exceeding 1 across all 30 days) - forcing a higher floor
      just buys idle hands the forecast never wanted, at real fib-scaled hiring cost, with nothing
      productive to show for it. The bottleneck confirmed to be genuinely elsewhere (most likely land/
      quadrant count limiting how much there is to plant in the first place, not the hiring formula) -
      not chased further here, out of scope for this task. No parameter changed; `tools/measure_t830.py`
      kept as a record of the re-test. No seed-900 trace or golden-episode re-record needed (nothing
      changed). No Kaggle submission in this task - ask before any further one, as always.

- [x] T8.31 — let animals compete for investment, not just win-or-nothing against the single top crop
      (the second of T8.29's own named follow-ups, same user request as T8.30 above). Confirmed
      structurally this session via direct `score_portfolio` computation: at day 0 (fresh market),
      MELON scores ~119/tile-day vs COW's ~23, and even saturating a single crop type to 25+ tiles
      (self-impact) only demotes *that* crop - the ranking just rotates to the next fresh crop type
      (STRAWBERRY ~30, CARROT ~21, WHEAT ~19), never forced to consider an animal, since
      `_top_investment_choice` requires the top animal to beat the single best crop score and
      self-impact decay is scoped per-crop, not farm-wide. Matches the user's own top-10 comparison:
      our farms run 1 quadrant/0 animals while competitors run animals *and* crops from day 1.

      **Stage 0** (cheap sanity check before building anything new, per this project's own established
      discipline): re-swept `investment_commit_margin` (T8.14, only ever tested positive before) into
      negative territory - -0.1, -0.2, -0.3, -0.5 - against the checked-in baseline
      (`tools/measure_t831_stage0.py`). **Result: every single candidate produced literally zero
      behavioral difference from the baseline across all 400 games measured (50 working + 50 holdout
      x 4 candidates, all ties, 0W/0L on every block)** - stronger than the predicted "unlikely to be
      sufficient": the gate never once flipped a single decision in a single game, even at the most
      extreme margin tested. Confirms the score gap (MELON ~119 vs COW ~23, needing roughly -80% to
      flip per this session's own direct computation) is far too wide for any margin in a plausible
      range to matter - `investment_commit_margin` is not the lever. This is real, decisive evidence
      that Stage 1's new-mechanism approach is necessary, not a wasted detour.

      **Stage 1** (the real fix, new mechanism): added `always_pursue_one_animal` (bool, `decide.py`/
      `params.py`/`policy.json`) - when set and the farm has no animal anywhere in any form (not
      placed, not stuck in the shed, nothing in `farmer_inventory` for any animal type), the single
      best-scoring animal (via new helper `_top_animal_choice`, mirroring `_top_investment_choice`'s
      animal branch and maturity check but scored via `score_portfolio` **without** ever comparing
      against `best_crop_score`) is pursued in parallel with whatever crop the normal ranking already
      picked - inserted right after `have_animal_anywhere` is computed in `decide()`, downstream of
      the existing `stuck_animal`/`max_animals_per_type` gates, which still take over unaffected once
      any animal exists. RED tests first (`test_policy_decide.py`, 6 new: 3 for `_top_animal_choice`
      in isolation - best animal wins, skips one that can't mature in time, `None` once nothing can -
      and 3 for `decide()`'s new parallel path - explicit-off reproduces the pre-T8.31 either/or
      behavior bit-identically, `True` queues `BUY_ANIMAL` alongside the crop's own `BUY_SEED`, and
      the path correctly stops firing once any animal already exists anywhere). Fixing exposed 3 more
      tests whose intent was unrelated to this new mechanism (fertilizer-priority, wheat-restock-
      ping-pong) - fixed the same way as T8.29's own churn, by pinning `always_pursue_one_animal=False`
      explicitly.
      **Measured** (`tools/measure_t831.py`, the flag alone against the checked-in baseline):
      **working 94% (47W/3L/0T), holdout 96% (48W/2L/0T)**, Wilson [0.865, 0.989] - a decisive,
      accepted win, stronger than the prediction stated up front ("genuinely uncertain in direction").
      Traced (`tools/trace_t831.py`, seed 900): the candidate acquires a COW by day 1 and holds it the
      entire game (zero animals on the baseline throughout, confirming the structural bias was real,
      not just theoretical), final money slightly *higher* on this seed too (37023 vs 36814, +0.6%)
      even with the 2nd quadrant opening one day later than the baseline. Default flipped to `True` in
      `params.py`/`policy.json`. Full suite green (446/446), compileall/boundary clean.
      Golden episodes re-recorded - an honest, notable finding, not glossed over: **all six fixed
      seeds moved lower** (e.g. starter/seed2: 46745 -> 42108, -9.9%) despite the large, decisive
      96%-holdout self-play win - the real ongoing spend of always acquiring an animal (cost + feed)
      is a real cost these six particular seeds don't happen to recoup, while the much larger 100-seed
      self-play sample does recoup it on net (and seed 900's own trace shows the opposite direction
      directly) - genuine seed-to-seed variance, not a sign the fix is wrong; the self-play win rate
      is the real acceptance signal, not six fixed numbers. This closes both of T8.29's own named
      follow-ups (T8.30 re-swept and confirmed rejected; T8.31 built and accepted). No Kaggle
      submission in this task - ask before any further one, as always.

- [x] T8.32 — comprehensive land+hiring re-sweep, the user's own follow-up hypothesis after seeing
      T8.30/T8.31's results (2026-09-14): late/capped quadrant openings and the hiring floor likely
      interact - land alone can't help without hands to work it, hands alone can't help without land
      to put them on. Two research agents confirmed this precisely: the game allows 4 quadrants/100
      tiles for $7,000 total (not a game limit); the real limiter is this repo's own `should_buy_land`
      gate (`land_purchase_threshold_money=15000`, `land_buy_max_free_tile_fraction=0.1`), tuned in
      T8.3/T8.8 when the farm had only 1-2 labor units and genuinely could not work even one 25-tile
      quadrant, never re-tested since T8.29's labor fix and T8.31's animal-pursuit mechanism landed;
      `hires_per_day`'s forecast only ever counts already-planted tiles, never free/potential land.
      Seed 900 (T8.29/T8.31 traces): 2nd quadrant opens day 14-15/30, never reaches a 3rd, despite
      money sitting at $20k-37k through the back half of the season - well past the gate's own
      threshold.

      **Stage 1** (cheap joint measurement, no new code): `tools/measure_t832.py`, joint
      `coordinate_ascent` sweep of `(land_purchase_threshold_money, land_buy_max_free_tile_fraction,
      min_hires_per_day)` - 7 curated combinations including land-only loosening, hiring-floor-only
      raising (a direct cross-check against T8.30's own result), and several joint strengths.
      **Result**: land-only loosening (10000, 0.2, 2) lost (20%); hiring-floor-only (15000, 0.1, 4)
      lost completely (0%), reproducing T8.30's own direction. **Every joint combination that raised
      both together scored above the land-only or hiring-only results** - winner `(10000, 0.2, 4)`:
      working 56% (0.560, Wilson [0.423, 0.688]), **held-out 64% (32W/18L/0T), Wilson
      [0.501, 0.759]** - a real, positive point estimate, clearly the strongest result this project has
      measured for either knob alone (T8.30's own best was 0.040), but **`accept_candidate=False`**:
      the held-out interval still overlaps the even-odds baseline's own Wilson interval
      ([0.366, 0.634], `harness.wilson_interval(25,50)`) - `wilson_intervals_overlap` correctly finds
      genuine overlap in `[0.501, 0.634]`, so this does not clear the project's own strict
      non-overlap acceptance bar at n=50, despite a numerically higher win rate (`tools/tuning.py`'s
      own documented discipline: "a numerically higher win rate alone isn't enough if the two
      intervals still overlap"). **Not accepted as the new default** - `params.py`/`policy.json`
      unchanged.
      Traced anyway (`tools/trace_t832.py`, seed 900, since this is a real, promising, well-evidenced
      direction even though unaccepted) to see the mechanism directly, and it confirms cleanly: the
      candidate hires 4 hands from day 0 (vs the baseline's 2), opens the 2nd quadrant on day 12 (vs
      day 15), and opens a **3rd quadrant on day 15 - something the baseline never reaches at all**
      across the full 30-day season on this seed; `plant_tiles` peaks at 32 vs the baseline's ~26;
      final money 43286 vs 37023 (+17% on this one seed, consistent with the 64% aggregate). The
      mechanism the user hypothesized is real and works exactly as described - it just hasn't yet
      cleared this project's own strict acceptance bar at the current sample size/parameterization.
      **Not a rejection to abandon** - a promising, honestly-recorded direction that motivates Stage 2
      directly (see below), and a candidate worth revisiting later (e.g. a wider grid search around
      `(10000, 0.2, 4)`, or simply a larger held-out sample) if Stage 2 alone doesn't close the gap.
      No parameter changed; no golden-episode re-record (nothing shipped differs).

      **Stage 2** (the deeper fix for the cold-start gap Stage 1's own prediction named): `hires_per_
      day`'s forecast had always counted only *already-planted* tiles, never free/unlocked-but-
      unplanted land, so hiring never proactively ramped ahead of newly-opened land. Added `workload_
      forecast_free_tile_weight` (float, default `0.0`) - `free_tiles * weight` is added into the
      forecast's `total_turns` alongside the existing `animal_turns`/`crop_turns` terms; `hires_per_
      day` gains a new `free_tiles` parameter, threaded into both of `decide.py`'s existing call sites
      (T8.29's own early `labor_units` call and the late HIRE-queuing one). RED tests first
      (`test_policy_strategy.py`, 3 new: weight defaults to `0.0`/bit-identical even with `free_tiles`
      given, a nonzero weight hand-verified to raise the forecast, `free_tiles` alone doesn't activate
      the branch without both tile-count dicts) plus a `test_policy_decide.py` glue test mirroring
      T8.29's own shape (fresh empty farm, `free_tiles=100` from the base fixture: `plant_qty` 3 at the
      default weight -> 5 at `weight=0.5`, hand-verified directly before writing the assertion). Full
      suite green (450/450), compileall/boundary clean.
      **Measured** (`tools/measure_t832b.py`, two sweeps of `workload_forecast_free_tile_weight`
      {0.1, 0.25, 0.5, 1.0}): **Stage A** (weight alone, shipped land gate untouched) - 0.1/0.25
      produced zero behavioral difference (all ties, land stays locked so there's nothing extra to
      hire for), 0.5/1.0 actively **lost** (8%/4%, worsening to 8%/8%) - confirms the predicted risk
      exactly: proactive hiring ahead of tiles still locked behind the strict gate is pure wasted
      cost. **Stage B** (weight combined with Stage 1's own unaccepted `(10000, 0.2, 4)`) - all four
      weights reproduced Stage 1's own result **exactly** (working 56%, held-out 64%, identical
      W/L counts and Wilson intervals at every weight tried) - verified this is real, not a wiring bug,
      via a direct mid-episode check (`plant_qty` 5 -> 7 at `weight=1.0` in a realistic farm state, so
      the mechanism does change intermediate hiring/planting decisions) - the marginal extra hiring
      pressure from free tiles, on top of Stage 1's already-loosened land+hiring, doesn't happen to
      flip enough of these 100 seeds' final win/loss outcome to move the aggregate number, even though
      it measurably changes behavior mid-game. **Conclusion**: neither Stage 1 alone, Stage 2 alone, nor
      any combination tried clears this project's own strict acceptance bar. Stage 1's `(10000, 0.2, 4)`
      remains the most promising lead measured so far (64% held-out, real mechanism confirmed by trace)
      but stays unaccepted; Stage 2's land-aware forecast is a real, correctly-wired mechanism that adds
      no further measured benefit on top of Stage 1 and actively hurts without it. No parameter changed;
      `workload_forecast_free_tile_weight` ships at its bit-identical default (`0.0`) purely so this
      remains a named, swept knob rather than unbuilt. No golden-episode re-record (nothing shipped
      differs). Both directions (a wider grid search around Stage 1's own winner, and/or a larger
      held-out sample) remain open, honestly-recorded leads for a future task, not abandoned. No Kaggle
      submission in this task - ask before any further one, as always.

      **Addendum - larger-sample retest** (user request: "Попробуй увеличить выборку"): Stage 1's own
      `(10000, 0.2, 4)` scored 64% on the standard 50-seed held-out block but was not accepted (interval
      overlap with the even-odds baseline). `tools/measure_t832_large_n.py` retested the same single
      candidate against the checked-in baseline on a 200-seed sample (`range(900, 1100)` - the original
      50 held-out seeds 900-949 plus 150 freshly-unused ones 950-1099, never touched by any prior
      search/tuning decision in this project), using the same `accept_candidate`-vs-even-odds convention
      as every prior script. **Result: win_rate dropped from 64% (n=50) to 54.5% (109W/91L/0T, n=200)**,
      Wilson interval `[0.476, 0.613]` overlapping the even-odds baseline's own `[0.431, 0.569]` at
      n=200 - `accept_candidate=False`, and clearly does *not* clear even the mathematically-computed
      n=190 threshold that would have been sufficient at a genuine 64% rate. **Conclusion: the original
      64%/n=50 was mostly sampling noise, not a stable large-sample effect** - the real underlying effect
      of `(10000, 0.2, 4)` is more likely a weak ~54-55% edge, which this project's strict acceptance bar
      correctly continues to reject even at 4x the sample size. This resolves the "larger held-out
      sample" lead named above: it was tried, and it revised the estimate down rather than confirming it.
      **Not accepted; no parameter changed.** No golden-episode re-record (nothing shipped differs). This
      closes out the T8.32 line of investigation for now - a materially different mechanism, not a bigger
      sample of the same one, would be needed to move further. No Kaggle submission in this task.

Fresh Kaggle submission (2026-09-14, user-approved: "Да, сабмитить сейчас"): ref `56224998`
(commit `da87ce2`), bundling every accepted change since the previous submission (ref `56214285`,
commit `777e46a`) - most notably T8.16(d)'s `dynamic_hiring` (98% held-out) and T8.27's corrected
workload-forecast hiring (92% held-out), plus the T8.25 WHEAT feed-restock fix. Logged to
`data/arena/submissions.jsonl` before the API call per `SPEC-ops.md`; confirmed registered via
`get_competition_submission` (team `Gruberx`, 159087 bytes). Score not yet checked - per this
project's own established finding, a fresh submission's score is volatile for its first ~20 minutes.

- [x] T8.33 — right-size the post-land-purchase cash reserve, the user's own follow-up question
      (2026-09-15): "Зачем так много денег должно оставаться после покупки нового квадранта? ...
      Нужно найти оптимальную сумму для баланса." Confirmed from source before measuring: realistic
      burn is $100-900/day (hands $54/day flat, seeds ~$50-900/day, animals $300-500 once) against
      mid-season balances of $20k-37k, land is last in `decide.py`'s spend tail so it can't outbid
      seeds/animals within a turn, and `land_purchase_threshold_money` is the only active cash floor
      (the purpose-built `seed_cash_reserve`/`hire_cash_reserve` both ship at 0, never swept). T7.4 and
      T8.8 both swept low thresholds and both moved the ascent upward, but neither ever recorded a
      per-value win rate, and both ran on code superseded by T8.29's labor fix and T8.31's
      `always_pursue_one_animal` - this task's Stage 1 is the first isolated, recorded sweep of these
      values on current code.

      **Stage 1** (measurement only, no new code): `tools/measure_t833.py`. Axis A swept
      `land_purchase_threshold_money` alone over `[0, 1000, 2000, 3000, 5000, 7500, 10000]`
      (`land_buy_max_free_tile_fraction` left at shipped 0.1) on the 50 tuning seeds against the
      checked-in baseline (15000). **Every single value produced the exact same result**: 12.0%
      win rate, 6W/44L/0T, byte-identical across all seven thresholds - a flatness striking enough to
      demand a direct trace before trusting it, per this project's own T8.3b discipline. Axis B (top
      two thresholds x `land_buy_max_free_tile_fraction` ∈ {0.1, 0.2}) found the same shape: 20.0%
      (10W/40L/0T) for threshold=0 at fraction=0.2, still a decisive loss.

      **Traced the mechanism directly** (not just accepted the aggregate): a solo-vs-"pass" trace on
      seed 900 (`tools/trace_t833.py`, following `trace_t832.py`'s pattern) showed *no* divergence at
      all between threshold=0 and the 15000 baseline - money on that seed jumps past $20k by day 12,
      so both thresholds clear trivially and the solo trace is misleading for this parameter. A scan of
      20 tuning seeds confirmed every one was "same" in solo play. The real divergence only shows up in
      *competitive* paired play (shared market with a real opponent, not "pass") - confirmed first by
      ruling out a harness bug: baseline played against a literal copy of itself produced 20/20 ties
      (perfect determinism, no confound), so the non-tie results genuinely come from the swept
      parameter. A direct paired trace of threshold=0 vs. baseline on seed 100
      (`tools/trace_paired.py`-style ad hoc script, both farms' state dumped from the *same* shared
      episode) found the actual mechanism: threshold=0 opens its 2nd quadrant on day 15 while still
      under-capitalized (~$13,470, well below the baseline's 15000 floor); the baseline instead waits
      until day 23, once money has already grown past $16,000 on its own. Critically, **hand count
      stays flat at 2 for both agents the entire 30-day season** - neither variant hires more labor to
      work the new land. The early-buying agent ends the season with *less* final money ($35,905 vs.
      $36,701) than the agent that waited: the second quadrant sits partially idle (planted-tile count
      never gets meaningfully ahead of the 1-quadrant baseline) while the cash that bought it is no
      longer compounding. **The 15000 threshold is not acting as a literal "cash needed for
      consumables" floor** (consumable burn genuinely is $100-900/day, confirming the pre-measurement
      analysis) - **it is acting as an indirect proxy for "production is established enough that
      expansion won't outpace labor,"** and lowering it defeats that proxy without offering anything in
      its place, since neither `should_buy_land` nor either candidate value gives the farm more hands
      to work the extra land.

      **Confirmation on the extended 200-seed holdout** (`range(900, 1100)`, per the T8.32 addendum's
      own lesson about n=50 noise): threshold=0/fraction=0.2 scored 31.5% (63W/137L/0T), Wilson interval
      `[0.255, 0.382]` cleanly excluding the even-odds baseline's `[0.431, 0.569]` - a *decisive*,
      statistically real rejection, not noise and not ambiguous. `accept_candidate=False`.

      **Not accepted; no parameter changed.** No golden-episode re-record (nothing shipped differs).
      This is a real, informative null result in the user's own preferred direction, not a failure to
      route around: the user's premise (burn is small relative to the reserve) is correct, but the
      reserve's actual job in this codebase is a labor-readiness proxy, not a liquidity buffer - so
      Stage 2 as originally scoped (a reserve sized to the *seed cost* of the land, i.e. still a pure
      liquidity measure) would very likely fail the same way, since seed-affordability was never the
      binding constraint here. Flagged to the user rather than built blind, since it changes what
      Stage 2 should even attempt (a labor-aware gate, not a smaller/adaptive liquidity floor) - this
      overlaps territory T8.30 already explored from the hiring-floor side and found losing. No Kaggle
      submission in this task.

- [x] T8.34 — widen `workload_forecast_free_tile_weight`'s sweep to test whether hiring's pin-to-
      floor problem can be fixed before any labor-aware land gate (T8.33's own follow-up; user's
      choice, 2026-09-17: "давай 1 вариант" - fix hiring first). Before measuring anything, confirmed
      empirically (not just from a docstring's claim) that hand count is pinned at `min_hires_per_day=2`
      for the *entire* season under shipped defaults, on all 15 tuning seeds checked (`max_hands=2`
      every time, solo play). Root cause pinned down analytically by calling `hires_per_day` directly
      with representative tile counts: T8.32 Stage 2's own swept range for
      `workload_forecast_free_tile_weight`, `[0.1, 0.25, 0.5, 1.0]`, **never crosses the point where the
      forecast's raw target exceeds the floor** - the target only starts moving at weight~2 and needs
      weight~5-10 to reach meaningful levels. This fully explains T8.32 Stage 2's "flat, no benefit"
      result: the swept range was structurally incapable of ever changing `hires_per_day`'s output, so
      of course every value performed identically to weight=0.

      **Stage 1**: `tools/measure_t834.py` swept the *calibrated* range `[1, 2, 5, 10, 20]`, and for
      each value both measured self-play win rate AND directly checked max hand count reached (10-seed
      solo diagnostic) - checking the mechanism alongside the aggregate this time, not only after a
      suspicious result (T8.33's own lesson). **The mechanism works exactly as predicted**: max hands
      reached climbed 4 (weight=1) -> 7 (weight=2) -> 8/saturated (weight>=5) - the floor genuinely
      breaks. **But win rate is a clean, decisive loss at every single weight, getting worse as hiring
      increases**: weight=1 8% (4W/45L/1T), weight=2 26% (13W/37L/0T, the least-bad), weight=5/10/20 all
      2% (1W/49L/0T) - a near-total wipeout once the boost saturates to `max_hires_per_day=8`.
      `accept_candidate=False` at every value; no confirmation run needed (Stage 1 itself already
      rejected outright).

      **Traced the mechanism** (weight=2 vs. baseline, paired match, seed 100): `free_tiles` is highest
      on **day 0**, before a single tile has been planted - exactly when there's no real backlog to
      justify extra hands. The forecast fires an immediate day-0 hiring burst (4-8 hands, Fibonacci-
      priced) that reverts to 2 hands again by day 1 once tiles get planted and `free_tiles` shrinks -
      a one-time, structurally-mistimed cost, not a sustained productive increase. That single day's
      overspend left the weight=2 variant with a persistently thinner cash cushion (~$300-700 behind
      baseline) for the rest of the season; in this traced seed, that lag caused its planted-tile count
      to fall just short of the `land_buy_max_free_tile_fraction=0.1` occupancy gate at the one moment
      late in the season when the baseline crossed it, so the weight=2 farm never opened its 2nd
      quadrant at all (final money $35,618 vs. baseline's $37,855, which did). `free_tiles` is a poor
      hiring-demand signal precisely because it peaks when demand is lowest (nothing planted yet, no
      maturing crops yet) - the mirror image of T8.33's own finding that spending ahead of established
      need loses, not a new lesson but the same one from the hiring side instead of the land side.

      **Not accepted; no parameter changed.** This closes the "fix hiring first" path the user chose:
      a real attempt, correctly calibrated (confirmed via direct computation, not guessed), which
      breaks the floor exactly as intended but loses decisively for a well-understood reason. Combined
      with T8.33's own finding, both directions of the land+hiring co-optimization hypothesis (loosen
      land waiting for hands to catch up, T8.33; loosen hiring waiting for land to justify it, T8.34)
      have now been tried and rejected on current code - the codebase's current shipped values
      (`land_purchase_threshold_money=15000`, hiring pinned near its floor) are not merely untested
      defaults but the surviving winners of a real, repeated search. No golden-episode re-record
      (nothing shipped differs). No Kaggle submission in this task.

- [x] T8.35 — daily development dashboard, reusable diagnostic infrastructure (user's own request,
      2026-09-17, after seeing T8.34's day-0 hiring-burst finding: a concrete hypothesis about the
      *shape* healthy development should have - hire, work, harvest, sell, reinvest, hire again - and a
      request for the instrumentation to check where the real trajectory departs from it: crop/animal
      loss, hand count, quadrant timing, cash flow, purchase affordability, and whether sale prices hit
      the floor, all by day). None of this existed - every prior `trace_t83N.py` read five fields
      (hands/planted-tiles/animal-tiles/money/quadrants) and nothing anywhere diffed consecutive steps
      for loss events, since the engine has no event log at all (`info` is always `{}`).

      Built `tools/daily_dashboard.py` as committed, reusable infrastructure (like `tools/harness.py`/
      `tools/tuning.py`, unlike the disposable `trace_t83N.py` one-offs) with real RED-then-GREEN tests
      (`tests/test_tools_daily_dashboard.py`, 20 tests, all passing on first implementation). Pure,
      independently-tested detection functions reconstruct events from the real engine's own end-of-day
      rules (`kaggle_environments/envs/kaggriculture/kaggriculture.py`, not `src/kagg/gamelib/` which
      only mirrors constants): `classify_plant_transition` (drought death at `consecutive_unwatered>=2`
      vs. lifespan decay, reusing this repo's own tested `kagg.gamelib.decay.decay_step` rather than
      reimplementing it), `classify_animal_transition` (escape at `consecutive_unfed>=2`),
      `is_price_floor_pinned` (price==1 AND inventory unchanged - the engine's own "sale only grows
      inventory when price>1" rule, the precise signature of dumping into a dead floor), `order_fill`
      (diffs `private["seeds"]`/`["shed"]`/`unlocked_quadrants`/`hires_today` against each submitted
      order's requested quantity for an exact, engine-truth affordability signal), and
      `land_gate_status` (delegates to the real `strategy.should_buy_land`, only adding the money-vs-
      occupancy breakdown it doesn't itself report). Schema correction found while building this:
      `obs["private"]["seeds"]` is a sibling of `farms`, not inside `farm[i]`, and must be read
      per-player (`steps[t][i].observation["private"]`), unlike the shared `farms`/`market`/`town` keys
      (always via index 0).

      `pytest tests/ -q` (470 passed, no regressions), `compileall` clean. No `strategy.py`/`params.py`/
      `policy.json` changes - read-only diagnostic tooling, no golden-episode re-record, no submission.

      **Ran it** (the actual deliverable) on seed 900 solo (vs. `pass`), seed 100 solo, and seed 900
      paired (checked-in baseline vs. itself, for real competitive market dynamics) - real findings, not
      a hypothetical instrument:
      - **Animal escapes do happen, but rarely**: one real escape found (seed 100, day 28, COW) out of
        3 traces - not the dominant failure mode in these samples.
      - **Crop deaths cluster almost entirely on the season's last 1-2 days** (day 28-29 in all three
        traces, mostly STRAWBERRY, a mix of drought and decay causes) - reads as the agent simply
        stopping maintenance once the season is ending (nothing left to gain from watering a crop that
        won't be harvested again), not a mid-season problem.
      - **Land-purchase timing is real and shifts a lot with competition**: quadrant 2 opened day 14-15
        in both solo traces but day 22 in the paired trace - confirms T8.33's own finding that a real
        competitor slows cash accumulation, now visible directly rather than inferred.
      - **New finding, only visible in paired play**: on day 3 of the paired trace, ~20 consecutive
        `BUY_PRODUCT` (WHEAT restock) orders came back `filled=0` - a sustained, nearly full-day feed-
        supply crunch from market competition for WHEAT that never appeared in either solo-vs-"pass"
        trace. Didn't cause an actual animal loss in this trace, but is exactly the kind of previously-
        invisible risk the user asked this tool to surface - worth a closer look as a future task, not
        chased further here.
      - **No product hit the price floor in any of the 3 traces** - contrary to the user's suspicion
        this might be a live problem, at least in these samples it wasn't; only 3 single-episode samples
        though, not a swept claim.
      - **Caveat, stated rather than hidden**: many `BUY_SEED requested=1 filled=0` events fire even at
        day 12+ with $20k+ on hand - almost certainly the documented `order_fill` lower-bound artifact
        (a same-turn PLANT consumes the seed before the buy is diffed), not real underfunding. Not fixed
        in this task (diagnostic scope only); flagged so the event log isn't over-read at face value.

      **Addendum - per-day minimum sale price** (user request after seeing the first table: "не хватает
      минимальной цены продажи товара по дням"): added `track_daily_min_price` (4 new tests, 24/24
      passing) - a pure accumulator run in a first pass over the *whole* episode before any headline row
      prints, since a day's row prints at `hour==1` (1-2 turns into that day), before most of that day's
      own price movement has happened. New `day_min_price` column shows the cheapest product and its
      lowest price reached that day. Re-ran the seed 900 vs. `starter` trial: the daily minimum was
      WHEAT for the first 14 days, **rising** from $25 to $35 (scarcity from active feed-buying, not a
      crash), then CARROT flat at $35-36 for the rest of the season - no evidence of price-floor dumping
      in this trace, consistent with the earlier "0 products at floor" finding, now shown as an actual
      trend instead of a single floor/not-floor bit. `pytest tests/ -q`: 474 passed, `compileall` clean.

      **Correction - a single global minimum was the wrong shape** (user's follow-up: "Это только цены
      на покупку семян и зерна? Мне также интересна цена на продажу готовой продукции... В разные ячейки
      покупка отдельно, продажа отдельно"): the single `day_min_price` figure was structurally dominated
      by whichever of the 9 `PRODUCTS` simply has the lowest *base* price (WHEAT $25, CARROT $35), so it
      could never surface MILK/MELON/WOOL/EGG's own price movement even when interesting - not a bug, a
      wrong question. Replaced it with two separate accumulators, `day_buys`/`day_sells` (new
      `record_daily_transaction`, 4 new tests, 29/29 passing), built the same first-pass way, populated
      only from orders that actually filled that turn (`order_fill`, now also handling `SELL` - the
      engine decrements `shed[item]` for a sale, the opposite direction from every `BUY_*`). Found and
      fixed one real bug before shipping this to the user, not after: WHEAT plays two distinct roles
      (a fixed seed cost via `BUY_SEED` and a genuinely market-priced feed restock via `BUY_PRODUCT`) -
      both were recorded under the same `"WHEAT"` key, so a same-day seed purchase silently overwrote
      that day's real feed-restock price (e.g. day 20 showed a misleading `WHEAT $10` - the fixed seed
      cost - hiding the actual $41 restock price). Fixed by keying seed purchases as `"<crop> seed"`,
      distinct from the market-priced product name. Re-ran the trial: WHEAT's feed-restock price rises
      steadily $27->$41 through day 20 (real, sustained scarcity, matching the paired-play finding from
      the original T8.35 entry above); sell prices show MILK appreciating steadily $186->$298, STRAWBERRY
      $100->$235, MELON oscillating $210->$81 without ever approaching the floor, FERTILIZER drifting
      $100->$98 - genuine per-product signal, none of it previously visible. `pytest tests/ -q`: 479
      passed, `compileall` clean.

- [x] T8.36 — investigate the daily WHEAT buy/sell pattern T8.35's new columns surfaced (user's own
      observation, 2026-09-18: "агент покупает пшеницу и потом её же и продаёт... возможно резерв на
      удержание пшеницы должен зависеть от количества животных"). Both the user's original hypothesis
      and my own follow-up attempt turned out wrong, in an honest and now precisely traced way - this is
      a real, informative rejection, not a failure to route around.

      **Investigation**: traced turn-by-turn (`check_t836_escapes.py`-style ad hoc script, seed 900 vs
      `starter`) rather than trusting the daily table. Found the actual mechanism: `tasks._WHEAT_PICKUP_
      BATCH=10` (matching `_WHEAT_FEED_RESERVE=10` by design - see `decide.py`'s own comment on
      `wheat_reserve`) pulls the *whole* reserve out of the shed into the farmer's own inventory the
      moment any animal needs feeding, even though only 1 unit/animal/day is actually consumed via FEED.
      The user's original hypothesis (reserve should scale with animal count) doesn't hold - a flat
      reserve of 10 is already generous for 1-3 animals; the real gap is that `market.buy_wheat_order`'s
      restock check only ever looks at the *shed* count, blind to WHEAT already secured in a unit's
      carried inventory (which safely returns to the shed at end-of-day via the real engine's own
      `_drop_inventories_to_shed` - nothing is lost there), so it re-buys a fresh batch nearly every day
      even with spare units already in hand.

      **The fix attempted** (my own hypothesis, also wrong in the end): new parameter
      `wheat_restock_counts_carried_inventory` (default `False`, bit-identical) - when set, sums shed +
      every unit's carried inventory for the restock decision instead of the shed alone. TDD: 4 new tests
      in `tests/test_policy_decide.py` (483 total passing), wired in `decide.py`
      (`_DEFAULT_WHEAT_RESTOCK_COUNTS_CARRIED_INVENTORY`), synced to `params.py`/`policy.json`.

      **Measured (`tools/measure_t836.py`) - a decisive loss, not the predicted win**: 38.0% win rate
      (19W/31L/0T) on the working block, Wilson interval `[0.259, 0.518]` - `accept_candidate=False`,
      stopped before the n=200 confirmation per this project's own convention (no point confirming a
      result that already lost outright). **Traced why** (seed 100, paired candidate vs. the checked-in
      baseline, same episode): the candidate lost a COW to starvation on day 25
      (`ANIMAL ESCAPED COW at (4,4)`) that the baseline, in the *identical* episode, never lost -
      `candidate final=34949` vs. `baseline final=35724`. Root cause: WHEAT carried in one unit's own
      inventory (e.g. the farmer's, after a PICKUP for feeding one animal) is not shareable with a
      *different* unit's own FEED task without a fresh shed PICKUP - summing all units' carried
      inventory into one "total wheat on hand" figure made the restock check think the farm was well-
      stocked when a second animal's own feeding hand actually had nothing to draw from, since the shed
      itself sat empty. **The daily buy/sell pattern that looked wasteful is not actually wasteful**: per
      `market.py`'s own docstring, a buy/sell round trip against a stable market nets ~$0 (verified
      numerically there already), and keeping the shed topped up is exactly what lets a *second* unit's
      independent PICKUP succeed mid-day - the same protection `wheat_reserve` was built for in T6.4/
      T8.3l, just showing up one layer further down than either hypothesis in this task expected.

      **Not accepted; parameter stays at its bit-identical `False` default** (kept as named, tested,
      documented-but-unaccepted infrastructure - same convention as `wheat_urgency_reserve`/
      `hire_cash_reserve`). No golden-episode re-record (nothing shipped differs). `pytest tests/ -q`:
      483 passed, `compileall` clean. No Kaggle submission in this task.

      **Correction to this entry's own "traced why" above** (found immediately after, while answering the
      user's own follow-up question about how much WHEAT one character can carry): `PICKUP`/`FEED`/
      `PLACE` are unconditionally pinned to the farmer alone (`tasks._PINNED_UNIT_INDEX=0`, T8.4's own
      fix - "a hired hand can never silently pick up wheat... or feed"), so there was never a *second*
      unit that could have needed its own separate wheat access - that explanation doesn't hold and
      should not have stood without first checking it. Re-traced the same seed 100 COW-escape properly:
      the real cause is that `wheat_price` sat at **$42-45 for the entire window** (days 18-25), already
      above `wheat_max_buy_price=40` - `buy_wheat_order`'s hard price ceiling, not the wheat-on-hand
      check, is what actually blocked every restock attempt in this window, for *both* variants equally.
      What differed is the *buffer built up before* hitting that wall: comparing total WHEAT (shed +
      carried) at each day's start, days 5-16, baseline restocks aggressively enough to hold a ~19-unit
      plateau, while the candidate's "skip the buy once the total already clears the threshold" logic
      lets it hover much lower (~5-14, oscillating with the flat `wheat_restock_qty=10`, never
      accumulating the same cushion). Baseline enters the day-17+ price-locked window with 9 units of
      runway (9 more days before a miss); the candidate enters it with roughly half that, and runs out
      first - the COW's second consecutive miss (day 24) and escape (day 25) is a direct consequence of
      the *thinner buffer*, not of any unit being denied access to wheat it structurally couldn't reach.
      Restated plainly: the "wasteful-looking" frequent restocking the user first noticed is accidentally
      building insurance against a hard, unconditional price ceiling that has no override by default
      (`wheat_urgency_reserve=0` - see `market.buy_wheat_order`'s own docstring for the already-built,
      currently-unswept escape valve this points to for a real future attempt). The measured rejection
      itself stands (a real, decisive loss, confirmed twice now under two different explanations) - only
      the *mechanism* is corrected here, not the result.

- [x] T8.37 — resweep `wheat_urgency_reserve` against today's shipped baseline (user's own request,
      2026-09-18, after T8.36's traced COW escape: past animal-unprofitability conclusions might be
      confounded by undetected starvation, not real economics). Three research agents confirmed the
      landscape first: raising `wheat_max_buy_price` and the `wheat_self_sufficiency_aware` "grow your
      own feed" hedge are both already-tried, decisively-rejected or near-no-op dead ends (see this
      session's plan file / T8.36's own entries); `wheat_urgency_reserve` was real, working, and traced
      to save 5/5 animals at `max_animals_per_type=3` (T8.25), but shelved because at the shipped
      `max_animals_per_type=1` "the single animal's buffer already survives without it." That premise
      was measured before T8.27/T8.29/T8.31 - since T8.31 now guarantees an animal from day 1 of every
      game (not rarely, as when T8.25 measured this), the premise looked stale enough to warrant a
      resweep, not just re-reasoned about.

      **Measured (`tools/measure_t837.py`) - the premise turns out to still hold; a real, decisive
      rejection, confirming T8.25's original finding rather than overturning it**: `wheat_urgency_
      reserve=0` (identical to baseline) ties 50/50 as expected (sanity check the harness is comparing
      correctly); `2`, `3`, and `5` all produce the *exact same* result, 16.0% win rate (8W/39L/3T),
      Wilson interval `[0.083, 0.285]` - a clean, decisive loss. `accept_candidate=False` at every value;
      no n=200 confirmation run (already rejected outright), no Stage B joint test with
      `max_animals_per_type=2` (gated on Stage A winning).

      **Traced why** (seed 105, paired candidate `wheat_urgency_reserve=3` vs. the checked-in baseline,
      same episode): the mechanism works exactly as designed - shed WHEAT stays comfortably stocked
      (~10) all season, **zero escapes** for the candidate. But once WHEAT's price crosses $40 (day 15),
      the override fires *every single day* for the rest of the season, buying at $40-53/unit instead of
      the $25-30 it would have paid earlier - an unconditional "insurance premium" paid daily whether or
      not an escape was actually imminent. The baseline, in the *same* episode, **did** lose its COW -
      but on day 29, the literal last day of the season, when the loss costs almost nothing (a full
      season of production already banked). Final money: candidate $32,846 vs. baseline $34,903 -
      baseline wins even *with* an escape, because losing an animal on the last possible day is far
      cheaper than paying full price-cap-defeating premiums for two weeks straight. Confirms the exact
      economic logic T8.25 originally found: escapes are still a *rare*, often *late-season and low-cost*
      event even under today's more animal-friendly defaults, while the override's cost is paid
      unconditionally and often - T8.31 changed how often an animal is *held*, not how often it's
      actually at real risk of a costly (early/mid-season) escape.

      **Not accepted; no parameter changed.** My own plan's prediction ("plausible real win... precisely
      because the premise that rejected it before... is what changed") was wrong, stated honestly rather
      than reframed after the fact - a good-faith, traceable prediction that a real measurement corrected,
      exactly the discipline this is for. `wheat_max_buy_price` stays 40, `wheat_urgency_reserve` stays 0.
      No golden-episode re-record. No Kaggle submission in this task.

- [x] T8.38 — permanent animal-escape regression guardrail (Stage 2 of the same task as T8.37).
      Confirmed directly (research agent, this session): no `measure_t8*.py` script and no
      golden-episode test anywhere had ever checked for an escape - the one animal-pipeline test
      (`test_at_least_one_animal_reaches_production_in_a_representative_episode`) only asserts a
      product appeared once, ever, so an animal that produces once and escapes on day 12 would still
      pass it silently.

      New `test_no_animal_escapes_across_the_golden_seeds` in `tests/test_agent_golden_episodes.py`,
      reusing `daily_dashboard.classify_animal_transition` (already unit-tested, zero new detection
      logic) against the exact same six `(opponent, seed)` pairs `_GOLDEN` already records money for -
      diffs every consecutive step pair across the *whole* episode, not just the final one. Checked
      first, not assumed: all six golden episodes currently have **zero** escapes under shipped
      defaults (confirmed by direct run before writing the assertion) - a real, currently-true
      invariant, not a test that starts red. Unlike `_GOLDEN`'s own money table (which legitimately
      gets re-recorded when an accepted change moves it), this test is designed to *never* need
      re-recording - a farm's animal escaping is never something to accept as a "new golden number."

      `pytest tests/ -q`: 484 passed, `compileall` clean. No shipped code changes - this is test
      infrastructure only. No Kaggle submission in this task.

      Closes out the cheap, high-confidence half of the T8.37/T8.38 plan. The larger, separate
      follow-up named in that plan - unpinning `FEED`/`PICKUP` so more than the farmer alone can feed
      animals (the user's own "помощники в кормёжке" request, confirmed feasible: it's a policy-layer
      bookkeeping simplification, not an engine constraint) - remains explicitly out of scope here, its
      own future task.

- [x] T8.39 — any free unit can FEED an animal / PICKUP its wheat (the T8.37/T8.38 follow-up, user's
      own request, 2026-09-18: "нужны помощники в кормёжке... их учет чтобы они кормили животных, а не
      просто удерживали зерно"). Confirmed directly against `kaggriculture.py`: `FEED`/`PICKUP`'s real
      handlers never check which unit acts - `tasks._PINNED_UNIT_INDEX=0` is a pure policy-layer
      bookkeeping choice, not an engine rule; it exists only because `decide()` historically modeled
      `inventories[0]` alone.

      **Part 1 (plumbing, gated where it had to be)**: `build_task_list`/`tasks` now thread the real
      per-unit `inventories` list through the task layer. New `_units_holding` helper; `Task` gains an
      additive `eligible_units` field; `assign_units` gains a third "restricted" resolution stage
      (between pinned and unpinned) that matches a restricted task to the globally nearest *free and
      eligible* unit, resolved before plain unpinned work. FEED/FERTILIZE bind to `eligible_units`
      (any unit currently holding the item); PLACE binds to the specific unit that actually holds the
      bought animal. FERTILIZE also picked up a real, previously-latent gap along the way - it had no
      unit binding at all before this, harmless only because `use_fertilizer` defaults off.

      New param `feed_pickup_unpinned` (default `False`) gates the actual behavior change: the
      aggregate wheat PICKUP becomes assignable to any free unit, and the WHEAT-holding scan widens
      from unit 0 alone to every unit. **That WHEAT scan specifically needed the gate, unlike
      FERTILIZE/PLACE's unconditional multi-unit awareness - found while implementing this, not
      anticipated in the plan**: making it unconditional moved two golden episodes' final money.
      Traced to a real coupling: `HARVEST`'s own handler deposits a crop's yield into the *acting*
      unit's own inventory, and WHEAT is both a crop and the feed item, so a hired hand harvesting a
      WHEAT tile genuinely holds WHEAT today, invisible to `decide()` only because nothing before this
      task ever looked past unit 0. Gating the scan behind `feed_pickup_unpinned` restored exact
      bit-identity with the flag off (confirmed, not assumed: full suite green, both golden-episode
      tests - money and the T8.38 escape guardrail - byte-identical). The animal PICKUP/PLACE pipeline
      stays pinned to the farmer regardless of this flag, a deliberate scope limit named in the plan.

      16 new tests (`tests/test_policy_tasks.py`, `tests/test_policy_decide.py`): the restricted
      `assign_units` stage, FEED/PICKUP/FERTILIZE binding, the livelock guard generalized to N tiles
      vs. M holders, and an end-to-end "busy farmer + free wheat-carrying hand" scenario. Committed
      separately (Part 1) before any measurement, per this session's own discipline.

      **Traced (`tools/trace_t839.py`, seeds 100/28, 105/29, 900) before measuring**: the mechanism
      works exactly as designed - a free hand really does FEED (seed 100 day 28: `hand[1]: ['FEED']`),
      never more than one wheat PICKUP per day (no livelock), and the flag *did* convert one of
      T8.35/T8.37's own known escapes into a survival (seed 100: baseline's COW escaped day 28,
      candidate's did not). Seed 105's previously-known escape no longer reproduces under today's
      baseline at all (superseded by later fixes this session) - not this task's mechanism at work.

      **But the traced money moved the wrong way**: seed 100, converting the escape into a survival
      still finished *lower* ($43,712 candidate vs. $46,706 baseline) - saving the animal cost more in
      diverted hand-turns and wheat than the animal's own last-two-days production was worth, the same
      "insurance premium exceeds a rare/late/cheap escape" economics T8.37 already found for
      `wheat_urgency_reserve`. Seed 105 (no escape either way) also finished lower for the candidate.

      **Measured (`tools/measure_t839.py`) - decisive rejection, confirming the trace**: Stage A
      (`feed_pickup_unpinned=True` alone, 50 tuning seeds) win rate 32.0% (16W/34L/0T), Wilson interval
      `[0.208, 0.458]` - does not clear `accept_candidate`. No n=200 confirmation run (already rejected
      outright), no Stage B joint test with `max_animals_per_type=2` (gated on Stage A winning, per the
      plan).

      **Not accepted; `feed_pickup_unpinned` stays `False`.** Part 1's plumbing ships regardless (a
      real correctness fix and the named prerequisite for ever retrying `max_animals_per_type>1` - see
      T8.25's own "labor-gating" note) - only the behavioral flag is rejected. Consistent with T8.37's
      own finding: at a single animal, the cost of *always* paying labor/wheat to avoid a rare, often
      late-season, often cheap escape outweighs the escape itself. The user's original hypothesis
      ("past animal-unprofitability conclusions may be confounded by undetected starvation") is now
      fully resolved across both halves: T8.37 found the wheat-price-cap escape path was real but its
      fix still loses; T8.39 found the farmer-only-feeding constraint was real but lifting it still
      loses too, for the same underlying reason - a single animal's escape risk is already cheap enough
      that today's other defaults (T8.31's `always_pursue_one_animal`, T8.25's `wheat_urgency_reserve=
      0`) have it about right. `max_animals_per_type` remains 1; unpinning the *animal* PICKUP itself
      (the once-per-game step this task deliberately left pinned) remains a cheap, unbuilt follow-up if
      `max_animals_per_type` is ever revisited with this labor-gating fix now in place. No golden-episode
      re-record (nothing accepted). No Kaggle submission in this task.

- [x] T8.40 — real statistical study of top-leaderboard games (tooling + findings). User's own request,
      2026-09-18: after watching top-10 leaderboard replays, observed top players hiring many workers
      and holding many animals from day 1, expanding aggressively through ~day 10, then banking profit
      - the opposite of what our own self-play-only numbers (`hires_per_day=1`, `max_animals_per_type=1`,
      both measured only in 1-2-quadrant self-play against `pass`/`starter`) would predict is optimal.
      Explicit goal: gather real evidence instead of "непродуктивно ход[ить] по кругу" tuning against
      weak opponents. Pure research/data-gathering - **no `src/kagg/` changes in this task**.

      **Data path**: Kaggle staff publish `kaggle/kaggriculture-episodes-index` (a manifest pointing at
      one child dataset per day, `kaggle/kaggriculture-episodes-<date>`, ~650 top-rated episodes/day as
      full replay JSON, ~33MB each) - `mcp__kaggle-mcp__get_episode_replay` does not work in this
      environment (unusable stub), this dataset is the real path in. New `tools/top_replay_stats.py`
      (33 tests, `tests/test_tools_top_replay_stats.py`) parses real replay JSON (or live `env.steps` -
      `kaggle_environments.utils.Struct` is a `dict` subclass, so the same functions run unmodified on
      either) into a compact daily-granularity `episode_record`: per-type animal/plant counts, hands
      (day max, not a single undercounting hour-0 sample), money open/close/min/max, cash flow by
      category (hire/land/seed/animal/wheat-restock/other cost vs. sell revenue, reconciled exactly
      against the money delta), WHEAT/seed stock buffer, per-op action tallies with pass-fraction
      (labor saturation), wheat flow (feed actions vs. bought/sold, the honest substitute for the
      undecidable feed-vs-sale WHEAT split), quadrant-unlock days, shop-unlock timeline, market prices,
      and animal-escape/plant-death events (reusing `daily_dashboard.classify_animal_transition`/
      `classify_plant_transition` directly, not reimplemented). Records are saved durably to
      `data/top_replay_records/` (outside `diskguard.EVICTABLE`, unlike the raw replays in
      `data/episodes/`) so this can be revisited without re-fetching - confirmed by a `--load-records`-
      only rerun reproducing the exact same summary from the saved extract alone.

      **Verified against the one real episode already on disk before any fetch**: every reference
      number in the plan (day 0/12/27 hands/money/animals/plants/quadrants/shop counts, the shop-unlock
      day list, both players' quadrant-unlock days, and team-0's whole-episode market-op totals) matched
      the tool's output exactly.

      **Fetch**: targeted the leaderboard's top 5 (Majkel1337, SpaTaro, DSM, THIRD FARM CLUB, ymg_aq) x
      3 episodes. Real complication, not anticipated in the plan: DSM and THIRD FARM CLUB's *entire*
      episode history is dated today (2026-09-18, both climbed the leaderboard same-day) - today's
      dataset isn't published yet (confirmed: `get_dataset_info` on `kaggriculture-episodes-2026-09-18`
      returns permission-denied, i.e. doesn't exist), so **zero** of their episodes were fetchable this
      session; substituted the next-ranked teams with older history (Sida Zuo, Orbital Terraformer).
      Second complication: even for available dates, a real fraction of individual episode files 404'd
      ("Dataset not found") on both first attempt and retry - not a clean per-date pattern (5/8 attempts
      on the same day succeeded, others on the same day failed) - so several picks were replaced with
      the next-best-scored candidate from the same team. Final real yield: **11 episodes, 22
      team-seasons**, all 2026-09-15/16/17, across Majkel1337 (3), SpaTaro (2), Sida Zuo (3), Orbital
      Terraformer (3) - short of the ~15 planned, reported honestly rather than padded.

      **Real bug found and fixed before trusting the "ours" comparison cohort**: `self_play_records`
      initially defaulted the opponent to `"pass"` - since `episode_record` tags cohort once per whole
      episode (both teams), the do-nothing `pass` bot's near-zero stats were silently folded into the
      "ours" cohort alongside our real agent, dragging every median toward zero (`hands_max` medians
      read ~0 across the whole game). Fixed by defaulting to a mirror match (`agent_main.py` vs itself)
      - the standard meaning of "self-play" - which is also what makes a same-cohort tag correct in the
      first place. 20 self-play seeds (40 team-seasons) re-run after the fix.

      **Findings (top cohort, n=22 team-seasons, vs. our own self-play, n=40 team-seasons, medians
      [q1-q3] unless noted)**:
      - **Hands**: top day 0 `4 [4-5]` growing to `10 [10-10]` by day 29. Ours: flat `2 [2-2]` for
        *all 30 days* - `hires_per_day=1` (farmer + one hire) is never revisited after day 0.
      - **Animals held**: top day 0 `5 [4-5]` (COW/SHEEP/GOOSE mixed) growing to `15 [13-18]` by day 29.
        Ours: flat at `1` the whole game (`max_animals_per_type=1`, one COW) - by day 29 sometimes `0`
        (an uncompensated escape).
      - **Season-end money (day 29 close)**: top `$151,829 [$144,454-$163,059]` vs. ours
        `$35,257 [$33,512-$35,744]` - **top players end the season with ~4.3x our own money**, not a
        marginal gap.
      - **Quadrant expansion**: top unlocks NE at median day 6 (22/22 reach it) and SW at median day 9
        (22/22) - both quadrants, reliably, inside the first third of the season. Ours reaches NE at
        median day **22** (4x slower) and **never once unlocks SW in 40 team-seasons (0/40)** - directly
        confirms the user's "our 1-2-quadrant self-play isn't representative" concern with a real number,
        not an impression. SE is rare even for top players (1/22, day 18) - a third quadrant is a
        late-season stretch goal, not a default expectation, for anyone.
      - **Cash flow**: top's day-29 net cash flow is `+$10,212 [+$6,250 to +$13,619]`/day vs. ours
        `+$2,951 [+$2,771 to +$3,048]`/day - top's late-game profit engine runs ~3.5x ours. Early game
        (day 0) both cohorts run a deliberate deficit (`top -$2,667`, `ours -$1,982`) - upfront
        investment, not a mistake, on both sides.
      - **Escape/death rate, normalized (not just raw counts - top players holding far more animals/
        plants makes raw counts misleading on their own)**: escapes per 1000 animal-days: top `10.96`
        vs. ours `12.09` - **comparable**, not meaningfully different; top's 108 vs. our 14 raw escapes
        reflects exposure (5-19x more animals held), not carelessness. Plant deaths per 1000 plant-days:
        top `14.52` vs. ours **`23.6`** - our own watering/care policy is actually *less* efficient per
        plant than top players', despite tending far fewer plants. Neither finding was expected going
        in; both argue against "more animals/plants = proportionally more loss" as a reason to stay
        small.
      - **WHEAT stock buffer**: top carries a thin `1 [1-2]` day-0 buffer (matches this project's own
        `wheat_urgency_reserve=0`/T8.25 finding), ours carries a much larger `10` (a one-time initial
        purchase, never drawn down as deliberately) - both trend toward 0 by late game either way.
      - **Shop-unlock schedule (n=11 episodes, not n=1)**: the *day* sequence is **byte-identical across
        all 11 real episodes** - exactly `[3, 6, 9, 12, 15, 18, 21, 24]`, matching
        `configuration["townShopUnlockInterval"]=3` exactly - confirms the exogenous-timing hypothesis
        decisively (not assumed from one sample). The *shop identity* at each slot is **not** invariant
        (11/11 episodes have distinct name sequences) - a random draw each episode, uncorrelated with
        either player's actions. Refines, doesn't overturn, the plan's own hypothesis: timing is fixed,
        identity is exogenous-random, neither is player-influenced.

      **Read together**: the user's original observation holds up under real data, decisively. Top
      players' edge isn't explained by lower loss rates (escape rate is a wash, death rate is actually
      worse for us) - it's explained by scale: more hands, more animals, faster land, sustained
      reinvestment through day ~11, then a cash-flow engine several times the size of ours. This is now
      the evidence base for retrying previously-rejected mechanisms at a scale this data suggests was
      never actually tested: `max_animals_per_type`/hiring-target (rejected at T8.22/T8.25/T8.27/T8.39
      only ever under `hires_per_day=1`-scale labor), `wheat_urgency_reserve`/`wheat_restock_threshold`
      against the real observed thin buffer, and `use_fertilizer`/`animal_care_aware` (both off by
      default; not confirmed whether top players use FERTILIZE/CARE at meaningfully higher rates than
      us - not measured this task, a natural next `action_counts`-based follow-up).

      Full suite green (533 passed) before and after, `compileall`/`boundary_check.py` clean. Committed:
      `tools/top_replay_stats.py`, `tests/test_tools_top_replay_stats.py`, this entry - no `src/kagg/`
      changes, so one commit. `data/top_replay_records/` and `data/episodes/` are outside the git root
      (nothing to add there). **No tactical/parameter changes in this task** - a deliberate scope limit,
      per the plan; retrying any of the named mechanisms is separate, later, measured work. No Kaggle
      submission.

- [x] T8.41 — joint labor + animal-cap resweep: unpinning, priority, and domestic WHEAT (the T8.40
      follow-up, user's own request, 2026-09-19: "давай теперь на основе этих данных обновим тактику" -
      update tactics based on T8.40's real-data gap). Two rounds of follow-up during planning, both
      investigated directly against the real code before finalizing the plan (see
      `/root/.claude/plans/jazzy-jumping-lamport.md` for the full write-up folded into this entry):

      1. **"Is anything else hardcoded to the farmer specifically?"** Grepped every `unit_index`/
         `_PINNED_UNIT_INDEX` use in `tasks.py`: exactly one action was still farmer-only - the animal
         PICKUP (T8.39 deliberately left it pinned, scoping that measurement to the wheat pipeline
         alone). Everything else was already generalized.
      2. **"Once bought, an animal's setup should outrank all other map tasks - is that actually true
         today?"** Read `assign_units`/`_new_investment_tasks` directly: BUILD_COOP/BUILD_PASTURE/
         animal-PICKUP/PLACE all sat at `PRIORITY_PLANT` - the same tier as ordinary crop planting -
         and `assign_units` resolves tiers strictly in order, so this pipeline got zero free units
         whenever tiers 0-2 already consumed them all, the expected case on a busy farm. Confirmed, not
         assumed.
      3. **"Should purchases be spread via specialized worker groups, and what do real WHEAT numbers
         show?"** Seeds are a non-issue mechanically - PLANT draws from the shared `private["seeds"]`
         pool, no per-unit pickup step exists, so no "one unit hoards the seeds" failure mode is even
         possible. Recommended against static worker-group specialization: `assign_units`'s existing
         global-nearest-(unit,task)-pair matching already load-balances once the two real gaps above are
         closed, and a rigid split would trade T8.2's proven turn-to-turn assignment stability for a
         partition with no evidence it's needed. Computed directly from T8.40's already-saved extract
         (no new fetching, 330 real episode-day rows): top players run WHEAT-tiles/animals-held at
         median `1.06`/mean `1.09` during the mid-game plateau, `corr(WHEAT bought, WHEAT price) =
         -0.03` (they grow their own feed, not buy their way into a price spike) - ours: exactly `0`
         across all 640 sampled team-days (verified turn-by-turn, WHEAT always bought, never planted).
         `wheat_self_sufficiency_aware` (T8.24, already built) measured as an exact no-op before because
         "animals essentially never get bought" - this task's own animal scaling was meant to be the
         missing demand that mechanism needed.

      **Stage 0 (built, committed separately first)**: two new flags, both default `False`, bit-
      identical when off. `animal_pickup_unpinned` mirrors `feed_pickup_unpinned`'s own mechanism for
      the one pipeline T8.39 left out of scope. `prioritize_animal_setup` adds a new
      `PRIORITY_ANIMAL_SETUP` tier (between `PRIORITY_HARVEST` and `PRIORITY_ROUTINE_CARE`, still below
      `PRIORITY_PREVENT_LOSS` - an unplaced animal is idle capital, not something actually at risk the
      way a genuine prevent-loss target is) for BUILD_COOP/BUILD_PASTURE/animal-PICKUP/PLACE. 15 new
      tests (`tests/test_policy_tasks.py`, `tests/test_policy_decide.py`), full suite green (547
      passed), `compileall`/`boundary_check.py` clean.

      **Stage A (measured, `tools/measure_t841.py`) - decisively rejected, not a marginal miss**: the
      untested cell (T8.22/T8.25/T8.27/T8.28/T8.32/T8.34/T8.37/T8.39 all tested labor and animal-cap
      increases on the wrong cell - hiring increases with at most 1 animal on the farm, animal-cap
      increases at flat `min_hires_per_day=2` - confirmed directly against `strategy.hires_per_day()`).
      A diagonal grid, each candidate = `(min_hires_per_day, max_animals_per_type)` bundled with
      `feed_pickup_unpinned=True`/`animal_pickup_unpinned=True`/`prioritize_animal_setup=True`, on the
      50-seed working block against the shipped baseline: `(4, 2)` win rate `0.020` (1W/49L/0T),
      `(6, 3)` `0.000` (0W/50L/0T), `(8, 4)` `0.000` (0W/50L/0T) - monotonically *worse* with more
      labor/animals, not the predicted rise-then-plateau (a large win itself would have been suspicious
      per T8.33's own lesson; a monotonic loss like this is a different, real signal). Baseline row
      (identical params played against itself, a harness sanity check) landed at the expected 50.0%/
      0W/0L/50T. No candidate cleared `accept_candidate`; no 200-seed holdout run (nothing to confirm),
      no Stage B/C (both gated on Stage A clearing, per the plan).

      **Traced (`tools/trace_t841.py`, seeds 100-102 at (4,2), seed 100 at (8,4)) before writing this
      up - the real cause, not a bug**: `max_animals_per_type` never actually bound in *any* sampled
      seed, baseline or candidate alike - `animals_total` stayed at exactly `1` the entire game every
      time. A second animal simply never outranks crops under today's market/scoring regardless of the
      cap or labor available - the cap-increase half of this task's own hypothesis was never really
      exercised by any of these games. The real driver of the loss: the single NW quadrant's ~24
      workable tiles are already fully worked by the *baseline's* 2 units within the first several
      days - extra hands have nothing more productive to do until land actually expands, and land
      purchase (`land_purchase_threshold_money`/`land_buy_*`) is gated purely on money, never on labor,
      so more hands don't buy land any sooner on their own. Where the extra hands' time went instead:
      comparable-to-slightly-worse weed counts (routine care missed during the same brief per-tile idle
      windows, now spread across more units walking further for the same task density) and real, if
      modest, extra hire cost (`(8,4)`: `$1,620` over the season vs. baseline's `$60` - the fib-scaled
      per-day hire cost genuinely compounds at 8 hires/day even though it's negligible at 2).
      `sell_revenue` came in *lower* for the candidate in most traced seeds too (e.g. seed 100 `(8,4)`:
      `$43,793` vs. baseline's `$50,564`) - coordination overhead, not just idle capacity, a real
      downside from more units competing for the same small tile set. In the one case extra hands *did*
      eventually fund a 3rd quadrant (`(8,4)`, seed 100: 3 quadrants vs. baseline's 2), it happened at
      day 29 - one turn from season end, too late to capitalize on before liquidation.

      **Verdict: rejected, with the same rigor as T8.25/T8.28/T8.37's own null-result precedent.**
      Stage 0's two flags ship (default `False`, a real correctness fix each - the farmer-only PICKUP
      pin and the priority-starvation gap are both genuine, confirmed defects, worth having available
      even though this specific bundle didn't pay off), but no behavioral default changes:
      `min_hires_per_day` stays `2`, `max_animals_per_type` stays `1`,
      `feed_pickup_unpinned`/`animal_pickup_unpinned`/`prioritize_animal_setup` stay `False`. No
      golden-episode re-record needed (shipped defaults byte-identical; both golden-episode tests,
      including the permanent T8.38 escape guardrail, passed unchanged as part of the full suite).

      **What this actually resolves vs. what's still open**: T8.22/T8.25/T8.37/T8.39's shared "revisit
      `max_animals_per_type` once real labor exists" reopening condition is now closed, decisively - not
      because labor was the missing piece, but because it wasn't: land was. **The real, well-evidenced
      next narrower thing** (T8.40's own headline finding, still unaddressed): top players reach a 2nd
      quadrant by median day 6-9 (22/22), ours only around day 22-24 in this task's own traces, gated
      purely on `land_purchase_threshold_money`/`land_buy_max_free_tile_fraction`/`land_buy_min_
      frontier_distance` - none of which this task touched. A future task should test land-expansion
      timing directly (e.g. a lower/scaling `land_purchase_threshold_money`, or gating less
      conservatively on `land_buy_min_frontier_distance`), decoupled from labor - land, not labor, is
      what top players' extra hands actually have to work with. Separately, `wheat_self_sufficiency_
      aware`/the real WHEAT-ratio finding (investigation question 3 above) remains untested in practice
      for the same reason `max_animals_per_type` never bound: animals never scaled up enough in this
      task's own measurement to create the feed demand that mechanism needs - worth revisiting once (or
      if) a future land-expansion task actually gets multiple animals onto the farm.

      Full suite green (547 tests, including the 15 new Stage 0 ones), `compileall`/`boundary_check.py`
      clean. Two commits: Stage 0's plumbing, then this entry plus `tools/measure_t841.py`/`tools/
      trace_t841.py` (one-off tuning/diagnostic scripts, not part of the committed test suite - no
      further `src/kagg/` changes, Stage A was rejected). No Kaggle submission (nothing accepted).

- [x] T8.42 — land expansion: a real-data-calibrated joint labor+land resweep (T8.41's own named next
      step, user's own request, 2026-09-19: "давай теперь займёмся расширением земли"). **Accepted -
      the strongest, most decisively confirmed self-play result this project has measured for either
      land or labor.**

      **Real numbers, pulled from T8.40's already-saved extract (`data/top_replay_records/`, no new
      fetching) - far more extreme than anything tested before**: top players buy their 2nd quadrant
      (NE, $1,000) leaving essentially zero cash reserve - money right after the purchase medians in
      the tens to low hundreds of dollars across all 11 real episodes, several as low as $1-$88 (DSM
      `$2`, Arda Ceylan `$1`, SpaTaro `$81`) - against this project's shipped `land_purchase_threshold_
      money=15000` (requiring $16,000 on hand just to buy a $1,000 quadrant). Hired-hand count is
      front-loaded from day 0 far beyond anything measured before: `hands_max` median **4 on day 0**
      (never below 4), **6 by day 2**, **8 by day 6**, **10 by day 9**, **11 by day 11** - ours ships
      flat at 2 all season.

      **Extensive prior art, respected not re-litigated**: T8.3/T8.8 first calibrated these two land
      params under a real 1-2-labor-unit regime, explicitly flagged stale once T8.29's labor fix
      landed. T8.32 found a joint `(min_hires_per_day=4, land_purchase_threshold_money=10000,
      land_buy_max_free_tile_fraction=0.2)` scoring 64% at n=50 but regressing to 54.5%
      (`accept_candidate=False`) at n=200 - named "a candidate worth revisiting... via a wider grid
      search or a larger held-out sample." T8.33 found lowering `land_purchase_threshold_money` *alone*
      (labor left at 2) decisively rejected at every value 0-10000, confirmed at n=200 (31.5%) - traced
      cause: land bought without labor to work it just sits idle. T8.34 found raising labor via a
      *reactive* signal (`workload_forecast_free_tile_weight`) also decisively rejected - traced cause:
      the signal peaks day 0 before any backlog exists, then reverts, a mistimed one-time burst. What's
      new here: real numbers calibrate both levers much further than T8.32's own point, using the
      *stable floor* mechanism (`min_hires_per_day`, T8.32's own mechanism, not T8.34's rejected
      reactive one).

      **Stage 1 (`tools/measure_t842.py`), diagonal grid, 50-seed working block**: baseline (shipped: 2,
      15000) `0.000` (0W/0L/50T, a harness sanity check - identical params vs. itself); `(4, 10000)`
      (T8.32's own point, re-confirmed) `0.600` (30W/20L/0T) - `accept_candidate=False`, still
      overlapping; `(6, 2000)` `0.920` (46W/4L/0T) - clears; `(8, 0)` `0.960` (48W/2L/0T) - clears,
      the strongest. Per T8.32's own explicit n=50-noise lesson, went straight to a 200-seed
      confirmation for `(8, 0)` rather than trusting the n=50 number: **`0.895` (179W/21L/0T), Wilson
      `[0.845, 0.930]` entirely clear of the even-odds baseline's `[0.431, 0.569]` - `accept_candidate=
      True`, holds up decisively, not a repeat of T8.32's own regression trap.**

      **Traced (`tools/trace_t842.py`, seeds 100/101/900) before accepting**: hand count flat at exactly
      8 from day 0 through day 11 in every traced seed - the stable-floor mechanism working exactly as
      designed, no reactive mistiming. Land expansion is dramatic: candidate reaches **all 4 quadrants**
      by day 15-20 (NE day 11, SW day 12, SE day 15-21) vs. the baseline's 2 by day 22-25 - closing most
      of T8.40's own real gap (top players: NE by day 6-9; still a real remaining gap, not fully closed,
      but a large, genuine move in the right direction). `BUY_LAND` fired promptly across the traced
      episodes with no sign of being permanently blocked. Final money favored the candidate in 2/3
      traced seeds (e.g. 44103 vs. 35378; 51115 vs. 38601) and lost in the third (19396 vs. 23525) -
      consistent with an ~90% win rate, not universal dominance.

      **Real mechanical finding, confirmed not assumed - `_MAX_MARKET_ORDERS=10` order-queue crowding
      is real, not just a hypothetical risk**: `decide.py`'s final order list is `(hires + sells +
      tail)[:_MAX_MARKET_ORDERS]` - at `min_hires_per_day=8`, a turn with `hires_today` still low can
      queue up to 8 `HIRE` orders, leaving little or no room for `sells`/`tail` (where `BUY_LAND`/wheat
      restock/`SELL` live) *that specific turn*. This was directly confirmed, not speculated: 5
      pre-existing unit tests broke exactly this way (`BUY_LAND`/`SELL FERTILIZER`/`SELL MELON` orders
      silently missing from `action["market"]` on a synthetic single-turn fixture with `hires_today`
      unset). **Not a practical blocker, though**: the real multi-turn trace above shows `BUY_LAND`
      firing successfully across full episodes regardless (once `hires_today` reaches its target
      partway through the day, later turns free up the queue) - a real, once-per-day-at-most delay,
      not a permanent block, consistent with the strong measured win rate. Fixed the 5 affected unit
      tests by setting `hires_today` in their fixtures (mirrors the existing `test_decide_does_not_
      hire_past_the_daily_target` pattern) rather than changing `decide.py`'s own order-construction
      logic, which was not part of what was measured/accepted here - a real `_MAX_MARKET_ORDERS`/
      order-priority fix (e.g. reserving room for `tail` before `hires`) is a separate, still-open lead
      for a future task if a trace ever shows it costing real games, not assumed necessary from this
      evidence alone.

      **14 more pre-existing unit tests needed updating for the same root cause** (not order-queue
      crowding, but the *default value itself* changing): several `test_policy_strategy.py` tests
      computed their own expected `hires_per_day()` output using the shipped defaults directly (some
      literally commented "min/max_hires_per_day defaults") and needed their hardcoded `2` updated to
      `8`; others relied on the *old* default floor (2) being low enough not to interfere with a
      smaller hand-computed target, and needed an explicit `min_hires_per_day` override added to keep
      isolating the mechanism they actually test (matching this file's own established precedent for
      exactly this kind of isolation, e.g. `test_hires_per_day_dynamic_hiring_never_drops_below_min_
      hires_per_day`'s own comment). One (`test_hires_per_day_dynamic_hiring_min_hires_per_day_
      defaults_to_two`) was the default-value test itself, renamed and updated to assert `8`.

      **Golden episodes re-recorded** (`tests/test_agent_golden_episodes.py`, nineteenth re-record) -
      every single one of the six fixed seeds moved *higher*, a real and uniform jump (e.g.
      starter/seed3: 44688 -> 67716, +51.5%; pass/seed1: 42123 -> 49283, +17.0%), unlike T8.31's own
      mixed-but-net-positive record. `test_no_animal_escapes_across_the_golden_seeds` (T8.38) - the
      permanently non-re-recordable guardrail - passed unchanged.

      **Accepted**: `min_hires_per_day` 2 -> 8, `land_purchase_threshold_money` 15000 -> 0
      (`src/kagg/params/policy.json`, `src/kagg/policy/params.py`'s `DEFAULT_PARAMS`, and the matching
      `_DEFAULT_MIN_HIRES_PER_DAY`/`_DEFAULT_LAND_PURCHASE_THRESHOLD_MONEY` constants in `kagg.policy.
      strategy`). `land_buy_max_free_tile_fraction` untouched (shipped `0.1`) - the money threshold
      alone was already the dominant, binding gate at every level tried; not swept further here.

      **What's still open**: the remaining gap to top players' own NE-by-day-6-9 timing (ours: day 11
      typically) - `land_buy_min_frontier_distance` (still its shipped no-op `99`) or `max_hires_per_day`
      itself (top's day-9-11 hand counts, 10-11, exceed our shipped ceiling of 8) are the natural next
      levers, not tried here to keep this task's own grid diagonal rather than a wider cross-product. A
      genuine `_MAX_MARKET_ORDERS`/order-priority fix, if a future trace shows the crowding above
      actually costing real games (not just unit-test fixtures). `wheat_self_sufficiency_aware` against
      the now-real multi-animal feed demand this task's own labor/land scaling may finally create -
      T8.41 found it untested for lack of exactly this demand; worth re-checking now that land is no
      longer the hard bottleneck it was.

      Full suite green (547), `compileall`/`boundary_check.py` clean. Committed: `tools/measure_t842.py`,
      `tools/trace_t842.py`, the `src/kagg/` param changes, the 19 fixed pre-existing tests, this entry.
      No Kaggle submission yet - ask before submitting, as always.

- [x] T8.43 — post-expansion refinement: adaptive hiring, harvest-timing fix, real multi-animal pursuit
      (the user's own detailed feedback after watching real games post-T8.42, 2026-09-19, four
      concrete problems - see `/root/.claude/plans/jazzy-jumping-lamport.md` for the full request and
      investigation). **Stages 1-2 measured (both reported honestly - a rejected null result and a
      strong-win-rate-but-guardrail-rejected result); Stages 3-5 not yet started.**

      **Investigation found two of the user's four claims were real, previously-undiscovered mechanism
      gaps, not just calibration questions** (full evidence in the plan file): (1) hiring is a flat
      floor with no reactive boost when a new quadrant opens - `workload_forecast_free_tile_weight`
      already exists for this but was only ever measured under the old `land_purchase_threshold_
      money=15000` regime (T8.32/T8.34), never re-tested since T8.42; (2) `always_pursue_one_animal`'s
      own gate (`not placed_animal_type_counts`) is a one-shot trigger that permanently disables itself
      the instant *any* animal exists anywhere - the real reason `max_animals_per_type` has never once
      bound in any measurement (T8.41: `animals_total` stuck at exactly 1 regardless of the cap); (3)
      confirmed the user's own watering question ("yes, watering past first eligibility keeps adding
      yield") and found the ranking layer (`strategy._crop_yield_and_tile_days`) already assumes full
      bonus-window maturation while the task layer (`tasks._is_actually_harvestable`) has always
      harvested the instant a crop is legally harvestable - a real, previously undocumented
      inconsistency.

      **Stage 1 (`tools/measure_t843.py`, `defer_one_time_harvest_to_max_yield`) - REJECTED (null
      result)**: first attempt (deferring every one-time crop's harvest to `max_yield_day`) was
      decisively rejected - 40% win rate (20W/30L/0T), n=50. Traced (`tools/trace_t843_stage1.py`) to a
      real cost the plan's own first draft got wrong: MELON's bonus window (ages 6-12) does precede
      `first_yield_day=10` for *most* of its span but not all of it - ages 10-12 are inside both the
      window and past eligibility, so deferring unscoped delayed MELON's own harvest (this project's
      dominant crop by far its highest tile-turnover volume) by up to 2 real days per cycle. Re-scoped
      to only defer crops whose bonus window *starts* at or after `first_yield_day` (`min(watering_
      bonus_window(crop)) >= first_yield_day` - a principled, general condition, not a hardcoded
      WHEAT/CARROT list) and re-measured: `0.300` (15W/12L/23T) - mostly ties (WHEAT/CARROT are rarely
      the top-ranked crop under current play, so the mechanism rarely even activates) and roughly a
      coin flip (15W/12L) in the minority of games where it does. Below the `0.58` meaningful-win
      threshold either way - kept available (tested, off by default) but not accepted. **What's still
      open**: whether WHEAT/CARROT would activate more often (and the fix matter more) once Stage 3's
      hiring work or a starting-portfolio nudge (Stage 4) actually gets them planted in volume - not
      re-tried here per the plan's own "move on, don't get stuck" discipline.

      **Stage 2 (`tools/measure_t843_stage2.py`/`trace_t843_stage2.py`, `always_pursue_animal_target_
      count`) - measured a strong, decisively-confirmed win rate, then REJECTED on a stricter guardrail,
      not on win rate.** Generalized `always_pursue_one_animal`'s one-shot gate to a count (`sum(placed_
      animal_type_counts.values()) < target_count`, bit-identical at the default 1), with `_top_animal_
      choice` gaining an `excluded_types` parameter so a higher target count diversifies across animal
      types (skipping any already at `max_animals_per_type`'s own cap) instead of re-buying unlimited
      copies of the single highest-scoring type - closing the exact structural gap the investigation
      found. Grid on 50 working seeds: `target_count=2,cap=1` `0.600` (30W/20L/0T, `accept_candidate=
      False`); `target_count=3,cap=1` (all three animal types) `0.860` (43W/7L/0T, clears); `target_
      count=2,cap=2` (a second copy of the *same* type instead of diversifying) `0.400` (20W/30L/0T -
      actively worse, a second COW is a weaker bet than a first SHEEP/GOOSE). `target_count=3,cap=1`
      confirmed at n=200: **`0.835` (167W/33L/0T), Wilson `[0.777, 0.880]`, `accept_candidate=True`.**
      Traced (5 seeds, 900-904): candidate reaches GOOSE+SHEEP+COW by day 3 in every seed (baseline: a
      single COW all season), winning on final money in all 5 traced seeds.

      **Then `pytest tests/test_agent_golden_episodes.py` found `test_no_animal_escapes_across_the_
      golden_seeds` (T8.38's own permanently non-re-recordable guardrail) failing: 30 real animal
      escapes across the 6 golden seeds at `target_count=3` (zero at `target_count=1`).** That
      guardrail's own explicit rule ("a farm having its animal escape is never an improvement to
      accept") makes this disqualifying regardless of the win rate - reverted `always_pursue_animal_
      target_count` back to its bit-identical default of `1` despite the strong measured number, exactly
      the discipline this task's own plan named up front ("never re-recordable... rejected regardless
      of win rate"). **Root cause, verified structurally in code, not just inferred from the escape
      count**: `decide._WHEAT_FEED_RESERVE` (10) and `wheat_restock_threshold`/`wheat_restock_qty`
      (5/10) are all flat constants, sized for "at most 1 animal" (the only case that ever existed
      before this task, enforced by the very one-shot gate this stage fixed) - three animals with
      different feed schedules (GOOSE `interval=1`, SHEEP `interval=3`, COW `interval=2`) roughly triple
      simultaneous feed demand with no matching scale-up, causing recurring `consecutive_unfed>=2`
      escapes, especially before hiring ramps up early game. **What's still open, a concrete named next
      step**: scale the feed-supply chain (`_WHEAT_FEED_RESERVE`/`wheat_restock_threshold`/`wheat_
      restock_qty`, or `wheat_self_sufficiency_aware`'s own existing mechanism) with the real number of
      animals placed before ever re-attempting `target_count>1` - the mechanism itself (the gated
      `always_pursue_animal_target_count` param) is kept available, off/safe by default, exactly this
      project's established convention for a well-evidenced-but-currently-unsafe idea.

      Both new mechanisms (code + tests) committed as gated, bit-identical-off building blocks
      (`3d9f642`, "T8.43 Stage 0"). Full suite green (557), `compileall`/`boundary_check.py` clean.
      Golden money table unchanged (both stages ship at their bit-identical defaults) -
      `test_golden_episodes_reproduce_recorded_final_money` and the T8.38 escape guardrail both pass
      unchanged, no re-record needed.

      **Stage 3 (`tools/measure_t843_stage3.py`/`measure_t843_stage3b.py`, dynamic hiring re-test) -
      REJECTED, with a sharper structural diagnosis than the plan started with.** Before sweeping
      anything, found a real, previously-unnoticed fact: T8.42 raised `min_hires_per_day` 2 -> 8 but
      never touched `max_hires_per_day` (already shipped at 8) - so today's shipped params have
      `min_hires_per_day == max_hires_per_day == 8`. `strategy.hires_per_day`'s own clip, `min(max(
      target, min_hires), max_hires)`, collapses to exactly 8 regardless of what the forecast computes -
      `dynamic_hiring=True` is currently inert in practice, a flat 8 every day. Two sub-experiments, both
      on the 50-seed working block:
      - **3a (lower the floor)**: `min_hires_per_day` in `{2, 4}` x `workload_forecast_free_tile_weight`
        in `{0.0, 0.1}`, `max_hires_per_day` left at 8. Decisively rejected at every point - `min=2`:
        `0.080` (4W/46L/0T); `min=4`: `0.240` (12W/38L/0T). Weight 0.0 and 0.1 produced bit-identical
        W/L records at every single seed - not a bug, a real finding: the forecast's own animal/crop-turn
        total (with or without a small free-tile term) computes well below 8 most of the time, so `min`
        clips it back up regardless of the weight either way. Lowering the floor just lets that
        undersized forecast value through - actively harmful, confirming T8.34's own original "mistimed/
        undersized" finding on this mechanism, now under the new land/labor regime too, not just the old
        one.
      - **3b (raise the ceiling instead, the user's own literal formula)**: `max_hires_per_day` in
        `{12, 16}` x `workload_forecast_free_tile_weight` in `{0.3, 1.0}` (the user's own request treats
        free and occupied tiles equally, not "small relative to 1.0" as the mechanism's own docstring
        assumed), `min_hires_per_day` left at the accepted 8. Every single point tied the baseline
        exactly - `0.000` (0W/0L/50T), bit-identical behavior on all 50 seeds, not just a weak effect.
        **Mechanically verified why, not just observed**: `target = ceil(total_turns / 24) - 1` needs
        `total_turns > 216` to ever exceed 8 (`(8+1)*24`). At `weight=1.0`, `free_tile_turns` alone maxes
        out at 100 (the entire board, best case) - even with every animal/crop-turn term added on top,
        216 is structurally out of reach for a 100-tile board. The `/24` full-day-divide the mechanism
        was designed with (T8.26/T8.32, deliberately dividing by the whole day rather than remaining
        turns, per that docstring's own reasoning) makes it roughly an order of magnitude too small to
        ever compete with a static floor of 8, not just occasionally too small.
      **Verdict: the accepted static floor (`min_hires_per_day=8`, T8.42) is doing real, necessary work
      that the "dynamic" forecast mechanism cannot currently replace or usefully augment at any tested
      setting - not a tuning miss, a structural mismatch between the forecast's own `/turns_per_day`
      scaling and what a competitive hiring level (8+) actually requires.** `workload_forecast_free_
      tile_weight` stays at its shipped bit-identical `0.0`; `min`/`max_hires_per_day` stay at 8. **A
      concrete next step, not attempted here**: redesign the forecast's own scale (e.g. divide by
      `turns_left_today` like the reactive `pending_task_count` path does, or drop the `/turns_per_day`
      full-day framing entirely) before ever re-sweeping this axis again - the current formula's ceiling
      is the problem, not any single parameter choice within it.

      **Stage 4 (starting portfolio) - deferred, not built**: contingent per the plan on Stages 1-2
      first showing the organic ranking already produces something close to the user's proposed mix.
      Stage 2's mechanism (the one that would produce real multi-animal diversification) was rejected on
      the escape guardrail, not accepted - building a forced starting allocation on top of a still-unsafe
      feed-supply chain would risk recreating the same escape problem from a different angle. Waits on
      Stage 2's own named next step (scaling the feed-supply chain with animal count) before this
      question can be usefully re-asked.

      **Stage 5 (WHEAT sell-withholding) - not attempted this task**, deprioritized given Stages 1-3's
      combined evidence: the user's own proposed starting mix leaned on WHEAT/animals maturing faster
      than MELON, but Stage 1 found WHEAT rarely even gets planted under current play (mostly ties) and
      Stage 2's animal diversification is blocked on the same feed-scaling prerequisite as Stage 4 -
      withholding WHEAT sales to deny an opponent's (currently rare, on our own side) animal economy has
      a weaker case to make right now than when the plan was first written. T8.41's own real-leaderboard
      correlation (`corr(combined WHEAT bought, WHEAT price) ~ -0.03`) already flagged this as the
      weakest-evidenced of the four original ideas.

      Committed: `tools/measure_t843_stage3.py`, `tools/measure_t843_stage3b.py`, this entry. No param
      changes from Stage 3 (rejected). Full suite green, `compileall`/`boundary_check.py` clean, no
      re-record needed (nothing accepted).

      **Post-review update, the user's own explicit decision, 2026-09-19**: after reviewing Stage 1's
      numbers directly ("Выведи сколько побед, поражений и ничьих было в 1 этапе"), the user asked to
      enable the re-scoped Stage 1 candidate (`defer_one_time_harvest_to_max_yield=True`) by default
      anyway - "Она не ухудшает ситуацию, но потенциально может улучшить если использовать эти
      культуры" (it doesn't make things worse, and could help once these crops are actually used). This
      is a deliberate ship-ahead-of-full-confirmation call, not a project `accept_candidate` verdict -
      the measured number (`0.300`, 15W/12L/23T, n=50) never cleared the acceptance bar and was never
      confirmed at n=200. Flipped `defer_one_time_harvest_to_max_yield` `False -> True` in `src/kagg/
      params/policy.json`, `DEFAULT_PARAMS`, and `decide._DEFAULT_DEFER_ONE_TIME_HARVEST_TO_MAX_YIELD`,
      with the reasoning and the caveat recorded directly in the code comments (not just here). Golden
      episodes re-recorded a twentieth time: only 2 of the 6 fixed seeds moved at all (starter/seed1:
      47663 -> 54893, +15.2%; pass/seed1: 49283 -> 56320, +14.3% - both higher), the other 4 untouched
      (WHEAT/CARROT weren't planted in those particular episodes) - consistent with the measured mostly-
      ties result. **`test_no_animal_escapes_across_the_golden_seeds` (T8.38's own never-re-recordable
      guardrail) still passes unchanged - zero escapes** - confirming this is safe by that guardrail's
      own standard even without a full self-play accept. Full suite green (557), `compileall`/`boundary_
      check.py` clean. No Kaggle submission - ask before submitting, as always.

- [x] T8.44 — day-plan-driven dynamic hiring: burst-day-aware forecast built from real per-tile-today
      action counts, direct follow-up to T8.43 Stage 3's mechanical proof that `workload_forecast_
      hiring_aware`'s own formula can never exceed 8 hires from a realistic board (`total_turns > 216`
      needed, unreachable). **The user's own detailed request** (2026-09-19, after a session of hand-
      verifying real per-scenario turn costs directly against `kaggriculture.py`): compute, every turn
      (`decide()` is a pure function of `(obs, params)` - no cross-turn memory, confirmed by reading
      `agent_main.py`), a real turns-needed-today estimate - maintenance for already-placed tiles
      (WATER/FEED plus whatever HARVEST/CARE/FERTILIZE is actually due right now) plus already-decided
      new commitments (new PLANT+WATER, new animal BUILD+PICKUP+PLACE+FEED) - and drive the hiring
      target from it directly, generalizing to whatever crop/animal mix is actually being pursued.
      Turn-by-turn task execution stays unchanged (reactive); only the hiring target changes. Plus a
      same-day top-up gate for a newly-opened quadrant, deferring to the next day if too few turns
      remain today to be productive.

      Built in one pass (a single coherent formula, not several independently-testable stages like
      T8.43's five): `kagg.policy.tasks.crop_tile_day_actions`/`animal_tile_day_actions` (new helpers,
      reusing `_is_actually_harvestable` - inherits T8.43's own harvest-timing scoping for free) give
      each already-placed tile's real action count *today*, not `_crop_actions_per_tile_day`'s
      lifetime-averaged rate. `decide()`'s existing six-purpose tile scan extended to a seventh purpose
      (`maintenance_actions_today`, summing the two new helpers over every placed tile, plus a new
      `WEED` branch this scan never distinguished before - it fell through to a bare `unlocked_tiles`
      increment, uncounted beyond that). `planned_new_crop_tiles`/`planned_new_animals` computed right
      after `plant_crop`/`acquisition_animal` are both finalized (verified no circularity), capped by
      `free_tiles`/`day_plan_max_new_tiles_per_day` (one quadrant, 25) and, by default, affordability
      (`day_plan_new_tiles_cash_aware`). New `strategy.hires_per_day` branch (`day_plan_hiring_aware`,
      checked *before* `workload_forecast_hiring_aware`, which stays untouched as the fallback), full
      reuse of the existing `turns_per_task_estimate`/buffer/`[min,max]_hires_per_day` clip machinery.
      `hire_min_turns_left` gates same-day top-up HIRE orders once turns remaining today are too few,
      with a `hires_today == 0` escape hatch (never leave the farm with zero labor for a whole day).
      `max_hire_orders_per_turn` (default matches `_MAX_MARKET_ORDERS=10`) caps the HIRE-emission loop -
      load-bearing once `target_hires` can exceed ~10 (this mechanism's whole point): `hires` sits first
      in the final `(hires + sells + tail)[:_MAX_MARKET_ORDERS]` truncation, so an uncapped burst would
      silently drop every `tail` order (BUY_SEED/BUY_ANIMAL/BUY_LAND/wheat restock) that turn.

      All 7 new params bit-identical/off by default. 37 new tests (14 `tasks.py`, 8 `strategy.py`, 15
      `decide.py`) - full suite 594 passed, golden episodes bit-identical, `compileall`/`boundary_
      check.py` clean, `decide()` timing unaffected (~0.7ms on and off, both well under the 50ms
      target). Committed gated (`6a828f0`, "T8.44 Stage 0").

      **Measured (`tools/measure_t844.py`, 50-seed working block) - DECISIVELY REJECTED at every grid
      point, with a real, traced structural cause, not a tuning miss.** Per the user's own explicit call
      ("min_hires_per_day думаю надо снизить до 2... если оно не действует то скорее надо править это
      чем заменять таким высоким минимальным порогом"), `min_hires_per_day` was swept DOWN to `{2, 4, 8}`
      in the primary grid, not held at the accepted 8:
      - `min=2` (headline, `max=12, cap=25`): `0.300` (15W/35L/0T) - the same catastrophic shape T8.43
        Stage 3a found for the *old* forecast at a low floor.
      - `min=4`: `0.660` (33W/17L/0T) working-block win, but **collapsed to `0.490` (98W/102L/0T) on the
        200-seed holdout (900-1099) - REJECTED, statistically even, the working-block result was noise,
        not a real effect.**
      - `min=8` (T8.42's own accepted floor, otherwise headline): `0.180` (9W/41L/0T) - still decisively
        worse than the shipped baseline, even at the *same* floor value, because the day-plan forecast's
        own ceiling (`max=12`) and shape differ from the old one.
      - `max=16`, `hire_min_turns_left=6`, `max_hire_orders_per_turn=6`: all statistically indistinguishable
        from the `min=2` headline (~0.30-0.32) - none of these secondary axes changed the outcome.
      - `cap=8` (smaller new-tile-per-day cap): `0.080` (4W/46L/0T) - the worst point in the grid.

      **Traced directly** (`tools/trace_t844.py`, seeds 900-902, hand counts/PLANT/HIRE/BUY_SEED/money
      day-by-day for both `min=2` and `min=8` against the shipped baseline), specifically checking the
      plan's own named risk (the `labor_units` -> `plant_qty`/`seed_target` throttle spiral) per the
      user's framing that a low-`min` loss should be diagnosed, not just reported as a reason to keep
      `min=8`. **That specific spiral did NOT occur** - BUY_SEED/PLANT counts track real board need
      correctly at every traced day, never collapsing to zero while seeds/tiles were actually needed.
      **The real, different cause found instead**: the day-plan forecast, even though it correctly sizes
      *today's already-known* workload (confirmed directly - hands legitimately drop to 2 during the
      steady-state watering phase, days 1-8, exactly matching this session's own hand-derived formula
      that a 24-tile quadrant needs only ~2-3 workers to water), has **no way to anticipate tomorrow's
      burst**. The shipped baseline's flat `min=8=max` floor pays for hands that sit idle ~54% of the
      time during that same steady-state window (`hands_pass_fraction=0.54`, confirmed in the trace) -
      but because `HIRE` is nearly free (`fib(8)=$21` total) while a land purchase's own newly-opened
      quadrant needs a large labor force *immediately* to be worth anything, pre-positioning idle labor
      *before* it's needed beats reactively sizing labor to *exactly* today's known work, every time a
      burst is coming. The day-plan forecast, however accurate about the present, structurally cannot
      see a burst before it happens - each traced episode shows `min=2`'s hand count ramping slowly
      (2 -> 7 -> 9 over several days) after a new quadrant opens, while the baseline's already-hired 8
      hands start working it the very same day.
      **A specific follow-up hypothesis was tested and refuted, not left unchecked**: suspected
      `day_plan_new_tiles_cash_aware`'s affordability cap was compounding the ramp lag (money crashes to
      near-zero the instant land is bought, so that same turn's `planned_new_crop_tiles` term collapses
      too) - re-measured `min=2`/`min=4` with `day_plan_new_tiles_cash_aware=False`: `0.220` (11W/39L/0T)
      and `0.660` (33W/17L/0T, bit-identical to the cash-aware version) - disabling it did not meaningfully
      change either result, ruling this out as the dominant cause.
      **Verdict: this is the same structural finding T8.43 Stage 3 already reached from a different
      angle, now confirmed from the opposite direction too** - a *reactive* hiring signal (however
      accurate about current workload) cannot compete with a static high floor in this game's economy,
      because hiring is nearly free and land-purchase bursts are large and sudden. `day_plan_hiring_
      aware` stays off (bit-identical shipped default); `min`/`max_hires_per_day` stay at the T8.42-
      accepted `8`/`8`. **A concrete next step, not attempted here** (out of this task's scope per the
      user's own request, which was about sizing today's workload, not anticipating land purchases): a
      genuinely *anticipatory* signal - e.g. hiring ahead of a land purchase the farm itself is about to
      make (its own `should_buy_land`/cash trajectory is already known one step ahead), not a same-day
      reactive one - would need to look forward, not just at the present tile board, to ever beat the
      static floor.

      Committed: `tools/measure_t844.py`, `tools/trace_t844.py`, this entry. No param changes from
      measurement (rejected). Golden episodes/T8.38 escape guardrail untouched (nothing accepted). Full
      suite green, `compileall`/`boundary_check.py` clean. No Kaggle submission - ask before submitting.

      **Post-review fix + re-measurement, the user's own follow-up (2026-09-19)**: after seeing a
      per-day table of the rejected `min=2` candidate (hands hired, the forecast's own components,
      real actions done, and unwatered/unfed/weed counts, all by day), the user asked why day 0's
      forecast was so wrong (`4` computed vs `~46` real actions) and whether it could be fixed. Traced
      to a real, narrow bug: `planned_new_crop_tiles` was gated on `plant_crop`, which stays `None`
      until a seed is *physically on hand* (`have_seed`) - on day 0 (or any day starting from zero
      seed stock of the target crop), `BUY_SEED` can't settle until next turn (T8.5: market orders
      resolve after this turn's unit actions), so `plant_crop` is `None` even though `fallback_crop`
      (the ranking layer's own already-computed intent, real market prices already factored in via
      `_top_crop_basket`) already knew exactly what would be planted. **Fixed**: use `fallback_crop`
      instead (still gated on `stuck_animal is None`, the same condition that nulls `plant_crop`
      itself, for the same "finish the paid-for animal first" reason) - `src/kagg/policy/decide.py`,
      2 new tests (zero-seeds-held day-0 case now sees the real intent; `stuck_animal` still zeroes
      the forecast). Full suite green (596), golden episodes/`boundary_check.py` unaffected (still
      ships off by default). Committed (`638d5f0`).

      Re-traced (`tools/trace_t844.py`'s day-table variant): day 0's forecast corrected from `4`
      (`maintenance=0, new_crop=0`) to `54` (`new_crop=25`) - much closer to the real `~47` actions
      actually performed. **Re-measured the same grid (`tools/measure_t844.py`) - still DECISIVELY
      REJECTED at every point**, confirming the day-0 bug was real but not the decisive cause:
      `min=2` headline `0.300 -> 0.360`; `min=4` `0.660 -> 0.640` (working-block win, but holdout
      `0.490 -> 0.515` - still statistically even, still REJECTED); `min=8` `0.180 -> 0.240`;
      `hire_min_turns_left=6` `0.320 -> 0.460`; `max_hire_orders_per_turn=6` `0.300 -> 0.420`;
      `cap=8` stays the worst point (`0.080`). Several points improved measurably (the fix is real
      and directionally correct), but none crossed the acceptance bar, and the best candidate
      (`min=4`) again collapsed on the 200-seed holdout - reconfirming this task's own root-cause
      finding: the day-0 forecast error only ever affected the *first* day of a 30-day season, while
      the dominant loss mechanism (a reactive forecast structurally cannot anticipate a future
      land-purchase burst, so pre-positioned idle labor beats reactive same-day sizing) operates
      every time a new quadrant opens throughout the whole game. No further param changes -
      `day_plan_hiring_aware` stays off, `min`/`max_hires_per_day` stay at 8/8.

      **Second post-review follow-up (2026-09-19, the user's own request)**: reviewing a per-day
      table (hands, forecast breakdown, real actions done, план_ход/реал_ход - planned vs. real
      movement turns - and quadrant-open markers, requested incrementally over several turns) surfaced
      two real, further gaps:

      1. **Real movement cost per productive action grows with how many quadrants are open at once** -
         measured directly (`1 + total_move_actions / total_real_actions`, grouped by
         `len(unlocked_quadrants)`, across 3 traced 30-day episodes): 1 quadrant averaged `2.386`, 2
         quadrants `2.841`, 3 quadrants `3.390`. Implemented as `day_plan_turns_per_task_by_quadrant_
         count` (a new list param, `[2.4, 2.8, 3.4, 3.9]`), looked up by `n_quadrants` in `strategy.
         hires_per_day`'s `day_plan_hiring_aware` branch instead of the flat `turns_per_task_estimate`.
         Gated code+tests committed (`95c754a`, 8 new tests, full suite 604, golden/boundary_check
         unaffected - the mechanism itself stays off by default).

      2. **A WEED tile's real DIG handler clears it straight to `None`** (kaggriculture.py -
         `farm["tiles"][fy][fx] = None`, no plant restored), so a weeded tile a farm intends to keep
         productive needs a follow-up PLANT+WATER right after DIG - the existing WEED branch (`+1` for
         DIG only) undercounted this. Added `day_plan_weed_replant_aware` (default `True`) - a WEED
         tile's `maintenance_actions_today` contribution becomes `1 + day_plan_new_crop_tile_actions`
         (3 total) instead of `1`. Same commit (`95c754a`).

      **Re-measured (`tools/measure_t844.py`) with both changes applied - the quadrant-coefficient
      piece DECISIVELY REGRESSED every grid point, not improved it**: headline `min=2` `0.360 -> 0.220`;
      `min=4` `0.640 -> 0.360`; `min=8` `0.240 -> 0.220`; `max=16` and `cap=8` both collapsed to a flat
      `0.000` (0W/50L/0T - every single seed lost, not just a weaker average); only `max_hire_orders_
      per_turn=6` improved (`0.420 -> 0.500`). **Diagnosed the mechanical cause, not just reported the
      regression**: the per-quadrant-count ratios (`2.386`/`2.841`/`3.390`) were averaged across *every*
      day at that quadrant count, blending quiet steady-state-watering days (real ratio `~1.3-1.4`) with
      busy expansion/harvest days (much higher) - applying the averaged coefficient *uniformly* to every
      day at that quadrant count over-hired specifically on the quiet days, where the pre-existing flat
      `turns_per_task_estimate=2.0` was already closer to correct.

      **A follow-up hypothesis was designed, described to the user for approval *before* implementing
      (per their own explicit ask), and then checked against real data before writing any code - and
      refuted**: blend a "calm" and a "burst" coefficient via linear interpolation on `new_work_fraction`
      (the share of a day's forecast coming from *new* planting/acquisition, `planned_new_crop_tiles *
      day_plan_new_crop_tile_actions + planned_new_animals * day_plan_new_animal_actions`, over
      `total_actions`) - already-available forecast components, no new board scan needed. A weighted
      least-squares regression (`ratio ~ b0 + b1*fraction + b2*(n_quadrants-1)`, fit on 90 real
      day-samples pooled across the 3 traced episodes - per-quadrant-count-bucket fits were tried first
      and found unstable/contradictory with this little data, e.g. the 2-quadrant bucket had only 6
      days) found `b1` (the fraction's own slope) came out **negative** (`-0.48`) - the opposite of the
      assumed direction. Plausible mechanism (not just an unexplained sign flip): a burst day's new-tile
      planting is a tight, systematic sweep across adjacent tiles (efficient), while a calm day's
      scattered single-tile watering, routed by greedy priority-based assignment across multiple
      simultaneously-moving hands, is apparently *less* path-efficient, not more. **Not implemented** -
      building on a hypothesis the data itself contradicts would have repeated the same mistake, not
      fixed it.

      **Reverted the quadrant-coefficient piece, per the user's own explicit instruction** (`fe5a015`) -
      `hires_per_day`'s `day_plan_hiring_aware` branch is back to the flat `turns_per_task_estimate`
      unconditionally, `day_plan_turns_per_task_by_quadrant_count` removed from `params.py`/`policy.
      json`, its 6 tests removed. **The WEED-replant-cost fix was kept, not reverted** - it was verified
      independently against the real DIG handler and was never itself measured to regress anything (the
      combined measurement above can't separate the two effects, but the user's instruction was
      specifically to revert "the quadrant coefficient," and this fix stands on its own real-mechanism
      verification regardless). Full suite green (598) after the revert, golden episodes/`boundary_
      check.py` unaffected throughout (the whole `day_plan_hiring_aware` line of work has stayed off by
      default at every step). `day_plan_hiring_aware` remains a well-tested, gated-off mechanism - three
      independent refinements attempted (fallback_crop fix, quadrant-coefficient, calm/burst
      interpolation), one kept (fallback_crop fix, real but insufficient), one reverted (quadrant
      coefficient, measured harmful), one never implemented (calm/burst interpolation, refuted before
      writing code) - the core structural finding (a reactive same-day forecast cannot beat a static
      high floor against a sudden land-purchase burst) stands unchanged throughout all of this.

- [x] T8.45 - bulk seed/animal purchase + `plant_while_animal_pending` (the user's own request, 2026-09-19,
      after a per-hour trace of day 0 under the T8.44 day-plan config): only **21 of 24** planned tiles were
      planted on day 0 despite **33** idle unit-turns. Traced by hour (`seeds_held`, hand ops, PLANT/PASS):
      the 33 idle turns were two separate clusters, neither a labor shortage. (1) Hours 0-3 (9 turns): no seeds
      yet (BUY_SEED settles next turn, hires act from H+1) and a bought-but-unplaced animal (`stuck_animal`)
      nulls `plant_crop` - and, found while fixing it, `tasks._new_investment_tasks` returns *only* the animal
      pipeline whenever `desired_animal` is set (early return), so 4 hands PASSed through the farmer's
      BUILD/PICKUP/PLACE. (2) Hours 17-23 (14 turns): the T8.6 seed formula `labor_units * seed_buffer_per_unit`
      (~5 seeds, restocked a few at a time) ran to 0 seeds at hour 22 with land still free - the hiring forecast
      and the seed purchase were independent mechanisms and the second never saw the first's ambition.

      Built (all default off/bit-identical, commit `4b16013`, 42 new tests, suite 635, golden/boundary clean):
      `market.bulk_purchase_plan` - one pure rule for seeds *and* animals: `ceil` (seeds, +10%) / `floor`
      (animals, +0%) of `planned * (1 + buffer)` minus what is already held *of the plan's own types*, spread over
      several crop types by water-filling (they sum to one total), limited by budget. `bulk_seed_purchase` sizes it
      from the free tiles about to be planted (minus tiles reserved for a planned animal, cap `bulk_purchase_max_
      new_tiles=25`); `bulk_animal_purchase` from the planned-animal count (capped by `max_animals_per_type` and
      shed room; the animal's cost is reserved out of the seed budget so a big seed order can't starve it);
      `plant_while_animal_pending` lifts the decide-level block and makes `build_task_list` emit PLANT tasks next
      to the animal tasks (`plant_alongside_animal`, excluding the tile the animal's BUILD claims).

      **Mechanism works as designed** (seed 900 day 0, day-plan min=2): PLANT 21 -> 23 (bulk seeds) -> 24 (all
      three), PASS 33 -> 16 -> 15, 27 seeds on hand at hour 1 instead of 5.

      **Measured (`tools/measure_t845.py`, 50-seed working block) - no win anywhere, REJECTED**: shipped hiring
      (min=8=max): bulk seeds `0.420` (21W/29L), no buffer `0.360`, +animals `0.420`, +plant_while `0.420`,
      plant_while alone `0.000` (all ties). Day-plan min=2 with all three on: `0.020` (1W/49L); min=4: `0.060`.
      Nothing cleared 0.58 so no automatic holdout; run by hand on 200 seeds (900-1099): bulk seeds and the full
      bundle both `0.410` (82W/118L, Wilson upper bound 0.479 - below even), *identical* to each other.
      **Why, traced not guessed** (`daily.py` day-by-day, seed 900): under the *shipped* 8-hand hiring day 0
      already plants all 24 (81 idle turns, ~26 seeds bought - the legacy trickle is enough with `labor_units=9`),
      so the flags only shift planting from hour 5 to hour 3 and change nothing that day - hence identical W/L;
      the small negative is cash locked in surplus seeds, not a fix landing. Under day-plan min=2 the mechanism
      is real but the loss is the T8.44 structural one: hands 2-4 at days 10-14 plant slowly, the second quadrant
      buys later (seed 900: q=1 at day 12 with $10.7k in hand vs baseline q=2), and bulk buying then over-orders
      (24-35 seeds on days 20/24, ~$2-2.8k idle) for labor that isn't there.
      **Verdict**: a real, correctly-scoped fix for a real day-0 defect that cannot convert into wins - the seed
      shortfall only existed *because* the day-plan config starves labor, and that config is what loses. All six
      params stay off; shipped defaults, golden episodes untouched. Neither `bulk_seed_purchase` nor
      `plant_while_animal_pending` is worth turning on for the shipped 8-hand config (measured neutral-to-worse).
      Committed: `4b16013` (code+tests), this entry + `tools/measure_t845.py`. No Kaggle submission.

- [x] T8.46 - two-step "sell everything, then buy seeds on the real new prices" (the user's idea, 2026-09-19).
      Traced cause first (`flip.py`, seeds 900-902, day 11): the T8.45 bulk seed buy at ~ turn 11.01 was priced on
      the market *before* the agent's own sale of last night's harvest (85-89 melons in the shed, dripped 5/turn)
      was priced in; 6-8 turns later MELON fell from 260 to 189 (level with STRAWBERRY 187), the ranking flipped
      and the 12-15 bought MELON seeds were stranded (17 MEL to the end of the game in all three seeds). The
      premise (89 melons in the shed) was already in the observation at purchase time; the ranking just does not
      price its own pending sales. An agent cannot query prices mid-turn (`decide()` returns every order at once,
      `_process_market` settles them afterwards, new prices appear in the next observation) - hence two steps.
      Built `defer_seed_purchase_on_crop_sale` (0 = off): a turn whose previewed sale of crop products is >= N
      units sends no BUY_SEED; the next turn buys on the real post-sale prices. Sell-everything half = the existing
      `drip_sell_max_per_turn` set large. Commit + 9 tests, suite 644, golden/boundary untouched (defaults off).
      Verified on the real trace: 11.00 `SELL MELON 89`, no BUY; 11.01 real MELON 183 vs STR 186 (my projection
      was 189) -> STRAWBERRY top, 17 STR bought, no stranded MELON.

      **Measured (`tools/measure_t846.py`, 50 seeds vs the shipped baseline)**: day-plan min=2 + T8.45 bundle
      `0.020` -> `+ dump` `0.400` (20W/30L) -> `+ dump + defer` `0.400` (identical); min=4 + bundle + dump +
      defer `0.960` (48W/2L); **shipped hiring + dump only `1.000` (50W/0L), 200-seed holdout `1.000` (200W/0L/0T,
      Wilson [0.981, 1.0]) - `accept_candidate=True`**; adding defer / bulk seeds / the full bundle on top of the
      shipped hiring changed nothing (all `1.000`, ceiling). The defer half shows no measurable effect anywhere
      (identical W/L to dump alone at every pair) - it works mechanically but the arena cannot see it.

      **Why this is NOT flipped to default, checked before believing a perfect score**: head-to-head money is
      robust (seed 900: 58244 vs 42360, same in both seats) but 200/200 is a *mirror-market* effect. The arena
      opponent is the shipped drip-seller competing for the same MELON price: dumping first captures the high
      price before the rival's supply arrives (avg 235/unit vs 197 in the traced day). Against the external
      opponents the golden tests use, 20 seeds each: vs `starter` dump-only `+551` mean (12/20 better), vs `pass`
      `+3120` (13/20 better); the min=4 + bundle + dump + defer point is `-959` / `-891` (9/20 each) - i.e. its
      arena `0.96` does not carry over. The six golden seeds move both ways (starter/1 54893 -> 48899, starter/2
      64798 -> 67418, pass/1 56320 -> 51571, pass/2 61973 -> 64263). So: dump-only is non-negative on average vs
      non-competing opponents and huge vs a same-market rival; whether the real ladder rivals behave like the
      mirror is unknowable from here. Defaults stay off (golden money table would also need a 21st re-record) -
      the user decides. `drip_sell_max_per_turn` is the one param to flip if they choose to.
      Side finding: T8.45's "1W/49L at min=2" was mostly the drip-sale starving cash (it recovers to 0.40 with
      dump alone), so the day-plan line is less dead in the arena than T8.44 concluded - but the external check
      says it is still not a gain in absolute money.

      **Defaults moved, the user's explicit decision, 2026-09-20** ("Включи dump по умолчанию и пересчитай golden,
      и включи min=2 + флаги T8.45"): `drip_sell_max_per_turn` 5 -> 1000, `day_plan_hiring_aware` False -> True,
      `min_hires_per_day` 8 -> 2, `max_hires_per_day` 8 -> 12, `bulk_seed_purchase` / `bulk_animal_purchase` /
      `plant_while_animal_pending` False -> True (params.py, policy.json and every module-level "belt and braces"
      default kept matching; `defer_seed_purchase_on_crop_sale` stays 0 - it showed no effect anywhere).
      **One addition the request did not name, forced by an invariant**: with these defaults the T8.38 escape
      guardrail (never re-recordable) FAILED - starter/seed 2, day 28, a COW. Traced (`escape.py`, `wheat.py`): from
      day 25 WHEAT trades at 48-50 > `wheat_max_buy_price=40`, `buy_wheat_order` silently refuses the restock, the
      shed's last WHEAT is gone and the COW goes unfed on days 26 and 27 (2 misses = escape). This is the T8.25
      price-ceiling failure the existing `wheat_urgency_reserve` override exists for, so it is now 3 (was 0);
      `wheat_max_buy_price=70` gave the identical result, the targeted override was chosen over a blanket raise.
      All six golden pairs then have zero escapes for -0.7% mean money. Also found: at max=12 a burst day's 10
      HIRE orders (cap = `_MAX_MARKET_ORDERS`) fill the whole hour-0 order list, so that turn's SELL/BUY orders are
      dropped (one turn, not fixed - `max_hire_orders_per_turn` was measured at 6 in T8.44 but is not part of this).
      Tests: 18 default-dependent tests updated (mechanism tests pin the old values via `_OLD_HIRING` /
      `_LEGACY_PURCHASE`, default-assertion tests renamed to the new values), suite 645 passed, `boundary_check` clean.
      Golden money table re-recorded a 21st time: starter 54893/64798/67716 -> 46396/58953/54065, pass
      56320/61973/69306 -> 43540/58587/57699.

      **What these defaults cost, measured right after (`final_compare.py`, 20 seeds each vs the external golden
      opponents; arena 50 seeds)**: vs `starter` NEW default `47743` vs old `58362` (**-18.2%**, better on 0/20); vs
      `pass` `48703` vs `56635` (**-14.0%**, better on 2/20); self-play NEW vs OLD default `0.360` (18W/32L).
      The dump alone on the old hiring was `+0.9%` (starter, 12/20) / `+5.5%` (pass, 13/20) and 200W/0L in self-play -
      so of the three pieces the user asked for, dump is the one that helps; day-plan min=2 + the T8.45 bundle is what
      costs 14-18% against non-competing opponents. **To revert to dump-only**: `day_plan_hiring_aware=False`,
      `min_hires_per_day=8`, `max_hires_per_day=8`, `bulk_seed_purchase=False`, `bulk_animal_purchase=False`,
      `plant_while_animal_pending=False`, keep `drip_sell_max_per_turn=1000` (and `wheat_urgency_reserve=3` is harmless)
      - then the golden table needs a 22nd re-record. No Kaggle submission.

- [x] T8.47 - day-plan forecast counts the replant of harvested one-time crops (the user's request after the day-10
      analysis, 2026-09-20). Traced (seed 900, day 10, hours 0-12): at hour 0 the forecast was 51 actions (24 HARVEST +
      upkeep, 0 free tiles) vs ~99 real, because the 24 melon tiles the HARVEST handler clears to `None` (and that then
      need PLANT+WATER) were still occupied -> 4 hands instead of 8. Also seen, NOT fixed: the forecast divides by 24
      turns all day, not the turns left; `planned_new_crop_tiles` is capped by seeds held + affordable cash (harvested
      melons sit in unit inventories until the nightly shed drop and are sold at hour 0 of day 11, so day 10 cash is ~$50
      after 14 early BUY_SEEDs); `PRIORITY_HARVEST` < `PRIORITY_PLANT` means no PLANT until the whole harvest is done
      (first PLANT at hour 14). Forcing hires (`cf.py`): 8 hands from hour 0 = +2.5k..+5.0k final money in all 3 seeds
      (only -5..0 free tiles at the end of the day - cash-limited), 8 hands from hour 9 / 6 from hour 5 = no gain.
      Built `day_plan_harvest_replant_aware` (default **False**): `crop_tile_day_actions(..., harvest_replant_actions)`
      adds `day_plan_new_crop_tile_actions` (2.0) to a harvestable one-time tile. Day-10 forecast 51 -> 99, hands 4 -> 8.
      Tests: +2 (tasks, decide). Measured (`tools/measure_t847.py`, flag on vs shipped defaults): vs `starter` 20 seeds
      `+6.1%` (better on 15/20); vs `pass` `+2.5%` (13/20); vs old-default mirror `-5.2%` (10/20); arena vs shipped
      defaults `0.500` (25W/25L, 50 working seeds); arena vs OLD default `0.560` (shipped defaults: `0.360`). Per-seed
      table (900/901/902): 32689 -> 32060, 44823 -> 41583, 46545 -> 50329 (opponent is coupled through the market).
      Verdict: helps against external opponents, neutral in self-play - not flipped (standing rule: default flips only on
      explicit request). Enable with `day_plan_harvest_replant_aware=True`.
      **Refinement + default flip (the user's explicit request, same day)**: the replant term must land on the day
      the tile actually frees up - for a crop whose extra watering still adds yield (WHEAT/CARROT) that is the last
      ripening day (`max_yield_day`), not earlier. This is what `_is_actually_harvestable(defer_one_time_harvest_to_
      max_yield=True)` already gives; factored out as `tasks.harvest_clears_tile_today` and pinned by tests (WHEAT: no
      replant on days 2-3, yes on day 4; MELON, whose window starts before first_yield_day and is never deferred: day
      10). One real fix found while checking: late in the season (days 27-29, `planned_new_crop_tiles` = 0) the term
      still inflated the forecast (maintenance 161 on day 27, seed 900), so it is now added only while a crop is worth
      planting (`plant_crop_intent is not None`). Re-measured with the refinement: vs `starter` `+6.5%` (15/20), vs `pass`
      `+2.8%` (13/20), vs old-default mirror `-4.9%`, arena vs shipped `0.500`, vs OLD default `0.560`. Default flipped
      to **True** (params.py, policy.json, module default). Golden re-recorded a 22nd time: starter 46396/58953/54065 ->
      49879/58430/56789, pass 43540/58587/57699 -> 56732/62026/58144; T8.38 escape guardrail passes unchanged.
      Revert: `day_plan_harvest_replant_aware=False` + one more golden re-record.

- [x] T8.48 - hold BUY_SEED while HARVEST / WATER tasks (which outrank PLANT) are queued (the user's request, 2026-09-20;
      option (a) of the day-10 follow-up, plus the same rule for watering). Params `seed_purchase_max_pending_harvest` /
      `seed_purchase_max_pending_water` (None = off, bit-identical): BUY_SEED is skipped while >= N `HARVEST` tasks
      (resp. `WATER` tasks ranked above PLANT) are queued. Tests +3. **Measured and REFUTED - defaults stay None.**
      `tools/measure_t848.py`, shipped defaults as baseline, final money vs `starter`/`pass` (20 seeds) and arena on the
      50 working seeds: H<4 and H<8 `-3.8%` / `-2.3%`, arena `7W/23L` and `3W/23L` (the rest ties); W<4 `-3.2%` /
      `-0.8%`, `0.40`; W<8 `-3.2%` / `-0.3%`, `0.44`; W<12 `-3.4%` / `-1.9%`, `0.46`; every combination is subsumed by
      its water half (`0.44`-`0.46`). Not one point is >= baseline. Traced cause (`d10h.py`, seed 900, day 10, H<4):
      the gate released at hour 11 (seeds bought then, arrive hour 12), the 8 hands sat at PASS for ~10 hours, and the day
      ended with 10 free tiles and 0 seeds - **cash, not timing, is the limit**: the harvest (120 melons in unit
      inventories) is only sold at hour 0 of day 11, so the same ~$900 buys the same ~12-14 seeds whether at hour 5 or
      hour 11; delaying only removes the chance to plant them as soon as a unit frees up. Conclusion: seed timing is not
      the lever on harvest days; money is. Untested ideas that follow from this: make the unit-carried harvest sellable
      mid-day (**correction, 2026-09-20: NOT impossible** - the engine has a `DROP` op (shed-adjacent tile, moves the
      unit's whole inventory to the shed) and unit actions resolve before market orders, so DROP + SELL works in one
      turn; the agent never emits `DROP`. Also verified in the same check: the nightly drop is capped by
      `shedCapacity` 100 and DISCARDS the overflow - day 10 carries 120 melons, 88-90 reach the shed in seeds
      900/901/902, i.e. ~30 melons lost per harvest), or plan the previous day's purchases so the
      seed stock for the harvest day's replant is already on hand (buy for tomorrow's freed tiles while today's cash
      exists).
- [x] T8.49 - carry harvested goods to the shed mid-day and sell them the same turn; bulk purchases count the tiles the
      harvest is about to free (the user's design, 2026-09-20). Two findings first (`shed.py`, seeds 900-902): (1) the
      engine has `DROP` and `PLACE item n` on a shed-access tile, unit actions resolve before market orders, so a
      same-turn drop + SELL works (the agent never emitted either); (2) the nightly drop into the shed is capped at
      `shedCapacity` 100 and DISCARDS the overflow: 120 melons harvested on day 10, 88-90 reach the shed (~30 lost).
      Built: `tasks.goods_drop_task` (item = largest total stock; carrier = the unit holding most of it, ties nearest a
      shed-access tile, then index; task `DROP_GOODS` pinned to it, `action_for_unit` -> `PLACE item qty`, never `DROP`
      because that would also empty the feed WHEAT), `market.sale_revenue` (per-unit price walk = engine settlement),
      decide wiring: when the carrier already stands on the shed tile, the dropped stock is added to the sells and the
      incremental sale revenue is added to the money the BUY_SEED/BUY_ANIMAL plans may spend (sells settle before the
      tail). Triggers: overflow (`drop_goods_overflow_fraction`, goods on units + shed >= fraction * capacity) and cash
      (`drop_goods_cash_min_units`: money < estimated seed/animal spend and the carrier holds >= N; the user's
      proposal); `bulk_purchase_counts_harvest_tiles` adds `harvest_cleared_tiles` to the tiles the seed plan covers
      and lets the animal plan run while land is about to be freed (animals: only changes anything when more than one
      animal is wanted - shipped `max_animals_per_type=1`, target count 1 - so it is inert for animals by default).
      All params default off (bit-identical). Tests +7 (tasks 4, market 1, decide 4 - incl. same-turn drop+sell+buy).
      **Measured** (`tools/measure_t849b.py`, external `starter`/`pass`, seeds 1-40, final money vs shipped defaults):
      overflow only `+6.1%` / `+3.8%` (better 29/40, 27/40); cash only `+4.4%` / `+0.6%`; both triggers `+3.1%` / `-1.1%`;
      both + harvest tiles `+6.4%` / `+2.0%`; **overflow + harvest tiles `+10.1%` / `+7.4%` (better 30/40, 29/40)**. The
      cash trigger adds nothing on top of the overflow trigger and is worse in combination (probably small mid-day
      trips on non-harvest days; not traced). Day-10 trace (seed 900, drop on): first drop at hour 4 (money 885 -> 2155),
      free tiles at the end of day 10 6 instead of 15, money at the end of the day 8078 instead of 17.
      **Arena (self-play) is NOT usable for this change and was discarded**: cash-only vs shipped scored 1W/49L (9-11k vs
      ~50k) while +2.9% vs `starter`. Traced (`arena2.py`, seed 100): the engine settles market orders in per-order-index
      lockstep between the two players, so a player whose SELL MELON has the lower list index sells its 88 melons alone
      on a fresh market ($214 avg) and the other player then sells into the crashed market ($89 avg, price $4 at the end).
      The candidate had 'SELL WHEAT' ahead of MELON, the opponent did not. This is the same effect that made the dump
      look like 200W/0L in T8.46. Idea not tried: order the SELL orders by revenue, biggest first, so a collision with a
      same-item opponent is won by us.
      Verdict: mechanism works, overflow trigger + harvest-tile counting is a clear external gain; defaults NOT flipped
      (standing rule). Enable with `drop_goods_to_shed=True`, `drop_goods_cash_min_units=None`,
      `bulk_purchase_counts_harvest_tiles=True`.
      **Sell-order sort + default flip (the user's explicit request, same day)**: `sell_orders_first_by_revenue` puts the
      SELL orders first, largest revenue first (`sale_revenue` per order), ahead of the HIRE orders; hires are atomic so
      their index does not matter, and `sells` is already capped at `10 - hires - tail` so nothing gets truncated. Test
      `test_hire_is_never_crowded_out_by_sell_orders` now checks both orders. Measured (`tools/measure_t849c.py`, 40 seeds
      vs `starter`/`pass`; arena 50 working seeds): A = drop(overflow) + harvest tiles `+10.1%` / `+7.4%`; **B = A + sort
      `+10.4%` / `+7.6%`** (30/40, 29/40); sort alone `+4.3%` / `+3.4%`. Arena: B vs shipped **50W/0L**, B vs A 38W/12L,
      A vs shipped 33W/17L, sort alone vs shipped 44W/6L - the sort removes the list-index artifact traced above (the
      arena becomes usable again). **Defaults flipped to on**: `drop_goods_to_shed`, `bulk_purchase_counts_harvest_tiles`,
      `sell_orders_first_by_revenue`; `drop_goods_cash_min_units` = None (the cash trigger stays available, off).
      Golden re-recorded a 23rd time: starter 49879/58430/56789 -> 56924/55756/72845, pass 56732/62026/58144 ->
      57488/59281/74637; T8.38 escape guardrail passes unchanged. Revert: the four params back to False/False/False/5 +
      one more golden re-record.
      **Cash trigger switched on with a shed gate (the user's explicit request, same day)**: `goods_drop_task(...,
      shed_has_sellable_goods)` - the cash trigger fires only when money < the estimated seed/animal spend AND the shed holds
      nothing to sell besides feed WHEAT (any other product, FERTILIZER only when it is not kept for use, blocks it; the
      overflow trigger is unaffected). `drop_goods_cash_min_units` back to 5. Tests +2. **Measured NEGATIVE** (`tools/
      measure_t849d.py`/`e.py`, 40 external seeds vs the previous defaults = cash trigger off): N=5 `-3.6%` (starter, better 13/40)
      / `-4.9%` (pass, 16/40), arena 10W/40L; N=10 `-7.6%` / `-6.0%`; N=20 and N=40 identical to off (never fires - a carrier holds
      <= ~15 of one item). Old shipped (T8.47) is `-9.4%` / `-7.1%` against the same baseline, so the bundle as a whole still wins. Traced
      (`cashdrops.py`, starter seed 3): the trigger only adds one early 5-melon drop at hour 4 of the harvest day (money 885 ->
      2155), which immediately funds ~20 melon seeds ahead of any possible planting (first PLANT is hours later) - that early
      spend, not the sale, is the difference (65073 vs 72845). Enabled at N=5 because the user asked for it. Golden re-recorded a
      24th time: starter 56924/55756/72845 -> 52867/51470/65073, pass 57488/59281/74637 -> 43354/62881/69958 (five of six down).
      **Revert**: `drop_goods_cash_min_units` = None (params.py, policy.json, `_DEFAULT_DROP_GOODS_CASH_MIN_UNITS`) restores the
      23rd golden table exactly.
- [x] T8.50 - block the 4th quadrant; end-of-day overflow drop (the user's proposals, 2026-09-20). (1) `max_extra_quadrants`
      (`strategy.should_buy_land`, None = no cap): 2 = the 4th quadrant is never bought. The user's premise: bigger land + many
      mid-day drops cost moves (`ходы` 200-230 of ~90 real actions with 12 hands), and the top-5 opponents almost never open it.
      (2) `drop_goods_deadline_mode` (+ `drop_goods_deadline_margin_turns`=2): replaces the immediate overflow trigger.
      `tasks.goods_deadline_drop_tasks` projects the midnight total = shed stock that stays (everything that is not a droppable
      good: feed WHEAT, animals) + all goods on the units + `remaining_harvest_units` (what today's HARVEST tasks will still bring:
      `tasks.harvestable_units_today`, summed in the decide tile scan) and, above the shed capacity, picks units biggest droppable
      stock first (ties nearest the shed) until they cover the excess; a picked unit is dispatched only when `hour + moves + (item
      types - 1) >= turns_per_day - 1 - margin`, i.e. the last safe moment, and drops its biggest item; shared shed room is tracked
      across units. The cash trigger (single carrier) is kept and de-duplicated per unit. Tests +7 (tasks 5, decide 3, strategy 1
      counted with the existing ones). **Measured** (`tools/measure_t850.py`, 40 external seeds; arena 50 working seeds; base =
      the defaults before this entry): Q alone `+5.4%` (starter, better 30/40) / `+5.7%` (pass, 35/40), arena **46W/1L**; D alone
      `+0.9%` / `+1.7%` (better 15/40, 17/40), arena **7W/42L**; Q + D `+7.1%` / `+6.9%`, arena 16W/34L; Q + D with the cash
      trigger off `+8.8%` / `+13.3%` (the cash trigger is still a cost, kept on by the user's decision). **Q is enabled by default**
      (explicit request, clear win in both metrics); **D stays off** (external gain within noise, unbiased self-play strongly
      against - not traced; the end-of-day sale lands after the opponent's mid-day sales, which is a real possibility against
      similar strategies). Golden re-recorded a 25th time: starter 52867/51470/65073 -> 61199/55910/65088, pass
      43354/62881/69958 -> 47962/62881/72078 (none down). Revert Q: `max_extra_quadrants` = None (params.py, policy.json).
      **D enabled (the user's explicit request, same day)**: `drop_goods_deadline_mode` default True (params.py, policy.json,
      module default), against the measured self-play result above. Golden re-recorded a 26th time: starter 61199/55910/65088 ->
      59095/56230/65866, pass 47962/62881/72078 -> 49190/62657/67359 (mixed, within +-7%). Table (seeds 900-902, defaults): day 10
      free tiles at the end 8/13/8, later days `lost` (night overflow) 0-29 units, unwatered 0-15 (was 8-35 with the 4th
      quadrant); finals vs the old-default opponent 16597/56901/36330. Revert D: `drop_goods_deadline_mode` False.
- [x] T8.51 - capacity-aware selling + honest overflow projection (the user's request, 2026-09-20, after the "why 29 units lost
      per night" analysis). Traced with an engine hook on `_drop_inventories_to_shed` (`lost.py`): in seeds 900/902 days 21-28
      the shed held 70-80 unsold MELON all week (day-11 dump crashed the price $202 -> $34, it recovers ~$3/day; the day-20/21
      harvest arrived at $57-60 < seed cost $80, so `sell_orders`' cost-basis rule held all of it) + 10 feed WHEAT = 90 of 100
      slots, so the daily strawberry harvest ($215-230 each, 10-29 units) overflowed at midnight: 102 strawberries + 16 wheat lost
      in seed 900 (~$22k at list price), 51 + 8 in seed 902 (~$11k), none in seed 901 (its melon price never fell below the
      cost). The T8.50 deadline drop did not help because it counted only non-droppable shed stock as "staying" (melons were
      assumed sold) and, even if it had seen it, only ~10 units fit into the jammed shed. Built (`capacity_aware_selling`):
      decide previews this turn's ordinary sale, projects the midnight content = shed left after it + everything the units
      carry + `remaining_harvest_units`, and above the capacity **sells the stock lying in the shed first - cheapest per unit
      first, even below the price rule** (`sell_orders(..., force_sell={item: units})`, forced units bypass the margin check only
      for items the rule would hold); only the remaining excess is left to the units (deadline drop, now with
      `shed_stay` = the honest post-sale content and `shed_room_after_sales`: a unit already on the shed tile drops into the room
      left NOW because this turn's sales settle after unit actions, a unit arriving later into the room after the sales). The
      wheat/liquidation definitions were moved ahead of the drop block for the preview. Tests +7 (market 1, tasks 1, decide 3,
      + the existing ones adapted). **Measured** (`tools/measure_t851.py`, 40 external seeds vs `starter`/`pass`; arena 50 working
      seeds): capacity-aware `-0.0%` / `-0.0%` (it almost never fires against them: the melon price does not crash without the
      mirror dump), arena **49W/1L**; with the deadline drop off `-1.7%` / `-1.2%`, arena 49W/1L. Traces (defaults, seed:
      before -> after final vs the old-default opponent): 900 `16597 -> 38286`, 902 `36330 -> 49925`, 901 `56901 -> 53834`; night
      losses 900: 102 strawberries -> 0, 902: 51 -> 0. **Enabled by default** (explicit request; neutral vs external, decisive
      in self-play). Golden unchanged (the six golden pairs are external opponents). Revert: `capacity_aware_selling` False.
- [x] T8.52 - land purchase by affordability instead of the free-tile gate (the user's rule, 2026-09-20). Trace that led to it
      (seed 900, day 11): the NE quadrant was bought at hour 18 although $17.8k was idle from hour 2, because the old gate
      (`land_buy_max_free_tile_fraction` 0.1) only opened when the last 5 free tiles had been planted - planting is starved behind
      WATER (first PLANT at hour 14) - so the 25 new tiles appeared with 5 turns left and 23 stayed empty at the end of day 11;
      the day's hire target (3) could not know about the purchase (6 after it, acting from the next hour). New
      `land_buy_affordability` (`strategy.should_buy_land(..., development_cost)`, `land_purchase_buffer` 500): the occupancy gates
      are dropped and the quadrant is bought when money >= its price + `development_cost` + buffer, where decide computes
      `development_cost` = seeds for all 25 tiles of the fallback crop + the planned animals + the extra hires the quadrant needs
      (`ceil(25 * 2 * 2 / 24)` = 5 hires priced with `labor.hire_cost` from today's hire count). `max_extra_quadrants` (the 4th
      quadrant block) still applies first. Tests +4. **Measured** (`tools/measure_t852.py`, 40 external seeds; arena 50 working
      seeds; base = the defaults before this entry): affordability with the cap `-0.7%` (starter, better 20/40) / `+2.1%` (pass,
      20/40), arena **47W/3L**; affordability without the cap `+3.5%` / `+9.1%` (better 23/40, 33/40), arena **9W/41L** (the
      4th quadrant loses in self-play, wins vs the non-competing opponents - the block stays, the user's decision). Trace (starter
      seed 3): base buys NE/SW on day 11 h20 / day 13 h23; affordability on day 10 h22 / h23 (money $6.6k / $9.1k), final `65866 ->
      72234`. **Enabled by default with the cap** (neutral-to-positive external, decisive in self-play). Golden re-recorded a 27th
      time: starter 59095/56230/65866 -> 59813/57212/72234, pass 49190/62657/67359 -> 67546/62552/78380 (five of six up). Revert:
      `land_buy_affordability` False.
- [x] T8.53 - day-plan hire forecast divides by the turns left today (the user's request, 2026-09-20; item from the day-10
      analysis). `strategy.hires_per_day` (day-plan branch) divided total forecast turns by the whole day (24) at every hour, so
      mid-day the target fell as the harvest progressed although the remaining work still had to fit into fewer turns (day 10 hour 9:
      100 turns of work / 24 -> 4 hands, but / 15 remaining turns -> 6). New `day_plan_remaining_turns_aware`: divisor
      `max(1, turns_per_day - hour)`, and the counted work is only what is still to be done - `crop_tile_day_actions(...,
      remaining_only)` skips the WATER of a tile with `watered_today`, `animal_tile_day_actions(..., remaining_only)` skips the FEED
      of a `fed_today` animal (identical at hour 0, where nothing is done yet). Tests +3. Traced side effect (`hires.py`, starter seed
      3): the plain flag hires 12/day from day 10 on and adds useless late hires (hours 18-21, several per day), final 72234 ->
      66386 on that seed; `hire_min_turns_left` (already existed, default 0) stops hires late in the day. **Measured**
      (`tools/measure_t853.py`, 40 external seeds; arena 50 working seeds; base = defaults before this entry): plain `+5.0%`
      (starter, better 26/40) / `+4.2%` (pass, 23/40), arena **33W/17L**; + `hire_min_turns_left` 6 `+7.6%` / `+6.3%`
      (31/40, 28/40), arena 34W/16L; + 12 `+7.4%` / `+4.8%`, arena **44W/6L**. **Enabled by default: the divisor only** (what was
      asked); `hire_min_turns_left` stays 0 - the guard is better in every measure and is the natural next flip. Golden
      re-recorded a 28th time: starter 59813/57212/72234 -> 59002/63636/66386, pass 67546/62552/78380 -> 66160/67947/75368
      (mixed). Revert: `day_plan_remaining_turns_aware` False.
      **`hire_min_turns_left` = 6 (the user's explicit request, same day)**: default 0 -> 6 (params.py, policy.json, module default).
      Also found while measuring: with the divisor a late-day forecast (3-4 turns left) targets 12 hands and up to 10 HIRE orders
      fill the market cap, crowding SELL/BUY orders out. Golden re-recorded a 29th time: starter 59002/63636/66386 ->
      55880/70208/67773, pass 66160/67947/75368 -> 53161/69469/76756 (mixed, pass/1 -19.7%). Revert: `hire_min_turns_left` 0.
- [x] Submission of the T8.44-T8.53 bundle (the user's explicit request, 2026-09-20): commit `b1bf9b4`, `build/submission.tar.gz`
      (228314 bytes, audit + smoke passed), Kaggle ref **56383677** (team Gruberx, confirmed via `get_competition_submission`),
      logged in `data/arena/submissions.jsonl` with `arena_win_rate` 0.68 (T8.53 arena vs its base). Public score not yet known -
      re-check after ~20 minutes (early scores are volatile). Expectation to hold it against: the external-opponent measurements were
      +5-10% per step, but the self-play-only wins (deadline drop, 4th-quadrant block) are unverified against real strong opponents.
- [x] T8.54 - no PLANT on the last turn of the day (the user's request, 2026-09-21: "weeds come from plants sown in the last hour
      that can no longer be watered - check and fix"). **Hypothesis confirmed.** Engine (`kaggriculture.py:222`): a new plant starts
      with `consecutive_unwatered=1` ("planting day counts as unwatered"), so a plant not watered on its planting day is a WEED at
      midnight (my first check, which looked for `cu>=1` on the next morning, missed this and wrongly said "no such plants").
      Traced with hooks on `_daily_refresh_plants` (seeds 900/901/902, vs the old-default opponent): 10/19/16 plants per game died the
      night they were planted, ALL sown on turn 23 (turn 22 is safe: someone waters on turn 23), on days 10-26, none survive
      (0 survivors of turn-23 plantings). Cause of the late sowing: planting sits behind WATER/HARVEST and walking all day, so a free
      tile is planted only when the queue empties at the very end. New flag `no_plant_on_last_turn` (`plant_qty=0` when
      `hour >= turns_per_day-1`, 1 test) removes the doomed sowings (weeds 6.6 -> 1.8 at noon, 16 seeds) but **measured negative**:
      external 40 seeds starter 59685 -> 57423 (-3.8%, better 14/40), pass 60093 -> 57205 (-4.8%, better 9/40); arena 12W/38L (0.24);
      16-seed side check: plants at noon 54.9 -> 53.6, final -2%. Mechanism not identified (the turn-23 unit had nothing else to do,
      the seed loss is small). **Enabled by default on the user's explicit request (2026-09-21) despite the negative measurement**; golden re-recorded together with T8.55. `tools/measure_t854.py`.
      The real fix (planting earlier in the day) is T8.55 below.
- [x] T8.55 - raise the priority of PLANT for free tiles (the user's request, 2026-09-21, follow-up to T8.54). Mechanism: an
      ordinary PLANT sat at tier 3, below every non-urgent WATER (tier 2, one task per unwatered plant tile), so with ~60 plants and
      units spending most turns walking, a free tile was planted only when the queue emptied - i.e. on the last turn (doomed, see
      T8.54) - and free tiles plus seeds idled for days (seed 900, days 13-19: 12 free tiles, 43 seeds, $13k). New params
      `plant_priority` (re-tiers the crop PLANT; `None` = tier 3) and `dig_weed_priority` (re-tiers the weed DIG; `None` = tier 4),
      applied in `build_task_list` (1 test). Fresh plants still get an urgent tier-0 WATER (`consecutive_unwatered=1`). Measured on
      top of T8.54 (base = current defaults with `no_plant_on_last_turn`), 40 external seeds + arena, `tools/measure_t855.py`:
      plant 1.75 (and 1.25, identical - no tier between 1.5 and 2): starter 57423 -> 61709 (+7.5%, better 30/40), pass 57205 ->
      62416 (+9.1%, better 34/40), arena 40W/10L; + dig 1.8: +8.6%/+9.2%, arena 40W/10L; + dig 3.0: +7.5%/+9.0%, arena 40W/10L.
      **Shipped `plant_priority=1.75`; `dig_weed_priority=1.8` enabled afterwards on the user's explicit request (2026-09-21)**
      (measured +1.0% on starter, +0.1% on pass over plant-only). Golden re-recorded a 31st time: starter 55366/72840/80426 ->
      53182/73202/80919, pass 60668/72953/75145 -> 62075/73091/75537. Revert: `dig_weed_priority` None.
      Side effect: animal BUILD/PICKUP/PLACE stay at tier 3 and now starve behind PLANT - the golden animal-pipeline guard test
      pins `plant_priority=None`. Golden re-recorded a 30th time: starter 55880/70208/67773 -> 55366/72840/80426, pass
      53161/69469/76756 -> 60668/72953/75145 (T8.54 + T8.55 together). Revert: `plant_priority` None (and `no_plant_on_last_turn` False).
- [x] T8.56 - does raising `max_hires_per_day` above 12 pay off (the user's question, 2026-09-21; the engine has no cap on hands,
      only the fib cost `farmHandCostMult * fib(n)` per day). Measured on the current defaults (T8.54/T8.55 on), 40 external seeds +
      arena, `tools/measure_t856.py`: **higher is decisively worse** - max 14: starter -6.5% / pass -7.5%, arena 0W/50L; max 16:
      -22.3% / -23.6%, 0W/50L; max 20: -72.8% / -69.8%, 0W/50L (cost of the 13th+ hire of the day grows fib-fast). **Lower is better**:
      max 11: +3.5% / +1.1% (better 36/40, 33/40), arena 46W/4L; **max 10: +3.6% / +2.8% (better 31/40, 28/40), arena 47W/3L**;
      max 8: +1.0% / +1.9%, arena 43W/7L. Shipped default NOT changed (`max_hires_per_day` 12): a flip needs the user's request.
      Candidate: 10.
- [x] T8.57 - per-product economics of ONE tile over 30 days (the user's request, 2026-09-21, extended the same day): continuous
      production of a single product, no fertilizer on plants, harvest at full ripeness / animal at its `max_held` cap, animal fertilizer
      counted as side income, starting prices with no price walk; on the last day (29) everything accumulated is collected and sold
      (the unfinished last crop cycle is planted only if what it holds on day 29 beats its seed). New column "ideal/day": profit per day
      if production ran on to the end of the in-progress cycle (crops: per-cycle profit / cycle days; animals: first horizon >= 30 days
      that ends on a cap harvest). `tools/tile_economics_30d.py` (real engine functions, watering schedule searched per crop; ~1 s).
      Profit / actions / profit-per-day / ideal per day: WHEAT 630 / 42 / 21.0 / 22.5; CARROT 815 / 49 / 27.2 / 28.3; TOMATO 380 / 17 /
      12.7 / 17.3; STRAWBERRY 520 / 20 / 17.3 / 23.8; MELON 2840 / 20 / 94.7 / 142.0; GOOSE 3550 / 52 / 118.3 / 119.5 (32 d); COW 3910 / 47 /
      130.3 / 133.7 (31 d); SHEEP 3650 / 47 / 121.7 / 133.1 (40 d). Animals include $350 of feed wheat at $25 and 29 fertilizer collections at
      $100 = $2900 (70-90% of their revenue). Engine facts confirmed: a new plant starts with `consecutive_unwatered=1`; an ongoing plant is
      not cleared by HARVEST (needs DIG - and only when the tile is replanted); an animal produces regardless of feeding (feeding only avoids
      escape and enables the CARE bonus) and its fertilizer flag refreshes daily. Correction to the first version of this table: the last
      DIG of an ongoing crop was counted although nothing is replanted after it (tomato 2 -> 1, strawberry 1 -> 0 before the partial cycle).
      **CARE added (the user's correction, same day)**: the first version left CARE out. Engine (`_daily_refresh_animals`): a day with
      BOTH fed and cared adds +1 to `pending_care_bonus` (after that day's production check); the next production event pays
      `1 + pending` (only if fed that day), capped at `max_held`; the bonus of every care day since the last event accumulates (cow
      first event = min(6, 1 + 7)). With FEED + CARE + COLLECT_FERTILIZER every day (29 feeds = $725, 29 cares): GOOSE 4575 (103
      actions, 54 eggs; was 3550 without care), COW 7535 (95 actions, 36 milk; was 3910), SHEEP 8475 (97 actions, 34 wool; was 3650).
      Harvest threshold is picked per animal (max profit, then fewest actions) because a strict harvest at the cap loses output when
      one care-boosted interval adds more than the room left (sheep: +4 wool per interval, cap 6 -> 7275 strict vs 8475). Ideal per day:
      GOOSE 152.5 (30 d), COW 261.0 (31 d), SHEEP 301.6 (31 d).
      **Per-life table (the user's restructuring, same day)**: `tools/tile_economics_30d.py` now prints one cycle of life per product
      (plant: planting to harvest, DIG counted for ongoing crops; animal: a 30-day cycle) with "profit per day per cycle" =
      profit / cycle days: SHEEP 8475 / 30 = 282.5, COW 7535 / 30 = 251.2, GOOSE 4575 / 30 = 152.5, MELON 1420 / 10 = 142.0, CARROT
      85 / 3 = 28.3, STRAWBERRY 380 / 16 = 23.8, WHEAT 90 / 4 = 22.5, TOMATO 190 / 11 = 17.3.
      **Fertilizer for plants (the user's request, cost of one fertilizer = 20), re-checked and corrected the same day**:
      `best_crop_cycle_fert` searches watering + FERTILIZE (+ intermediate harvests of ongoing crops) schedules with the real engine
      rules (DP over (tile state, units taken), Pareto on fertilizers/waterings/harvests) for the highest profit per cycle day;
      re-verified by exhaustive DFS without merging (tomato 0.9M nodes, strawberry 20M, wheat/carrot/melon). Engine timing, tested
      directly: FERTILIZE sets `fertilized_until_day = max(old, day+2)` = active the day it is used and the next two. One-time crops:
      the doubling happens inside WATER (age in the window, cap `max_yield`), so FERTILIZE must come BEFORE that day's WATER (after
      it that day's bonus is lost: wheat 2 vs 3); fertilizing on day 0 is mostly wasted (only the age-2 water is doubled). Ongoing
      crops: doubling happens at midnight on event nights and only if the plant was watered that day (tomato fertilized but not
      watered day 7: 1 instead of 2). Max product per plant life (no fert -> with fert): WHEAT 4 -> 6, CARROT 3 -> 4, TOMATO 4 -> 8,
      STRAWBERRY 4 -> 8, MELON 6 -> 6 (cap reached day 8 but the first harvest is day 10). A tomato/strawberry holds 4 at once and has
      4 events, so 8 needs 2 fertilizers and 2 harvests (first version wrongly allowed one harvest: tomato 18.9, strawberry 30.0).
      Best profit per day (no fert / fert): WHEAT 22.5 / 31.7 (fert day 2, 5 units, 3 d; max-product 6 units = 30.0), CARROT 28.3 /
      33.3, TOMATO 17.3 / 35.5 (fert 7 and 10, harvest 9 and 11, 8 units, 390), STRAWBERRY 23.8 / 51.2 (fert 9 and 13, harvest 13 and
      16, 8 units, 820), MELON 142.0 / 142.0. Break-even fertilizer price for the day rate: wheat ~47, carrot ~35, tomato ~120,
      strawberry ~240.
      **Re-check against the official "How to Play" page (the user's request, 2026-09-21)**: every claim of the page matches the engine
      on all five plants (yield by age with daily watering, without and with fertilizer: WHEAT 4 / 6 at age 4, CARROT 3 / 4 at age 3,
      MELON 6 at age 10 / at age 8 with fertilizer, TOMATO events at ages 8-11, STRAWBERRY at ages 10/12/14/16 with the tile cap 4;
      decay one day after max age). One convention difference: the page's yield/tile/day divides by age + 1 (the harvest day still
      counts as occupied), my rates assumed the next plant is sown on the harvest day (cycle = age). `best_crop_cycle_fert(...,
      extra_days=1)` gives the page's convention: WHEAT best is then 6 units / 4 d / 120 = 24.0 per day (5 units / 3 d only wins
      with same-day sowing: 31.7), CARROT 25.0, TOMATO 32.5, STRAWBERRY 48.2, MELON 129.1; no fertilizer: 18.0 / 21.2 / 15.8 / 22.4 / 129.1.
      **Convention chosen by the user (2026-09-21): "sow on the harvest day"** (cycle = age, `extra_days=0`, the script's default); the
      parenthesised page-convention numbers are dropped from the tables.
      **Saved for later use (the user's request)**: `tasks/data/tile_economics.json` + `.md`, regenerated by `python tools/tile_economics_30d.py --write`; a memory entry
      points to them. Purpose: the basis of the formula that picks the next product for a free tile.
- [x] T8.58 - is a one-time crop harvested before that day's watering, losing the last bonus? (the user's suspicion, 2026-09-21;
      check only, nothing changed). **Confirmed** by the code and by 4 self-play episodes (seeds 900-903, shipped defaults vs `starter`,
      `tools/check_harvest_before_water.py`). Cause: on the harvest-eligible day the tile has a HARVEST (tier 1) and a routine WATER
      (tier 2; tier 0 only if `consecutive_unwatered>=1`), so the harvest wins and removes the tile, and the watering that day
      (+1 unit inside the bonus window ages 2-4 wheat / 2-3 carrot / 6-12 melon) never happens. MELON: 44-46 harvests per game, ALL at
      age 10 with 5 units and unwatered that day (attainable 6): 83% of attainable, +20% output lost. WHEAT: harvests at age 4 with 2-3
      units (never 4): 62-71% of attainable; 4-24 harvests per game lost the last bonus, the rest of the shortfall (about 60%) is
      earlier window days that were not watered. CARROT: 67%, 0-6 harvests per game lost the last bonus. Ongoing crops: not
      applicable (watering adds no yield without fertilizer); they are harvested one unit at a time at every event (strawberry ages
      10/12/14/16, tomato 8/9) = up to 4 HARVEST actions per plant instead of 1, an action-efficiency issue, no product lost. Animals:
      not applicable. Proposed fix (not done): for one-time crops, hold HARVEST while the day's watering would still add yield (age in
      the window, not watered today, yield < max_yield) and give that WATER the harvest tier; costs one extra action per harvest.
## Not planned yet (see plan.md)

`fastsim` (no evidence the arena is the bottleneck) and `tuning` Stage 2 (search-generated value
targets — gated behind a Stage-1 baseline that doesn't exist yet).

**Open questions recorded for later, not forgotten (the user's own request, 2026-09-12):**
- Opponent production/price-impact awareness (T8.3g/T8.3h): rejected at every weight tried
  (0.0-1.0), traced to the estimate having no timing information about the opponent's tiles. A
  signal-based approach (trust the opponent term only when the *observed* market price already
  shows movement unexplained by our own activity) remains untried - the user's own follow-up idea,
  flagged for a real return visit, not abandoned.
- Re-validate T8.3f/T8.3g/T8.3h (crop self-impact awareness) via self-play once hiring actually
  works (after T8.4-T8.7): the user's own observation - faster multi-worker production could plant
  a crop's full tile commitment much sooner than the single-farmer games these were measured
  against. The mechanism itself should already generalize correctly (`_crop_tile_counts` counts
  real current tiles regardless of how many workers planted them, not planting *rate*), but this is
  an assumption, not yet confirmed by a real measurement under nonzero `hires_per_day`.

**Open questions recorded for later, not forgotten (the user's own request, 2026-09-13, T8.3j):**
- **Exploit `hinge`-shaped scarcity for CARROT/TOMATO/EGG specifically** - see `SPEC.md`'s new
  "Economic analysis" section for the full mechanism (price stays near base under ordinary demand,
  then climbs *sharply* once a real deficit passes `T`). Concrete shape for a future attempt:
  detect an approaching `T`-deficit for one of these three (from `market_inventory` trending toward
  `I0 - T`, cross-checked against visible supply - ours and the opponent's) and preferentially
  plant it before the price has fully caught up. Nothing in `kagg.policy` currently treats `hinge`
  products differently from any other scarcity curve.
- **WHEAT-for-feed cross-pressure** - the user's own follow-up to the "hiring speeds up wool
  production" discussion. `BUY_PRODUCT` (restocking WHEAT to feed animals) reduces the shared
  market inventory exactly like a `SELL` raises it (verified in `_commit_unit`), so (a) growing our
  own feed wheat instead of buying it avoids a real, currently-unvalued self-inflicted price cost
  when scoring WHEAT as a crop, and (b) the opponent feeding their own animals is a second, distinct
  kind of opponent-driven WHEAT pressure (tightening supply) from T8.3g/T8.3h's crop-tile one
  (adding supply) - both currently unmodeled.
  **(a) addressed by T8.24** (`wheat_feed_credit_per_tile_day`, built, tested, measured - null/
  inconclusive at self-play scale, see T8.24's own entry above). **(b) still open** - T8.24's own
  measurement explicitly could not test contested demand (the harness has no way to bias the
  opponent toward animal purchases); remains a real, unmodeled gap if a future session finds a way
  to exercise it.
  **A third, related but distinct issue found and fixed by T8.25**: independent of any opponent
  contested-demand pressure, WHEAT's own market price drifts past `wheat_max_buy_price` from
  ordinary town/shop consumption alone, in every sufficiently long game - a static, never-swept cap
  was silently blocking all feed restocking for the rest of the season once that happened, with no
  urgency override. See T8.25's own entry above for the full traced story and measured fix.
- **Animal-product self-impact + escape risk, once hiring lifts the one-animal-per-type cap** - the
  user's own observation: WOOL/MILK/EGG overproduction from stacking animals is a structural
  non-issue *today* only because of a hard cap in `decide.py` ("never pursue a second instance of an
  animal type we already have placed and alive"), not price awareness, and animal escape from missed
  feeding is a real but currently low-probability risk at n=1 animal (FEED is the highest task
  priority). Both stop being dormant the moment T8.4-T8.7 lifts that cap - an animal-product analog
  of T8.3f's self-impact (bounded by *some* real horizon, e.g. remaining season days, since animal
  production is otherwise unbounded) becomes a real gap to close then, alongside the crop
  re-validation above.
  **Resolved by T8.22, not in the direction this question anticipated**: the cap WAS lifted
  (`max_animals_per_type`) and measured directly - the *escape risk* half of this question turned
  out to dominate completely (every animal escaped from neglect by episode end at every cap tried,
  2/3/4 - see T8.22's own trace), decisively enough that the self-impact half never got to matter in
  practice. Stays a real gap only if `max_animals_per_type>1` is revisited with the labor-gating fix
  T8.22's own entry names (real spare labor before allowing a second animal).
  **T8.25 found the escapes were not primarily a labor problem at all**: the true cause was the
  WHEAT price-ceiling bug (animals starved because there was no WHEAT to feed with, not because no
  hand was free to FEED) - fixing it (`wheat_urgency_reserve`) substantially closes the gap
  (cap=3: 14%/14% -> 40%/44%) without any labor change. T8.26 then tested whether a *proactive*
  hiring forecast closes the remainder - measured and decisively rejected (see T8.26's own entry).
  The self-impact half of this question, and the FEED-vs-PLANT task-priority question T8.26's own
  plan named, both remain untested - `max_animals_per_type` never reached a net win in aggregate
  self-play even with both fixes, so neither mechanism yet has a scenario where it would bind.

**Open questions recorded for later, not forgotten (the user's own request, 2026-09-13, T8.3k):**
- **Labor cost (farmer turns) is still completely unranked**, a distinct gap from T8.3k's seed-cost
  fix - the user's own original framing named three missing dimensions (acquisition cost, labor,
  time), and only the first is fixed. `crop_revenue_per_tile_day`/`animal_revenue_per_tile_day`
  divide by *tile-occupancy* days, not by farmer *turns* actually spent tending the option (daily
  WATER vs FEED+CARE+PICKUP-wheat trips are not the same labor cost per unit of revenue) - nothing
  in the ranking sees this difference at all. A real, unscoped future problem: needs some notion of
  "turns consumed per unit of revenue," not just calendar days.
- **Animal purchase + recurring feed cost, net of season-remaining days** - T8.3k explicitly scoped
  itself to crops only; animals need both a one-time purchase cost (`ANIMALS[animal]["cost"]`) and a
  recurring WHEAT feed cost netted out, amortized over some horizon (the natural candidate:
  remaining season days from `current_day`, which `rank_portfolio` doesn't currently receive at
  all). Related to, but distinct from, the animal self-impact gap already recorded above - worth
  tackling together once hiring (T8.4-T8.7) makes more than one animal relevant.
