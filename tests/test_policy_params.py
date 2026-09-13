"""Unit tests for kagg.policy.params - see SPEC-policy.md "Parameters"
and tasks/plan.md T3.4.

Loading is a construction-time concern, not a per-turn one, so it isn't
covered by agent()'s own try/except (SPEC-agent.md) - a broken params
file must not be able to crash agent construction itself, which is the
whole point of this module existing separately from a bare `json.load`.
"""

import json

from kagg.policy.params import DEFAULT_PARAMS, load_params


def test_missing_file_falls_back_to_defaults(tmp_path):
    assert load_params(str(tmp_path / "does_not_exist.json")) == DEFAULT_PARAMS


def test_malformed_json_falls_back_to_defaults(tmp_path):
    bad_file = tmp_path / "policy.json"
    bad_file.write_text("{not valid json")
    assert load_params(str(bad_file)) == DEFAULT_PARAMS


def test_non_dict_top_level_falls_back_to_defaults(tmp_path):
    array_file = tmp_path / "policy.json"
    array_file.write_text(json.dumps([1, 2, 3]))
    assert load_params(str(array_file)) == DEFAULT_PARAMS


def test_partial_file_merges_onto_defaults(tmp_path):
    partial_file = tmp_path / "policy.json"
    partial_file.write_text(json.dumps({"hires_per_day": 3}))
    result = load_params(str(partial_file))
    assert result["hires_per_day"] == 3
    # Everything else still comes from DEFAULT_PARAMS, unaffected.
    for key, value in DEFAULT_PARAMS.items():
        if key != "hires_per_day":
            assert result[key] == value


def test_load_params_never_mutates_default_params(tmp_path):
    partial_file = tmp_path / "policy.json"
    partial_file.write_text(json.dumps({"hires_per_day": 99}))
    load_params(str(partial_file))
    assert DEFAULT_PARAMS["hires_per_day"] == 1  # module-level default untouched (T8.7)


def test_the_real_shipped_file_loads_without_error():
    # No path argument - resolves against the actual params/policy.json
    # shipped alongside this module (src/kagg/params/policy.json),
    # exercising the real default-path resolution, not just synthetic
    # tmp_path files.
    result = load_params()
    assert isinstance(result, dict)
    for key in DEFAULT_PARAMS:
        assert key in result
