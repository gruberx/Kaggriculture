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
- **Animal-product self-impact + escape risk, once hiring lifts the one-animal-per-type cap** - the
  user's own observation: WOOL/MILK/EGG overproduction from stacking animals is a structural
  non-issue *today* only because of a hard cap in `decide.py` ("never pursue a second instance of an
  animal type we already have placed and alive"), not price awareness, and animal escape from missed
  feeding is a real but currently low-probability risk at n=1 animal (FEED is the highest task
  priority). Both stop being dormant the moment T8.4-T8.7 lifts that cap - an animal-product analog
  of T8.3f's self-impact (bounded by *some* real horizon, e.g. remaining season days, since animal
  production is otherwise unbounded) becomes a real gap to close then, alongside the crop
  re-validation above.

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
