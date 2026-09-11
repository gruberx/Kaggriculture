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
- [ ] T1.7 — Boundary test: no `kaggle_environments` import anywhere under `src/kagg/gamelib/`
- [ ] **Checkpoint 1** — `pytest repo/tests -k gamelib` all green. Commit.

## Phase 2 — `agent` hardening

- [ ] T2.1 — Time-budget guard (400ms ceiling, cached-plan fallback)
- [ ] T2.2 — Fault-tolerance fuzzing (malformed observations never raise)
- [ ] T2.3 — Full-episode timing test (p100 < 400ms, cumulative overage < 10s target)
- [ ] T2.4 — Golden-episode fixture (fixed seeds vs `starter`/`random`, recorded final money)
- [ ] **Checkpoint 2** — `agent` matches `SPEC-agent.md` fully. Commit.

## Phase 3 — `policy` complete

- [ ] T3.1 — Strategic layer (portfolio, land threshold, `hires_per_day` — all as named params)
- [ ] T3.2 — Task layer (prioritized list + greedy assignment via `tile_distance`)
- [ ] T3.3 — Market layer (sell thresholds, drip-selling, ≤10 orders/turn, `BUY_PRODUCT` restricted)
- [ ] T3.4 — `params/policy.json` schema + loader (with safe fallback on missing/malformed file)
- [ ] T3.5 — Replace Phase 0's wheat loop with T3.1–T3.3 in `agent_main.py`
- [ ] T3.6 — Ad-hoc baseline: ~20 seeds vs `starter`/`random` (pre-harness sanity check)
- [ ] **Checkpoint 3** — Commit; note T3.6 numbers in the commit message.

## Phase 4 — `harness`

- [ ] T4.1 — `run_paired()` (+ pass-vs-pass tie test)
- [ ] T4.2 — `run_block()` + Wilson interval (+ closed-form check, seat-invariance test)
- [ ] T4.3 — `detect_shop_reroll()` (+ fixture test)
- [ ] T4.4 — `params/seed_blocks.json` (`tuning_seeds` / `holdout_seeds`, disjoint, committed)
- [ ] T4.5 — `tools/arena.py` CLI (`--opponent`, `--seeds`, `--jobs auto`, gated `--holdout`)
- [ ] **Checkpoint 4** — `SPEC-harness.md` Testing section all passes; re-measure Phase 3's baseline
      through the real harness (working block only). Commit.

## Not planned yet (see plan.md)

`tuning` and `ops` — follow-up `/agent-skills:plan` pass after Checkpoint 4.
