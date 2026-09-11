# Kaggriculture agent

Heuristic economic planner for the Kaggle simulation competition
[Kaggriculture](https://www.kaggle.com/competitions/kaggriculture).

See [`SPEC.md`](SPEC.md) for the full specification (objective, capability map, module specs,
testing strategy, boundaries).

## Status

Pre-implementation: specifications are being written before code (see `SPEC*.md`). This README
is filled in as each module lands.

## Reproducing results

> Filled in once `tools/` and `tests/` exist. Until then, see `SPEC.md` → "Commands" for the
> intended `pytest` / arena / build invocations.

Competition data (downloaded replays, the daily top-episodes dataset, arena run logs) is
intentionally **not** part of this repository — see `SPEC.md` → "Boundaries" and the competition's
Data Security rules. It lives one level up, outside this repo, at a path configured via
`KAGG_DATA_DIR` (default: `../data`).

## License

The code in this repository is licensed under [CC BY 4.0](LICENSE), per the competition's
Winner License requirement (Official Rules §2.5).
