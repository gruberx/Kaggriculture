# SPEC: `agent`

Part of the [capability map](SPEC.md#capability-map). Depends on: `gamelib`. **Ships in the
submission** — this module *is* the submission's entry point.

## Objective

Own the actual Kaggle submission contract: a `main.py` exposing `agent(obs) -> dict` that never
crashes, never exceeds its time budget, and never violates Official Rules §2.11 (no ingress/
egress during an episode). Everything this module does is either delegated to `gamelib`/`policy`
or exists purely to make delegation safe.

## Contract

Per `AGENTS.md`/`kaggriculture.json`: `agent(obs)` receives the observation described in
`SPEC.md`'s referenced game rules (`player`, `day`, `hour`, `farms`, `private`, `market`, `town`)
and returns `{"farmer": [op, ...], "hands": [[op, ...], ...], "market": [[op, ...], ...]}`. On
Kaggle, submission files live at `/kaggle_simulations/agent/`, so `agent_main.py` must not assume
`__file__`'s directory is the working directory when locating `params/*.json` — resolve paths
relative to `os.path.dirname(__file__)`.

## Time budget

Source of the constraint: `kaggriculture.json` sets `actTimeout: 1` (second) per turn, and
`kaggle_environments/agent.py` enforces a *shared* `remainingOverageTime` pool (`60` seconds,
`kaggriculture.json` `observation.remainingOverageTime`) across the *entire* 720-turn episode —
unused time does not carry over per turn, but overage is deducted from one shrinking pool for the
whole game (`agent.py:220`: `duration - actTimeout > remainingOverageTime` → `DeadlineExceeded`).
Exhausting the pool is an instant loss, indistinguishable from a crash.

Design:
- **Target**: ≤50ms per turn in the common case (task-layer + market-layer work, no strategic
  replan).
- **Hard ceiling**: 400ms per turn, measured with `time.perf_counter()` around the whole
  `agent()` body. If the ceiling is hit, return the last cached full plan's next action rather than
  a partial computation — a stale-but-valid action beats a timeout.
- **Strategic replanning** (the daily portfolio/land/hiring decision, see `SPEC-policy.md`) runs
  once per day (`obs["hour"] == 0`) or is amortized across several turns if profiling shows it
  can't fit in one turn's ceiling — but the amortized pieces still individually respect the same
  400ms ceiling, they just spread the total strategic cost over multiple turns rather than paying
  it all on turn 0 of the day.
- A single 400ms turn 720 times over would exhaust the entire 60s overage pool roughly 5x over —
  the ceiling is a circuit breaker for pathological cases, not a budget to spend routinely. The
  time-budget test in `SPEC.md` asserts both the p100-per-turn ceiling *and* that cumulative
  overage across a full episode stays comfortably under the 60s pool (target: <10s total, leaving
  margin for slower Kaggle hardware than this dev machine).

## Fault tolerance

`agent()`'s top-level body is a single `try/except Exception`. On any exception — malformed
observation, a `gamelib`/`policy` bug, anything — it returns the environment's own safe default:

```python
{"farmer": ["PASS"], "hands": [], "market": []}
```

This is deliberate and matches the environment's own behavior: invalid actions are silent no-ops
(`AGENTS.md`: "Invalid actions are silent no-ops"), so a crash is the *only* way this agent can
lose on a technicality rather than on strategy. `hands` is returned as `[]` rather than one `PASS`
per hand because the interpreter tolerates a shorter-than-expected hands list (unspecified hands
implicitly pass) — confirmed by property test against `_apply_unit_action`'s per-index dispatch.

## Rule compliance (Official Rules §2.11)

`agent_main.py` and everything it imports (`gamelib`, `policy`):
- No `socket`, `urllib`, `http`, `requests`, or any networking import.
- No `open()` on a path outside `os.path.dirname(__file__)` — parameter files ship inside the
  bundle, nothing is fetched or read from elsewhere at runtime.
- `print()`/`stderr` output is fine — that's the environment's own agent-logs channel
  (`kaggriculture.json` `maxLogLength`), not egress in the sense the rule means.

Enforced by the bundle-audit test in `SPEC.md` (static `ast` scan of the built `submission.tar.gz`
for forbidden imports and `open()` calls with non-relative-to-bundle paths), run as part of
`tools/build_submission.py` before every submission — not just asserted in prose.

## Testing

- Full-episode timing test (as above) — this is the module's primary correctness gate, since a
  strategically-perfect agent that times out still loses.
- Fuzzing: feed `agent()` observations with missing keys, wrong types, an out-of-range `player`
  index, and a `farms` list shorter than expected; assert it always returns the safe-default shape
  above without raising.
- Bundle audit (described above), run against the actual `build/submission.tar.gz`, not source
  files in isolation — a dynamic `importlib` trick could theoretically evade a source-only scan.
- Golden-episode regression: a handful of fixed seeds where `agent()` played against `starter`/
  `random` have recorded final-money outcomes; any change to `agent`/`policy` that moves these
  needs a deliberate re-record.

## Boundaries specific to this module

- Standard library only (inherits from `SPEC.md`'s bundle boundary) — this is the module most
  tempted to add "just a small helper library"; don't.
- Never remove or weaken the top-level `try/except` to "improve" a stack trace during development —
  use the golden-episode/fuzz tests locally instead, where exceptions are allowed to propagate.
