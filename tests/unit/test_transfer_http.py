"""The HTTP views of the import and export (``transfer_http.py``).

The views load with fake aiohttp and HTTP helpers (``transfer_harness.load_http``)
and run against the real ``transfer_runner``. ``require_admin`` is a no-op fake
here, so these tests prove the second gate in each view: a non-admin user, a system
user and a request with no user get 401 and start no export or import.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import hk_transfer as tr
import pytest
from transfer_harness import (
    FakeHass,
    FakePart,
    FakeRequest,
    FakeStore,
    coordinator,
    load_http,
    load_runner,
    user,
)

runner = load_runner()
http = load_http(runner)

YAML = b"home_keeper: {format: 1}\ntasks:\n  - name: Clean the gutters\n"


@pytest.fixture
def hass(tmp_path: Path) -> FakeHass:
    instance = FakeHass(tmp_path / "config")
    instance.coord = coordinator(FakeStore())
    return instance


def _run(coro):
    return asyncio.run(coro)


def _runs(hass: FakeHass) -> list[Path]:
    root = hass.root / ".storage" / "home_keeper_import_export"
    return list(root.iterdir()) if root.is_dir() else []


@pytest.mark.parametrize(
    "caller",
    [None, user(admin=False), user(admin=True, system=True)],
    ids=["no user", "non-admin", "system user"],
)
def test_only_an_admin_user_can_use_the_views(hass, caller):
    upload = http.HomeKeeperImportUploadView()
    request = FakeRequest(hass, user=caller, parts=[FakePart("file", YAML, "a.yaml")])
    assert _run(upload.post(request)) == ("message", "unauthorized_transfer", 401)
    download = http.HomeKeeperBundleExportView()
    assert _run(download.get(FakeRequest(hass, user=caller))) == (
        "message",
        "unauthorized_transfer",
        401,
    )
    assert hass.coord.store.writes == []
    assert hass.bus.fired == []
    assert _runs(hass) == []


def test_an_uploaded_yaml_document_returns_the_import_report(hass):
    view = http.HomeKeeperImportUploadView()
    parts = [
        FakePart("dry_run", b"true"),
        FakePart("file", YAML, "export.yaml"),
        FakePart("match", b"bogus"),
    ]
    kind, report = _run(view.post(FakeRequest(hass, user=user(), parts=parts)))
    assert kind == "json"
    assert report["ok"] is True
    assert report["dry_run"] is True
    assert report["counts"]["tasks"] == {"created": 1, "updated": 0}
    assert hass.coord.store.writes == []
    assert _runs(hass) == []


def test_an_uploaded_document_is_applied_without_dry_run(hass):
    view = http.HomeKeeperImportUploadView()
    parts = [FakePart("file", YAML, "export.yaml")]
    _kind, report = _run(view.post(FakeRequest(hass, user=user(), parts=parts)))
    assert report["ok"] is True and report["dry_run"] is False
    assert len(hass.coord.store.writes) == 1
    assert hass.bus.fired[-1][2].user_id == "admin-user"


def test_an_uploaded_bundle_is_extracted_and_imported(hass):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("home_keeper.yaml", YAML)
    view = http.HomeKeeperImportUploadView()
    parts = [FakePart("file", buffer.getvalue(), "home.zip")]
    kind, report = _run(view.post(FakeRequest(hass, user=user(), parts=parts)))
    assert kind == "json"
    assert report["ok"] is True
    assert hass.bus.fired[-1][1]["kind"] == "bundle"
    assert _runs(hass) == []


def test_an_upload_over_the_limit_is_refused(hass, monkeypatch):
    monkeypatch.setattr(http, "MAX_BUNDLE_BYTES", 10)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("home_keeper.yaml", YAML)
    view = http.HomeKeeperImportUploadView()
    parts = [FakePart("file", buffer.getvalue(), "home.zip")]
    assert _run(view.post(FakeRequest(hass, user=user(), parts=parts))) == (
        "message",
        "file_too_large",
        413,
    )
    assert _runs(hass) == []


def test_a_yaml_upload_over_the_service_limit_is_refused(hass, monkeypatch):
    monkeypatch.setattr(http, "MAX_IMPORT_BYTES", 10)
    view = http.HomeKeeperImportUploadView()
    parts = [FakePart("file", YAML, "export.yaml")]
    result = _run(view.post(FakeRequest(hass, user=user(), parts=parts)))
    assert result == ("message", "file_too_large", 413)


def test_an_upload_with_no_file_or_with_binary_text_is_refused(hass):
    view = http.HomeKeeperImportUploadView()
    empty = FakeRequest(hass, user=user(), parts=[FakePart("dry_run", b"1")])
    assert _run(view.post(empty)) == ("message", "no_file_in_upload", 400)
    binary = FakeRequest(hass, user=user(), parts=[FakePart("file", b"\xff\xfe", "x")])
    assert _run(view.post(binary)) == ("message", "import_not_text", 400)


def test_the_views_need_a_loaded_entry(hass):
    hass.coord = None
    view = http.HomeKeeperImportUploadView()
    parts = [FakePart("file", YAML, "export.yaml")]
    assert _run(view.post(FakeRequest(hass, user=user(), parts=parts)))[2] == 404
    assert (
        _run(http.HomeKeeperBundleExportView().get(FakeRequest(hass, user=user())))[2]
        == 404
    )


def test_the_download_streams_a_bundle_and_deletes_its_run_folder(hass):
    task = tr.models.build_task({"name": "Clean the gutters"}, now=runner.dt_util.now())
    hass.coord = coordinator(FakeStore(tasks={task["id"]: task}))
    request = FakeRequest(hass, user=user(), query={"include": "tasks, settings"})
    response = _run(http.HomeKeeperBundleExportView().get(request))
    assert response.prepared and response.ended
    assert response.headers["Content-Type"] == "application/zip"
    assert response.headers["Content-Length"] == str(len(response.body))
    assert "home-keeper-2026-06-13.zip" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(bytes(response.body))) as archive:
        document = tr.parse_document(archive.read("home_keeper.yaml").decode())
    assert [t["name"] for t in document["tasks"]] == ["Clean the gutters"]
    assert "appliances" not in document
    assert "profiles" in document
    assert _runs(hass) == []
    assert not (hass.root / "home_keeper_exports").exists()


def test_the_download_refuses_an_unknown_section(hass):
    request = FakeRequest(hass, user=user(), query={"include": "nope"})
    kind, _message, status = _run(http.HomeKeeperBundleExportView().get(request))
    assert (kind, status) == ("message", 400)
    assert _runs(hass) == []


def test_a_text_field_over_its_limit_is_refused_before_it_is_read_whole(
    hass, monkeypatch
):
    monkeypatch.setattr(http, "MAX_UPLOAD_FIELD_BYTES", 16)
    field = FakePart("match", b"a" * 1000)
    parts = [field, FakePart("file", YAML, "export.yaml")]
    result = _run(
        http.HomeKeeperImportUploadView().post(
            FakeRequest(hass, user=user(), parts=parts)
        )
    )
    assert result == ("message", "upload_field_too_large", 413)
    assert field.consumed <= 16 + 7
    assert hass.coord.store.writes == []
    assert _runs(hass) == []


def test_a_text_field_at_its_limit_is_read(hass, monkeypatch):
    monkeypatch.setattr(http, "MAX_UPLOAD_FIELD_BYTES", 4)
    parts = [FakePart("dry_run", b"true"), FakePart("file", YAML, "export.yaml")]
    kind, report = _run(
        http.HomeKeeperImportUploadView().post(
            FakeRequest(hass, user=user(), parts=parts)
        )
    )
    assert kind == "json" and report["dry_run"] is True


def test_a_field_with_an_unknown_name_is_not_read(hass, monkeypatch):
    monkeypatch.setattr(http, "MAX_UPLOAD_FIELD_BYTES", 16)
    extra = [FakePart(f"x{i}", b"a" * 1000) for i in range(3)]
    parts = [*extra, FakePart("dry_run", b"true"), FakePart("file", YAML, "e.yaml")]
    kind, report = _run(
        http.HomeKeeperImportUploadView().post(
            FakeRequest(hass, user=user(), parts=parts)
        )
    )
    assert kind == "json" and report["dry_run"] is True
    assert [part.consumed for part in extra] == [0, 0, 0]


def test_the_upload_reads_only_its_3_fields():
    assert {"dry_run", "include_settings", "match"} == http._UPLOAD_FIELDS


def test_the_field_limit_is_a_small_constant():
    assert http.MAX_UPLOAD_FIELD_BYTES == 64 * 1024


def test_a_yaml_upload_stops_as_soon_as_it_passes_the_yaml_limit(hass, monkeypatch):
    monkeypatch.setattr(http, "MAX_IMPORT_BYTES", 20)
    part = FakePart("file", YAML * 100, "export.yaml")
    result = _run(
        http.HomeKeeperImportUploadView().post(
            FakeRequest(hass, user=user(), parts=[part])
        )
    )
    assert result == ("message", "file_too_large", 413)
    assert part.consumed <= 20 + 7
    assert _runs(hass) == []


def test_a_bundle_can_pass_the_yaml_limit(hass, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("home_keeper.yaml", YAML)
    monkeypatch.setattr(http, "MAX_IMPORT_BYTES", 20)
    parts = [FakePart("file", buffer.getvalue(), "home.zip")]
    kind, report = _run(
        http.HomeKeeperImportUploadView().post(
            FakeRequest(hass, user=user(), parts=parts)
        )
    )
    assert kind == "json" and report["ok"] is True


def test_the_view_leaves_the_request_body_cap_alone(hass):
    request = FakeRequest(hass, user=user(), parts=[FakePart("file", YAML, "a.yaml")])
    _run(http.HomeKeeperImportUploadView().post(request))
    assert request._client_max_size == 0
