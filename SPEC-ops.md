# SPEC: `ops`

Part of the [capability map](SPEC.md#capability-map). Depends on: `agent` (packages its output),
`diskguard` (guards every download below). Dev-only, does not ship.

## Objective

Everything needed to get a built agent onto Kaggle and get information back: bundling, submitting,
polling, pulling replays/logs for post-mortem, pulling competition intelligence (daily top-episode
dataset, forum). Two tools cover this, both authenticated against the same Kaggle account/token:
the official **Kaggle MCP server** (`https://www.kaggle.com/mcp`, streamable HTTP, verified
reachable — `initialize` and `tools/list` both responded during spec research) for interactive work
in this session, and the **`kaggle` CLI** for batch/scripted operations that don't need a live
Claude session (e.g. a nightly cron-style pull of the top-episodes dataset).

## Kaggle access setup (blocking, user-side)

1. **User action, before September 23, 2026**: complete identity verification and click "Join
   Competition" at the competition page. Submissions are impossible before this, and this cannot
   be done from here.
2. MCP: `claude mcp add --transport http kaggle https://www.kaggle.com/mcp`, then `/mcp` to
   authorize. Confirmed available tools relevant here (of 71 total): `submit_to_competition`,
   `get_competition_submission`, `search_competition_submissions`,
   `start_competition_submission_upload`, `list_submission_episodes`, `get_episode_replay`,
   `get_episode_agent_logs`, `get_competition_leaderboard`, `download_competition_leaderboard`,
   `list_competition_topics`, `get_forum_topic`, `list_topic_messages`, `get_competition`,
   `list_competition_pages`, `download_competition_data_file`, `download_competition_data_files`.
3. CLI: token at `~/.kaggle/access_token` (outside this repo — see `SPEC.md` "Rule compliance" and
   `.gitignore`), `chmod 600`. Used for scripted/batch operations per `AGENTS.md`'s documented
   command set (`kaggle competitions submit|submissions|episodes|replay|logs|leaderboard`).

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
build_submission.py  ->  submit_to_competition (MCP) or `kaggle competitions submit` (CLI)
                      ->  poll get_competition_submission / `kaggle competitions submissions`
                      ->  once scored episodes exist: list_submission_episodes
                      ->  get_episode_replay + get_episode_agent_logs for any loss worth
                          understanding, saved to data/replays/ through
                          diskguard.ensure_budget() like any other replay pull
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
  Pulled via `download_competition_data_file`/CLI into `data/episodes/` (outside the repo), calling
  `diskguard.ensure_budget(need_bytes=<listed size>)` first — see `SPEC-diskguard.md` for the
  2.5 TB project-wide cap and its oldest-first eviction policy. Used for: (a) refreshing `tuning`'s
  opponent panel with genuinely current strong play rather than a frozen baseline, (b)
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
- A dry-run mode (`--no-submit`) that does everything except call `submit_to_competition`/`kaggle
  competitions submit`, for exercising the pipeline without spending a submission slot.

## Boundaries specific to this module

- *Ask first* (from `SPEC.md`, restated here since this is the module that actually executes it):
  every real submission, every download of the top-episodes dataset large enough to matter for
  disk space, every forum post.
- *Never*: let this module's automation call `submit_to_competition`/`kaggle competitions submit`
  without a human-approved step immediately before it — no cron job auto-submits.
- Competition Data pulled here goes to `data/`, never to `repo/` — this module is the primary place
  that boundary could be violated by a careless path, so `build_submission.py` and the download
  helpers hardcode `KAGG_DATA_DIR`-relative destinations rather than accepting an arbitrary
  `--out` path that could point inside the repo.
