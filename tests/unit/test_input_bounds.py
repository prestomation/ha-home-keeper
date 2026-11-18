"""Upper limits on the numbers, texts and lists that a caller can store.

Each limit keeps the date math and the loops that read a stored value finite.
"""

from __future__ import annotations

import copy

import hk_const as const
import hk_models as models
import hk_notifications as notifications
import pytest

# ── snooze hours ─────────────────────────────────────────────────────────────


def test_the_longest_snooze_is_1_year():
    assert const.MAX_SNOOZE_HOURS == 8760


@pytest.mark.parametrize("hours", [1, 24, 8760, "8760"])
def test_a_task_snooze_length_up_to_the_limit_is_kept(hours):
    assert models.normalize_snooze_hours(hours) == int(hours)


@pytest.mark.parametrize("hours", [8761, 10**9, "100000000000"])
def test_a_task_snooze_length_over_the_limit_is_refused(hours):
    with pytest.raises(models.TaskValidationError, match="snooze_hours must be 8760"):
        models.normalize_snooze_hours(hours)


@pytest.mark.parametrize(("hours", "kept"), [(8760, 8760), (8761, 8760), (10**9, 8760)])
def test_a_notification_snooze_length_is_cut_to_the_limit(hours, kept):
    notification = notifications.normalize_notification(
        {"id": "n1", "name": "Walk", "snooze_hours": hours}
    )
    assert notification["snooze_hours"] == kept


# ── device and area links ───────────────────────────────────────────────────
NOW = __import__("datetime").datetime(
    2026, 5, 10, 12, tzinfo=__import__("datetime").UTC
)


@pytest.mark.parametrize("field", ["device_id", "area_id"])
@pytest.mark.parametrize("value", [["a"], {"id": "a"}, 7, True])
def test_a_link_id_that_is_not_text_is_refused(field, value):
    with pytest.raises(models.TaskValidationError, match=rf"^{field} must be text$"):
        models.build_task({"name": "x", field: value}, now=NOW)


@pytest.mark.parametrize("field", ["device_id", "area_id"])
def test_an_update_with_a_link_id_that_is_not_text_is_refused(field):
    task = models.build_task({"name": "x"}, now=NOW)
    with pytest.raises(models.TaskValidationError, match=rf"^{field} must be text$"):
        models.merge_update(task, {field: ["a"]}, now=NOW)


@pytest.mark.parametrize("field", ["device_id", "area_id"])
@pytest.mark.parametrize(
    ("value", "stored"), [("abc", "abc"), ("", None), (None, None)]
)
def test_a_text_or_empty_link_id_is_kept(field, value, stored):
    assert models.build_task({"name": "x", field: value}, now=NOW)[field] == stored


# ── season windows ───────────────────────────────────────────────────────────
def _windows(count: int) -> list[dict]:
    return [
        {"start": f"{(n % 12) + 1:02d}-01", "end": f"{(n % 12) + 1:02d}-10"}
        for n in range(count)
    ]


def test_a_season_holds_at_most_12_windows():
    assert const.MAX_SEASON_WINDOWS == 12
    assert len(models.normalize_active_season(_windows(12))) == 12


@pytest.mark.parametrize("count", [13, 10_000])
def test_a_season_with_more_windows_is_refused(count):
    with pytest.raises(
        models.TaskValidationError, match=r"^active_season holds at most 12 windows$"
    ):
        models.normalize_active_season(_windows(count))


# ── the rule probe ───────────────────────────────────────────────────────────
import hk_recurrence as recurrence  # noqa: E402


def _count_expansions(monkeypatch) -> list[str]:
    seen: list[str] = []
    real = recurrence._rrulestr

    def _counting(text, *, dtstart):
        seen.append(text)
        return real(text, dtstart=dtstart)

    monkeypatch.setattr(recurrence, "_rrulestr", _counting)
    recurrence._probe_rule.cache_clear()
    return seen


def test_a_rule_is_probed_once_for_each_text(monkeypatch):
    seen = _count_expansions(monkeypatch)
    for _ in range(3):
        assert (
            recurrence.normalize_rule("FREQ=WEEKLY;BYDAY=TU") == "FREQ=WEEKLY;BYDAY=TU"
        )
    assert len(seen) == 1


def test_a_rule_with_no_date_is_probed_once_and_still_refused(monkeypatch):
    seen = _count_expansions(monkeypatch)
    for _ in range(3):
        with pytest.raises(recurrence.RuleError) as err:
            recurrence.normalize_rule("FREQ=DAILY;BYMONTH=2;BYMONTHDAY=31")
        assert err.value.reason == "empty"
    assert len(seen) == 1


def test_a_rule_that_fails_to_expand_is_still_a_syntax_error(monkeypatch):
    _count_expansions(monkeypatch)

    def _broken(text, *, dtstart):
        raise ValueError("bad part")

    monkeypatch.setattr(recurrence, "_rrulestr", _broken)
    with pytest.raises(recurrence.RuleError) as err:
        recurrence.normalize_rule("FREQ=WEEKLY;BYDAY=WE")
    assert (err.value.reason, err.value.detail) == ("syntax", "bad part")


# ── text lengths ─────────────────────────────────────────────────────────────
LONG_URL = "https://example.com/" + "a" * 2029  # 2049 characters
LONG_ID = "sensor." + "a" * 249  # 256 characters


def test_the_text_limits_match_home_assistant_and_the_appliance_links():
    assert const.MAX_URL_LEN == 2048
    assert const.MAX_ENTITY_ID_LEN == 255
    assert len(LONG_URL) == 2049
    assert len(LONG_ID) == 256


def test_a_completion_photo_over_the_url_limit_is_refused():
    with pytest.raises(
        models.TaskValidationError, match=r"^photo must be at most 2048"
    ):
        models.normalize_completion_metadata({"photo": LONG_URL}, allow_reading=False)
    kept = models.normalize_completion_metadata(
        {"photo": LONG_URL[:-1]}, allow_reading=False
    )
    assert kept["photo"] == LONG_URL[:-1]


def test_a_completion_who_over_the_entity_id_limit_is_refused():
    with pytest.raises(models.TaskValidationError, match=r"^who must be at most 255"):
        models.normalize_completion_metadata({"who": LONG_ID}, allow_reading=False)
    kept = models.normalize_completion_metadata(
        {"who": LONG_ID[:-1]}, allow_reading=False
    )
    assert kept["who"] == LONG_ID[:-1]


def test_a_task_chip_url_over_the_url_limit_is_refused():
    chip = {"label": "Manual", "url": LONG_URL}
    with pytest.raises(
        models.TaskValidationError, match=r"^task_chips url must be at most 2048"
    ):
        models.build_task({"name": "x", "task_chips": [chip]}, now=NOW)
    ok = models.build_task(
        {"name": "x", "task_chips": [{**chip, "url": LONG_URL[:-1]}]}, now=NOW
    )
    assert ok["task_chips"][0]["url"] == LONG_URL[:-1]


@pytest.mark.parametrize("field", ["entity_id", "attribute"])
def test_a_sensor_entity_id_or_attribute_over_the_limit_is_refused(field):
    sensor = {
        "entity_id": "sensor.a",
        "mode": "threshold",
        "comparison": ">",
        "value": 1,
    }
    data = {"name": "x", "recurrence_type": "sensor"}
    with pytest.raises(
        models.TaskValidationError, match=rf"^sensor.{field} must be at most 255"
    ):
        models.build_task({**data, "sensor": {**sensor, field: LONG_ID}}, now=NOW)
    ok = models.build_task({**data, "sensor": {**sensor, field: LONG_ID[:-1]}}, now=NOW)
    assert ok["sensor"][field] == LONG_ID[:-1]


# ── declarative companion id lists ───────────────────────────────────────────
import hk_assets as assets  # noqa: E402
import hk_declarative_companions as dc  # noqa: E402
from test_declarative_companions import _spec  # noqa: E402


@pytest.mark.parametrize("field", ["device_ids", "exclude_entity_ids"])
def test_a_selection_id_list_holds_at_most_100_ids(field):
    selection = {**_spec()["selection"], field: [f"id{n}" for n in range(101)]}
    with pytest.raises(
        dc.DeclarativeCompanionValidationError,
        match=rf"^selection.{field} must have <= 100 entries$",
    ):
        dc.normalize_declarative_companion(_spec(selection=selection))
    selection[field] = selection[field][:100]
    spec = dc.normalize_declarative_companion(_spec(selection=selection))
    assert len(spec["selection"][field]) == 100


def test_a_selection_id_over_the_entity_id_limit_is_refused():
    selection = {**_spec()["selection"], "exclude_entity_ids": [LONG_ID]}
    with pytest.raises(
        dc.DeclarativeCompanionValidationError,
        match=r"^selection.exclude_entity_ids entries must be at most 255 characters$",
    ):
        dc.normalize_declarative_companion(_spec(selection=selection))


# ── ids that a caller sends for an appliance record ──────────────────────────
LONG_RECORD_ID = "a" * 101


def _asset(**over):
    return {"name": "Heater", **over}


@pytest.mark.parametrize(
    "data",
    [
        _asset(parts=[{"id": LONG_RECORD_ID, "name": "Filter"}]),
        _asset(
            metadata=[
                {"id": LONG_RECORD_ID, "type": "text", "label": "L", "value": "v"}
            ]
        ),
        _asset(
            documents=[
                {
                    "id": LONG_RECORD_ID,
                    "kind": "link",
                    "name": "Manual",
                    "url": "https://example.com/m.pdf",
                }
            ]
        ),
    ],
)
def test_an_appliance_record_id_over_100_characters_is_refused(data):
    data = copy.deepcopy(data)
    with pytest.raises(assets.AssetValidationError, match="id must be at most 100"):
        assets.build_asset(data, now=NOW)
    first_key = next(k for k in ("parts", "metadata", "documents") if k in data)
    data[first_key][0]["id"] = "a" * 100
    built = assets.build_asset(data, now=NOW)
    assert built[first_key][0]["id"] == "a" * 100


# ── option lists and spec timestamps ─────────────────────────────────────────
import hk_options as options  # noqa: E402


@pytest.mark.parametrize(
    ("key", "limit"),
    [("hidden_panel_tabs", 20), ("dismissed_companions", 50)],
)
def test_an_option_list_is_cut_to_its_limit(key, limit):
    assert options.coerce_value(key, [f"x{n}" for n in range(limit + 5)]) == [
        f"x{n}" for n in range(limit)
    ]


def test_a_spec_timestamp_that_is_not_a_time_is_left_out():
    spec = dc.normalize_declarative_companion(
        _spec(created="x" * 10_000, updated="2026-05-10T12:00:00+00:00")
    )
    assert "created" not in spec
    assert spec["updated"] == "2026-05-10T12:00:00+00:00"
    with pytest.raises(
        dc.DeclarativeCompanionValidationError,
        match=r"^created must be an ISO timestamp string$",
    ):
        dc.normalize_declarative_companion(_spec(created=5))
