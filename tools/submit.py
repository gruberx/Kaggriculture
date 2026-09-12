"""Submission workflow helpers - see SPEC-ops.md "Submission workflow"
and tasks/plan.md T5.2.

Architecture note, a real deviation from a literal reading of the plan
(documented here rather than silently forced to fit): SPEC-ops.md's own
text says an MCP tool "is invoked by an agent... acting on the user's
behalf, not by a standalone script running unattended." Kaggle's
start_competition_submission_upload, submit_to_competition, and
get_competition_submission are MCP-only calls with no Python library
exposing them to a plain script - only the agent (this Claude Code
session) can make them. This module therefore implements exactly the
pieces SPEC-ops.md itself calls "plain HTTP, not an MCP tool call" (the
upload PUT) plus the surrounding bookkeeping (file metadata for the
start_competition_submission_upload request the agent makes separately,
and the data/arena/submissions.jsonl log) - it never calls
submit_to_competition itself, under any flag, because it structurally
cannot. The real orchestration is:

    agent calls start_competition_submission_upload (MCP)
      -> gets (upload_url, blob_file_token)
      -> this module's upload_bytes() PUTs the tarball's bytes there
      -> this module logs the attempt to data/arena/submissions.jsonl
         *before* the next step (SPEC-ops.md: "logged... before the
         actual API call")
      -> agent calls submit_to_competition (MCP) - gated on an explicit,
         real-time human go-ahead (tasks/plan.md T5.3), not automated

`--dry-run` (this module's own "--no-submit" from SPEC-ops.md, renamed
to avoid implying a --submit mode exists) stops before the network call
and the log write entirely - useful for exercising the CLI's argument
handling without touching anything real. The *default* mode (no flag)
still never reaches submit_to_competition (this module has no such
call), matching SPEC-ops.md's "for exercising the pipeline without
spending a submission slot" intent for its entire scope, not just a flag.

Dev-only, never ships. Standard library only - no new dependency for the
HTTP PUT (urllib.request).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diskguard  # noqa: E402

_SUBMISSIONS_LOG_RELATIVE_PATH = os.path.join("data", "arena", "submissions.jsonl")


def compute_file_metadata(path: str) -> tuple[int, int]:
    """(content_length, last_modified_epoch_seconds) - the two fields
    start_competition_submission_upload's request needs (SPEC-ops.md
    "Interface"), computed once here so the agent's MCP call and this
    module's own upload use the same numbers."""
    st = os.stat(path)
    return st.st_size, int(st.st_mtime)


def upload_bytes(upload_url: str, file_path: str) -> None:
    """PUT `file_path`'s exact bytes to `upload_url` - the plain-HTTP step
    SPEC-ops.md splits out from the MCP calls (a submission bundle is
    small - source files plus one JSON params file - so reading it fully
    into memory rather than streaming is a deliberate simplicity choice,
    not an oversight)."""
    with open(file_path, "rb") as f:
        data = f.read()
    request = urllib.request.Request(upload_url, data=data, method="PUT")
    request.add_header("Content-Length", str(len(data)))
    with urllib.request.urlopen(request) as response:
        if response.status not in (200, 201, 204):
            raise RuntimeError(f"upload to {upload_url} failed: HTTP {response.status}")


def build_submission_log_entry(
    description: str, policy_git_commit: str, arena_win_rate: float, tarball_path: str
) -> dict:
    """SPEC-ops.md: "message, timestamp, git commit of policy at build
    time, arena win-rate that justified it" - the fields this project's
    own Winner Obligations writeup needs on record."""
    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "description": description,
        "policy_git_commit": policy_git_commit,
        "arena_win_rate": arena_win_rate,
        "tarball_path": tarball_path,
    }


def log_submission_attempt(log_path: str, entry: dict) -> None:
    """Append `entry` to `log_path` as one JSON line. Exempt from
    diskguard.ensure_budget() per SPEC-ops.md - kilobytes over the whole
    competition, not one of the disk-hungry paths diskguard exists for
    (contrast tools/arena.py's holdout log, which does call it)."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Upload a built submission tarball and log the attempt (never submits)."
    )
    parser.add_argument("--tarball", required=True, help="path to the built submission.tar.gz")
    parser.add_argument("--upload-url", required=True, help="upload URL from start_competition_submission_upload")
    parser.add_argument("--description", required=True, help="submission message")
    parser.add_argument("--policy-commit", required=True, help="git commit of policy at build time")
    parser.add_argument("--arena-win-rate", required=True, type=float, help="arena win rate that justified this submission")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be uploaded/logged without any network call or file write",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    entry = build_submission_log_entry(
        description=args.description,
        policy_git_commit=args.policy_commit,
        arena_win_rate=args.arena_win_rate,
        tarball_path=args.tarball,
    )

    if args.dry_run:
        print("--dry-run: would upload and log the following, but did neither:")
        print(json.dumps(entry, indent=2))
        return 0

    upload_bytes(args.upload_url, args.tarball)
    log_path = os.path.join(diskguard._project_root(), _SUBMISSIONS_LOG_RELATIVE_PATH)
    log_submission_attempt(log_path, entry)
    print(f"Uploaded {args.tarball} to {args.upload_url}")
    print(f"Logged to {_SUBMISSIONS_LOG_RELATIVE_PATH}")
    print("submit_to_competition was NOT called - that MCP call is the agent's, gated on human go-ahead.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
