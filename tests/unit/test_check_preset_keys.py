"""The pure half of ``ci/check_preset_keys.py``: which keys are missing upstream."""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "check_preset_keys.py"
_spec = importlib.util.spec_from_file_location("check_preset_keys", _SCRIPT)
assert _spec and _spec.loader
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

ENTRY = {
    "domain": "demo",
    "duties": [
        {"keys": ["filter_time_left", "brush_time_left"]},
        {"platform": "binary_sensor", "keys": ["salt_low"]},
    ],
}


def test_no_key_is_missing_when_the_translations_name_them_all():
    translations = {
        "entity": {
            "sensor": {"filter_time_left": {}, "brush_time_left": {}},
            "binary_sensor": {"salt_low": {}},
        }
    }
    assert check.missing_keys(ENTRY, translations) == []


def test_a_key_is_missing_when_its_platform_does_not_name_it():
    translations = {
        "entity": {
            # The binary sensor key under the wrong platform does not count.
            "sensor": {"filter_time_left": {}, "salt_low": {}},
        }
    }
    assert check.missing_keys(ENTRY, translations) == [
        ("sensor", "brush_time_left"),
        ("binary_sensor", "salt_low"),
    ]


def test_every_key_is_missing_from_a_file_with_no_entity_section():
    assert len(check.missing_keys(ENTRY, {"config": {}})) == 3


def test_the_script_reads_the_shipped_catalog():
    assert len(check._integrations()) > 50


# --- The key diff since the pinned commit --------------------------------------

SOURCE = (
    "https://raw.githubusercontent.com/acme/vacuum/main/"
    "custom_components/vacuum/translations/en.json"
)
OLD = {"entity": {"sensor": {"filter_time_left": {}, "brush_time_left": {}}}}
NEW = {
    "entity": {
        "sensor": {"filter_time_left": {}, "mop_life": {}, "battery": {}},
        "binary_sensor": {"salt_low": {}, "docked": {}},
        "number": "not a table",
    }
}


def _entry(**extra):
    return {**ENTRY, "source": SOURCE, **extra}


def _fake_fetch(files):
    def fetch(url):
        return files.get(url)

    return fetch


def test_a_raw_url_splits_into_owner_repo_branch_and_path():
    assert check.parse_source(SOURCE) == {
        "owner": "acme",
        "repo": "vacuum",
        "branch": "main",
        "path": "custom_components/vacuum/translations/en.json",
    }
    assert check.parse_source("https://example.com/en.json") is None
    assert check.raw_url(check.parse_source(SOURCE), "abc123") == (
        "https://raw.githubusercontent.com/acme/vacuum/abc123/"
        "custom_components/vacuum/translations/en.json"
    )


def test_every_catalog_source_is_a_raw_url_with_a_pinned_commit():
    for entry in check._integrations():
        assert check.parse_source(entry["source"]), entry["domain"]
        verified = entry["verified"]
        assert len(verified["ref"]) == 40, entry["domain"]
        assert int(verified["ref"], 16) >= 0, entry["domain"]
        assert len(verified["date"]) == 10, entry["domain"]


def test_the_key_diff_lists_added_and_removed_keys_by_platform():
    added, removed = check.key_diff(check.entity_keys(OLD), check.entity_keys(NEW))
    assert added == {
        "binary_sensor": ["docked", "salt_low"],
        "sensor": ["battery", "mop_life"],
    }
    assert removed == {"sensor": ["brush_time_left"]}
    # A platform entry that is not a table is not a list of keys.
    assert "number" not in check.entity_keys(NEW)


def test_the_hints_are_the_added_keys_that_name_a_duty_word():
    assert check.duty_hints(
        {"sensor": ["battery", "mop_life"], "binary_sensor": ["Salt_Low"]}
    ) == ["sensor.mop_life", "binary_sensor.Salt_Low"]


def test_a_record_compares_the_head_with_the_pinned_commit():
    entry = _entry(verified={"ref": "old", "date": "2026-01-01"})
    fetch = _fake_fetch(
        {
            SOURCE.replace("/main/", "/head/"): NEW,
            SOURCE.replace("/main/", "/old/"): OLD,
        }
    )
    record = check.check_entry(entry, fetch, "head")
    assert record["pinned_ref"] == "old"
    assert record["head_ref"] == "head"
    assert record["missing"] == ["sensor.brush_time_left"]
    assert record["added"]["sensor"] == ["battery", "mop_life"]
    assert record["removed"] == {"sensor": ["brush_time_left"]}
    assert record["hints"] == ["binary_sensor.salt_low", "sensor.mop_life"]
    assert record["fetch_error"] is None


def test_a_record_with_no_pin_or_a_current_pin_has_no_diff():
    fetch = _fake_fetch({SOURCE.replace("/main/", "/head/"): NEW})
    for verified in (None, {"ref": "head", "date": "2026-01-01"}):
        record = check.check_entry(_entry(verified=verified), fetch, "head")
        assert record["added"] == {} and record["hints"] == []
        assert record["fetch_error"] is None


def test_a_record_says_what_it_cannot_read():
    entry = _entry(verified={"ref": "old", "date": "2026-01-01"})
    assert (
        "branch main not found"
        in check.check_entry(entry, _fake_fetch({}), "")["fetch_error"]
    )
    assert (
        "ls-remote failed"
        in check.check_entry(entry, _fake_fetch({}), None)["fetch_error"]
    )
    assert (
        "branch head"
        in check.check_entry(entry, _fake_fetch({}), "head")["fetch_error"]
    )
    head_only = _fake_fetch({SOURCE.replace("/main/", "/head/"): NEW})
    # A pinned commit that is gone gives no diff, but the head is still checked, so
    # the entry is not a break and can be pinned again.
    gone = check.check_entry(entry, head_only, "head")
    assert gone["fetch_error"] is None
    assert "commit old" in gone["pin_error"]
    assert gone["missing"] == ["sensor.brush_time_left"]
    assert gone["added"] == {}
    bad = {**entry, "source": "https://example.com/en.json"}
    assert (
        "not a raw GitHub URL"
        in check.check_entry(bad, head_only, "head")["fetch_error"]
    )


def test_one_ls_remote_serves_every_entry_on_the_same_branch():
    calls = []

    def head_ref(owner, repo, branch):
        calls.append((owner, repo, branch))
        return f"{repo}-{branch}"

    entries = [
        {"domain": "a", "source": SOURCE},
        {"domain": "b", "source": SOURCE.replace("vacuum/translations", "b/x")},
        {"domain": "c", "source": SOURCE.replace("/main/", "/dev/")},
        {"domain": "d", "source": "https://example.com/en.json"},
    ]
    assert check.head_refs(entries, head_ref) == {
        "a": "vacuum-main",
        "b": "vacuum-main",
        "c": "vacuum-dev",
    }
    assert sorted(calls) == [("acme", "vacuum", "dev"), ("acme", "vacuum", "main")]


CATALOG_TEXT = """INTEGRATIONS = [
    {
        "domain": "first",
        "brand": "First",
        "source": "https://raw.githubusercontent.com/a/b/main/en.json",
        "duties": [],
    },
    {
        "domain": "second",
        "source": "https://raw.githubusercontent.com/a/c/main/en.json",
        "verified": {
            "ref": "old",
            "date": "2026-01-01",
        },
        "duties": [],
    },
]
"""


def test_a_pin_is_added_after_the_source_line():
    text = check.pin_text(CATALOG_TEXT, "first", "abc", "2026-10-01")
    assert (
        '        "source": "https://raw.githubusercontent.com/a/b/main/en.json",\n'
        '        "verified": {\n'
        '            "ref": "abc",\n'
        '            "date": "2026-10-01",\n'
        "        },\n"
        '        "duties": [],\n'
    ) in text
    # The other entry is left alone.
    assert '"ref": "old"' in text


def test_a_pin_replaces_an_older_one_and_touches_no_other_entry():
    text = check.pin_text(CATALOG_TEXT, "second", "new", "2026-10-01")
    assert '"ref": "old"' not in text
    assert text.count('"verified"') == 1
    assert '"ref": "new"' in text
    # Pinning again is stable.
    assert check.pin_text(text, "second", "new", "2026-10-01") == text


def test_a_pin_for_an_unknown_domain_is_refused():
    try:
        check.pin_text(CATALOG_TEXT, "third", "x", "2026-10-01")
    except ValueError as err:
        assert "third" in str(err)
    else:
        raise AssertionError("an unknown domain must not be pinned")


def test_a_duty_word_matches_the_start_of_a_part_of_the_key():
    assert check.has_duty_word("descaling_needed")
    assert check.has_duty_word("filter_time_left")
    assert check.has_duty_word("cleaning_brush_time_left")
    assert check.has_duty_word("Toner_Black")
    # Inside a part is not a match: "ink" is not "link", "left" alone is a side.
    assert not check.has_duty_word("link_speed")
    assert not check.has_duty_word("sprinkler_mode")
    assert not check.has_duty_word("door_front_left")
    assert not check.has_duty_word("battery")


def test_pinning_a_new_entry_twice_leaves_one_block():
    once = check.pin_text(CATALOG_TEXT, "first", "abc", "2026-10-01")
    twice = check.pin_text(once, "first", "def", "2026-10-02")
    assert twice.count('"verified"') == 2  # first and second, one each
    assert '"ref": "abc"' not in twice
    assert '"ref": "def"' in twice and '"ref": "old"' in twice
