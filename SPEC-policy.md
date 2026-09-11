# SPEC: `policy`

Part of the [capability map](SPEC.md#capability-map). Depends on: `agent` (and, through it,
`gamelib`). **Ships in the submission.**

## Objective

The actual decision-making logic: what to plant, when to buy land/hire, how to route farmer +
hands across tiles, and when to sell. Every numeric threshold here is a named parameter loaded
from `params/*.json` (see `SPEC-tuning.md`) — this module encodes the *shape* of the strategy,
not the specific numbers, so that `tuning` can improve the numbers without touching this code.

## Three layers

### 1. Strategic layer (runs once per day, `obs["hour"] == 0`)

Decides, for the coming day:
- **Portfolio** — how to allocate empty/replantable tiles across crops and animal structures.
  Ranked by marginal revenue *given current market depth*, not by base price: `gamelib.price()`
  evaluated at the farm's own projected sell volume, not at `I0`. This operationalizes the
  economic finding in `SPEC.md`'s market-depth table (premium goods — milk, wool, melon,
  strawberry — collapse to the $1 floor after a few dozen units; wheat and eggs barely move) as a
  portfolio cap per product, not a hard-coded crop list.
- **Land purchases** — `gamelib.land_price()`-driven; a parameter (not a hard-coded "always buy
  ASAP") controls the money threshold at which the next quadrant is bought, since this interacts
  with the hiring question below and must be tuned jointly, not decided from first principles.
- **Hiring count for the day** — **explicitly a tunable parameter swept by `tuning`, not a fixed
  policy**, per the correction recorded in `SPEC.md`'s economic analysis: the "labor is nearly
  free, hire many hands" intuition derived from `hire_cost`'s Fibonacci curve was directly
  contradicted by a forum measurement ("adding workers has zero marginal value" — thread 740792),
  and a sequential-assignment hand scheduler in that same thread lost heavily to a simpler fixed
  script. Do not hardcode a hiring count in this module; expose it as `params.hires_per_day` (or a
  small formula with tunable coefficients) and let the arena settle the question. Plausible
  explanations worth testing rather than assuming: hands spawn shed-adjacent where 3 of 4 tiles
  start locked, and both shed capacity (100 items) and market depth cap the value of extra
  production regardless of labor.
- **CARE scheduling for animals** — tunable, but the mechanism (`pending_care_bonus`, paid out on
  the next scheduled production if fed) rewards *daily* CARE on ongoing-production animals more
  than the game's other systems reward attention; treated as a strong prior to verify by measurement,
  not a hard-coded "always CARE," since `SPEC.md` flags it as unverified.

### 2. Task layer (every turn)

Builds a prioritized task list (`WATER` tile X, `HARVEST` tile Y, `FEED` animal Z, `PLANT` on a
free tile, `COLLECT_FERTILIZER`, `DIG` a weed) from the current farm state, then greedily assigns
the farmer and each hand to the highest-priority reachable task using `gamelib.tile_distance`. At
up to 100 tiles and a small number of units, this is a bounded greedy assignment, not a search
problem — the time budget (`SPEC-agent.md`) does not allow anything fancier here, and there's no
evidence yet (see hiring note above) that sophisticated multi-unit coordination pays for itself.

Priority order (initial, tunable via weights rather than hardcoded ordering): prevent-loss actions
(water/feed a tile about to hit `consecutive_unwatered`/`consecutive_unfed` == 2) outrank
harvest-value actions, which outrank plant-new-tile actions, which outrank opportunistic
maintenance (DIG, COLLECT_FERTILIZER).

### 3. Market layer (every turn, ≤10 orders per `maxMarketOrdersPerTurn`)

- **Sell thresholds**: sell shed contents when `gamelib.price()` at the farm's own likely sale
  volume clears a tunable margin over the crop's cost basis; premium goods are drip-sold across
  multiple turns rather than dumped, since a large single-turn `SELL` order walks the price down
  unit-by-unit within that same turn (README.md "Selling inventory to the market").
- **Feed-stock buying**: `BUY_PRODUCT WHEAT` when the price is below a tunable threshold and
  on-hand wheat is projected to run out before the next harvest, so animal feeding never lapses
  into the two-consecutive-missed-days escape condition.
- **Opponent-aware market pressure** (advanced, not a base-mode default): since `market.inventory`
  is shared and visible, and only the win/loss/tie outcome matters (not the money margin — see
  `SPEC.md` Evaluation), deliberately selling into a product the opponent is farming can be
  rational once basic profitability is validated. This is a `tuning`-stage experiment gated behind
  a feature flag, not part of the initial policy — it adds real risk of misreading the opponent's
  farm and should only be attempted once the base strategy's win rate is established as a
  baseline to compare against.

## Parameters

All strategic/task/market thresholds live in `params/policy.json`, loaded once at agent
construction (not per turn — respects the time budget in `SPEC-agent.md`). The schema is owned by
this module and versioned; `tuning` writes new parameter files, it never edits `policy`'s code to
smuggle in a magic number.

## Testing

- Portfolio allocation unit tests: given a synthetic farm state and market snapshot, the chosen
  allocation matches hand-computed expected marginal revenue ranking.
- Task-layer unit tests: given a farm with tiles in various states (about to weed, ready to
  harvest, empty), the greedy assignment picks the prevent-loss action first.
- Market-layer unit tests: sell/buy decisions respect the ≤10-orders-per-turn cap and never queue
  a `BUY_PRODUCT` for an item other than `WHEAT`/`FERTILIZER` (the only two the market allows
  buying back, per README.md).
- End-to-end: `policy` driven through `agent`, measured via the `harness` arena against `starter`
  and `random` before any parameter tuning — this is the pre-tuning baseline that `tuning` must
  beat, not just "some number."

## Boundaries specific to this module

- Standard library only (inherits the bundle boundary from `SPEC.md`).
- No hardcoded strategic constant that should plausibly vary by opponent or market state — if
  tempted to hardcode "always hire 9" or "always buy land by day 5," make it a named parameter
  instead, even before `tuning` has a value for it. Getting the *shape* right here is this
  module's job; getting the *numbers* right is `tuning`'s.
