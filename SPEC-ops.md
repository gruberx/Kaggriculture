# SPEC: `ops`

Part of the [capability map](SPEC.md#capability-map). Depends on: `agent` (packages its output),
`diskguard` (guards every download below). Dev-only, does not ship.

## Objective

Everything needed to get a built agent onto Kaggle and get information back: bundling, submitting,
polling, pulling replays/logs for post-mortem, pulling competition intelligence (daily top-episode
dataset, forum). All of it goes through the official **Kaggle MCP server**
(`https://www.kaggle.com/mcp`, connected in this project as `kaggle-mcp`, streamable HTTP,
authenticated as the project owner's Kaggle account — verified: `get_competition("kaggriculture")`
returns the account-specific field `user_has_entered: true`, not just public metadata).

**No separate `kaggle` CLI/API token is needed.** An earlier revision of this spec assumed one
would be, for "batch/scripted operations" — that assumption didn't survive checking the actual
tool surface. Every operation this module needs has an MCP equivalent, verified directly rather
than inferred from the tool list:
- `search_competitions(group="Entered")` — confirmed to return kaggriculture with
  `user_has_entered: true`, the exact equivalent of `kaggle competitions list --group entered`.
- `start_competition_submission_upload` + `submit_to_competition` — the full submit flow (see
  "Submission workflow" below), equivalent to `kaggle competitions submit`.
- `get_competition_submission`, `list_submission_episodes`, `get_episode_replay`,
  `get_episode_agent_logs`, `get_competition_leaderboard` — equivalents of
  `kaggle competitions submissions|episodes|replay|logs|leaderboard`.
- `download_competition_data_file`/`download_competition_data_files` and `download_dataset` (for
  the daily top-episodes dataset, which is a Kaggle *Dataset*, not a competition data file) —
  equivalents of `kaggle competitions download`/`kaggle datasets download`.

The one real difference is *who* can invoke a call, not *what* can be done: an MCP tool is
invoked by an agent (this Claude Code session) acting on the user's behalf, not by a standalone
script running unattended with no agent in the loop. That distinction doesn't cost us anything
here — every operation this module performs (submitting, downloading enough data to matter) is
already specified as an "ask first" action in `SPEC.md` Boundaries, i.e. deliberately
agent-mediated rather than run by an unattended cron job. If a genuine need for headless,
agent-free scripting ever appears (none identified so far), that is the concrete trigger for
revisiting a CLI token — not "batch operations" in the abstract.

## Kaggle access setup

1. **User action, before September 23, 2026**: complete identity verification and click "Join
   Competition" at the competition page. **Done** — confirmed via `user_has_entered: true`.
2. MCP: connected as `kaggle-mcp`, authorized. **Done.**

## Submission bundling

`tools/build_submission.py`:
1. Copies `src/kagg/agent_main.py` → `build/main.py`.
2. Copies `src/kagg/gamelib/`, `src/kagg/policy/` → `build/kagg/gamelib/`, `build/kagg/policy/`.
3. Copies the currently-accepted `params/policy.json` (and `params/seed_blocks.json` only if
   `policy` actually reads it at runtime — otherwise leave tuning-only files out of the bundle
   entirely, since Official Rules §2.11 permits *using* only what's in the bundle, and a smaller
   bundle is a smaller audit surface) into `build/kagg/params/`.
4. Fixes up `sys.path` inside `build/main.py`'s header so `import kagg.gamelib...` resolves when
   Kaggle unpacks the bundle at `/kaggle_simulations/agent/` (per `AGENTS.md`: "Your files will be
   located in `/kaggle_simulations/agent/`. Ensure all your file imports are set appropriately").
5. Runs the bundle audit from `SPEC.md`'s testing strategy (static scan for network/file-outside-
   bundle access) — **build fails, does not warn, if the audit finds a violation.**
6. Runs a smoke-test local episode (`kaggle_environments.make(...).run(["build/main.py", "random"])`)
   to catch import/path errors before they cost a submission slot.
7. `tar -czf build/submission.tar.gz -C build main.py kagg params` (matches `AGENTS.md`'s
   documented multi-file format: `main.py` at the tar root).

## Submission workflow

```
build_submission.py
  -> start_competition_submission_upload(competitionName, fileName, contentLength,
                                          lastModifiedEpochSeconds)
       returns an upload URL + a blob file token
  -> PUT the built submission.tar.gz's bytes to that URL directly (plain HTTP, not
       an MCP tool call — this is why the upload step is split from the submit
       step: MCP tool calls aren't meant to carry multi-GB binary payloads)
  -> submit_to_competition(competitionName, blobFileTokens, submissionDescription)
  -> poll get_competition_submission(ref)
  -> once scored episodes exist: list_submission_episodes(submissionId)
  -> get_episode_replay + get_episode_agent_logs for any loss worth understanding,
       saved to data/replays/ through diskguard.ensure_budget() like any other pull
```

Every submission is logged (message, timestamp, git commit of `policy` at build time, arena
win-rate that justified it) to `data/arena/submissions.jsonl` (outside the repo — see `SPEC.md`)
before the actual API call, so "why did we submit this" is answerable later even if the day's
5-submission budget runs out from an unrelated mistake. This particular write is exempt from the
`ensure_budget()` call — it's a small append-only log, kilobytes over the whole competition, not
one of the disk-hungry operations `diskguard` exists for (see `SPEC-diskguard.md`).

**5/day limit, only the latest 2 scored** (`kaggriculture` competition metadata:
`maxDailySubmissions: 5`, `numScoredSubmissions: 2`) — per `SPEC.md` Boundaries, spending a
submission is an ask-first action, not something automated tooling triggers on its own.

## Competition intelligence

- **Daily top-episodes dataset** — Kaggle publishes up to 20 GB/day of the highest-rated episodes'
  replays: [`kaggle/kaggriculture-episodes-index`](https://www.kaggle.com/datasets/kaggle/kaggriculture-episodes-index).
  Pulled via `download_dataset` (owner `kaggle`, slug `kaggriculture-episodes-index`) into
  `data/episodes/` (outside the repo), calling `diskguard.ensure_budget(need_bytes=<listed size>)`
  first — see `SPEC-diskguard.md` for the 2.5 TB project-wide cap and its oldest-first eviction
  policy. Used for: (a) refreshing `tuning`'s opponent panel with genuinely current strong play
  rather than a frozen baseline, (b)
  sanity-checking `gamelib`'s forecasts against what top agents actually achieve. Even with
  `diskguard` enforcing the cap, pull selectively (e.g. top-N by rating, not the full daily drop)
  rather than mirroring everything — the guard is a backstop against exceeding the budget, not a
  reason to stop being deliberate about what's worth keeping.
- **Public strong baseline** — the `yhay81/shop-router-0909` notebook, referenced on the forum as
  a benchmark opponent; add it to `tuning`'s opponent panel once downloaded.
- **Forum monitoring** — `list_competition_topics`/`list_topic_messages` via MCP. The forum has
  already saved real work during spec-writing (the hiring-count correction, the paired-seat/
  held-out/reroll evaluation pitfalls, the RL cost-benefit numbers); check it periodically rather
  than only once, since new negative results there are cheaper to read than to rediscover.

## Testing

- `build_submission.py`'s bundle audit and smoke test (described above) are the tests for this
  module — a bundle that fails either must not be a candidate for submission, enforced by the
  script's own exit code, not by a separate test file.
- A dry-run mode (`--no-submit`) that does everything up to and including the upload step but
  skips `submit_to_competition`, for exercising the pipeline without spending a submission slot.

## Boundaries specific to this module

- *Ask first* (from `SPEC.md`, restated here since this is the module that actually executes it):
  every real submission, every download of the top-episodes dataset large enough to matter for
  disk space, every forum post.
- *Never*: let this module's automation call `submit_to_competition` without a human-approved step
  immediately before it — no cron job auto-submits. This falls out naturally from MCP tools being
  agent-invoked rather than callable by an unattended script, but the boundary holds regardless of
  mechanism.
- Competition Data pulled here goes to `data/`, never to `repo/` — this module is the primary place
  that boundary could be violated by a careless path, so `build_submission.py` and the download
  helpers hardcode `KAGG_DATA_DIR`-relative destinations rather than accepting an arbitrary
  `--out` path that could point inside the repo.
