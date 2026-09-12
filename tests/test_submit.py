"""Tests for tools/submit.py - see SPEC-ops.md "Submission workflow" and
tasks/plan.md T5.2.

Architecture note (a real deviation from a literal reading of the plan,
documented rather than silently forced): SPEC-ops.md's own text says an
MCP tool "is invoked by an agent... acting on the user's behalf, not by
a standalone script running unattended." start_competition_submission_
upload, submit_to_competition, and get_competition_submission are all
MCP-only calls - no Python library exposes them to a plain script. This
module therefore only implements the genuinely scriptable pieces SPEC-
ops.md itself calls out as "plain HTTP, not an MCP tool call" (the PUT
upload) plus the pre/post bookkeeping (file metadata, the
submissions.jsonl log) - it never calls submit_to_competition itself,
regardless of any flag, because it structurally cannot. The actual
orchestration (call start_competition_submission_upload -> pass its
upload_url/blob token into this module's upload_bytes -> decide whether
to call submit_to_competition) is carried out by the agent directly at
T5.3, with a human go-ahead gate immediately before submit_to_competition.
"""

import http.server
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import submit  # noqa: E402


def test_compute_file_metadata_reads_real_size_and_mtime(tmp_path):
    path = tmp_path / "submission.tar.gz"
    path.write_bytes(b"fake tarball bytes")
    os.utime(path, (1_700_000_000, 1_700_000_000))

    content_length, last_modified = submit.compute_file_metadata(str(path))

    assert content_length == len(b"fake tarball bytes")
    assert last_modified == 1_700_000_000


class _RecordingPutHandler(http.server.BaseHTTPRequestHandler):
    received = []

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _RecordingPutHandler.received.append(
            (self.headers.get("Content-Length"), self.headers.get("Content-Type"), body)
        )
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass  # keep test output quiet


def test_upload_bytes_puts_the_exact_file_contents(tmp_path):
    payload = b"the actual submission tarball bytes"
    path = tmp_path / "submission.tar.gz"
    path.write_bytes(payload)

    _RecordingPutHandler.received.clear()
    server = http.server.HTTPServer(("127.0.0.1", 0), _RecordingPutHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/upload"
        submit.upload_bytes(url, str(path))
    finally:
        server.shutdown()
        thread.join()

    assert len(_RecordingPutHandler.received) == 1
    content_length_header, content_type_header, body = _RecordingPutHandler.received[0]
    assert body == payload
    assert content_length_header == str(len(payload))
    # Real bug found submitting for real (T5.3, ref 56175204): Kaggle's
    # upload URL is a GCS resumable-upload session - a PUT with no
    # Content-Type header was never actually exercised against it before
    # this (the real submission was pushed through by hand with curl,
    # bypassing this function entirely). GCS accepted the upload once
    # Content-Type was set; this test would not have caught its absence
    # before, since it never checked the header at all.
    assert content_type_header == "application/gzip"


def test_build_submission_log_entry_has_the_documented_fields():
    entry = submit.build_submission_log_entry(
        description="baseline agent",
        policy_git_commit="abc1234",
        arena_win_rate=1.0,
        tarball_path="build/submission.tar.gz",
    )
    assert entry["description"] == "baseline agent"
    assert entry["policy_git_commit"] == "abc1234"
    assert entry["arena_win_rate"] == 1.0
    assert entry["tarball_path"] == "build/submission.tar.gz"
    assert "timestamp" in entry


def test_log_submission_attempt_appends_jsonl_lines(tmp_path):
    log_path = str(tmp_path / "submissions.jsonl")
    submit.log_submission_attempt(log_path, {"description": "first"})
    submit.log_submission_attempt(log_path, {"description": "second"})

    with open(log_path) as f:
        lines = [json.loads(line) for line in f]
    assert [entry["description"] for entry in lines] == ["first", "second"]


def test_cli_dry_run_never_uploads_or_logs(monkeypatch, tmp_path, capsys):
    tarball = tmp_path / "submission.tar.gz"
    tarball.write_bytes(b"x")
    monkeypatch.setenv("KAGG_PROJECT_ROOT", str(tmp_path))

    def _boom(*a, **kw):
        raise AssertionError("upload_bytes must not be called in --dry-run")

    monkeypatch.setattr(submit, "upload_bytes", _boom)

    exit_code = submit.main(
        [
            "--tarball", str(tarball),
            "--upload-url", "http://example.invalid/upload",
            "--description", "would-be submission",
            "--policy-commit", "deadbeef",
            "--arena-win-rate", "1.0",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert not (tmp_path / "data" / "arena" / "submissions.jsonl").exists()
    out = capsys.readouterr().out
    assert "would-be submission" in out


def test_cli_default_mode_uploads_and_logs(monkeypatch, tmp_path):
    tarball = tmp_path / "submission.tar.gz"
    tarball.write_bytes(b"x")
    monkeypatch.setenv("KAGG_PROJECT_ROOT", str(tmp_path))

    calls = []
    monkeypatch.setattr(submit, "upload_bytes", lambda url, path: calls.append((url, path)))

    exit_code = submit.main(
        [
            "--tarball", str(tarball),
            "--upload-url", "http://example.invalid/upload",
            "--description", "real dry-run-free call",
            "--policy-commit", "deadbeef",
            "--arena-win-rate", "1.0",
        ]
    )

    assert exit_code == 0
    assert calls == [("http://example.invalid/upload", str(tarball))]
    log_path = tmp_path / "data" / "arena" / "submissions.jsonl"
    assert log_path.is_file()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert entries[0]["description"] == "real dry-run-free call"


def test_module_never_defines_a_submit_to_competition_call():
    # Guards the architectural boundary this module documents up top:
    # nothing in here may *call* the MCP-only submit_to_competition step
    # (call syntax, not the module's own docstring/comments explaining
    # why it doesn't) - that's the agent's job at T5.3, with a human
    # go-ahead gate.
    source = open(submit.__file__).read()
    assert "submit_to_competition(" not in source
