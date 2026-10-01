"""The pure half of ``ci/find_preset_candidates.py``: which integrations to look at."""

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "find_preset_candidates.py"
_spec = importlib.util.spec_from_file_location("find_preset_candidates", _SCRIPT)
assert _spec and _spec.loader
find = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(find)

STRINGS = {
    "purifier": {"entity": {"sensor": {"filter_life": {}, "pm25": {}}}},
    "weather": {"entity": {"sensor": {"temperature": {}}}},
    "zha": {"entity": {"sensor": {"filter_run_time": {}}}},
    "boiler": {
        "entity": {
            "sensor": {"service_due": {}},
            "binary_sensor": {"descaling_needed": {}},
        }
    },
}


def test_a_core_candidate_has_a_duty_key_and_no_catalog_entry():
    found = find.core_candidates(STRINGS, {"zha"}, {})
    assert found == {
        "boiler": ["binary_sensor.descaling_needed", "sensor.service_due"],
        "purifier": ["sensor.filter_life"],
    }


def test_a_reviewed_candidate_comes_back_only_with_a_new_duty_key():
    reviewed = {
        "core:purifier": {"keys": ["sensor.filter_life"], "reason": "x"},
        "core:boiler": {"keys": ["sensor.service_due"], "reason": "y"},
    }
    found = find.core_candidates(STRINGS, {"zha"}, reviewed)
    assert found == {"boiler": ["binary_sensor.descaling_needed"]}


def test_a_hacs_candidate_is_new_in_the_list_and_not_in_the_catalog():
    old = ["acme/old"]
    new = ["acme/old", "Acme/Purifier", "acme/known", "acme/skipped"]
    found = find.hacs_candidates(
        old, new, {"acme/known"}, {"hacs:acme/skipped": {"keys": [], "reason": "z"}}
    )
    assert found == ["Acme/Purifier"]


def test_the_catalog_gives_its_domains_and_source_repos():
    domains, repos = find.catalog_domains_and_repos(
        [
            {
                "domain": "dreo",
                "source": "https://raw.githubusercontent.com/JeffSteinbok/hass-dreo/"
                "main/custom_components/dreo/translations/en.json",
            }
        ]
    )
    assert domains == {"dreo"}
    assert repos == {"jeffsteinbok/hass-dreo"}


def test_the_state_file_round_trips_with_sorted_reviews(tmp_path):
    path = tmp_path / "state.json"
    assert find.load_state(path) == {"hacs_default_ref": None, "reviewed": {}}
    state = {"hacs_default_ref": "abc", "reviewed": {"core:b": {}, "core:a": {}}}
    find.save_state(state, path)
    assert list(json.loads(path.read_text())["reviewed"]) == ["core:a", "core:b"]
    assert find.load_state(path)["hacs_default_ref"] == "abc"


def test_the_shipped_state_file_is_valid():
    state = find.load_state()
    assert len(state["hacs_default_ref"]) == 40
    for ident, review in state["reviewed"].items():
        assert ident.startswith(("core:", "hacs:")), ident
        assert review["reason"], ident


def test_core_strings_are_read_from_a_sparse_clone(tmp_path):
    folder = tmp_path / "homeassistant" / "components" / "purifier"
    folder.mkdir(parents=True)
    (folder / "strings.json").write_text(json.dumps(STRINGS["purifier"]))
    bad = tmp_path / "homeassistant" / "components" / "broken"
    bad.mkdir()
    (bad / "strings.json").write_text("{not json")
    assert find.read_core(tmp_path) == {"purifier": STRINGS["purifier"]}


def test_hacs_names_compare_in_any_case():
    found = find.hacs_candidates(
        [],
        ["Acme/Known", "ACME/Skipped", "acme/new"],
        {"acme/KNOWN"},
        {"hacs:Acme/skipped": {"keys": [], "reason": "z"}},
    )
    assert found == ["acme/new"]
