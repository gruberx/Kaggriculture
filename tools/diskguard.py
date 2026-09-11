"""Disk budget guard for the Kaggriculture project's dev-only tooling.

Dev-only: this never ships in the submission bundle (see SPEC.md's stdlib-only
boundary for gamelib/agent/policy). It exists to stop `ops` downloads (the
daily top-episodes dataset, replays) and `harness`/`tuning` arena log writes
from growing this project past its disk budget on a filesystem shared with
other projects on the same host.

Why this lives in application code rather than the filesystem: the volume
under /root has no project-quota support available inside this container (no
`prjquota` mount option, no `xfs_quota`/`setquota`/`repquota`, no loop
devices) - see SPEC.md "Environment" for the investigation. A hard limit
would need a dedicated mounted volume or filesystem project quota, both of
which require action on the host. Enforcement therefore happens here.

See SPEC-diskguard.md for the full design and the eviction policy rationale.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# 2.5 *decimal* TB, not TiB - deliberately the smaller of the two readings of
# "2.5 TB", so the guard never allows more than what was actually asked for.
BUDGET_BYTES = 2_500_000_000_000

# Once projected usage crosses this fraction of BUDGET_BYTES, ensure_budget()
# starts evicting rather than waiting until the hard cap is actually hit -
# leaves headroom for the write in progress plus whatever else is in flight.
SOFT_RATIO = 0.9

# Paths (relative to the project root) eligible for automatic oldest-first
# eviction: re-downloadable Kaggle data, never original work product.
EVICTABLE = ("data/replays", "data/episodes")

# Paths ensure_budget() will never delete from, no matter how far over
# budget usage remains after evicting everything in EVICTABLE. data/arena
# holds our own tuning history (needed for the Winner Obligations
# methodology writeup, Official Rules Sec 2.5/2.8); repo is the only
# directory git can see at all.
PROTECTED = ("data/arena", "repo")


class DiskBudgetExceeded(RuntimeError):
    """Raised when projected usage stays over BUDGET_BYTES after evicting
    everything eligible under EVICTABLE. Callers must treat this as "do not
    perform the write" - never touch a PROTECTED path to work around it."""


@dataclass
class EvictionResult:
    freed_bytes: int = 0
    evicted_paths: list[str] = field(default_factory=list)


def _project_root() -> str:
    """Default: two directories above this file (tools/diskguard.py -> repo/
    -> project root). Overridable via KAGG_PROJECT_ROOT for anyone
    reproducing this outside /root/kaggriculture (see SPEC.md's
    KAGG_DATA_DIR convention - this follows the same idea one level up)."""
    env = os.environ.get("KAGG_PROJECT_ROOT")
    if env:
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def _is_protected(path: str, root: str) -> bool:
    rel = os.path.relpath(path, root)
    return any(rel == p or rel.startswith(p + os.sep) for p in PROTECTED)


def usage_bytes(root: str | None = None) -> int:
    """Total size in bytes of everything under `root` (default: the whole
    project root, not just data/ - repo/ and .venv/ are negligible next to
    downloaded replays/episodes, and measuring the whole tree is simpler and
    harder to get subtly wrong than trying to carve out just data/)."""
    root = root or _project_root()
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                total += os.lstat(path).st_size
            except OSError:
                # Vanished between listing and stat (e.g. a concurrent
                # eviction pass elsewhere) - not a reason to fail the count.
                continue
    return total


def _iter_evictable_files(root: str):
    """Yield (mtime, path, size) for every file under EVICTABLE paths,
    oldest download first."""
    files = []
    for rel in EVICTABLE:
        base = os.path.join(root, rel)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                path = os.path.join(dirpath, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                files.append((st.st_mtime, path, st.st_size))
    files.sort(key=lambda entry: entry[0])
    return files


def ensure_budget(need_bytes: int = 0, root: str | None = None) -> EvictionResult:
    """Call before any write that could grow the project's disk usage.

    If projected usage (current + need_bytes) stays under
    SOFT_RATIO * BUDGET_BYTES, this is a no-op. Otherwise, evict the oldest
    files under EVICTABLE (data/replays, data/episodes) - oldest first -
    until projected usage is back under the soft threshold, or there is
    nothing left to evict. PROTECTED paths (data/arena, repo) are never
    considered for eviction, regardless of how far over budget usage is.

    Raises DiskBudgetExceeded if, after evicting everything evictable,
    projected usage still exceeds BUDGET_BYTES (the hard cap, not the soft
    one). Callers must not proceed with the write in that case.
    """
    root = root or _project_root()
    projected = usage_bytes(root) + need_bytes
    result = EvictionResult()

    soft_cap = int(BUDGET_BYTES * SOFT_RATIO)
    if projected <= soft_cap:
        return result

    for _mtime, path, size in _iter_evictable_files(root):
        if projected <= soft_cap:
            break
        if _is_protected(path, root):
            # Defense in depth: EVICTABLE and PROTECTED must never overlap,
            # but a future config edit could introduce a prefix clash -
            # skip rather than delete if that ever happens.
            continue
        try:
            os.remove(path)
        except OSError:
            continue
        projected -= size
        result.freed_bytes += size
        result.evicted_paths.append(path)

    if projected > BUDGET_BYTES:
        raise DiskBudgetExceeded(
            f"Project usage would be {projected:,} bytes after evicting "
            f"{result.freed_bytes:,} bytes from {EVICTABLE}, still over the "
            f"{BUDGET_BYTES:,}-byte budget. data/arena and repo/ are never "
            f"evicted automatically - free space manually or raise the budget."
        )

    return result
