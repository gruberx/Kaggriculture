# SPEC: `diskguard`

Part of the [capability map](SPEC.md#capability-map). Depends on: nothing. Dev-only, does not ship.

## Objective

Cap this project's disk footprint at 2.5 TB on a machine where the underlying volume is shared
with other projects, without silently exceeding that cap and without a filesystem-level quota to
lean on. The two operations capable of actually growing usage without bound over the ~19 remaining
days are `ops`'s downloads (the daily top-episodes dataset, replays) and `harness`/`tuning`'s arena
run logs — both call `ensure_budget()` before writing.

## Why application-level, not a filesystem quota

Investigated and ruled out: the volume mounted at `/root` is `ext4` without the `prjquota` mount
option (`stat -f` reports the `ext2/ext3` family; `mount` shows no quota option),
`xfs_quota`/`setquota`/`repquota` are not installed, and there are no loop devices available to
mount a fixed-size image at `data/`. A real filesystem-level cap would need either a project quota
enabled at mount time or a dedicated loopback-mounted volume — both require action on the host,
not something achievable from inside this container. The volume is also shared across every
project on this devbox (`near_intents`, `near_test`, `sandbox`, `kaggriculture`), not dedicated to
this one, so even a host-side fix would need to be scoped per-project rather than per-mount.

Given that, enforcement lives in code that every disk-hungry operation in this project calls
through, not in the filesystem underneath it.

## Design

```python
# tools/diskguard.py
BUDGET_BYTES = 2_500_000_000_000  # 2.5 decimal TB, deliberately the smaller
                                   # reading of "2.5 TB" between TB/TiB
SOFT_RATIO = 0.9                  # eviction starts here, not at 100%
EVICTABLE = ("data/replays", "data/episodes")   # re-downloadable Kaggle data
PROTECTED = ("data/arena", "repo")              # never auto-deleted

def usage_bytes(root: str | None = None) -> int: ...
def ensure_budget(need_bytes: int = 0, root: str | None = None) -> EvictionResult: ...
class DiskBudgetExceeded(RuntimeError): ...
```

- **What's measured**: the whole project root (`/root/kaggriculture`), not just `data/`. `repo/`
  and `.venv/` are negligible next to downloaded replays/episodes (measured: ~1.5 GB total
  currently, essentially all `.venv`), so measuring the whole tree is simpler and harder to get
  subtly wrong than trying to carve out exactly `data/`.
- **Eviction policy** (the substantive decision, made by the project owner — see the plan's
  "Дисковый бюджет" section): once projected usage crosses the soft threshold, evict the
  oldest-by-mtime files under `EVICTABLE` first, until back under the soft threshold. `data/arena`
  (tuning history needed for the Winner Obligations methodology writeup, Official Rules §2.5/§2.8)
  and `repo` (the only directory git can see) are never auto-deleted, no matter how far over
  budget usage remains after evicting everything evictable — in that case, `ensure_budget` raises
  `DiskBudgetExceeded` rather than silently exceeding the cap or touching a protected path.
- **`need_bytes`**: callers that know the size of an incoming write in advance (e.g. a dataset
  listing reports its size before download) pass it so the check is based on projected, not
  current, usage. Callers that don't know the size in advance call with no argument as a
  pre-check, and may call again after the write completes to catch an underestimate.
- **`root` override / `KAGG_PROJECT_ROOT` env var**: both `usage_bytes` and `ensure_budget` accept
  an explicit `root`, and `_project_root()` honors `KAGG_PROJECT_ROOT` when neither is given — this
  is what makes the module testable against a synthetic tree instead of the real 2.5 TB budget,
  and what lets someone reproducing this project elsewhere point it at a different layout.

## Call sites

- `SPEC-ops.md`: before downloading the daily top-episodes dataset or replay files.
- `SPEC-harness.md`: before writing "did we peek at the held-out block" logs to `data/arena/`.
- `SPEC-tuning.md`: before writing an accepted run's configuration/history to `data/arena/`.

Each of these already existed as a described write in its own spec; this spec's contribution is
the shared guard they all call through, not a new write path.

## Testing

`tests/test_diskguard.py` (implemented — 7 tests, all passing), against synthetic trees under
`tmp_path` with `BUDGET_BYTES`/`SOFT_RATIO` monkeypatched to small values rather than exercising
the real 2.5 TB budget:

- `usage_bytes` matches the sum of actual file sizes on a small synthetic tree.
- `ensure_budget` is a no-op when projected usage stays under the soft threshold.
- `ensure_budget` evicts the oldest `EVICTABLE` file first and stops as soon as usage is back
  under the soft threshold — it does not over-evict.
- `ensure_budget` never removes a file under a `PROTECTED` path, even when eviction can't bring
  usage under budget at all (an all-protected tree raises immediately without deleting anything).
- `ensure_budget` still evicts everything it can from `EVICTABLE` before raising, even when that
  isn't enough — it doesn't leave evictable files behind just because the hard cap can't be met.
- `ensure_budget` accounts for `need_bytes` against projected, not current, usage.
- `_project_root()` honors `KAGG_PROJECT_ROOT`.

Also manually verified against the real project tree (`usage_bytes("/root/kaggriculture")` →
~1.5 GB, `ensure_budget()` → no-op, as expected at current usage).

## Boundaries specific to this module

- Dev-only: not imported by `gamelib`/`agent`/`policy`, never ships.
- Never delete anything outside `EVICTABLE` automatically — this is the one invariant every test
  above exists to protect, and the defense-in-depth check (`_is_protected` re-verified immediately
  before every `os.remove`) exists specifically so that a future edit to `EVICTABLE` that
  accidentally overlaps `PROTECTED` fails safe instead of deleting tuning history.
- `ensure_budget` raising `DiskBudgetExceeded` means "stop, don't write" for the caller — no call
  site should catch it and proceed anyway.
