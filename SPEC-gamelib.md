# SPEC: `gamelib`

Part of the [capability map](SPEC.md#capability-map). Depends on: nothing. **Ships in the
submission.**

## Objective

Give `policy` a correct, fast, standard-library-only model of the game's economics to plan
against. "Correct" is not asserted — it's verified turn by turn against the real interpreter
(`kaggle_environments/envs/kaggriculture/kaggriculture.py`) via property tests, because `gamelib`
ships without ever importing that module (Official Rules §2.11, and the general no-network/no-extra-
deps boundary in `SPEC.md`).

## Scope

Reimplements, as pure functions with no side effects and no environment import, exactly these
pieces of `kaggriculture.py`'s logic:

| `gamelib` function | Mirrors | Source line |
|---|---|---|
| `price(item, inventory, params) -> int` | `market_price` | `kaggriculture.py:192` |
| `shape(func, x, T) -> float` | `_shape` | `kaggriculture.py:61` |
| `hire_cost(n_already_today, mult) -> int` | `_hire_cost` | `kaggriculture.py:698` |
| `watering_bonus_window(crop) -> range` | inline logic in `WATER` handling | `kaggriculture.py:440` |
| `forecast_one_time_yield(crop, watered_days, fertilized) -> int` | `WATER`/`FERTILIZE` handlers | `kaggriculture.py:431-482` |
| `forecast_ongoing_schedule(crop, planted_day) -> list[int]` | `_daily_refresh_plants` | `kaggriculture.py:769` |
| `forecast_animal_schedule(animal, placed_day) -> list[int]` | `_daily_refresh_animals` | `kaggriculture.py:805` |
| `decay_step(max_lifespan_step, step) -> bool` | `_decay_plants` | `kaggriculture.py:752` |
| `shed_room(shed, capacity) -> int` | `_drop_inventories_to_shed` | `kaggriculture.py:843` |
| `tile_distance(a, b) -> int` | (new — Manhattan distance, matches `FARMER_MOVES`) | `kaggriculture.py:88` |
| `land_price(n_unlocked_extra) -> int \| None` | `_do_buy_land` | `kaggriculture.py:712` |

Constants (`CROPS`, `ANIMALS`, `MARKET_PARAMS`, `SHOPS`, `LAND_PRICES`, `TOWN_CENTER_PRODUCTS`,
`MAX_SHOP_INSTANCES`) are copied verbatim as `gamelib/constants.py` — these are game rules, not
implementation details, and the environment does not expose them as an importable, dependency-free
module we could rely on at submission time.

**Explicitly out of scope for `gamelib`:** anything that requires the full turn-processing order
or RNG (weed spawning, town shop unlock draws, simultaneous order matching against an opponent).
Those are inherently about the live episode, not a static forecast — `policy` reasons about them
using `gamelib`'s per-tile/per-order primitives, not a duplicated event loop.

## Key subtleties to get right (each gets its own property test)

- **Watering bonus window** is `ceil(max_yield_day / 2) <= age_days <= max_yield_day` (source:
  `window_start = (crop_data["max_yield_day"] + 1) // 2`, `kaggriculture.py:440`), not "half the
  growth time" loosely — off-by-one here silently costs yield in `policy`'s harvest planning.
- **Fertilizer window is inclusive of 3 days**: `fertilized_until_day = day + 2` on the day
  `FERTILIZE` is used, i.e. active for `day, day+1, day+2` (`kaggriculture.py:481`).
- **`price()` rounds to nearest int and floors at `PRICE_FLOOR = 1`** — a forecast that returns a
  float will silently disagree with the real market by ±1 near the floor, which matters because
  the floor is exactly where `policy`'s "is this market saturated" threshold lives.
- **Buy price is quoted post-buy inventory; sell price pre-sell** (README.md "Buying inventory
  from the market") — `gamelib.price()` must take an explicit inventory argument rather than
  assume a direction, so `policy` cannot accidentally quote the wrong side.
- **Ongoing crop production is capped, not indefinite**: tomato caps at 4 scheduled yields (ages
  8–11), strawberry at 4 (ages 10/12/14/16); `forecast_ongoing_schedule` must return a finite list,
  not a generator that a caller might iterate too far.
- **`hire_cost` resets to `fib(0)=1` at the start of each day** — a caller must pass
  `hires_today` from the current farm state, not a running total across days.

## Property tests (against the real interpreter)

Import the real `kaggriculture.py` **only from the test suite** (never from `gamelib` itself — see
Boundaries) as the oracle:

- `price()` matches `market_price()` for 1,000 randomized `(item, inventory)` pairs spanning
  `[0, 3*I0]`, including both sides of `I0` and the `hinge` knee at `T`.
- `forecast_one_time_yield()` matches a real single-tile simulation: plant a crop in a scratch
  `_new_farm`, apply `WATER`/`FERTILIZE`/`HARVEST` via `_apply_unit_action` for a randomized
  watering schedule, and compare final `yield_units` to the forecast for the same schedule.
- `forecast_ongoing_schedule()` and `forecast_animal_schedule()` match the day-indexed yield
  bumps produced by driving `_daily_refresh_plants`/`_daily_refresh_animals` for 30 simulated days.
- `hire_cost()` matches `_hire_cost()` for `n_already_today in range(0, 20)`.
- `shed_room()` matches a scratch shed filled to a randomized level.

## Testing (unit, no oracle needed)

- `tile_distance` is symmetric, zero on identity, and matches hand-computed Manhattan distances on
  a few fixed coordinate pairs including opposite corners of a 10×10 board.
- `land_price` returns `None` once all three extra quadrants are bought (mirrors `_do_buy_land`'s
  `n_unlocked_extra >= len(LAND_ORDER)` guard, `kaggriculture.py:714`).

## Boundaries specific to this module

- No import of `kaggle_environments` from any file under `src/kagg/gamelib/` — only from
  `repo/tests/`. A test asserts this via `ast`-scanning `gamelib`'s source files for the import,
  so the boundary can't regress silently.
- No third-party dependency, ever — this ships in the submission bundle (Official Rules §2.11).
