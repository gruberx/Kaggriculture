# SPEC: `tuning`

Part of the [capability map](SPEC.md#capability-map). Depends on: `harness`, `policy`. Dev-only,
does not ship (its *output* — a `params/*.json` file — ships as part of `policy`'s data).

## Objective

Turn `policy`'s named-but-unset parameters into numbers, using the `harness` arena as the only
source of truth, and produce a regression-gated `params/policy.json` that `agent`/`policy` load at
submission time.

## Stage 1 — coordinate ascent

For each parameter (or small correlated group — e.g. `hires_per_day` and `land_purchase_threshold`
are suspected to interact, per `SPEC-policy.md`'s hiring note, and should be swept jointly rather
than independently): hold all other parameters fixed, sweep a small grid of candidate values,
evaluate each via `harness.run_block` on the *working* seed block (never the held-out block —
see `SPEC-harness.md`), and keep the value with the best Wilson-interval-adjusted win rate against
a fixed opponent panel (`starter`, `random`, the public `yhay81/shop-router-0909` notebook if
downloaded per `SPEC-ops.md`, and the previous best `policy` snapshot). Repeat until no parameter
change improves the working-block win rate beyond noise (Wilson interval overlap).

**First sweep priority**: the hiring-count question flagged in `SPEC-policy.md` as an open,
forum-contradicted hypothesis. This determines whether the "buy land aggressively, hire heavily"
family of strategies is worth pursuing at all, so it gates a large fraction of the rest of the
portfolio/land parameter space and should be resolved before spending search budget elsewhere.

**Cost budget** (measured, see `SPEC.md`): ~1.3–1.4s per real episode. A sweep of ~20 parameters ×
5 candidate values × 100 paired seeds (~20,000 episodes) costs on the order of 2 hours on today's
4-CPU container, well under an hour once the pending 12-CPU change lands (`SPEC.md` "Environment").
No `fastsim` rewrite is needed to make this tractable (see `SPEC.md`'s rationale for dropping it).

## Stage 2 — search-generated value targets (only after Stage 1 has a working baseline)

The one ML-flavored technique that fits a no-GPU, ~19-day budget (see `SPEC.md` "Why not RL"):
from real game states encountered during arena play, branch the actual `kaggle_environments`
simulator across a handful of *complete* strategic alternatives (e.g. "commit to the melon-heavy
plan" vs. "commit to the wheat-volume plan" for the rest of the day), play each out, and train a
lightweight selector (not a full policy network — a small model choosing among a handful of
named, `policy`-executable plans) on the outcomes. This needs no RL loop and no GPU: it's
supervised learning on simulator-labeled branches, with `policy` remaining the thing that actually
executes turns. Deferred until Stage 1 produces a checked-in baseline `params/policy.json` that
beats `starter` and `random` by the `SPEC.md` success criteria — no point building a selector over
plans that haven't been shown to be individually good.

## Held-out evaluation and the regression gate

Before any `params/policy.json` update is accepted:
1. Run the *held-out* seed block (untouched during Stage 1/2 search) via `harness.run_block`.
2. Compare against the currently-checked-in `params/policy.json` on the same held-out block.
3. Accept only if the held-out win rate improves outside the Wilson interval overlap — the working
   block's number is not sufficient evidence, per `SPEC-harness.md`.
4. Record the accepted run's full configuration (seed blocks used, opponent panel, resulting win
   rates, git commit of `policy` at the time) in `data/arena/` (outside the repo — this is
   Competition-Data-adjacent tuning history, not source code) so a regression can be traced later.

## Evaluation context (Official Rules / Evaluation page)

There is no private leaderboard to worry about overfitting to a hidden test set (simulation
competitions have none — `SPEC.md` "Rule compliance"). The actual final ranking comes from a
single Bradley–Terry tournament run on episodes played in the two weeks after the entry deadline
(chosen by the host specifically to avoid rewarding "hot streaks"), so the harness's job is to
predict *relative* strength against a broad, evolving opponent field — not to chase a single
number against one fixed opponent. The opponent panel in Stage 1 should be refreshed periodically
from the daily top-episodes dataset (`SPEC-ops.md`) rather than frozen at project start.

## Testing

- The regression gate itself is tested: feed it a synthetic "worse" candidate and confirm it's
  rejected; feed it a synthetic "clearly better" candidate (e.g. an opponent that always passes)
  and confirm it's accepted.
- Coordinate-ascent loop termination is tested on a toy 2-parameter objective with a known optimum
  before being trusted on the real (expensive) arena.

## Boundaries specific to this module

- Dev-only: full freedom to depend on `kaggle_environments`, numerical libraries, etc. — none of
  this ships.
- Never accept a `params/policy.json` update based on the working seed block alone (see gate above)
  — this is the single most important discipline this module exists to enforce.
- Every accepted parameter update is a separate, described commit (not squashed into "tuning
  wip") — the Winner Obligations methodology writeup (`SPEC.md` §2.5/§2.8) needs this history to
  be legible.
