"""Unit tests for per-completion metadata (note / cost / photo / who).

Covers the pure layer: metadata normalization, recording metadata on a completion,
amending it after the fact (without disturbing the schedule), and the per-task
capture-mode fields (including the forward-compatible ``completion_required_fields``).
"""

from datetime import datetime, timedelta, timezone

import hk_const as const
import hk_events as events
import hk_models as m
import hk_recurrence as r
from asserts import raises_exactly

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)

# The keys an edit may carry. Driven off the const rather than a literal so this
# tier notices a new completion field instead of quietly ignoring it.
FIELDS = tuple(const.COMPLETION_ENTRY_FIELDS)


# ── metadata normalization ───────────────────────────────────────────────────


def test_normalize_metadata_keeps_only_nonempty_keys():
    out = m.normalize_completion_metadata(
        {"note": "  hinge fixed  ", "cost": "12.5", "photo": "", "who": "person.al"}
    )
    assert out == {"note": "hinge fixed", "cost": 12.5, "who": "person.al"}


def test_normalize_metadata_empty_inputs():
    assert m.normalize_completion_metadata(None) == {}
    assert m.normalize_completion_metadata({}) == {}
    assert m.normalize_completion_metadata({"note": "   ", "cost": ""}) == {}


def test_normalize_metadata_rejects_bad_cost():
    with raises_exactly(m.TaskValidationError, "cost must be a number"):
        m.normalize_completion_metadata({"cost": "free"})
    with raises_exactly(m.TaskValidationError, "cost must be >= 0"):
        m.normalize_completion_metadata({"cost": -1})


def test_normalize_metadata_accepts_safe_photo_urls():
    # http(s) and the site-relative shape ha-picture-upload produces are allowed.
    assert m.normalize_completion_metadata({"photo": "https://x/y.jpg"})["photo"] == (
        "https://x/y.jpg"
    )
    assert (
        m.normalize_completion_metadata({"photo": "/api/image/serve/abc/original"})[
            "photo"
        ]
        == "/api/image/serve/abc/original"
    )


def test_normalize_metadata_rejects_unsafe_photo_urls():
    # javascript:/data: URIs and protocol-relative URLs are stored-XSS vectors when
    # the panel renders `photo` into an href/img src.
    for bad in ("javascript:alert(1)", "data:text/html,<script>", "//evil.com/x"):
        with raises_exactly(
            m.TaskValidationError,
            "photo must be an http(s) URL or a site-relative path",
        ):
            m.normalize_completion_metadata({"photo": bad})


# ── recording metadata on a completion ───────────────────────────────────────


def _floating_task():
    return m.build_task(
        {
            "name": "Filter",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
        },
        now=NOW,
    )


def test_apply_completion_records_metadata():
    task = _floating_task()
    r.apply_completion(task, NOW, now=NOW, metadata={"note": "done", "cost": 9.0})
    entry = task["completions"][-1]
    assert entry["ts"] == NOW.isoformat()
    assert entry["note"] == "done"
    assert entry["cost"] == 9.0


def test_apply_completion_without_metadata_is_bare_timestamp():
    task = _floating_task()
    r.apply_completion(task, NOW, now=NOW)
    assert task["completions"][-1] == {"ts": NOW.isoformat()}


def test_completion_event_includes_metadata():
    task = _floating_task()
    data = events.completion_event_data(task, NOW, None, metadata={"who": "person.al"})
    assert data["who"] == "person.al"
    assert data["completed_at"] == NOW.isoformat()
    # A bare completion adds nothing beyond the spine.
    bare = events.completion_event_data(task, NOW, None)
    assert "who" not in bare


# ── amending a recorded completion ───────────────────────────────────────────


def test_update_completion_edits_in_place_without_touching_schedule():
    task = _floating_task()
    r.apply_completion(task, NOW, now=NOW, metadata={"note": "old"})
    due_before = task["next_due"]
    last_before = task["last_completed"]
    ts = task["completions"][-1]["ts"]

    updated, replaced = r.update_completion(
        task, ts, {"note": "new", "cost": 5.0}, fields=FIELDS
    )
    entry = updated["completions"][-1]
    assert entry["note"] == "new"
    assert entry["cost"] == 5.0
    assert replaced is None
    # Editing the log must not rewind or re-arm the task.
    assert updated["next_due"] == due_before
    assert updated["last_completed"] == last_before


def test_update_completion_blank_clears_key():
    task = _floating_task()
    r.apply_completion(task, NOW, now=NOW, metadata={"note": "x", "cost": 3.0})
    ts = task["completions"][-1]["ts"]
    r.update_completion(task, ts, {"note": "", "cost": 3.0}, fields=FIELDS)
    entry = task["completions"][-1]
    assert "note" not in entry
    assert entry["cost"] == 3.0


def test_update_completion_reports_replaced_photo():
    task = _floating_task()
    r.apply_completion(task, NOW, now=NOW, metadata={"photo": "img-1"})
    ts = task["completions"][-1]["ts"]
    _, replaced = r.update_completion(task, ts, {"photo": "img-2"}, fields=FIELDS)
    assert replaced == "img-1"
    assert task["completions"][-1]["photo"] == "img-2"


def test_update_completion_unknown_ts_raises():
    task = _floating_task()
    r.apply_completion(task, NOW, now=NOW)
    with raises_exactly(ValueError, "no completion at '2000-01-01T00:00:00+00:00'"):
        r.update_completion(task, "2000-01-01T00:00:00+00:00", {}, fields=FIELDS)


# ── per-task capture mode ────────────────────────────────────────────────────


def test_default_capture_mode_is_none():
    task = _floating_task()
    assert task["completion_detail"] == "none"
    assert task["completion_required_fields"] == []


def test_required_mode_defaults_required_fields_to_note():
    task = m.build_task(
        {
            "name": "Service",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "completion_detail": "required",
        },
        now=NOW,
    )
    assert task["completion_detail"] == "required"
    assert task["completion_required_fields"] == ["note"]


def test_required_fields_explicit_list_filtered_to_known():
    task = m.build_task(
        {
            "name": "Service",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "completion_detail": "required",
            "completion_required_fields": ["cost", "bogus", "who", "cost"],
        },
        now=NOW,
    )
    assert task["completion_required_fields"] == ["cost", "who"]


def test_optional_mode_clears_required_fields():
    task = m.build_task(
        {
            "name": "Service",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "completion_detail": "optional",
            "completion_required_fields": ["note"],
        },
        now=NOW,
    )
    assert task["completion_required_fields"] == []


def test_invalid_capture_mode_rejected():
    with raises_exactly(
        m.TaskValidationError, "invalid completion_detail: 'sometimes'"
    ):
        m.build_task(
            {
                "name": "x",
                "recurrence_type": "floating",
                "interval": 1,
                "unit": "months",
                "completion_detail": "sometimes",
            },
            now=NOW,
        )


def test_merge_update_preserves_capture_mode_on_unrelated_edit():
    task = m.build_task(
        {
            "name": "Service",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "completion_detail": "required",
        },
        now=NOW,
    )
    merged = m.merge_update(task, {"name": "Renamed"}, now=NOW)
    assert merged["completion_detail"] == "required"
    assert merged["completion_required_fields"] == ["note"]


def test_merge_update_can_change_capture_mode():
    task = m.build_task(
        {
            "name": "Service",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "completion_detail": "required",
        },
        now=NOW,
    )
    merged = m.merge_update(task, {"completion_detail": "none"}, now=NOW)
    assert merged["completion_detail"] == "none"
    assert merged["completion_required_fields"] == []


# ── the captured meter reading ───────────────────────────────────────────────
#
# ``reading`` is the bound sensor's value at completion time. It rides the same
# metadata plumbing as note/cost/photo/who but is *captured*, not asked for, so it
# sits in its own const list and is gated on the task actually having a sensor.


def test_reading_is_rejected_unless_the_task_has_a_numeric_binding():
    # Silently dropping it would let a caller believe a floating task's history
    # recorded a meter it has no sensor to read. Same discipline as _reject_fields.
    with raises_exactly(
        m.TaskValidationError,
        "reading is only valid for a sensor task with a numeric binding",
    ):
        m.normalize_completion_metadata({"reading": 45000})


def test_reading_is_kept_when_allowed():
    out = m.normalize_completion_metadata({"reading": "45000.5"}, allow_reading=True)
    assert out == {"reading": 45000.5}


def test_reading_allows_zero_and_negative_values():
    # A brand-new hour meter reads 0; a net-energy or temperature sensor goes below
    # it. Unlike ``cost`` there is deliberately no >= 0 floor — ``sensor.baseline``,
    # the number this has to stay comparable with, has none either.
    assert m.normalize_completion_metadata({"reading": 0}, allow_reading=True) == {
        "reading": 0.0
    }
    assert m.normalize_completion_metadata({"reading": -12.5}, allow_reading=True) == {
        "reading": -12.5
    }


def test_blank_reading_drops_the_key_rather_than_raising():
    # A blank form field is "no reading", not "a reading on a task that can't have
    # one" — so it must not trip the gate even when readings are disallowed.
    assert m.normalize_completion_metadata({"reading": "", "note": "x"}) == {
        "note": "x"
    }
    assert m.normalize_completion_metadata({"reading": None, "note": "x"}) == {
        "note": "x"
    }


def test_reading_rejects_non_numeric_and_infinite_values():
    # NaN would serialize to null on the JSON round-trip and compares False against
    # every baseline, so it has to fail at the edge rather than persist.
    with raises_exactly(m.TaskValidationError, "reading must be a number"):
        m.normalize_completion_metadata({"reading": "abc"}, allow_reading=True)
    for bad in (float("nan"), float("inf")):
        with raises_exactly(m.TaskValidationError, "reading must be a finite number"):
            m.normalize_completion_metadata({"reading": bad}, allow_reading=True)


def test_reading_is_not_requirable():
    # COMPLETION_METADATA_FIELDS doubles as the allowlist for a task's
    # ``completion_required_fields``. A captured field must stay out of it: the user
    # is never asked for a reading, and on a task with no sensor one can never
    # arrive at all — a required-but-unfillable field is an uncompletable task.
    assert "reading" not in const.COMPLETION_METADATA_FIELDS
    assert "reading" in const.COMPLETION_ENTRY_FIELDS
    assert m.normalize_completion_required_fields(["reading"], "required") == ["note"]
    assert m.normalize_completion_required_fields(["reading", "cost"], "required") == [
        "cost"
    ]


def test_a_zero_reading_survives_an_edit_rather_than_being_cleared():
    # ``update_completion`` clears a field whose new value is None/"". 0.0 is neither,
    # but it *is* falsy — one `if not value:` refactor away from silently wiping the
    # reading on a meter that legitimately sits at zero. Pin the behaviour.
    task = _sensor_task()
    r.apply_completion(task, NOW, now=NOW, metadata={"reading": 12.0})
    ts = task["completions"][0]["ts"]
    updated, _ = r.update_completion(task, ts, {"reading": 0.0}, fields=FIELDS)
    assert updated["completions"][0]["reading"] == 0.0


def test_editing_only_a_note_would_clear_an_unsent_reading():
    # The panel's edit dialog must therefore seed `reading` from the completion (see
    # _openCompletionEdit) — an omitted key clears it, which would destroy a captured
    # value the user never typed and doesn't know is there.
    task = _sensor_task()
    r.apply_completion(task, NOW, now=NOW, metadata={"reading": 780.0})
    ts = task["completions"][0]["ts"]
    updated, _ = r.update_completion(task, ts, {"note": "oil"}, fields=FIELDS)
    assert "reading" not in updated["completions"][0]
    # ...whereas sending it back through keeps it.
    again, _ = r.update_completion(
        task, ts, {"note": "oil", "reading": 780.0}, fields=FIELDS
    )
    assert again["completions"][0]["reading"] == 780.0


def test_task_records_reading_covers_the_numeric_modes_only():
    assert m.task_records_reading(_sensor_task()) is True
    assert m.task_records_reading(_sensor_task(mode="threshold")) is True
    # A ``state`` binding compares a string ("on", "docked") — no number to log.
    assert m.task_records_reading(_sensor_task(mode="state")) is False
    assert m.task_records_reading({"recurrence_type": "floating"}) is False
    # A sensor task with a malformed/absent binding can't be read either.
    assert m.task_records_reading({"recurrence_type": "sensor"}) is False
    assert m.task_records_reading({"recurrence_type": "sensor", "sensor": []}) is False
    assert m.task_records_reading(None) is False


def test_task_records_reading_defaults_a_missing_mode_to_usage():
    # ``normalize_sensor`` defaults ``mode`` to usage, so a binding that omits it is
    # a meter and does record a reading.
    assert (
        m.task_records_reading(
            {"recurrence_type": "sensor", "sensor": {"entity_id": "sensor.x"}}
        )
        is True
    )


def _sensor_task(mode: str = "usage") -> dict:
    sensor: dict = {"entity_id": "sensor.odometer", "mode": mode}
    if mode == "usage":
        sensor["target"] = 10000
    elif mode == "threshold":
        sensor.update({"comparison": ">=", "value": 90})
    else:
        sensor["state"] = "on"
    return {
        "recurrence_type": "sensor",
        "sensor": sensor,
        "next_due": None,
        "completions": [],
        "last_completed": None,
    }


def test_a_cost_of_zero_is_recorded_rather_than_rejected():
    # The gate is `< 0`, not `<= 0`: a free job (warranty, DIY) legitimately costs
    # nothing, and recording that is different from recording no cost at all.
    assert m.normalize_completion_metadata({"cost": 0}) == {"cost": 0.0}


def test_an_uppercase_url_scheme_is_still_a_valid_photo():
    # The scheme check runs against a lowercased copy, so "HTTP://..." must pass —
    # comparing the original would reject a perfectly good URL.
    assert m.normalize_completion_metadata({"photo": "HTTP://x/i.png"}) == {
        "photo": "HTTP://x/i.png"
    }
    assert m.normalize_completion_metadata({"photo": "HTTPS://x/i.png"}) == {
        "photo": "HTTPS://x/i.png"
    }


def test_a_non_mapping_input_yields_no_metadata():
    # Reached from the websocket/service edge, where the payload is caller-shaped.
    for junk in ([1], "note", 5, None, {}, []):
        assert m.normalize_completion_metadata(junk) == {}


# ── F10-1: editing an entry after the task stopped recording readings ────────
#
# A usage task logs completions with a reading, then becomes a floating task (or its
# sensor mode becomes state). The edit dialog sends the stored reading back with a
# changed note. That must save, and the stored reading must stay on the entry.

_READING_ERROR = "reading is only valid for a sensor task with a numeric binding"


def test_f10_1_an_unchanged_reading_is_accepted_and_kept():
    out = m.normalize_entry_edit_metadata(
        {"reading": 55, "note": "new note"}, allow_reading=False, stored_reading=55.0
    )
    assert out == {"reading": 55.0, "note": "new note"}


def test_f10_1_an_absent_reading_keeps_the_stored_one():
    out = m.normalize_entry_edit_metadata(
        {"note": "x"}, allow_reading=False, stored_reading=55.0
    )
    assert out == {"note": "x", "reading": 55.0}
    blank = m.normalize_entry_edit_metadata(
        {"reading": "", "note": "x"}, allow_reading=False, stored_reading=55.0
    )
    assert blank == {"note": "x", "reading": 55.0}


def test_f10_1_a_changed_reading_is_refused():
    with raises_exactly(m.TaskValidationError, _READING_ERROR):
        m.normalize_entry_edit_metadata(
            {"reading": 56}, allow_reading=False, stored_reading=55.0
        )


def test_f10_1_a_reading_on_an_entry_that_had_none_is_refused():
    with raises_exactly(m.TaskValidationError, _READING_ERROR):
        m.normalize_entry_edit_metadata(
            {"reading": 0}, allow_reading=False, stored_reading=None
        )


def test_f10_1_no_reading_stays_no_reading():
    assert m.normalize_entry_edit_metadata(
        {"note": "x"}, allow_reading=False, stored_reading=None
    ) == {"note": "x"}
    assert (
        m.normalize_entry_edit_metadata(None, allow_reading=False, stored_reading=None)
        == {}
    )


def test_f10_1_a_task_that_records_readings_edits_them_as_before():
    # The stored value does not matter here: the user can see and change the box.
    out = m.normalize_entry_edit_metadata(
        {"reading": "60", "note": "x"}, allow_reading=True, stored_reading=55.0
    )
    assert out == {"reading": 60.0, "note": "x"}
    cleared = m.normalize_entry_edit_metadata(
        {"note": "x"}, allow_reading=True, stored_reading=55.0
    )
    assert cleared == {"note": "x"}


def test_f10_1_the_other_fields_are_still_cleaned():
    with raises_exactly(m.TaskValidationError, "cost must be >= 0"):
        m.normalize_entry_edit_metadata(
            {"reading": 55, "cost": -1}, allow_reading=False, stored_reading=55.0
        )
