"""Integration tests for the portable import/export document.

The unit tier proves the *decisions* are right with an injected clock and fake
stores. These prove the round trip survives a real Home Assistant: that a virtual
appliance really gets provisioned a device before the tasks that point at it are
written, that the ids survive so entities do, and that re-running the same import
changes nothing — the property a migration script depends on and the one no pure
test can establish, because it turns on the reconcile-and-reload the applier does
in the middle.
"""

from conftest import call_service


def _export(ha, **data):
    resp = call_service(ha, "home_keeper", "export_data", data, return_response=True)
    return resp.get("service_response", resp)


def _import(ha, document, **data):
    resp = call_service(
        ha,
        "home_keeper",
        "import_data",
        {"document": document, **data},
        return_response=True,
    )
    return resp.get("service_response", resp)


def _tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _assets(ha):
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    return resp.get("service_response", resp)["assets"]


def test_export_returns_the_document_and_a_file_to_save(ha):
    payload = _export(ha)
    assert "document" in payload and "yaml" in payload
    document = payload["document"]
    assert document["home_keeper"]["format"] == 1
    assert document["home_keeper"]["version"]
    assert isinstance(document["tasks"], list)
    assert isinstance(document["appliances"], list)
    # The YAML is the same document, not a second rendering of it.
    text = payload["yaml"]
    assert "format: 1" in text
    # An editor reads the first line to find the schema to check the file against.
    assert text.splitlines()[0].startswith("# yaml-language-server: $schema=")
    assert "/schema/home-keeper-1.schema.json" in text.splitlines()[0]


def test_export_can_be_narrowed_to_one_section(ha):
    document = _export(ha, include=["tasks"])["document"]
    assert "tasks" in document
    assert "appliances" not in document


def test_a_dry_run_reports_what_would_happen_and_writes_nothing(ha):
    before = len(_tasks(ha))
    report = _import(
        ha,
        {
            "home_keeper": {"format": 1},
            "tasks": [{"name": "Dry run only", "interval": 1, "unit": "days"}],
        },
        dry_run=True,
    )
    assert report["ok"] is True
    assert report["dry_run"] is True
    assert report["counts"]["tasks"]["created"] == 1
    assert len(_tasks(ha)) == before


def test_an_import_creates_an_appliance_and_a_task_attached_to_it(ha):
    # The ordering this exercises is the one the applier exists for: a virtual
    # appliance has no device id until provisioning runs, so the task that names it
    # can only be written afterwards.
    report = _import(
        ha,
        {
            "home_keeper": {"format": 1},
            "appliances": [
                {
                    "external_id": "it-boiler",
                    "name": "Imported boiler",
                    "manufacturer": "Acme",
                    "model": "B-1",
                    "parts": [{"name": "Anode rod", "type": "wear"}],
                }
            ],
            "tasks": [
                {
                    "external_id": "it-boiler-flush",
                    "name": "Flush the imported boiler",
                    "appliance": "it-boiler",
                    "interval": 12,
                    "unit": "months",
                    "history": [
                        {"completed_at": "2024-05-01", "note": "First flush"},
                        {"completed_at": "2025-05-01", "cost": 40},
                    ],
                }
            ],
        },
    )
    assert report["ok"] is True, report["problems"]
    assert report["counts"]["completions"] == 2

    asset = next(a for a in _assets(ha) if a.get("external_id") == "it-boiler")
    assert asset["device_id"], "a virtual appliance must be provisioned a device"

    task = next(t for t in _tasks(ha) if t.get("external_id") == "it-boiler-flush")
    assert task["device_id"] == asset["device_id"]
    # History replayed in date order, so the newest completion is what counts.
    assert len(task["completions"]) == 2
    assert task["last_completed"].startswith("2025-05-01")


def test_re_running_the_same_import_changes_nothing(ha):
    # Idempotence is the property a migration script lives on: fix three rows, run it
    # again, and the other two hundred stay exactly as they are.
    document = {
        "home_keeper": {"format": 1},
        "tasks": [
            {
                "external_id": "it-idempotent",
                "name": "Idempotent task",
                "interval": 2,
                "unit": "weeks",
            }
        ],
    }
    first = _import(ha, document)
    assert first["counts"]["tasks"] == {"created": 1, "updated": 0}
    created_id = first["records"][0]["id"]

    second = _import(ha, document)
    assert second["counts"]["tasks"] == {"created": 0, "updated": 1}
    assert second["records"][0]["matched_by"] == "external_id"
    assert second["records"][0]["id"] == created_id
    assert len([t for t in _tasks(ha) if t["name"] == "Idempotent task"]) == 1


def test_an_export_re_imports_onto_itself_as_a_pure_update(ha):
    document = _export(ha)["document"]
    report = _import(ha, document, dry_run=True)
    assert report["ok"] is True, report["problems"]
    assert all(r["action"] == "update" for r in report["records"]), report["records"]
    assert all(r["matched_by"] == "id" for r in report["records"])


def test_a_document_with_one_bad_record_writes_nothing(ha):
    before = len(_tasks(ha))
    report = _import(
        ha,
        {
            "home_keeper": {"format": 1},
            "tasks": [
                {"name": "This one is fine", "interval": 1, "unit": "days"},
                {"name": "", "interval": 1, "unit": "days"},
            ],
        },
    )
    assert report["ok"] is False
    assert report["problems"]
    assert len(_tasks(ha)) == before, "a failed import must leave the store untouched"


def test_an_unknown_field_is_reported_but_does_not_block_the_import(ha):
    report = _import(
        ha,
        {
            "home_keeper": {"format": 1},
            "tasks": [
                {
                    "external_id": "it-forward-compat",
                    "name": "Task from a newer Home Keeper",
                    "interval": 1,
                    "unit": "days",
                    "some_field_from_the_future": "hello",
                }
            ],
        },
    )
    assert report["ok"] is True
    warnings = [p for p in report["problems"] if p["severity"] == "warning"]
    assert any("some_field_from_the_future" in p["message"] for p in warnings)
    assert any(t.get("external_id") == "it-forward-compat" for t in _tasks(ha))


def test_a_document_from_a_newer_format_is_refused_with_something_to_act_on(ha):
    report = _import(ha, {"home_keeper": {"format": 99}, "tasks": []})
    assert report["ok"] is False
    assert "Update Home Keeper" in report["problems"][0]["message"]


def test_a_document_given_as_text_is_read_the_same_way(ha):
    """The panel sends the file as text, so the service has to take it as text.

    Both spellings on purpose: YAML because that is what an export writes now, and
    JSON because YAML is a superset of it, so a file saved before the format changed
    still imports. If these two ever disagree the panel and an automation would be
    reading different documents.
    """
    as_yaml = (
        "home_keeper:\n"
        "  format: 1\n"
        "tasks:\n"
        "  - external_id: text-import-yaml\n"
        "    name: Text import via YAML\n"
        "    interval: 4\n"
        "    unit: months\n"
    )
    as_json = (
        '{"home_keeper": {"format": 1}, "tasks": [{"external_id": "text-import-json",'
        ' "name": "Text import via JSON", "interval": 4, "unit": "months"}]}'
    )
    for text in (as_yaml, as_json):
        report = _import(ha, text, dry_run=True)
        assert report["ok"], report["problems"]
        assert report["counts"]["tasks"]["created"] == 1


def test_a_file_that_is_not_yaml_is_reported_with_a_line_and_a_column(ha):
    report = _import(ha, "tasks:\n  - name: A\n   bad: B\n", dry_run=True)
    assert not report["ok"]
    problem = report["problems"][0]
    assert problem["path"] == "line 3, column 4"
    assert "not valid YAML" in problem["message"]
