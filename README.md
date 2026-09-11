# Kaggriculture agent

Heuristic economic planner for the Kaggle simulation competition
[Kaggriculture](https://www.kaggle.com/competitions/kaggriculture).

See [`SPEC.md`](SPEC.md) for the full specification (objective, capability map, testing strategy,
boundaries, and competition rule compliance). Module specs, in build order:

1. [`SPEC-harness.md`](SPEC-harness.md) — arena/evaluation protocol
2. [`SPEC-gamelib.md`](SPEC-gamelib.md) — pure economic model, ships in the submission
3. [`SPEC-agent.md`](SPEC-agent.md) — submission contract, time budget, fault tolerance
4. [`SPEC-policy.md`](SPEC-policy.md) — the actual decision-making logic
5. [`SPEC-tuning.md`](SPEC-tuning.md) — parameter search and the regression gate
6. [`SPEC-ops.md`](SPEC-ops.md) — Kaggle MCP/CLI, bundling, submission, forum monitoring

## Status

Pre-implementation: all specs above are written and approved; no code yet. This README fills in
as each module lands.

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
