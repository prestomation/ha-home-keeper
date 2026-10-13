"""Companion sections and bundles, through the real ``transfer_runner.py``.

The runner is loaded by ``transfer_harness`` with a fake service registry. A fake
companion registers the ``import_export`` capability and real async handlers for
``<domain>.export_data`` and ``<domain>.import_data``, which check the admin user in
the context, as docs/INTEGRATING.md §11 asks a companion to do. The store is a fake
on plain dicts that uses the real pure helpers to add documents and photos.
"""

from __future__ import annotations

import asyncio
import io
import os
import time
import types
import zipfile
from pathlib import Path
from typing import Any

import hk_transfer as tr
import pytest
from transfer_harness import (
    FakeCompanions,
    FakeHass,
    FakeStore,
    coordinator,
    load_runner,
)

runner = load_runner()
Unauthorized = __import__("homeassistant.exceptions", fromlist=["x"]).Unauthorized
ServiceValidationError = __import__(
    "homeassistant.exceptions", fromlist=["x"]
).ServiceValidationError

ADMIN = types.SimpleNamespace(user_id="admin-user")
USER = types.SimpleNamespace(user_id="plain-user")
PDF = b"%PDF-1.4\n" + b"x" * 64


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
    return buffer.getvalue()


class Dogs:
    """A fake companion with the §11 services. It checks admin like a real one."""

    def __init__(self, hass: FakeHass, domain: str = "dogs") -> None:
        self.domain = domain
        self.data: dict[str, Any] = {"dogs": [{"name": "Rex"}]}
        self.imported: list[dict[str, Any]] = []
        self.problems: list[dict[str, Any]] = []
        self.fail_export = False
        self.file_seen: bytes | None = None
        hass.services.register(domain, "export_data", self.export_data)
        hass.services.register(domain, "import_data", self.import_data)

    @staticmethod
    def _check_admin(context: Any) -> None:
        if context is not None and context.user_id != ADMIN.user_id:
            raise Unauthorized(context=context)

    async def export_data(self, data: dict[str, Any], context: Any) -> dict:
        self._check_admin(context)
        if self.fail_export:
            raise RuntimeError("the database is locked")
        if files_dir := data.get("files_dir"):
            Path(files_dir, "photos").mkdir()
            Path(files_dir, "photos", "rex.jpg").write_bytes(b"rex")
        return {"format": 1, "version": "1.0", "data": self.data, "skipped": {}}

    async def import_data(self, data: dict[str, Any], context: Any) -> dict:
        self._check_admin(context)
        self.imported.append(data)
        if files_dir := data.get("files_dir"):
            photo = Path(files_dir, "photos", "rex.jpg")
            self.file_seen = photo.read_bytes() if photo.is_file() else None
        errors = [p for p in self.problems if p["level"] == "error"]
        return {
            "ok": not errors,
            "dry_run": data["dry_run"],
            "counts": {"dogs": {"created": 1, "updated": 0}},
            "records": [],
            "problems": list(self.problems),
        }


@pytest.fixture
def hass(tmp_path: Path) -> FakeHass:
    return FakeHass(tmp_path / "config")


@pytest.fixture
def registry() -> FakeCompanions:
    found = FakeCompanions()
    runner.companions = found.module()
    yield found
    runner.companions = FakeCompanions().module()


def _run(coro):
    return asyncio.run(coro)


def _document(**extra: Any) -> dict[str, Any]:
    return {
        "home_keeper": {"format": 1},
        "tasks": [{"name": "Brush the dog", "interval": 1, "unit": "weeks"}],
        **extra,
    }


def _section() -> dict[str, Any]:
    return {"format": 1, "version": "1.0", "data": {"dogs": [{"name": "Rex"}]}}


# ── Export ───────────────────────────────────────────────────────────────────


def test_an_export_holds_the_companion_section_as_the_companion_returned_it(
    hass, registry
):
    dogs = Dogs(hass)
    registry.register("dogs", "import_export")
    result = _run(runner.async_export_document(hass, coordinator(), {}, context=ADMIN))
    assert result["document"]["dogs"] == {
        "format": 1,
        "version": "1.0",
        "data": dogs.data,
        "skipped": {},
    }
    assert tr.parse_document(result["yaml"])["dogs"]["data"] == dogs.data
    ((domain, service, data, context),) = hass.services.calls
    assert (domain, service, data) == ("dogs", "export_data", {})
    assert context is ADMIN
    assert "skipped" not in result["document"]["home_keeper"]
    ((event, payload, event_context),) = hass.bus.fired
    assert event == "home_keeper_data_exported"
    assert payload == {
        "kind": "data",
        "sections": {"appliances": 0, "tasks": 0, "dogs": 1},
    }
    assert event_context is ADMIN


def test_a_companion_that_cannot_export_is_named_in_skipped(hass, registry):
    Dogs(hass, "dogs").fail_export = True
    registry.register("dogs", "import_export")
    registry.register("glue")
    registry.register("cats", "import_export")
    result = _run(runner.async_export_document(hass, coordinator(), {}, context=ADMIN))
    document = result["document"]
    assert "dogs" not in document and "glue" not in document
    assert document["home_keeper"]["skipped"]["companions"] == {
        "dogs": "failed",
        "glue": "no_import_export",
        "cats": "no_service",
    }


def test_a_non_admin_context_makes_the_companion_refuse(hass, registry):
    Dogs(hass)
    registry.register("dogs", "import_export")
    result = _run(runner.async_export_document(hass, coordinator(), {}, context=USER))
    assert result["document"]["home_keeper"]["skipped"]["companions"] == {
        "dogs": "failed"
    }


def test_include_selects_the_sections_and_the_companions(hass, registry):
    Dogs(hass)
    Dogs(hass, "cats")
    registry.register("dogs", "import_export")
    registry.register("cats", "import_export")
    result = _run(
        runner.async_export_document(
            hass, coordinator(), {"include": ["cats"]}, context=ADMIN
        )
    )
    assert set(result["document"]) == {"home_keeper", "cats"}
    assert [call[0] for call in hass.services.calls] == ["cats"]


def test_an_unknown_include_name_is_refused(hass, registry):
    with pytest.raises(ServiceValidationError) as raised:
        _run(
            runner.async_export_document(
                hass, coordinator(), {"include": ["tasks", "nope"]}, context=ADMIN
            )
        )
    assert raised.value.translation_key == "unknown_export_section"
    assert raised.value.translation_placeholders == {"sections": "nope"}
    assert hass.bus.fired == []


def test_a_yaml_export_writes_the_settings_only_when_include_names_them(hass, registry):
    coord = coordinator(options={"profiles": [{"id": "p1", "name": "Kitchen"}]})
    plain = _run(runner.async_export_document(hass, coord, {}, context=ADMIN))
    assert "profiles" not in plain["document"]
    named = _run(
        runner.async_export_document(
            hass, coord, {"include": ["settings"]}, context=ADMIN
        )
    )
    assert named["document"]["profiles"][0]["name"] == "Kitchen"
    assert named["document"]["options"]["allow_snooze"] is True
    assert "appliances" not in named["document"]


# ── Import ───────────────────────────────────────────────────────────────────


def test_an_import_dry_runs_every_section_then_applies_in_order(hass, registry):
    dogs = Dogs(hass)
    registry.register("dogs", "import_export")
    store = FakeStore()
    report = _run(
        runner.async_import_document(
            hass,
            coordinator(store),
            {"document": _document(dogs=_section())},
            context=ADMIN,
        )
    )
    assert report["ok"] is True
    assert report["dry_run"] is False
    assert [d["dry_run"] for d in dogs.imported] == [True, False]
    assert dogs.imported[0]["document"] == _section()
    assert "files_dir" not in dogs.imported[0]
    assert report["sections"]["dogs"]["dry_run"] is False
    assert report["counts"]["tasks"] == {"created": 1, "updated": 0}
    assert len(store.writes) == 1
    assert hass.config_entries.reloads == 1
    ((event, payload, _ctx),) = hass.bus.fired
    assert event == "home_keeper_data_imported"
    assert payload["kind"] == "data"
    assert payload["sections"]["tasks"] == {"created": 1, "updated": 0}
    assert payload["sections"]["dogs"] == {"dogs": {"created": 1, "updated": 0}}


def test_a_dry_run_writes_nothing_and_fires_nothing(hass, registry):
    dogs = Dogs(hass)
    registry.register("dogs", "import_export")
    store = FakeStore()
    report = _run(
        runner.async_import_document(
            hass,
            coordinator(store),
            {"document": _document(dogs=_section()), "dry_run": True},
            context=ADMIN,
        )
    )
    assert report["ok"] is True and report["dry_run"] is True
    assert [d["dry_run"] for d in dogs.imported] == [True]
    assert store.writes == [] and hass.bus.fired == []


def test_an_error_in_a_companion_blocks_the_home_keeper_write(hass, registry):
    dogs = Dogs(hass)
    dogs.problems = [{"level": "error", "path": "dogs[0].name", "message": "bad"}]
    registry.register("dogs", "import_export")
    store = FakeStore()
    report = _run(
        runner.async_import_document(
            hass,
            coordinator(store),
            {"document": _document(dogs=_section())},
            context=ADMIN,
        )
    )
    assert report["ok"] is False
    assert store.writes == []
    assert [d["dry_run"] for d in dogs.imported] == [True]
    (problem,) = report["problems"]
    assert problem == {
        "section": "dogs",
        "index": None,
        "path": "dogs.dogs[0].name",
        "message": "bad",
        "severity": "error",
    }
    assert hass.bus.fired == []


def test_an_error_in_home_keeper_blocks_the_companion_write(hass, registry):
    dogs = Dogs(hass)
    registry.register("dogs", "import_export")
    document = {"home_keeper": {"format": 1}, "tasks": [{"interval": 1}], "dogs": {}}
    report = _run(
        runner.async_import_document(
            hass, coordinator(), {"document": document}, context=ADMIN
        )
    )
    assert report["ok"] is False
    assert [d["dry_run"] for d in dogs.imported] == [True]


def test_a_section_of_a_missing_companion_is_a_warning(hass, registry):
    registry.register("glue")
    store = FakeStore()
    report = _run(
        runner.async_import_document(
            hass,
            coordinator(store),
            {"document": _document(cats=_section(), glue=_section())},
            context=ADMIN,
        )
    )
    assert report["ok"] is True
    warnings = {p["path"]: p for p in report["problems"]}
    assert set(warnings) == {"cats", "glue"}
    assert all(p["severity"] == "warning" for p in warnings.values())
    assert "no companion with that domain" in warnings["cats"]["message"]
    assert "does not support import" in warnings["glue"]["message"]
    assert report["sections"] == {}
    assert len(store.writes) == 1


def test_a_companion_that_fails_is_an_error_row(hass, registry):
    async def broken(data, context):
        raise RuntimeError("boom")

    hass.services.register("dogs", "import_data", broken)
    registry.register("dogs", "import_export")
    report = _run(
        runner.async_import_document(
            hass,
            coordinator(),
            {"document": _document(dogs=_section())},
            context=ADMIN,
        )
    )
    assert report["ok"] is False
    assert report["sections"]["dogs"]["ok"] is False
    (problem,) = report["problems"]
    assert problem["path"] == "dogs"
    assert problem["message"] == "the companion dogs failed: boom"


def test_a_companion_that_does_not_answer_in_time_is_an_error_row(
    hass, registry, monkeypatch
):
    async def slow(data, context):
        await asyncio.sleep(5)

    hass.services.register("dogs", "import_data", slow)
    registry.register("dogs", "import_export")
    monkeypatch.setattr(runner, "COMPANION_TRANSFER_TIMEOUT_S", 0.01)
    report = _run(
        runner.async_import_document(
            hass,
            coordinator(),
            {"document": _document(dogs=_section())},
            context=ADMIN,
        )
    )
    assert report["ok"] is False
    assert "did not answer in 0.01 seconds" in report["problems"][0]["message"]


def test_companions_import_in_the_order_of_registration(hass, registry):
    order: list[str] = []
    for domain in ("zebra", "alpha"):
        companion = Dogs(hass, domain)

        async def spy(data, context, companion=companion):
            order.append(f"{companion.domain}:{data['dry_run']}")
            return await Dogs.import_data(companion, data, context)

        hass.services.register(domain, "import_data", spy)
        registry.register(domain, "import_export")
    document = {"home_keeper": {"format": 1}, "alpha": _section(), "zebra": _section()}
    report = _run(
        runner.async_import_document(
            hass, coordinator(), {"document": document}, context=ADMIN
        )
    )
    assert report["ok"] is True
    assert order == ["zebra:True", "alpha:True", "zebra:False", "alpha:False"]


def test_settings_are_skipped_unless_the_caller_asks(hass, registry):
    coord = coordinator()
    document = _document(profiles=[{"name": "Garden"}])
    report = _run(
        runner.async_import_document(hass, coord, {"document": document}, context=ADMIN)
    )
    assert report["ok"] is True
    (problem,) = report["problems"]
    assert problem["path"] == "profiles" and problem["severity"] == "warning"
    assert coord.entry.options == {}


def test_settings_import_merges_profiles_and_warns_on_a_missing_notify_target(
    hass, registry
):
    hass.services.notify.add("mobile_app_pixel")
    coord = coordinator(options={"profiles": [{"id": "p1", "name": "Kitchen"}]})
    document = _document(
        profiles=[{"name": "Garden"}],
        notifications=[
            {"name": "Morning", "targets": ["mobile_app_pixel", "mobile_app_gone"]}
        ],
        options={"allow_skip": False},
    )
    report = _run(
        runner.async_import_document(
            hass,
            coord,
            {"document": document, "include_settings": True},
            context=ADMIN,
        )
    )
    assert report["ok"] is True
    (problem,) = report["problems"]
    assert problem["path"] == "notifications[0].targets[1]"
    assert problem["severity"] == "warning"
    names = [p["name"] for p in coord.entry.options["profiles"]]
    assert names == ["Kitchen", "Garden"]
    assert coord.entry.options["allow_skip"] is False
    assert report["counts"]["settings"]["profiles"] == {"created": 1, "updated": 0}
    payload = hass.bus.fired[-1][1]
    assert payload["sections"]["profiles"] == {"created": 1, "updated": 0}


def test_settings_import_warns_on_profile_filter_ids_from_another_install(
    hass, registry
):
    hass.label_ids = {"lbl_here"}
    coord = coordinator()
    filt = {"labels": ["lbl_here", "lbl_gone"], "areas": ["attic"], "devices": ["d1"]}
    document = _document(profiles=[{"name": "Garden", "filter": filt}])
    report = _run(
        runner.async_import_document(
            hass,
            coord,
            {"document": document, "include_settings": True, "dry_run": True},
            context=ADMIN,
        )
    )
    assert report["ok"] is True
    assert [(p["path"], p["severity"]) for p in report["problems"]] == [
        ("profiles[0].filter.areas", "warning"),
        ("profiles[0].filter.labels", "warning"),
        ("profiles[0].filter.devices", "warning"),
    ]
    assert '"lbl_gone"' in report["problems"][1]["message"]
    assert '"lbl_here"' not in report["problems"][1]["message"]


def test_a_files_section_outside_a_bundle_is_a_warning(hass, registry):
    report = _run(
        runner.async_import_document(
            hass,
            coordinator(),
            {"document": _document(files=[{"kind": "document"}])},
            context=ADMIN,
        )
    )
    assert report["ok"] is True
    (problem,) = report["problems"]
    assert problem["path"] == "files" and problem["severity"] == "warning"


def test_a_bad_document_reports_one_error_and_calls_no_companion(hass, registry):
    Dogs(hass)
    registry.register("dogs", "import_export")
    report = _run(
        runner.async_import_document(
            hass, coordinator(), {"document": ["a", "list"]}, context=ADMIN
        )
    )
    assert report["ok"] is False
    assert report["sections"] == {}
    assert hass.services.calls == []


# ── Bundles ──────────────────────────────────────────────────────────────────


def _stored_with_files(hass: FakeHass) -> FakeStore:
    """A store with an appliance document, a part file and a task photo on disk."""
    asset_id = "0b0e3b1a-0000-4000-8000-000000000001"
    doc_id = "0b0e3b1a-0000-4000-8000-000000000002"
    task_id = "0b0e3b1a-0000-4000-8000-000000000003"
    photo_id = "0b0e3b1a-0000-4000-8000-000000000004"
    asset = tr.assets_model.build_asset({"name": "Furnace"}, now=runner.dt_util.now())
    asset["id"] = asset_id
    asset["documents"] = [
        {
            "id": doc_id,
            "kind": "file",
            "name": "Manual",
            "filename": "manual.pdf",
            "content_type": "application/pdf",
            "size": len(PDF),
        }
    ]
    asset["parts"] = [
        {
            "id": "part-1",
            "name": "Filter",
            "file_name": "filter.pdf",
            "file_content_type": "application/pdf",
            "file_size": len(PDF),
        }
    ]
    task = tr.models.build_task({"name": "Brush the dog"}, now=runner.dt_util.now())
    task["id"] = task_id
    png = _png()
    task["photos"] = [
        {
            "id": photo_id,
            "name": "Before",
            "filename": "before.png",
            "content_type": "image/png",
            "size": len(png),
        }
    ]
    root = hass.root
    docs = root / "home_keeper" / "documents" / asset_id
    docs.mkdir(parents=True)
    (docs / f"{doc_id}__manual.pdf").write_bytes(PDF)
    (docs / "part_part-1__filter.pdf").write_bytes(PDF)
    photos = root / "home_keeper" / "task_photos" / task_id
    photos.mkdir(parents=True)
    (photos / f"{photo_id}__before.png").write_bytes(png)
    return FakeStore(tasks={task_id: task}, assets={asset_id: asset})


def _runs(hass: FakeHass) -> list[Path]:
    root = hass.root / ".storage" / "home_keeper_import_export"
    return list(root.iterdir()) if root.is_dir() else []


def test_a_bundle_holds_the_document_the_files_and_the_companion_files(hass, registry):
    Dogs(hass)
    registry.register("dogs", "import_export")
    store = _stored_with_files(hass)
    coord = coordinator(store, options={"profiles": [{"id": "p", "name": "All"}]})
    result = _run(runner.async_export_bundle(hass, coord, {}, context=ADMIN))
    path = Path(result["path"])
    assert path == hass.root / "home_keeper_exports" / "home-keeper-2026-06-13.zip"
    assert result["size"] == path.stat().st_size
    assert result["skipped"] == {}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        document = tr.parse_document(archive.read("home_keeper.yaml").decode())
        assert archive.read("files/dogs/photos/rex.jpg") == b"rex"
    assert {entry["kind"] for entry in document["files"]} == {
        "document",
        "part_file",
        "task_photo",
    }
    assert {entry["path"] for entry in document["files"]} <= names
    assert document["profiles"][0]["name"] == "All"
    assert "skipped" not in document["home_keeper"]
    assert hass.services.calls[0][2]["files_dir"].startswith(
        str(hass.root / ".storage" / "home_keeper_import_export")
    )
    assert _runs(hass) == []
    assert hass.bus.fired[-1][1]["kind"] == "bundle"
    assert hass.bus.fired[-1][1]["sections"]["files"] == 3


def test_a_missing_file_is_left_out_of_the_bundle_and_counted(hass, registry):
    store = _stored_with_files(hass)
    for path in (hass.root / "home_keeper" / "task_photos").rglob("*.png"):
        path.unlink()
    result = _run(runner.async_export_bundle(hass, coordinator(store), {}))
    assert result["skipped"] == {"missing_files": 1}
    with zipfile.ZipFile(result["path"]) as archive:
        document = tr.parse_document(archive.read("home_keeper.yaml").decode())
    assert [entry["kind"] for entry in document["files"]] == ["document", "part_file"]


def test_a_bundle_restores_the_records_the_files_and_the_companion(
    hass, registry, tmp_path
):
    source = FakeHass(tmp_path / "source")
    Dogs(source)
    registry.register("dogs", "import_export")
    exported = _run(
        runner.async_export_bundle(
            source, coordinator(_stored_with_files(source)), {}, context=ADMIN
        )
    )
    dogs = Dogs(hass)
    store = FakeStore()
    coord = coordinator(store)
    hass.coord = coord
    preview = _run(
        runner.async_import_bundle(
            hass, coord, Path(exported["path"]), {"dry_run": True}, context=ADMIN
        )
    )
    assert preview["ok"] is True, preview["problems"]
    assert preview["counts"]["files"] == {"created": 3, "unchanged": 0}
    assert store.writes == []
    report = _run(
        runner.async_import_bundle(
            hass, coord, Path(exported["path"]), {}, context=ADMIN
        )
    )
    assert report["ok"] is True, report["problems"]
    assert report["counts"]["files"] == {"created": 3, "unchanged": 0}
    (asset,) = store.list_assets()
    (task,) = store.list_tasks()
    (document,) = asset["documents"]
    assert document["kind"] == "file" and document["name"] == "Manual"
    assert asset["parts"][0]["file_name"] == "filter.pdf"
    assert task["photos"][0]["name"] == "Before"
    stored = hass.root / "home_keeper" / "documents" / asset["id"]
    assert (stored / f"{document['id']}__manual.pdf").read_bytes() == PDF
    photo_dir = hass.root / "home_keeper" / "task_photos" / task["id"]
    assert len(list(photo_dir.iterdir())) == 2  # the photo and its thumbnail
    assert dogs.file_seen == b"rex"
    assert dogs.imported[-1]["files_dir"].endswith("/bundle/files/dogs")
    assert _runs(hass) == []
    # The settings are in the bundle, and the caller did not ask for them.
    assert {p["path"] for p in report["problems"]} == {
        "profiles",
        "notifications",
        "options",
    }
    again = _run(
        runner.async_import_bundle(
            hass, coord, Path(exported["path"]), {}, context=ADMIN
        )
    )
    assert again["counts"]["files"] == {"created": 0, "unchanged": 3}


def test_an_unsafe_bundle_is_refused_and_its_run_folder_deleted(hass, registry):
    path = hass.root / "evil.zip"
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("home_keeper.yaml", "home_keeper: {format: 1}\n")
        archive.writestr("../escape.txt", "x")
    store = FakeStore()
    report = _run(runner.async_import_bundle(hass, coordinator(store), path, {}))
    assert report["ok"] is False
    (problem,) = report["problems"]
    assert problem["section"] == "bundle"
    assert "goes up a folder" in problem["message"]
    assert store.writes == []
    assert _runs(hass) == []
    assert not (hass.root / ".storage" / "escape.txt").exists()


def test_the_service_imports_a_bundle_by_its_name_only(hass, registry):
    exports = hass.root / "home_keeper_exports"
    exports.mkdir(parents=True)
    with zipfile.ZipFile(exports / "ok.zip", "w") as archive:
        archive.writestr("home_keeper.yaml", "home_keeper: {format: 1}\ntasks: []\n")
    good = _run(
        runner.async_import_document(
            hass, coordinator(), {"bundle": "ok.zip", "dry_run": True}
        )
    )
    assert good["ok"] is True
    (hass.root / "secret.zip").write_bytes((exports / "ok.zip").read_bytes())
    for name in ("../secret.zip", "/etc/passwd", ".hidden.zip", "nope.zip"):
        bad = _run(runner.async_import_document(hass, coordinator(), {"bundle": name}))
        assert bad["ok"] is False, name
        assert bad["problems"][0]["section"] == "bundle"


def test_setup_deletes_only_the_stale_run_folders(hass):
    root = hass.root / ".storage" / "home_keeper_import_export"
    old = root / "old"
    new = root / "new"
    old.mkdir(parents=True)
    new.mkdir()
    stale = time.time() - 2 * 24 * 60 * 60
    os.utime(old, (stale, stale))
    _run(runner.async_cleanup_runs(hass))
    assert sorted(p.name for p in root.iterdir()) == ["new"]


def test_a_companion_that_fails_after_the_write_marks_the_import_partial(
    hass, registry
):
    dogs = Dogs(hass)

    async def fails_on_write(data, context):
        if data["dry_run"]:
            return await dogs.import_data(data, context)
        raise RuntimeError("boom")

    hass.services.register("dogs", "import_data", fails_on_write)
    registry.register("dogs", "import_export")
    store = FakeStore()
    report = _run(
        runner.async_import_document(
            hass,
            coordinator(store),
            {"document": _document(dogs=_section())},
            context=ADMIN,
        )
    )
    assert report["ok"] is False and report["dry_run"] is False
    assert report["partial"] is True
    assert len(store.writes) == 1


@pytest.mark.parametrize("dry_run", [True, False])
def test_an_import_that_writes_nothing_is_not_partial(hass, registry, dry_run):
    dogs = Dogs(hass)
    dogs.problems = [{"level": "error", "path": "dogs[0].name", "message": "bad"}]
    registry.register("dogs", "import_export")
    report = _run(
        runner.async_import_document(
            hass,
            coordinator(),
            {"document": _document(dogs=_section()), "dry_run": dry_run},
            context=ADMIN,
        )
    )
    assert report["ok"] is False and report["partial"] is False
    dogs.problems = []
    report = _run(
        runner.async_import_document(
            hass,
            coordinator(),
            {"document": _document(dogs=_section()), "dry_run": dry_run},
            context=ADMIN,
        )
    )
    assert report["ok"] is True and report["partial"] is False
