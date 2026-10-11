"""The pure half of companion sections and bundles.

``transfer.split_document``, ``resolve_include``, ``companion_problems`` and
``merge_reports`` sort a document and its reports. ``transfer_bundle`` reads and
writes the zip file safely, and plans the ``files`` and settings sections. Every
test here runs without Home Assistant.
"""

from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path

import hk_transfer as tr
import hk_transfer_bundle as tb
import pytest

PDF = b"%PDF-1.4\n" + b"x" * 64
READY = {"dogs": tr.COMPANION_READY}


# ── Sorting a document ───────────────────────────────────────────────────────


def test_split_sorts_each_key_by_its_owner():
    document = {
        "home_keeper": {"format": 1},
        "appliances": [],
        "tasks": [{"name": "A"}],
        "dogs": {"format": 1, "data": {}},
        "profiles": [],
        "options": {},
        "files": [],
    }
    parts = tr.split_document(document, companions=READY)
    assert parts.home_keeper == {
        "home_keeper": {"format": 1},
        "appliances": [],
        "tasks": [{"name": "A"}],
    }
    assert parts.companions == {"dogs": {"format": 1, "data": {}}}
    assert parts.settings == {"profiles": [], "options": {}}
    assert parts.files == []
    assert parts.problems == ()


def test_split_orders_the_companions_by_registration_not_by_the_file():
    companions = {"zebra": tr.COMPANION_READY, "alpha": tr.COMPANION_READY}
    parts = tr.split_document({"alpha": {}, "zebra": {}}, companions=companions)
    assert list(parts.companions) == ["zebra", "alpha"]
    assert parts.files is None


@pytest.mark.parametrize(
    ("state", "phrase"),
    [
        (tr.COMPANION_NO_CAPABILITY, "does not support import and export"),
        (tr.COMPANION_NO_SERVICE, "has no import_data service"),
        (None, "no companion with that domain is installed"),
    ],
)
def test_split_skips_a_section_that_no_ready_companion_reads(state, phrase):
    companions = {"cats": state} if state else {}
    parts = tr.split_document({"cats": {}}, companions=companions)
    assert parts.companions == {}
    (problem,) = parts.problems
    assert (problem.section, problem.path, problem.severity) == (
        "cats",
        "cats",
        "warning",
    )
    assert phrase in problem.message


def test_split_refuses_a_companion_section_that_is_not_a_mapping():
    parts = tr.split_document({"dogs": [1]}, companions=READY)
    assert parts.companions == {}
    (problem,) = parts.problems
    assert problem.severity == "error"
    assert problem.path == "dogs"


def test_include_defaults_to_everything_and_settings_only_for_a_bundle():
    assert tr.resolve_include(None, companions=["dogs"], bundle=False) == (
        ("appliances", "tasks"),
        ("dogs",),
        False,
        (),
    )
    assert tr.resolve_include([], companions=["dogs"], bundle=True)[2] is True


def test_include_names_sections_companions_and_settings():
    sections, domains, settings, unknown = tr.resolve_include(
        ["tasks", "settings", "dogs", "cats", "tasks"],
        companions=["dogs", "birds"],
        bundle=False,
    )
    assert sections == ("tasks",)
    assert domains == ("dogs",)
    assert settings is True
    assert unknown == ("cats",)


def test_companion_problems_get_the_domain_prefix_and_a_level():
    report = {
        "ok": True,
        "problems": [
            {"level": "warning", "path": "dogs[0].owner", "message": "unknown"},
            {"level": "fatal", "path": "", "message": "odd level"},
            "not a mapping",
        ],
    }
    problems = tr.companion_problems("dogs", report)
    assert [p.as_dict() for p in problems] == [
        {
            "section": "dogs",
            "index": None,
            "path": "dogs.dogs[0].owner",
            "message": "unknown",
            "severity": "warning",
        },
        {
            "section": "dogs",
            "index": None,
            "path": "dogs",
            "message": "odd level",
            "severity": "error",
        },
    ]


def test_a_report_that_is_not_ok_without_an_error_is_an_error():
    (problem,) = tr.companion_problems("dogs", {"ok": False, "problems": []})
    assert problem.severity == "error"
    assert "cannot be applied" in problem.message
    assert tr.companion_problems("dogs", {"ok": True}) == []
    (missing,) = tr.companion_problems("dogs", None)
    assert missing.severity == "error"
    assert missing.message == "the companion dogs returned no import report"


def test_merge_keeps_the_report_keys_and_adds_sections():
    report = tr.ImportPlan().as_report(dry_run=True)
    warning = tr.Problem("cats", None, "cats", "skipped", severity="warning")
    merged = tr.merge_reports(
        report, sections={"dogs": {"ok": True}}, problems=[warning]
    )
    assert set(merged) == {"ok", "dry_run", "counts", "records", "problems", "sections"}
    assert merged["ok"] is True
    assert merged["sections"] == {"dogs": {"ok": True}}
    assert merged["problems"] == [warning.as_dict()]
    error = tr.Problem("dogs", None, "dogs.x", "bad")
    assert tr.merge_reports(report, sections={}, problems=[error])["ok"] is False
    # The input report is not changed.
    assert report["problems"] == []


# ── Reading a bundle safely ──────────────────────────────────────────────────


def _zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_a_good_bundle_extracts_every_file(tmp_path):
    bundle = _zip(
        tmp_path / "ok.zip",
        {"home_keeper.yaml": b"home_keeper: {}\n", "files/dogs/a/b.txt": b"b"},
    )
    names = tb.safe_extract(bundle, tmp_path / "out")
    assert names == ["home_keeper.yaml", "files/dogs/a/b.txt"]
    assert (tmp_path / "out" / "files/dogs/a/b.txt").read_bytes() == b"b"
    assert tb.read_document_text(tmp_path / "out") == "home_keeper: {}\n"


@pytest.mark.parametrize(
    ("name", "phrase"),
    [
        ("../evil.txt", "goes up a folder"),
        ("files/../../evil.txt", "goes up a folder"),
        ("/etc/evil.txt", "absolute path"),
        ("C:/evil.txt", "absolute path"),
        ("files\\evil.txt", "bad name"),
    ],
)
def test_a_zip_slip_name_refuses_the_whole_bundle(tmp_path, name, phrase):
    bundle = _zip(tmp_path / "evil.zip", {"home_keeper.yaml": b"x", name: b"x"})
    with pytest.raises(tb.BundleError, match=phrase):
        tb.safe_extract(bundle, tmp_path / "out")
    # The check runs before the first write.
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "evil.txt").exists()


def test_a_symbolic_link_refuses_the_whole_bundle(tmp_path):
    path = tmp_path / "link.zip"
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("files/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")
    with pytest.raises(tb.BundleError, match="symbolic link"):
        tb.safe_extract(path, tmp_path / "out")


def test_an_encrypted_entry_refuses_the_whole_bundle(tmp_path):
    path = _zip(tmp_path / "locked.zip", {"secret.txt": b"x"})
    # ``zipfile`` writes no encrypted entry, so set the flag bit in the bytes: in
    # the local header (offset 6) and in the central directory (offset 8).
    data = bytearray(path.read_bytes())
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        at = data.index(signature) + offset
        data[at] |= 0x1
    path.write_bytes(bytes(data))
    with pytest.raises(tb.BundleError, match="encrypted"):
        tb.safe_extract(path, tmp_path / "out")


def test_too_many_entries_refuse_the_bundle(tmp_path):
    bundle = _zip(tmp_path / "many.zip", {f"f{i}": b"" for i in range(4)})
    assert len(tb.safe_extract(bundle, tmp_path / "ok", max_entries=4)) == 4
    with pytest.raises(tb.BundleError, match="4 entries, and the limit is 3"):
        tb.safe_extract(bundle, tmp_path / "out", max_entries=3)


def test_a_zip_bomb_stops_at_the_real_size(tmp_path):
    # 2 entries of 600 bytes each, a few bytes compressed: the second crosses 1000.
    bundle = _zip(tmp_path / "bomb.zip", {"a": b"0" * 600, "b": b"0" * 600})
    assert tb.safe_extract(bundle, tmp_path / "ok", max_bytes=1200) == ["a", "b"]
    with pytest.raises(tb.BundleError, match="larger than 0 MB"):
        tb.safe_extract(bundle, tmp_path / "out", max_bytes=1000)


def test_a_file_that_is_not_a_zip_is_refused(tmp_path):
    path = tmp_path / "text.zip"
    path.write_text("home_keeper: {}")
    with pytest.raises(tb.BundleError, match="not a zip file"):
        tb.safe_extract(path, tmp_path / "out")


def test_a_bundle_needs_its_document(tmp_path):
    bundle = _zip(tmp_path / "empty.zip", {"other.txt": b"x"})
    tb.safe_extract(bundle, tmp_path / "out")
    with pytest.raises(tb.BundleError, match=r"no home_keeper\.yaml"):
        tb.read_document_text(tmp_path / "out")
    (tmp_path / "out" / "home_keeper.yaml").write_bytes(b"\xff\xfe")
    with pytest.raises(tb.BundleError, match="not UTF-8"):
        tb.read_document_text(tmp_path / "out")


def test_the_zip_header_check():
    assert tb.is_zip_header(b"PK\x03\x04rest")
    assert tb.is_zip_header(b"PK\x05\x06")
    assert not tb.is_zip_header(b"home_keeper:")


# ── Writing a bundle ─────────────────────────────────────────────────────────


def test_write_bundle_skips_a_missing_file_and_a_companion_symlink(tmp_path):
    source = tmp_path / "manual.pdf"
    source.write_bytes(PDF)
    companion = tmp_path / "dogs"
    (companion / "photos").mkdir(parents=True)
    (companion / "photos" / "rex.jpg").write_bytes(b"rex")
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    os.symlink(secret, companion / "photos" / "leak.txt")
    os.symlink(tmp_path, companion / "loop")
    path = tmp_path / "out" / "bundle.zip"
    missing = tb.write_bundle(
        path,
        "home_keeper: {}\n",
        files=[(source, "files/home_keeper/x.pdf"), (tmp_path / "gone", "y")],
        companion_dirs={"dogs": companion},
    )
    assert missing == 1
    with zipfile.ZipFile(path) as archive:
        assert sorted(archive.namelist()) == [
            "files/dogs/photos/rex.jpg",
            "files/home_keeper/x.pdf",
            "home_keeper.yaml",
        ]
        assert archive.read("files/home_keeper/x.pdf") == PDF


# ── The files section ────────────────────────────────────────────────────────


def _asset():
    return {
        "id": "asset-1",
        "name": "Furnace",
        "documents": [
            {"id": "doc-1", "kind": "file", "name": "Manual", "filename": "m.pdf"},
            {"id": "doc-2", "kind": "link", "url": "https://example.com"},
        ],
        "parts": [{"id": "part-1", "file_name": "p.pdf"}, {"id": "part-2"}],
    }


def _task():
    return {
        "id": "task-1",
        "name": "Clean",
        "photos": [{"id": "photo-1", "name": "Before", "filename": "b.png"}],
    }


def test_bundled_files_lists_the_files_of_portable_records(tmp_path):
    owned = {**_asset(), "id": "asset-2", "managed_by": {"integration": "x"}}
    found = tb.bundled_files([_asset(), owned], [_task()])
    assert [item.entry for item in found] == [
        {
            "kind": "document",
            "appliance": "asset-1",
            "id": "doc-1",
            "name": "Manual",
            "path": "files/home_keeper/documents/asset-1/doc-1/m.pdf",
        },
        {
            "kind": "part_file",
            "appliance": "asset-1",
            "part": "part-1",
            "path": "files/home_keeper/part_files/asset-1/part-1/p.pdf",
        },
        {
            "kind": "task_photo",
            "task": "task-1",
            "id": "photo-1",
            "name": "Before",
            "path": "files/home_keeper/task_photos/task-1/photo-1/b.png",
        },
    ]
    docs, photos = tmp_path / "docs", tmp_path / "photos"
    assert (
        found[0].source(docs, photos) == (docs / "asset-1" / "doc-1__m.pdf").resolve()
    )
    assert (
        found[1].source(docs, photos)
        == (docs / "asset-1" / "part_part-1__p.pdf").resolve()
    )
    assert (
        found[2].source(docs, photos)
        == (photos / "task-1" / "photo-1__b.png").resolve()
    )


def _plan(section, *, assets=None, tasks=None, present=(), ids=None):
    stored_assets = assets or {}
    stored_tasks = tasks or {}
    return tb.plan_files(
        section,
        appliance_ids=(ids or {}).get("appliances", {}),
        task_ids=(ids or {}).get("tasks", {}),
        find_asset=stored_assets.get,
        find_task=stored_tasks.get,
        present=set(present),
    )


def test_plan_files_adds_a_file_to_a_planned_record():
    path = "files/home_keeper/documents/old/doc-1/m.pdf"
    entry = {"kind": "document", "appliance": "old", "id": "doc-1", "path": path}
    plan = _plan([entry], present=[path], ids={"appliances": {"old": "new"}})
    assert plan.problems == ()
    (action,) = plan.actions
    assert (action.kind, action.owner_id, action.item_id, action.path) == (
        "document",
        "new",
        "doc-1",
        path,
    )
    assert plan.counts() == {"created": 1, "unchanged": 0}


def test_plan_files_keeps_a_file_that_the_record_has():
    path = "files/home_keeper/documents/asset-1/doc-1/m.pdf"
    entry = {"kind": "document", "appliance": "asset-1", "id": "doc-1", "path": path}
    plan = _plan([entry, entry], assets={"asset-1": _asset()}, present=[path])
    assert plan.actions == ()
    assert plan.counts() == {"created": 0, "unchanged": 2}
    photo = "files/home_keeper/task_photos/task-1/photo-1/b.png"
    photo_entry = {
        "kind": "task_photo",
        "task": "task-1",
        "id": "photo-1",
        "path": photo,
    }
    assert (
        _plan([photo_entry], tasks={"task-1": _task()}, present=[photo]).unchanged == 1
    )
    part = "files/home_keeper/part_files/asset-1/part-1/p.pdf"
    part_entry = {
        "kind": "part_file",
        "appliance": "asset-1",
        "part": "part-1",
        "path": part,
    }
    assert (
        _plan([part_entry], assets={"asset-1": _asset()}, present=[part]).unchanged == 1
    )


@pytest.mark.parametrize(
    ("entry", "field", "phrase"),
    [
        ("text", "", "must be a mapping"),
        ({"kind": "video"}, "kind", "not a kind of file"),
        ({"kind": "document", "path": "../x"}, "path", "must start with"),
        ({"kind": "document", "path": "files/dogs/x"}, "path", "must start with"),
        (
            {"kind": "document", "path": "files/home_keeper/gone.pdf"},
            "path",
            "has no file",
        ),
        (
            {"kind": "document", "appliance": "nope", "path": "files/home_keeper/a"},
            "appliance",
            "is not a appliance",
        ),
        (
            {"kind": "document", "appliance": "asset-1", "path": "files/home_keeper/a"},
            "id",
            "is missing",
        ),
        (
            {
                "kind": "part_file",
                "appliance": "asset-1",
                "part": "part-9",
                "path": "files/home_keeper/a",
            },
            "part",
            "no part",
        ),
    ],
)
def test_plan_files_warns_and_skips_a_bad_entry(entry, field, phrase):
    plan = _plan([entry], assets={"asset-1": _asset()}, present=["files/home_keeper/a"])
    assert plan.actions == ()
    (problem,) = plan.problems
    assert problem.severity == "warning"
    assert problem.path == ("files[0]" + (f".{field}" if field else ""))
    assert phrase in problem.message


def test_plan_files_warns_on_a_section_that_is_not_a_list():
    plan = _plan({"kind": "document"})
    (problem,) = plan.problems
    assert problem.path == "files" and problem.severity == "warning"
    assert _plan(None) == tb.FilesPlan()


# ── The settings sections ────────────────────────────────────────────────────


def test_settings_sections_split_the_options():
    current = {
        "profiles": [{"id": "p"}],
        "notifications": [{"id": "n"}],
        "allow_skip": True,
    }
    assert tb.settings_sections(current) == {
        "profiles": [{"id": "p"}],
        "notifications": [{"id": "n"}],
        "options": {"allow_skip": True},
    }


def _settings(sections, current=None, *, notify=(), entities=()):
    return tb.plan_settings(
        sections,
        current=current or {},
        option_keys=("profiles", "notifications", "allow_skip", "shopping_list_entity"),
        notify_services=set(notify),
        entity_ids=set(entities),
    )


def test_profiles_merge_by_id_then_by_name_and_keep_the_rest():
    current = {
        "profiles": [
            {"id": "p1", "name": "Kitchen"},
            {"id": "p2", "name": "Garden"},
            {"id": "p3", "name": "Garage"},
        ]
    }
    plan = _settings(
        {
            "profiles": [
                {"id": "p1", "name": "Kitchen 2"},
                {"id": "other", "name": "Garden", "filter": {"labels": ["x"]}},
                {"name": "Attic"},
            ]
        },
        current,
    )
    assert plan.problems == ()
    assert plan.updates["profiles"] == [
        {"id": "p1", "name": "Kitchen 2"},
        {"id": "p2", "name": "Garden", "filter": {"labels": ["x"]}},
        {"id": "p3", "name": "Garage"},
        {"name": "Attic"},
    ]
    assert plan.counts == {"profiles": {"created": 1, "updated": 2}}


def test_a_missing_notify_target_and_todo_list_are_warnings():
    plan = _settings(
        {
            "notifications": [
                {"name": "N", "targets": ["mobile_app_a", "mobile_app_b"]}
            ],
            "profiles": [{"name": "P", "sync": {"entity_id": "todo.gone"}}],
            "options": {"shopping_list_entity": "todo.shop", "allow_skip": False},
        },
        notify=["mobile_app_a"],
        entities=["todo.shop"],
    )
    assert [(p.path, p.severity) for p in plan.problems] == [
        ("profiles[0].sync.entity_id", "warning"),
        ("notifications[0].targets[1]", "warning"),
    ]
    assert plan.updates["allow_skip"] is False
    assert plan.counts["options"] == {"changed": 2}


def test_an_unknown_option_is_a_warning_and_a_bad_shape_is_an_error():
    plan = _settings({"options": {"nope": 1, "allow_skip": True}}, {"allow_skip": True})
    (problem,) = plan.problems
    assert (problem.path, problem.severity) == ("options.nope", "warning")
    assert plan.updates == {"allow_skip": True}
    assert plan.counts == {"options": {"changed": 0}}
    bad = _settings({"options": [], "profiles": {}, "notifications": ["x"]})
    assert [(p.path, p.severity) for p in bad.problems] == [
        ("profiles", "error"),
        ("notifications[0]", "error"),
        ("options", "error"),
    ]
    assert "profiles" not in bad.updates
    assert bad.updates["notifications"] == []


def test_skipped_settings_are_named():
    problems = tb.settings_skipped({"options": {}, "profiles": []})
    assert [p.path for p in problems] == ["profiles", "options"]
    assert all(p.severity == "warning" for p in problems)
