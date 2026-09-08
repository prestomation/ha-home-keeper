"""The import/export document's behaviour: the primary-key ladder, and what it refuses.

The round-trip test proves a record survives the journey. This one covers the
decisions made along the way — which stored record an incoming one *is*, what happens
when that is ambiguous, and the things the document deliberately will not carry.
"""

from datetime import datetime, timedelta, timezone

import hk_transfer as tr
import pytest

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def _doc(**sections) -> dict:
    return {"home_keeper": {"format": 1}, **sections}


def _task(**kw) -> dict:
    return tr.models.build_task({"name": "Furnace filter", **kw}, now=NOW)


def _plan(document, *, tasks=None, assets=None, **kw):
    return tr.plan_import(
        document, tasks=tasks or {}, assets=assets or {}, now=NOW, **kw
    )


def _errors(plan) -> list[str]:
    return [p.message for p in plan.problems if p.severity == "error"]


def _warnings(plan) -> list[str]:
    return [p.message for p in plan.problems if p.severity == "warning"]


# ── The primary-key ladder ───────────────────────────────────────────────────


def test_a_record_matches_on_its_home_keeper_id_first():
    stored = _task(external_id="other", name="Something else")
    plan = _plan(
        _doc(tasks=[{"id": stored["id"], "name": "Renamed"}]),
        tasks={stored["id"]: stored},
    )
    (record,) = plan.records
    assert (record.action, record.matched_by) == ("update", "id")
    assert record.record_id == stored["id"]


def test_a_record_matches_on_its_external_id_when_it_has_no_home_keeper_id():
    stored = _task(external_id="furnace-filter", name="Something else entirely")
    plan = _plan(
        _doc(tasks=[{"external_id": "furnace-filter", "name": "Replace filter"}]),
        tasks={stored["id"]: stored},
    )
    (record,) = plan.records
    assert (record.action, record.matched_by) == ("update", "external_id")
    assert record.record_id == stored["id"]


def test_a_record_matches_on_its_name_last():
    stored = _task()
    plan = _plan(
        _doc(tasks=[{"name": "Furnace filter", "notes": "MERV 13"}]),
        tasks={stored["id"]: stored},
    )
    (record,) = plan.records
    assert (record.action, record.matched_by) == ("update", "name")


def test_a_name_match_tolerates_case_and_whitespace():
    stored = _task()
    plan = _plan(
        _doc(tasks=[{"name": "  furnace FILTER  "}]), tasks={stored["id"]: stored}
    )
    assert plan.records[0].matched_by == "name"


def test_an_id_that_names_nothing_creates_rather_than_falling_through_to_the_name():
    # The steps are independent on purpose. Falling through would let a stale id from
    # another install silently overwrite a same-named task that has nothing to do
    # with it — the one outcome a migration must never produce.
    stored = _task()
    plan = _plan(
        _doc(
            tasks=[
                {"id": "11111111-2222-3333-4444-555555555555", "name": "Furnace filter"}
            ]
        ),
        tasks={stored["id"]: stored},
    )
    (record,) = plan.records
    assert (record.action, record.matched_by) == ("create", None)
    # A free, well-formed id is kept, so a restore preserves entity unique_ids.
    assert record.record_id == "11111111-2222-3333-4444-555555555555"


def test_an_empty_external_id_never_matches_another_keyless_record():
    stored = _task()  # external_id == ""
    plan = _plan(_doc(tasks=[{"name": "Water filter"}]), tasks={stored["id"]: stored})
    assert plan.records[0].action == "create"


def test_a_name_matching_two_stored_tasks_is_an_error_not_a_guess():
    one, two = _task(), _task()
    plan = _plan(
        _doc(tasks=[{"name": "Furnace filter"}]),
        tasks={one["id"]: one, two["id"]: two},
    )
    assert not plan.ok
    assert not plan.records
    assert "matches several tasks" in _errors(plan)[0]


def test_match_none_creates_everything():
    stored = _task()
    plan = _plan(
        _doc(tasks=[{"name": "Furnace filter"}]),
        tasks={stored["id"]: stored},
        match="none",
    )
    assert [r.action for r in plan.records] == ["create"]


def test_two_document_records_cannot_upsert_onto_the_same_stored_one():
    stored = _task()
    plan = _plan(
        _doc(tasks=[{"name": "Furnace filter"}, {"name": "Furnace filter"}]),
        tasks={stored["id"]: stored},
    )
    actions = [r.action for r in plan.records]
    assert actions == ["update", "create"]
    assert plan.records[1].record_id != stored["id"]


# ── History ──────────────────────────────────────────────────────────────────


def test_history_is_replayed_in_date_order_whatever_order_it_is_written_in():
    # apply_completion stamps last_completed from whichever entry it is handed, so
    # replaying the oldest last would leave the task claiming it was done in 2019.
    plan = _plan(
        _doc(
            tasks=[
                {
                    "name": "Furnace filter",
                    "interval": 3,
                    "unit": "months",
                    "history": [
                        {"completed_at": "2019-01-05"},
                        {"completed_at": "2026-03-04"},
                        {"completed_at": "2022-06-01"},
                    ],
                }
            ]
        )
    )
    task = plan.records[0].payload
    assert [e["ts"][:10] for e in task["completions"]] == [
        "2019-01-05",
        "2022-06-01",
        "2026-03-04",
    ]
    assert task["last_completed"].startswith("2026-03-04")
    assert plan.completions == 3


def test_a_bare_date_is_qualified_with_the_callers_zone():
    # One naive datetime in the history poisons every later comparison in the store.
    plan = _plan(
        _doc(tasks=[{"name": "T", "history": [{"completed_at": "2026-03-04"}]}])
    )
    ts = plan.records[0].payload["completions"][0]["ts"]
    assert datetime.fromisoformat(ts).tzinfo is not None


def test_history_carries_its_metadata():
    plan = _plan(
        _doc(
            tasks=[
                {
                    "name": "T",
                    "history": [
                        {
                            "completed_at": "2026-03-04",
                            "note": "Used a MERV 13",
                            "cost": 24.5,
                            "who": "person.chris",
                        }
                    ],
                }
            ]
        )
    )
    entry = plan.records[0].payload["completions"][0]
    assert entry["note"] == "Used a MERV 13"
    assert entry["cost"] == 24.5
    assert entry["who"] == "person.chris"


def test_over_the_cap_the_newest_history_is_what_survives():
    # The history cap keeps the tail of the list, so replaying out of order would
    # keep the oldest entries and throw away everything recent.
    history = [{"completed_at": f"{year}-01-05"} for year in range(1200, 1200 + 600)]
    plan = _plan(
        _doc(tasks=[{"name": "T", "interval": 1, "unit": "days", "history": history}])
    )
    kept = plan.records[0].payload["completions"]
    assert len(kept) == 500
    assert kept[-1]["ts"].startswith("1799-01-05")


def test_a_backdated_skip_is_logged_without_inventing_a_due_date():
    plan = _plan(
        _doc(
            tasks=[
                {
                    "name": "T",
                    "interval": 3,
                    "unit": "months",
                    "history": [{"completed_at": "2026-03-04"}],
                    "skips": [{"skipped_at": "2025-09-01", "note": "Away"}],
                }
            ]
        )
    )
    task = plan.records[0].payload
    assert [e["ts"][:10] for e in task["skips"]] == ["2025-09-01"]
    assert task["skips"][0]["note"] == "Away"
    # The completion after it is what set the due date, not the skip.
    assert task["next_due"].startswith("2026-06-04")
    assert plan.skips == 1


def test_an_unparseable_date_is_reported_against_its_own_entry():
    plan = _plan(
        _doc(tasks=[{"name": "T", "history": [{"completed_at": "last spring"}]}])
    )
    assert not plan.ok
    problem = plan.problems[0]
    assert problem.path == "tasks[0].history[0].completed_at"
    assert "is not a date" in problem.message


# ── What the document will not carry ─────────────────────────────────────────


def test_a_reconciler_owned_task_is_refused_on_the_way_in():
    plan = _plan(
        _doc(
            tasks=[
                {
                    "name": "Filter",
                    "source": {"part": {"asset_id": "a", "part_id": "p"}},
                }
            ]
        )
    )
    assert not plan.ok
    assert "reconcilers own" in _errors(plan)[0]


def test_a_managed_task_is_refused_on_the_way_in():
    plan = _plan(
        _doc(
            tasks=[
                {"name": "Walk the dog", "managed_by": {"integration": "pawsistant"}}
            ]
        )
    )
    assert not plan.ok
    assert "another integration as its owner" in _errors(plan)[0]


@pytest.mark.parametrize(
    "source",
    [
        {"part": {"asset_id": "a", "part_id": "p"}},
        {"buy": {"asset_id": "a", "part_id": "p"}},
        {"problem_sensor": {"entity_id": "binary_sensor.x"}},
        {"declarative_companion": {"spec_id": "s"}},
    ],
)
def test_a_reconciler_owned_task_is_left_out_of_the_export(source):
    task = _task()
    task["source"] = source
    document = tr.build_document([task], [], now=NOW)
    assert document["tasks"] == []


def test_a_managed_task_is_left_out_of_the_export():
    task = _task()
    task["managed_by"] = {"integration": "pawsistant"}
    assert tr.build_document([task], [], now=NOW)["tasks"] == []


def test_an_uploaded_file_is_counted_rather_than_passed_over_in_silence():
    asset = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    asset["documents"] = [
        {"id": "d1", "kind": "link", "name": "Manual", "url": "https://example.com/m"},
        {
            "id": "d2",
            "kind": "file",
            "name": "Receipt",
            "filename": "r.pdf",
            "content_type": "application/pdf",
            "size": 10,
        },
    ]
    document = tr.build_document([], [asset], now=NOW)
    assert document["home_keeper"]["skipped"] == {"file_documents": 1}
    assert [d["kind"] for d in document["appliances"][0]["documents"]] == ["link"]


# ── Forward and backward compatibility ───────────────────────────────────────


def test_an_unknown_field_is_a_named_warning_not_a_failure():
    # An older Home Keeper must be able to read a newer document — but silently
    # discarding what the author wrote is how a migration loses data unnoticed.
    plan = _plan(_doc(tasks=[{"name": "T", "priority": "high"}]))
    assert plan.ok
    assert plan.records[0].action == "create"
    assert '"priority" is not a field' in _warnings(plan)[0]


def test_an_unknown_section_is_a_named_warning_not_a_failure():
    plan = _plan(_doc(tasks=[], recipes=[{"name": "x"}]))
    assert plan.ok
    assert '"recipes" is not a section' in _warnings(plan)[0]


def test_a_newer_format_is_refused_with_a_version_to_act_on():
    plan = _plan({"home_keeper": {"format": 99}, "tasks": [{"name": "T"}]})
    assert not plan.ok
    assert "Update Home Keeper" in _errors(plan)[0]


def test_a_document_with_no_envelope_is_refused():
    assert not _plan({"tasks": [{"name": "T"}]}).ok


def test_a_document_that_is_not_a_mapping_is_refused():
    assert not _plan([{"name": "T"}]).ok


# ── Guard rails ──────────────────────────────────────────────────────────────


def test_a_section_over_the_record_cap_is_refused_whole():
    plan = _plan(_doc(tasks=[{"name": f"T{i}"} for i in range(2001)]))
    assert not plan.ok
    assert not plan.records
    assert "Split the document" in _errors(plan)[0]


def test_an_invalid_record_blocks_the_whole_import():
    # All-or-nothing validation is what makes a plain (non-dry-run) import safe to
    # hand a generated file: a document that is wrong anywhere writes nothing.
    plan = _plan(_doc(tasks=[{"name": "Good"}, {"name": "", "interval": 1}]))
    assert not plan.ok
    assert len(plan.records) == 1  # planned, but the caller must not apply it


def test_an_unknown_match_mode_is_refused():
    assert not _plan(_doc(tasks=[]), match="sideways").ok


def test_planning_never_mutates_the_stored_records():
    stored = _task()
    before = dict(stored)
    _plan(
        _doc(
            tasks=[
                {
                    "name": "Furnace filter",
                    "notes": "changed",
                    "history": [{"completed_at": "2026-01-01"}],
                }
            ]
        ),
        tasks={stored["id"]: stored},
    )
    assert stored == before


# ── Appliance references ─────────────────────────────────────────────────────


def test_an_appliance_in_the_document_wins_over_a_same_named_stored_one():
    # A file describing an appliance and its tasks together must wire them to each
    # other, not to whatever already answers to that name.
    existing = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    existing["device_id"] = "dev_old"
    plan = _plan(
        _doc(
            appliances=[{"external_id": "new-furnace", "name": "Furnace"}],
            tasks=[{"name": "Filter", "appliance": "new-furnace"}],
        ),
        assets={existing["id"]: existing},
    )
    task = next(r for r in plan.records if r.section == "tasks")
    appliance = next(r for r in plan.records if r.section == "appliances")
    assert tr.planned_asset_id(task.payload["device_id"]) == appliance.record_id


def test_a_task_naming_an_appliance_nobody_has_is_refused():
    plan = _plan(_doc(tasks=[{"name": "Filter", "appliance": "Boiler"}]))
    assert not plan.ok
    assert "has nothing to attach to" in _errors(plan)[0]


def test_a_stored_appliance_can_be_named_by_external_id():
    stored = tr.assets_model.build_asset(
        {"name": "Furnace", "external_id": "centriq-4711"}, now=NOW
    )
    stored["device_id"] = "dev_furnace"
    plan = _plan(
        _doc(tasks=[{"name": "Filter", "appliance": "centriq-4711"}]),
        assets={stored["id"]: stored},
    )
    assert plan.records[0].payload["device_id"] == "dev_furnace"


def test_a_device_id_from_another_install_falls_back_to_the_appliance():
    stored = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    stored["device_id"] = "dev_here"
    plan = _plan(
        _doc(
            tasks=[
                {"name": "Filter", "device_id": "dev_elsewhere", "appliance": "Furnace"}
            ]
        ),
        assets={stored["id"]: stored},
        device_ids=frozenset({"dev_here"}),
    )
    assert plan.records[0].payload["device_id"] == "dev_here"


def test_a_device_id_from_another_install_with_no_appliance_imports_standalone():
    plan = _plan(
        _doc(tasks=[{"name": "Filter", "device_id": "dev_elsewhere"}]),
        device_ids=frozenset({"dev_here"}),
    )
    assert plan.ok
    assert plan.records[0].payload["device_id"] is None
    assert "was imported without an appliance" in _warnings(plan)[0]


# ── Export shape ─────────────────────────────────────────────────────────────


def test_the_export_states_its_format_so_a_reader_knows_what_it_is_holding():
    document = tr.build_document([], [], version="0.22.0b5", now=NOW)
    assert document["home_keeper"]["format"] == tr.TRANSFER_FORMAT
    assert document["home_keeper"]["version"] == "0.22.0b5"
    assert document["home_keeper"]["exported_at"] == NOW.isoformat()


def test_include_narrows_the_export_to_the_sections_asked_for():
    task, asset = _task(), tr.assets_model.build_asset({"name": "F"}, now=NOW)
    document = tr.build_document([task], [asset], now=NOW, include=["tasks"])
    assert "tasks" in document
    assert "appliances" not in document


def test_the_export_omits_empty_values_so_the_file_stays_readable():
    document = tr.build_document([_task()], [], now=NOW)
    record = document["tasks"][0]
    assert "notes" not in record  # "" — set on every task, meaningful on few
    assert "labels" not in record
    assert record["name"] == "Furnace filter"


def test_the_json_form_is_something_a_person_can_read():
    text = tr.document_to_json(tr.build_document([_task()], [], now=NOW))
    assert text.startswith("{\n")
    assert text.endswith("\n")
    assert '"name": "Furnace filter"' in text


# ── Every planned payload is a whole record ──────────────────────────────────


@pytest.mark.parametrize("section", ["tasks", "appliances"])
def test_a_planned_payload_is_always_a_complete_record(section):
    """The applier writes a payload into the store verbatim, so a fragment corrupts it.

    An update is built by merging, and it is the *merged record* that must be planned
    — never the updates that produced it. Handing the applier a bare updates mapping
    replaced a whole appliance with a fragment that had no ``id``, and the next device
    reconcile tripped over it (``KeyError: 'id'``). Nothing in the plan's own shape
    said that was wrong, so this asks the question directly, for both sections and for
    both actions.
    """
    stored_task = _task(external_id="k")
    stored_asset = tr.assets_model.build_asset(
        {"name": "Furnace", "external_id": "k"}, now=NOW
    )
    document = _doc(
        tasks=[
            {"external_id": "k", "name": "Updated task"},
            {"external_id": "fresh-task", "name": "New task"},
        ],
        appliances=[
            {"external_id": "k", "name": "Updated appliance"},
            {"external_id": "fresh-appliance", "name": "New appliance"},
        ],
    )
    plan = _plan(
        document,
        tasks={stored_task["id"]: stored_task},
        assets={stored_asset["id"]: stored_asset},
    )
    assert plan.ok, _errors(plan)
    planned = plan.for_section(section)
    assert {r.action for r in planned} == {"create", "update"}
    for record in planned:
        # The id the store will file it under has to be *in* the record, or the
        # record and its key disagree the moment anything reads the store back.
        assert record.payload.get("id") == record.record_id, record.action
        assert record.payload.get("name"), record.action
        assert "created" in record.payload, record.action


def test_an_appliance_update_keeps_the_fields_the_document_left_out():
    stored = tr.assets_model.build_asset(
        {
            "name": "Furnace",
            "external_id": "furnace",
            "manufacturer": "Carrier",
            "serial_number": "1234",
        },
        now=NOW,
    )
    plan = _plan(
        _doc(appliances=[{"external_id": "furnace", "name": "Furnace (renamed)"}]),
        assets={stored["id"]: stored},
    )
    payload = plan.records[0].payload
    assert payload["name"] == "Furnace (renamed)"
    assert payload["manufacturer"] == "Carrier"
    assert payload["serial_number"] == "1234"


# ── Nested appliances ────────────────────────────────────────────────────────


def test_a_child_appliance_names_its_parent_from_the_same_document():
    # A nested tree has to survive as a tree. Without resolution the author's own
    # parent key would ride through as an id, and the store's link cleanup would
    # quietly null it on the next load — losing the tree with nothing said.
    plan = _plan(
        _doc(
            appliances=[
                {"external_id": "hvac", "name": "HVAC"},
                {
                    "external_id": "furnace",
                    "name": "Furnace",
                    "parent_asset_id": "hvac",
                },
            ]
        )
    )
    assert plan.ok, _errors(plan)
    parent, child = plan.records
    assert child.payload["parent_asset_id"] == parent.record_id


def test_a_child_appliance_can_name_a_parent_already_in_home_keeper():
    stored = tr.assets_model.build_asset(
        {"name": "HVAC", "external_id": "hvac"}, now=NOW
    )
    plan = _plan(
        _doc(appliances=[{"name": "Furnace", "parent_asset_id": "hvac"}]),
        assets={stored["id"]: stored},
    )
    assert plan.records[0].payload["parent_asset_id"] == stored["id"]


def test_a_parent_nobody_has_is_refused_rather_than_silently_dropped():
    plan = _plan(_doc(appliances=[{"name": "Furnace", "parent_asset_id": "hvac"}]))
    assert not plan.ok
    assert "List the parent before its children" in _errors(plan)[0]


def _stored_assets(*names) -> dict:
    built = [
        tr.assets_model.build_asset({"name": n.title(), "external_id": n}, now=NOW)
        for n in names
    ]
    return {a["id"]: a for a in built}


def test_an_appliance_cannot_be_made_its_own_parent():
    # Every other write path refuses this through `store._validate_parent`, and an
    # import writes built records straight in — so without the check it is the one
    # way to put a loop in the store.
    stored = _stored_assets("boiler")
    plan = _plan(
        _doc(appliances=[{"external_id": "boiler", "parent_asset_id": "boiler"}]),
        assets=stored,
    )
    assert not plan.ok
    assert "would sit under itself" in _errors(plan)[0]
    assert plan.records == ()


def test_two_appliances_cannot_be_made_each_others_parent():
    # The pair is what is wrong, not either edge: taken one at a time each looks
    # harmless, which is why this is judged against the projected graph.
    stored = _stored_assets("boiler", "pump")
    plan = _plan(
        _doc(
            appliances=[
                {"external_id": "boiler", "parent_asset_id": "pump"},
                {"external_id": "pump", "parent_asset_id": "boiler"},
            ]
        ),
        assets=stored,
    )
    assert not plan.ok
    # Both ends are named, because changing either one opens the loop.
    assert len(_errors(plan)) == 2
    assert plan.records == ()


def test_a_loop_closed_through_an_appliance_the_document_leaves_alone():
    # The document moves one appliance; the rest of the chain is already stored.
    # Nothing in this document is wrong on its own.
    stored = _stored_assets("hvac", "furnace")
    hvac, furnace = (a for a in stored.values())
    furnace["parent_asset_id"] = hvac["id"]
    plan = _plan(
        _doc(appliances=[{"external_id": "hvac", "parent_asset_id": "furnace"}]),
        assets=stored,
    )
    assert not plan.ok
    assert "would sit under itself" in _errors(plan)[0]


def test_a_parent_loop_problem_points_at_the_parent_key():
    stored = _stored_assets("boiler")
    plan = _plan(
        _doc(appliances=[{"external_id": "boiler", "parent_asset_id": "boiler"}]),
        assets=stored,
    )
    assert _only(plan)["path"] == "appliances[0].parent_asset_id"


def test_a_loop_takes_the_tasks_that_named_that_appliance_down_with_it():
    # A rejected appliance stops being something a task can attach to. The task is
    # refused in its own right rather than planned with nothing to attach to, so the
    # preview never shows a task landing on an appliance that will not be written.
    stored = _stored_assets("boiler")
    plan = _plan(
        _doc(
            appliances=[{"external_id": "boiler", "parent_asset_id": "boiler"}],
            tasks=[{"name": "Flush it", "appliance": "boiler"}],
        ),
        assets=stored,
    )
    assert not plan.ok
    assert plan.records == ()
    assert [p.path for p in plan.problems] == [
        "appliances[0].parent_asset_id",
        "tasks[0].appliance",
    ]


def test_nesting_that_forms_no_loop_is_left_alone():
    stored = _stored_assets("hvac")
    plan = _plan(
        _doc(
            appliances=[
                {"name": "Furnace", "parent_asset_id": "hvac"},
                {"name": "Burner", "parent_asset_id": "Furnace"},
            ]
        ),
        assets=stored,
    )
    assert plan.ok, _errors(plan)
    assert len(plan.records) == 2


# ── A problem says *where*, not just what ────────────────────────────────────
#
# Every problem carries a section, an index and a path, and the panel draws all
# three: the path is what tells somebody which record of two hundred to open.
# Asserting only the message leaves them free to be wrong, which is how a report
# ends up pointing at `tasks[0]` for a fault in `tasks[57]`.


def _only(plan) -> dict:
    (problem,) = plan.problems
    return problem.as_dict()


def test_a_task_problem_points_at_the_record_it_came_from():
    plan = _plan(
        _doc(
            tasks=[{"name": "Fine"}, {"name": "Fine too"}, {"name": "", "interval": 1}]
        )
    )
    assert _only(plan) == {
        "section": "tasks",
        "index": 2,
        "path": "tasks[2]",
        "message": "missing required field: 'name'",
        "severity": "error",
    }


def test_an_appliance_problem_points_at_the_record_it_came_from():
    plan = _plan(_doc(appliances=[{"name": "Fine"}, {"name": "", "kind": "virtual"}]))
    problem = _only(plan)
    assert (problem["section"], problem["index"], problem["path"]) == (
        "appliances",
        1,
        "appliances[1]",
    )
    assert problem["severity"] == "error"


def test_an_unknown_field_warning_names_the_field_in_its_path():
    plan = _plan(_doc(tasks=[{"name": "T"}, {"name": "T2", "priority": "high"}]))
    assert _only(plan) == {
        "section": "tasks",
        "index": 1,
        "path": "tasks[1].priority",
        "message": '"priority" is not a field this version of Home Keeper reads, so '
        "it was ignored",
        "severity": "warning",
    }


def test_an_unknown_section_warning_names_the_section():
    plan = _plan(_doc(recipes=[]))
    assert _only(plan) == {
        "section": "recipes",
        "index": None,
        "path": "recipes",
        "message": '"recipes" is not a section this version of Home Keeper reads, so '
        "it was left alone",
        "severity": "warning",
    }


def test_a_section_that_is_not_a_list_says_which_section():
    plan = _plan(_doc(tasks={"name": "not a list"}))
    assert _only(plan) == {
        "section": "tasks",
        "index": None,
        "path": "tasks",
        "message": '"tasks" must be a list',
        "severity": "error",
    }


def test_a_record_that_is_not_a_mapping_says_which_one():
    plan = _plan(_doc(tasks=[{"name": "T"}, "just a string"]))
    problem = _only(plan)
    assert (problem["section"], problem["index"], problem["path"]) == (
        "tasks",
        1,
        "tasks[1]",
    )
    assert problem["message"] == "each record must be a mapping"


def test_the_record_cap_problem_names_the_section_and_the_limit():
    plan = _plan(_doc(tasks=[{"name": f"T{i}"} for i in range(2001)]))
    assert _only(plan) == {
        "section": "tasks",
        "index": None,
        "path": "tasks",
        "message": '"tasks" has 2001 records; at most 2000 can be imported at once. '
        "Split the document.",
        "severity": "error",
    }


def test_a_history_that_is_not_a_list_says_so_at_its_own_path():
    plan = _plan(_doc(tasks=[{"name": "T", "history": "2026-03-04"}]))
    assert _only(plan) == {
        "section": "tasks",
        "index": 0,
        "path": "tasks[0].history",
        "message": '"history" must be a list',
        "severity": "error",
    }


def test_a_history_entry_with_no_date_says_which_entry():
    plan = _plan(
        _doc(tasks=[{"name": "T", "history": [{"completed_at": "2026-01-01"}, {}]}])
    )
    assert _only(plan) == {
        "section": "tasks",
        "index": 0,
        "path": "tasks[0].history[1]",
        "message": 'each entry needs a "completed_at" date',
        "severity": "error",
    }


def test_a_skip_entry_with_no_date_names_the_skip_key():
    plan = _plan(_doc(tasks=[{"name": "T", "skips": [{"note": "no date"}]}]))
    problem = _only(plan)
    assert problem["path"] == "tasks[0].skips[0]"
    assert problem["message"] == 'each entry needs a "skipped_at" date'


def test_an_envelope_problem_is_attributed_to_the_envelope():
    plan = _plan({"tasks": []})
    assert _only(plan) == {
        "section": "home_keeper",
        "index": None,
        "path": "home_keeper",
        "message": 'the document needs a "home_keeper" block naming its format',
        "severity": "error",
    }


def test_a_reserved_source_problem_points_at_the_source_key():
    plan = _plan(_doc(tasks=[{"name": "T", "source": {"buy": {"asset_id": "a"}}}]))
    problem = _only(plan)
    assert problem["path"] == "tasks[0].source"
    assert problem["index"] == 0


def test_a_managed_by_problem_points_at_the_managed_by_key():
    plan = _plan(_doc(tasks=[{"name": "T", "managed_by": {"integration": "x"}}]))
    assert _only(plan)["path"] == "tasks[0].managed_by"


def test_a_source_home_keeper_does_not_reserve_is_carried_through():
    # Only the *reserved* namespaces are refused. An integration's own opaque
    # provenance is exactly what `source` is for, and a check that tested
    # "has any source at all" would reject it.
    plan = _plan(_doc(tasks=[{"name": "T", "source": {"pawsistant": {"pet": "7"}}}]))
    assert plan.ok, _errors(plan)
    assert plan.records[0].payload["source"] == {"pawsistant": {"pet": "7"}}


def test_a_source_that_is_not_a_mapping_is_refused_rather_than_stored():
    # An import builds records without going through the service schemas, which are
    # what types this `dict` everywhere else. A plausible hand-written `source: part`
    # would otherwise be stored verbatim and break `store.async_repoint_device_ids`
    # much later, with nothing to connect the crash to the document that caused it.
    plan = _plan(_doc(tasks=[{"name": "T", "source": "part"}]))
    assert not plan.ok
    assert _errors(plan) == ["source must be a mapping"]
    assert plan.records == ()


def test_an_ambiguous_name_problem_points_at_the_record():
    one, two = _task(), _task()
    plan = _plan(
        _doc(tasks=[{"name": "Furnace filter"}]),
        tasks={one["id"]: one, two["id"]: two},
    )
    problem = _only(plan)
    assert (problem["section"], problem["index"], problem["path"]) == (
        "tasks",
        0,
        "tasks[0]",
    )
    assert one["id"] in problem["message"] and two["id"] in problem["message"]


def test_an_ambiguous_appliance_name_problem_points_at_the_record():
    one = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    two = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    plan = _plan(
        _doc(appliances=[{"name": "Furnace"}]),
        assets={one["id"]: one, two["id"]: two},
    )
    problem = _only(plan)
    assert problem["section"] == "appliances"
    assert "matches several appliances" in problem["message"]


def test_a_missing_appliance_problem_points_at_the_appliance_key():
    plan = _plan(_doc(tasks=[{"name": "T", "appliance": "Boiler"}]))
    assert _only(plan)["path"] == "tasks[0].appliance"


def test_a_missing_parent_problem_points_at_the_parent_key():
    plan = _plan(_doc(appliances=[{"name": "F", "parent_asset_id": "nope"}]))
    assert _only(plan)["path"] == "appliances[0].parent_asset_id"


def test_a_stale_device_warning_points_at_the_device_key():
    plan = _plan(
        _doc(tasks=[{"name": "T", "device_id": "dev_elsewhere"}]),
        device_ids=frozenset({"dev_here"}),
    )
    assert _only(plan) == {
        "section": "tasks",
        "index": 0,
        "path": "tasks[0].device_id",
        "message": 'no device "dev_elsewhere" exists here, so the task was imported '
        "without an appliance. Name the appliance instead.",
        "severity": "warning",
    }


# ── The exported record's exact shape ────────────────────────────────────────


def test_an_exported_appliance_carries_every_field_under_its_own_name():
    asset = tr.assets_model.build_asset(
        {
            "name": "Furnace",
            "external_id": "centriq-4711",
            "manufacturer": "Carrier",
            "model": "59TP6A",
            "serial_number": "1234",
            "notes": "Installed by ABC.",
            "icon": "mdi:fire",
            "cost": 4200,
            "area_id": "area_base",
            "parts": [{"name": "Filter"}],
            "metadata": [{"type": "text", "label": "Breaker", "value": "B14"}],
        },
        now=NOW,
    )
    asset["device_id"] = "dev_furnace"
    asset["archived_at"] = NOW.isoformat()
    record = tr.build_document(
        [], [asset], area_names={"area_base": "Basement"}, now=NOW
    )["appliances"][0]

    assert record["id"] == asset["id"]
    assert record["external_id"] == "centriq-4711"
    assert record["name"] == "Furnace"
    assert record["manufacturer"] == "Carrier"
    assert record["model"] == "59TP6A"
    assert record["serial_number"] == "1234"
    assert record["notes"] == "Installed by ABC."
    assert record["icon"] == "mdi:fire"
    assert record["cost"] == 4200
    assert record["area"] == "Basement"
    assert record["area_id"] == "area_base"
    assert record["device_id"] == "dev_furnace"
    assert record["archived"] is True
    assert [p["name"] for p in record["parts"]] == ["Filter"]
    assert [m["label"] for m in record["metadata"]] == ["Breaker"]
    # The raw timestamp is re-shaped as the boolean, not carried as well.
    assert "archived_at" not in record
    # Registry snapshots of *this* install's device never travel.
    assert "identifiers" not in record and "connections" not in record


def test_an_unarchived_appliance_says_nothing_about_archiving():
    asset = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    record = tr.build_document([], [asset], now=NOW)["appliances"][0]
    assert "archived" not in record


def test_an_appliance_with_no_area_omits_both_area_keys():
    asset = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    record = tr.build_document([], [asset], now=NOW)["appliances"][0]
    assert "area" not in record and "area_id" not in record


def test_an_area_with_no_name_falls_back_to_its_id():
    # A task can outlive the area it named. Emitting the bare id keeps the record
    # honest rather than dropping the attachment silently.
    task = _task()
    task["area_id"] = "area_gone"
    record = tr.build_document([task], [], area_names={}, now=NOW)["tasks"][0]
    assert record["area"] == "area_gone"


def test_an_exported_task_names_its_appliance_by_name_when_it_has_no_key():
    asset = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    asset["device_id"] = "dev_furnace"
    task = _task()
    task["device_id"] = "dev_furnace"
    record = tr.build_document([task], [asset], now=NOW)["tasks"][0]
    assert record["appliance"] == "Furnace"


def test_history_entries_are_re_keyed_for_the_document():
    task = _task()
    tr.recurrence.apply_completion(
        task, datetime(2026, 3, 4, 9, tzinfo=TZ), now=NOW, metadata={"note": "n"}
    )
    tr.recurrence.record_skip(task, datetime(2026, 4, 1, 9, tzinfo=TZ))
    record = tr.build_document([task], [], now=NOW)["tasks"][0]
    assert record["history"][0]["completed_at"].startswith("2026-03-04")
    assert record["history"][0]["note"] == "n"
    assert record["skips"][0]["skipped_at"].startswith("2026-04-01")
    # `ts` is the storage key; the document uses the service's vocabulary.
    assert "ts" not in record["history"][0]


def test_the_export_counts_only_uploaded_files_as_skipped():
    asset = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    asset["documents"] = [
        {"id": "d1", "kind": "link", "name": "M", "url": "https://example.com/m"},
    ]
    assert "skipped" not in tr.build_document([], [asset], now=NOW)["home_keeper"]


def test_the_json_form_keeps_non_ascii_readable_and_the_document_order():
    document = {"home_keeper": {"format": 1}, "tasks": [{"name": "Cambiar filtro ñ"}]}
    text = tr.document_to_json(document)
    # Not ñ escapes: somebody has to read and edit this file.
    assert "ñ" in text
    # Envelope first, as written — sorting the keys would bury it mid-file.
    assert text.index('"home_keeper"') < text.index('"tasks"')


def test_the_json_form_is_indented_rather_than_one_long_line():
    text = tr.document_to_json({"home_keeper": {"format": 1}, "tasks": []})
    assert '\n  "home_keeper"' in text


# ── Guard-rail details ───────────────────────────────────────────────────────


def test_a_bare_id_that_is_not_a_uuid_is_replaced_rather_than_stored():
    # The id keys the store, so a value that is not one would be a record nobody
    # can address. Minting a fresh one keeps the import going.
    plan = _plan(_doc(tasks=[{"id": "not-a-uuid", "name": "T"}]))
    assert plan.records[0].record_id != "not-a-uuid"
    assert plan.records[0].payload["id"] == plan.records[0].record_id


def test_two_new_records_stating_the_same_id_do_not_both_take_it():
    same = "11111111-2222-3333-4444-555555555555"
    plan = _plan(_doc(tasks=[{"id": same, "name": "One"}, {"id": same, "name": "Two"}]))
    first, second = plan.records
    assert first.record_id == same
    assert second.record_id != same


def test_an_area_named_by_its_own_id_resolves_to_itself():
    plan = _plan(
        _doc(tasks=[{"name": "T", "area": "area_base"}]),
        area_ids={"Basement": "area_base"},
    )
    assert plan.records[0].payload["area_id"] == "area_base"


def test_an_area_name_match_ignores_case_and_spaces():
    plan = _plan(
        _doc(tasks=[{"name": "T", "area": "  basement  "}]),
        area_ids={"Basement": "area_base"},
    )
    assert plan.records[0].payload["area_id"] == "area_base"


def test_an_area_id_beats_an_area_name_that_disagrees_with_it():
    plan = _plan(
        _doc(tasks=[{"name": "T", "area": "Kitchen", "area_id": "area_base"}]),
        area_ids={"Basement": "area_base", "Kitchen": "area_kitchen"},
    )
    assert plan.records[0].payload["area_id"] == "area_base"


def test_an_appliance_reference_can_be_the_stored_appliances_own_id():
    stored = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    stored["device_id"] = "dev_furnace"
    plan = _plan(
        _doc(tasks=[{"name": "T", "appliance": stored["id"]}]),
        assets={stored["id"]: stored},
    )
    assert plan.records[0].payload["device_id"] == "dev_furnace"


def test_a_stored_appliance_with_no_device_is_not_a_usable_reference():
    # An unprovisioned appliance has no device for a task to hang on, so naming it
    # is an error rather than a task quietly imported unattached.
    stored = tr.assets_model.build_asset({"name": "Furnace"}, now=NOW)
    plan = _plan(
        _doc(tasks=[{"name": "T", "appliance": "Furnace"}]),
        assets={stored["id"]: stored},
    )
    assert not plan.ok


def test_planned_asset_id_only_answers_for_its_own_placeholder():
    assert tr.planned_asset_id("dev_real") is None
    assert tr.planned_asset_id(None) is None


def test_a_parent_can_be_named_by_the_stored_appliances_id():
    stored = tr.assets_model.build_asset({"name": "HVAC"}, now=NOW)
    plan = _plan(
        _doc(appliances=[{"name": "Furnace", "parent_asset_id": stored["id"]}]),
        assets={stored["id"]: stored},
    )
    assert plan.records[0].payload["parent_asset_id"] == stored["id"]
