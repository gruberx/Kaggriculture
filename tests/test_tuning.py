"""Tests for tools/tuning.py's regression gate - see SPEC-tuning.md
"Held-out evaluation and the regression gate" and tasks/plan.md T7.1.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import diskguard  # noqa: E402
import harness  # noqa: E402
import tuning  # noqa: E402

_REAL_POLICY_JSON = os.path.join(
    os.path.dirname(__file__), "..", "src", "kagg", "params", "policy.json"
)


def _block(wins: int, n: int = 50) -> harness.BlockResult:
    return harness.BlockResult(
        n=n,
        wins_a=wins,
        wins_b=n - wins,
        ties=0,
        win_rate_a=wins / n,
        wilson_interval_a=harness.wilson_interval(wins, n),
        paired_results=(),
    )


def test_accept_candidate_rejects_a_worse_candidate():
    # SPEC-tuning.md's own Testing section, literally: "feed it a
    # synthetic 'worse' candidate and confirm it's rejected."
    baseline = _block(45)  # 0.90, interval (0.786, 0.957)
    candidate = _block(10)  # 0.20, interval (0.112, 0.330)
    assert tuning.accept_candidate(candidate, baseline) is False


def test_accept_candidate_accepts_a_clearly_better_candidate():
    # SPEC-tuning.md's own Testing section: "feed it a synthetic 'clearly
    # better' candidate (e.g. an opponent that always passes) and confirm
    # it's accepted."
    baseline = _block(10)  # 0.20, interval (0.112, 0.330)
    candidate = _block(48)  # 0.96, interval (0.865, 0.989) - no overlap
    assert tuning.accept_candidate(candidate, baseline) is True


def test_accept_candidate_rejects_a_numerically_higher_but_overlapping_candidate():
    # The precise requirement (SPEC-harness.md, restated in SPEC-tuning.md):
    # "the working block's number is not sufficient evidence" - a higher
    # point estimate alone isn't enough if the intervals still overlap.
    baseline = _block(25)  # 0.50, interval (0.366, 0.634)
    candidate = _block(27)  # 0.54, interval (0.404, 0.670) - overlaps baseline's
    assert tuning.accept_candidate(candidate, baseline) is False


def test_accept_candidate_rejects_a_tied_candidate():
    baseline = _block(25)
    candidate = _block(25)
    assert tuning.accept_candidate(candidate, baseline) is False


def test_wilson_intervals_overlap_detects_overlap():
    assert tuning.wilson_intervals_overlap((0.3, 0.6), (0.5, 0.8)) is True


def test_wilson_intervals_overlap_detects_no_overlap():
    assert tuning.wilson_intervals_overlap((0.1, 0.3), (0.6, 0.9)) is False


def test_wilson_intervals_overlap_treats_touching_endpoints_as_overlapping():
    assert tuning.wilson_intervals_overlap((0.1, 0.5), (0.5, 0.9)) is True


def test_record_accepted_run_logs_via_ensure_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("KAGG_PROJECT_ROOT", str(tmp_path))
    ensure_budget_calls = []
    real_ensure_budget = diskguard.ensure_budget

    def spying_ensure_budget(*a, **kw):
        ensure_budget_calls.append((a, kw))
        return real_ensure_budget(*a, **kw)

    monkeypatch.setattr(diskguard, "ensure_budget", spying_ensure_budget)

    baseline = _block(10)
    candidate = _block(48)
    tuning.record_accepted_run(
        opponent="starter",
        tuning_seeds=[100, 101],
        holdout_seeds=[900, 901],
        candidate_block=candidate,
        baseline_block=baseline,
        policy_git_commit="deadbeef",
    )

    assert len(ensure_budget_calls) == 1
    log_path = tmp_path / "data" / "arena" / "accepted_runs.jsonl"
    assert log_path.is_file()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["opponent"] == "starter"
    assert entry["tuning_seeds"] == [100, 101]
    assert entry["holdout_seeds"] == [900, 901]
    assert entry["policy_git_commit"] == "deadbeef"
    assert entry["candidate_win_rate"] == candidate.win_rate_a
    assert entry["baseline_win_rate"] == baseline.win_rate_a
    assert "timestamp" in entry


# --- coordinate_ascent (T7.2) --------------------------------------------

_TOY_N = 2_000_000  # large enough that the toy objective's grid points
# are cleanly Wilson-distinguishable even far from the optimum, e.g. at
# a large fixed offset in the untouched parameter (verified directly
# before writing this - at smaller n, adjacent grid points' intervals
# overlap and coordinate_ascent never moves) - this is a synthetic
# sample size for an instant-to-evaluate toy function, not a real
# episode count, so a large n costs nothing.


def _toy_block(win_rate: float, n: int = _TOY_N) -> harness.BlockResult:
    wins = round(win_rate * n)
    return harness.BlockResult(
        n=n,
        wins_a=wins,
        wins_b=n - wins,
        ties=0,
        win_rate_a=wins / n,
        wilson_interval_a=harness.wilson_interval(wins, n),
        paired_results=(),
    )


def _toy_evaluate(params: dict) -> harness.BlockResult:
    # A separable objective with a known, unique optimum at (x=3, y=7) -
    # 1.0 exactly there, strictly decreasing with distance elsewhere.
    x, y = params["x"], params["y"]
    win_rate = 1 / (1 + (x - 3) ** 2 + (y - 7) ** 2)
    return _toy_block(win_rate)


def test_coordinate_ascent_finds_the_known_optimum_of_a_toy_objective():
    # SPEC-tuning.md's own requirement: "tested on a toy 2-parameter
    # objective with a known optimum... before being trusted on the real
    # (expensive) arena."
    param_grid = {
        ("x",): [(1,), (2,), (3,), (4,), (5,)],
        ("y",): [(5,), (6,), (7,), (8,), (9,)],
    }
    result = tuning.coordinate_ascent(
        param_grid, _toy_evaluate, initial_params={"x": 1, "y": 5}
    )
    assert result == {"x": 3, "y": 7}


def test_coordinate_ascent_sweeps_a_correlated_group_jointly():
    # SPEC-tuning.md: "a small correlated group... should be swept
    # jointly rather than independently" - one grid entry keyed by a
    # tuple of parameter names, candidates as tuples of values.
    param_grid = {
        ("x", "y"): [(1, 5), (2, 6), (3, 7), (4, 8), (5, 9)],
    }
    result = tuning.coordinate_ascent(
        param_grid, _toy_evaluate, initial_params={"x": 1, "y": 5}
    )
    assert result == {"x": 3, "y": 7}


def test_coordinate_ascent_leaves_params_unchanged_when_already_optimal():
    param_grid = {("x",): [(1,), (2,), (3,), (4,), (5,)]}
    result = tuning.coordinate_ascent(
        param_grid, _toy_evaluate, initial_params={"x": 3, "y": 7}
    )
    assert result == {"x": 3, "y": 7}


def test_coordinate_ascent_never_regresses_a_parameter_not_in_the_grid():
    # Only x is swept - y (and its contribution to the score) must be
    # left exactly as given, never touched.
    param_grid = {("x",): [(1,), (2,), (3,), (4,), (5,)]}
    result = tuning.coordinate_ascent(
        param_grid, _toy_evaluate, initial_params={"x": 1, "y": 2}
    )
    assert result == {"x": 3, "y": 2}


# --- opponent panel (T7.3) ------------------------------------------------


def test_write_candidate_agent_produces_a_real_runnable_agent(tmp_path):
    from kagg.policy.params import DEFAULT_PARAMS

    candidate = dict(DEFAULT_PARAMS, hires_per_day=2)
    agent_path = tuning.write_candidate_agent(candidate, str(tmp_path))

    result = harness.run_paired(agent_path, "pass", seed=1, episode_steps=48)

    assert result.winner in ("a", "b", "tie")  # ran to completion without error


def test_write_candidate_agent_never_touches_the_checked_in_policy_json(tmp_path):
    from kagg.policy.params import DEFAULT_PARAMS

    before = os.stat(_REAL_POLICY_JSON)
    candidate_a = dict(DEFAULT_PARAMS, hires_per_day=3)
    candidate_b = dict(DEFAULT_PARAMS, hires_per_day=0)
    agent_a = tuning.write_candidate_agent(candidate_a, str(tmp_path))
    agent_b = tuning.write_candidate_agent(candidate_b, str(tmp_path))

    harness.run_paired(agent_a, agent_b, seed=1, episode_steps=48)

    after = os.stat(_REAL_POLICY_JSON)
    assert before.st_mtime == after.st_mtime
    assert before.st_size == after.st_size


def test_two_candidate_agents_genuinely_use_their_own_distinct_params(tmp_path):
    # The real hazard this design avoids (found while designing T7.3, not
    # anticipated in advance): kaggle_environments' loader execs each
    # agent's raw source into its own fresh globals dict (verified
    # directly in kaggle_environments/agent.py: exec(code_object, env),
    # never going through sys.modules) - safe on its own, but a wrapper
    # that did `import kagg.agent_main` instead of copying its source
    # would have its *inner* import cached process-wide, silently
    # reusing the first candidate's params for the second. This test
    # compares two candidates against *each other* within one
    # run_paired call (both seatings, same process) - exactly the
    # scenario where that hazard would surface if it existed.
    from kagg.policy.params import DEFAULT_PARAMS

    many_hires = tuning.write_candidate_agent(dict(DEFAULT_PARAMS, hires_per_day=3), str(tmp_path))
    no_hires = tuning.write_candidate_agent(dict(DEFAULT_PARAMS, hires_per_day=0), str(tmp_path))

    result = harness.run_paired(many_hires, no_hires, seed=1, episode_steps=240)

    assert result.a_total_money != result.b_total_money  # genuinely different behavior


def test_build_opponent_panel_includes_starter_and_random_by_default():
    panel = tuning.build_opponent_panel()
    assert panel == ["starter", "random"]


def test_build_opponent_panel_appends_a_previous_best_snapshot():
    from kagg.policy.params import DEFAULT_PARAMS

    panel = tuning.build_opponent_panel(previous_best_params=DEFAULT_PARAMS)
    assert panel == ["starter", "random", DEFAULT_PARAMS]


def test_resolve_opponent_passes_through_a_plain_string():
    assert tuning.resolve_opponent("starter", "/unused") == "starter"


def test_resolve_opponent_writes_a_params_dict_to_a_real_agent(tmp_path):
    from kagg.policy.params import DEFAULT_PARAMS

    resolved = tuning.resolve_opponent(DEFAULT_PARAMS, str(tmp_path))
    assert resolved != "starter"
    assert os.path.isfile(resolved)


# --- evaluate_against_panel (T7.4) ----------------------------------------


def test_evaluate_against_panel_aggregates_wins_across_every_opponent(monkeypatch, tmp_path):
    # SPEC-tuning.md: "the best Wilson-interval-adjusted win rate against
    # a fixed opponent panel" - one combined score, not a separate one
    # per opponent. Fast, monkeypatched arithmetic check (no real
    # episodes) - the real wiring is covered by the next test.
    calls = []

    def fake_run_block(agent_a, agent_b, seeds, jobs=None):
        calls.append((agent_a, agent_b))
        wins = {"starter": 3, "random": 4}[agent_b]
        return _block(wins, n=5)

    monkeypatch.setattr(harness, "run_block", fake_run_block)

    result = tuning.evaluate_against_panel(
        "agent_path", ["starter", "random"], seeds=[1, 2, 3, 4, 5], workdir=str(tmp_path)
    )

    assert [c[1] for c in calls] == ["starter", "random"]
    assert result.n == 10
    assert result.wins_a == 7
    assert result.win_rate_a == 0.7
    assert result.wilson_interval_a == harness.wilson_interval(7, 10)


def test_evaluate_against_panel_resolves_dict_opponents(monkeypatch, tmp_path):
    from kagg.policy.params import DEFAULT_PARAMS

    resolved_opponents = []

    def fake_run_block(agent_a, agent_b, seeds, jobs=None):
        resolved_opponents.append(agent_b)
        return _block(3, n=5)

    monkeypatch.setattr(harness, "run_block", fake_run_block)

    tuning.evaluate_against_panel(
        "agent_path", ["starter", DEFAULT_PARAMS], seeds=[1, 2, 3, 4, 5], workdir=str(tmp_path)
    )

    assert resolved_opponents[0] == "starter"
    assert resolved_opponents[1] != "starter"  # a real generated agent path
    assert os.path.isfile(resolved_opponents[1])


def test_evaluate_against_panel_real_end_to_end(tmp_path):
    result = tuning.evaluate_against_panel(
        tuning._AGENT_MAIN_PATH, ["pass", "pass"], seeds=[1], workdir=str(tmp_path)
    )
    assert result.n == 2  # 2 opponents x 1 seed each
