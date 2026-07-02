"""Unit tests for per-completion metadata (note / cost / photo / who).

Covers the pure layer: metadata normalization, recording metadata on a completion,
amending it after the fact (without disturbing the schedule), and the per-task
capture-mode fields (including the forward-compatible ``completion_required_fields``).
"""

from datetime import datetime, timedelta, timezone

import hk_events as events
import hk_models as m
import hk_recurrence as r
import pytest

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)

FIELDS = ("note", "cost", "photo", "who")


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
    with pytest.raises(m.TaskValidationError):
        m.normalize_completion_metadata({"cost": "free"})
    with pytest.raises(m.TaskValidationError):
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
        with pytest.raises(m.TaskValidationError):
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
    with pytest.raises(ValueError):
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
    with pytest.raises(m.TaskValidationError):
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
