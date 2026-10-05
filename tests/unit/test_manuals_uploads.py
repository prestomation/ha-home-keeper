"""Upload paths in ``manuals.py`` that lose a file or leave one behind.

* B06-4: a client abort cancels the upload handler with ``CancelledError``, which
  is not an ``Exception``. The temp file must still go.
* B06-10: a part upload whose appliance was deleted during the upload must not
  keep the new blob, also for a same-name re-upload, and must not leave the
  appliance directory that the move made again.
* X02-1: an upload that spans an entry reload must not write to the replaced
  store.

``manuals.py`` imports aiohttp and Home Assistant's http component. Like
``test_card_delivery.py``, it loads here with fakes for those imports, put in
``sys.modules`` only while it loads. The views then run against a fake request,
a fake store and a temp directory. ``tests/integration/test_documents.py`` and
``test_part_files.py`` drive the real views.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest
from ha_stubs import install_ha_stubs

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"
PDF = b"%PDF-1.4\n" + b"x" * 64


def _fake(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


class _Response:
    def __init__(self, status: int = 200, **kwargs: object) -> None:
        self.status = status


class _TooLarge(Exception):
    pass


class _BodyPartReader:
    """A body part that returns *chunks*, then hangs if *hang* is set."""

    def __init__(self, filename, chunks, *, hang=False, before_end=None) -> None:
        self.name = "file"
        self.filename = filename
        self._chunks = list(chunks)
        self._hang = hang
        self._before_end = before_end
        self.reached_hang = asyncio.Event()

    async def read_chunk(self, size: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        if self._hang:
            self.reached_hang.set()
            await asyncio.Event().wait()
        if self._before_end is not None:
            self._before_end()
            self._before_end = None
        return b""

    async def text(self) -> str:
        return ""


class _View:
    def json_message(self, message, status=200):
        return ("message", message, int(status))

    def json(self, data):
        return ("json", data)


def _load() -> types.ModuleType:
    install_ha_stubs()
    fakes = {
        "aiohttp": _fake(
            "aiohttp",
            BodyPartReader=_BodyPartReader,
            hdrs=types.SimpleNamespace(CONTENT_DISPOSITION="Content-Disposition"),
            web=types.SimpleNamespace(
                Response=_Response,
                StreamResponse=_Response,
                FileResponse=_Response,
                Request=object,
                HTTPRequestEntityTooLarge=_TooLarge,
            ),
        ),
        "homeassistant.components.http": _fake(
            "homeassistant.components.http",
            HomeAssistantView=_View,
            require_admin=lambda func: func,
        ),
        "homeassistant.components.http.auth": _fake(
            "homeassistant.components.http.auth",
            async_sign_path=lambda *args, **kwargs: "/signed",
        ),
        "homeassistant.components.http.const": _fake(
            "homeassistant.components.http.const", KEY_HASS_USER="hass_user"
        ),
        "homeassistant.helpers.http": _fake(
            "homeassistant.helpers.http", KEY_HASS="hass"
        ),
        "hk.backend_i18n": _fake(
            "hk.backend_i18n", resolve_exception=lambda lang, key, **kw: key
        ),
    }
    saved = {name: sys.modules.get(name) for name in fakes}
    sys.modules.update(fakes)
    try:
        spec = importlib.util.spec_from_file_location(
            "hk.manuals_under_test", str(_COMPONENT / "manuals.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        # ``dataclass`` reads the module's namespace from ``sys.modules``.
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


manuals = _load()


class _Hass:
    def __init__(self, root: Path) -> None:
        self.config = types.SimpleNamespace(
            language="en", path=lambda *parts: str(root.joinpath(*parts))
        )
        self.coord: object | None = None
        self.data: dict = {}

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _Store:
    def __init__(self, assets: dict) -> None:
        self.assets = assets
        self.writes: list[str] = []

    def get_asset(self, asset_id):
        return self.assets.get(asset_id)

    async def add_asset_document(self, asset_id, document):
        self.writes.append("add_asset_document")
        return {**document}

    async def set_part_file(self, asset_id, part_id, meta):
        self.writes.append("set_part_file")
        # The appliance was deleted in another tab while the body streamed.
        self.assets.pop(asset_id, None)
        raise KeyError(asset_id)


class _Reader:
    def __init__(self, parts) -> None:
        self._parts = list(parts)
        self.hang_after = False
        self.reached_hang = asyncio.Event()

    async def next(self):
        if self._parts:
            return self._parts.pop(0)
        if self.hang_after:
            self.reached_hang.set()
            await asyncio.Event().wait()
        return None


class _Request:
    def __init__(self, hass, reader) -> None:
        self.app = {"hass": hass}
        self._data = {"hass_user": types.SimpleNamespace(system_generated=False)}
        self._reader = reader

    def get(self, key):
        return self._data.get(key)

    async def multipart(self):
        return self._reader


@pytest.fixture
def hass(tmp_path, monkeypatch):
    instance = _Hass(tmp_path)
    monkeypatch.setattr(manuals, "_coordinator", lambda hass: hass.coord)
    return instance


def _incoming(tmp_path: Path) -> list[str]:
    tmp_root = tmp_path / manuals.MANUALS_SUBDIR / manuals._TMP_SUBDIR
    return sorted(p.name for p in tmp_root.iterdir()) if tmp_root.exists() else []


async def _cancel_when(task: asyncio.Task, event: asyncio.Event) -> None:
    await event.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── B06-4 ────────────────────────────────────────────────────────────────────
def test_b06_4_a_cancel_mid_body_removes_the_temp_file(hass, tmp_path):
    part = _BodyPartReader("manual.pdf", [PDF], hang=True)

    async def _run() -> None:
        task = asyncio.ensure_future(manuals._stream_to_temp(hass, part))
        await _cancel_when(task, part.reached_hang)

    asyncio.run(_run())
    assert _incoming(tmp_path) == []


def test_b06_4_a_cancel_between_parts_removes_the_temp_file(hass, tmp_path):
    reader = _Reader([_BodyPartReader("manual.pdf", [PDF])])
    reader.hang_after = True

    async def _run() -> None:
        task = asyncio.ensure_future(
            manuals._parse_upload(hass, _View(), _Request(hass, reader))
        )
        await _cancel_when(task, reader.reached_hang)

    asyncio.run(_run())
    assert _incoming(tmp_path) == []


def test_b06_4_a_finished_body_keeps_its_temp_file(hass, tmp_path):
    reader = _Reader([_BodyPartReader("manual.pdf", [PDF])])
    uploaded, filename, _ = asyncio.run(
        manuals._parse_upload(hass, _View(), _Request(hass, reader))
    )
    assert filename == "manual.pdf"
    assert uploaded.path.read_bytes() == PDF
    assert _incoming(tmp_path) == [uploaded.path.name]


# ── B06-10 ───────────────────────────────────────────────────────────────────
def test_b06_10_a_same_name_part_upload_to_a_deleted_appliance_leaves_no_file(
    hass, tmp_path
):
    asset = {
        "id": "a1",
        "parts": [{"id": "p1", "name": "Filter", "file_name": "manual.pdf"}],
    }
    store = _Store({"a1": asset})
    hass.coord = types.SimpleNamespace(store=store)
    reader = _Reader([_BodyPartReader("manual.pdf", [PDF])])

    result = asyncio.run(
        manuals.HomeKeeperPartFileView().post(_Request(hass, reader), "a1", "p1")
    )

    assert result[0] == "message"
    assert result[2] == 400
    assert store.writes == ["set_part_file"]
    assert not (tmp_path / manuals.MANUALS_SUBDIR / "a1").exists()
    assert _incoming(tmp_path) == []


# ── X02-1 ────────────────────────────────────────────────────────────────────
def test_x02_1_an_upload_that_spans_a_reload_writes_no_store(hass, tmp_path):
    old = _Store({"a1": {"id": "a1", "documents": []}})
    new = _Store({"a1": {"id": "a1", "documents": []}})
    hass.coord = types.SimpleNamespace(store=old)

    def _reload() -> None:
        hass.coord = types.SimpleNamespace(store=new)

    reader = _Reader([_BodyPartReader("manual.pdf", [PDF], before_end=_reload)])
    result = asyncio.run(
        manuals.HomeKeeperDocumentView().post(
            _Request(hass, reader), "a1", "3f2c8a1e-5b6d-4c7e-8f90-a1b2c3d4e5f6"
        )
    )

    assert result == ("message", "integration_not_loaded", 404)
    assert old.writes == []
    assert new.writes == []
    assert not (tmp_path / manuals.MANUALS_SUBDIR / "a1").exists()
    assert _incoming(tmp_path) == []


def test_x02_1_an_upload_with_no_reload_writes_the_store(hass, tmp_path):
    store = _Store({"a1": {"id": "a1", "documents": []}})
    hass.coord = types.SimpleNamespace(store=store)
    reader = _Reader([_BodyPartReader("manual.pdf", [PDF])])
    document_id = "3f2c8a1e-5b6d-4c7e-8f90-a1b2c3d4e5f6"

    result = asyncio.run(
        manuals.HomeKeeperDocumentView().post(_Request(hass, reader), "a1", document_id)
    )

    assert result[0] == "json"
    assert store.writes == ["add_asset_document"]
    stored = tmp_path / manuals.MANUALS_SUBDIR / "a1" / f"{document_id}__manual.pdf"
    assert stored.read_bytes() == PDF
    assert _incoming(tmp_path) == []


# ── task photos (#399) ───────────────────────────────────────────────────────
def _png(size=(40, 30)) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, "PNG")
    return buffer.getvalue()


PHOTO_ID = "3f2c8a1e-5b6d-4c7e-8f90-a1b2c3d4e5f6"


class _TaskStore:
    def __init__(self, tasks: dict, *, fail: Exception | None = None) -> None:
        self.tasks = tasks
        self.fail = fail
        self.added: list[dict] = []

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    async def add_task_photo(self, task_id, photo):
        if self.fail is not None:
            if isinstance(self.fail, KeyError):
                self.tasks.pop(task_id, None)
            raise self.fail
        self.added.append(photo)
        self.tasks[task_id].setdefault("photos", []).append(photo)
        return photo


class _PhotoRequest(_Request):
    def __init__(self, hass, reader, query=None) -> None:
        super().__init__(hass, reader)
        self.query = query or {}


def _task_dir(tmp_path: Path, task_id: str = "t1") -> Path:
    return tmp_path / manuals.TASK_PHOTOS_SUBDIR / task_id


def _post_photo(hass, filename, data):
    reader = _Reader([_BodyPartReader(filename, [data])])
    return asyncio.run(
        manuals.HomeKeeperTaskPhotoView().post(
            _PhotoRequest(hass, reader), "t1", PHOTO_ID
        )
    )


def test_a_task_photo_upload_stores_the_file_and_a_thumbnail(hass, tmp_path):
    store = _TaskStore({"t1": {"id": "t1"}})
    hass.coord = types.SimpleNamespace(store=store)
    data = _png()

    result = _post_photo(hass, "Attic gap.png", data)

    assert result[0] == "json"
    assert store.added == [
        {
            "id": PHOTO_ID,
            "name": "Attic gap.png",
            "filename": "Attic_gap.png",
            "content_type": "image/png",
            "size": len(data),
        }
    ]
    folder = _task_dir(tmp_path)
    assert (folder / f"{PHOTO_ID}__Attic_gap.png").read_bytes() == data
    assert (folder / f"thumb_{PHOTO_ID}__thumb.jpg").is_file()
    assert _incoming(tmp_path) == []


def test_a_task_photo_upload_refuses_a_pdf(hass, tmp_path):
    store = _TaskStore({"t1": {"id": "t1"}})
    hass.coord = types.SimpleNamespace(store=store)

    result = _post_photo(hass, "manual.pdf", PDF)

    assert result == ("message", "invalid_task", 400)
    assert store.added == []
    assert not _task_dir(tmp_path).exists()
    assert _incoming(tmp_path) == []


def test_a_task_photo_that_does_not_decode_leaves_nothing(hass, tmp_path):
    store = _TaskStore({"t1": {"id": "t1"}})
    hass.coord = types.SimpleNamespace(store=store)

    result = _post_photo(hass, "fake.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 64)

    assert result == ("message", "invalid_task", 400)
    assert store.added == []
    assert list(_task_dir(tmp_path).glob("*")) == []
    assert _incoming(tmp_path) == []


def test_a_task_photo_upload_to_an_unknown_task(hass, tmp_path):
    hass.coord = types.SimpleNamespace(store=_TaskStore({}))

    result = _post_photo(hass, "a.png", _png())

    assert result == ("message", "task_not_found", 404)
    assert _incoming(tmp_path) == []


def test_a_task_photo_upload_to_a_task_deleted_meanwhile_leaves_no_folder(
    hass, tmp_path
):
    store = _TaskStore({"t1": {"id": "t1"}}, fail=KeyError("t1"))
    hass.coord = types.SimpleNamespace(store=store)

    result = _post_photo(hass, "a.png", _png())

    assert result == ("message", "task_not_found", 404)
    assert not _task_dir(tmp_path).exists()
    assert _incoming(tmp_path) == []


def test_a_task_photo_upload_to_a_full_task_removes_its_files(hass, tmp_path):
    from hk_models import TaskValidationError

    store = _TaskStore({"t1": {"id": "t1"}}, fail=TaskValidationError("full"))
    hass.coord = types.SimpleNamespace(store=store)

    result = _post_photo(hass, "a.png", _png())

    assert result == ("message", "invalid_task", 400)
    assert list(_task_dir(tmp_path).glob("*")) == []


def test_a_task_photo_upload_with_a_taken_id_gets_a_new_one(hass, tmp_path):
    store = _TaskStore({"t1": {"id": "t1", "photos": [{"id": PHOTO_ID}]}})
    hass.coord = types.SimpleNamespace(store=store)

    _post_photo(hass, "a.png", _png())

    new_id = store.added[0]["id"]
    assert new_id != PHOTO_ID
    assert (_task_dir(tmp_path) / f"{new_id}__a.png").is_file()


def test_a_task_photo_upload_with_an_id_in_flight_gets_a_new_one(hass, tmp_path):
    # A double submit: the first upload with this id has not saved its record yet.
    # The second must not write to the same path.
    uploads = hass.data.setdefault(manuals._PHOTO_UPLOADS_KEY, set())
    uploads.add(("t1", PHOTO_ID))
    store = _TaskStore({"t1": {"id": "t1"}})
    hass.coord = types.SimpleNamespace(store=store)

    _post_photo(hass, "a.png", _png())

    new_id = store.added[0]["id"]
    assert new_id != PHOTO_ID
    assert (_task_dir(tmp_path) / f"{new_id}__a.png").is_file()
    assert not (_task_dir(tmp_path) / f"{PHOTO_ID}__a.png").exists()
    # The upload frees its own id when it ends, and leaves the other one alone.
    assert uploads == {("t1", PHOTO_ID)}


def test_a_task_photo_upload_holds_its_id_until_the_record_is_saved(hass, tmp_path):
    seen: list[set] = []

    class _Watching(_TaskStore):
        async def add_task_photo(self, task_id, photo):
            seen.append(set(hass.data[manuals._PHOTO_UPLOADS_KEY]))
            return await super().add_task_photo(task_id, photo)

    hass.coord = types.SimpleNamespace(store=_Watching({"t1": {"id": "t1"}}))
    _post_photo(hass, "a.png", _png())
    assert seen == [{("t1", PHOTO_ID)}]
    assert hass.data[manuals._PHOTO_UPLOADS_KEY] == set()


def test_a_task_photo_upload_to_a_full_task_stops_before_the_body(hass, tmp_path):
    photos = [{"id": f"p{i}"} for i in range(manuals.MAX_TASK_PHOTOS)]
    hass.coord = types.SimpleNamespace(
        store=_TaskStore({"t1": {"id": "t1", "photos": photos}})
    )
    reader = _Reader([_BodyPartReader("a.png", [_png()])])

    result = asyncio.run(
        manuals.HomeKeeperTaskPhotoView().post(
            _PhotoRequest(hass, reader), "t1", PHOTO_ID
        )
    )

    assert result == ("message", "invalid_task", 400)
    assert len(reader._parts) == 1
    assert not _task_dir(tmp_path).exists()


def test_a_task_photo_upload_to_one_below_the_cap_is_read(hass, tmp_path):
    photos = [{"id": f"p{i}"} for i in range(manuals.MAX_TASK_PHOTOS - 1)]
    store = _TaskStore({"t1": {"id": "t1", "photos": photos}})
    hass.coord = types.SimpleNamespace(store=store)

    result = _post_photo(hass, "a.png", _png())

    assert result[0] == "json"
    assert len(store.added) == 1


def test_a_task_photo_upload_across_an_unload_removes_its_files(hass, tmp_path):
    from hk_models import StoreClosedError

    store = _TaskStore({"t1": {"id": "t1"}}, fail=StoreClosedError("closed"))
    hass.coord = types.SimpleNamespace(store=store)

    result = _post_photo(hass, "a.png", _png())

    assert result == ("message", "integration_not_loaded", 404)
    assert list(_task_dir(tmp_path).glob("*")) == []
    assert hass.data[manuals._PHOTO_UPLOADS_KEY] == set()


def test_a_task_photo_upload_needs_a_real_user(hass, tmp_path):
    hass.coord = types.SimpleNamespace(store=_TaskStore({"t1": {"id": "t1"}}))
    request = _PhotoRequest(hass, _Reader([]))
    request._data["hass_user"] = types.SimpleNamespace(system_generated=True)

    result = asyncio.run(
        manuals.HomeKeeperTaskPhotoView().post(request, "t1", PHOTO_ID)
    )

    assert result == ("message", "upload_requires_user", 401)


def test_a_photo_upload_stops_at_its_own_limit(hass, tmp_path):
    reader = _Reader([_BodyPartReader("a.png", [b"x" * 11])])
    result = asyncio.run(
        manuals._parse_upload(hass, _View(), _Request(hass, reader), max_bytes=10)
    )
    assert result == ("message", "file_too_large", 413)
    assert _incoming(tmp_path) == []


def test_a_photo_upload_at_its_limit_is_read(hass, tmp_path):
    reader = _Reader([_BodyPartReader("a.png", [b"x" * 10])])
    uploaded, _, _ = asyncio.run(
        manuals._parse_upload(hass, _View(), _Request(hass, reader), max_bytes=10)
    )
    assert uploaded.size == 10


def _get_photo(hass, photo_id, query=None):
    return asyncio.run(
        manuals.HomeKeeperTaskPhotoView().get(
            _PhotoRequest(hass, _Reader([]), query), "t1", photo_id
        )
    )


def test_a_task_photo_get_serves_the_original_or_the_thumbnail(
    hass, tmp_path, monkeypatch
):
    served: list[Path] = []
    monkeypatch.setattr(
        manuals.web,
        "FileResponse",
        lambda path, headers: served.append(Path(path)) or ("file", headers),
        raising=False,
    )
    store = _TaskStore({"t1": {"id": "t1"}})
    hass.coord = types.SimpleNamespace(store=store)
    _post_photo(hass, "a.png", _png())

    original = _get_photo(hass, PHOTO_ID)
    thumb = _get_photo(hass, PHOTO_ID, {"size": "thumb"})

    assert served == [
        (_task_dir(tmp_path) / f"{PHOTO_ID}__a.png").resolve(),
        (_task_dir(tmp_path) / f"thumb_{PHOTO_ID}__thumb.jpg").resolve(),
    ]
    assert original[1]["Content-Disposition"].startswith('inline; filename="a.png"')
    assert thumb[1]["Content-Disposition"] == 'inline; filename="thumb.jpg"'


def test_a_task_photo_get_of_an_unknown_photo_is_404(hass, tmp_path):
    hass.coord = types.SimpleNamespace(store=_TaskStore({"t1": {"id": "t1"}}))
    assert _get_photo(hass, "nope").status == 404


def test_a_task_photo_get_of_a_missing_file_is_404(hass, tmp_path):
    photo = {"id": PHOTO_ID, "filename": "gone.png"}
    hass.coord = types.SimpleNamespace(
        store=_TaskStore({"t1": {"id": "t1", "photos": [photo]}})
    )
    assert _get_photo(hass, PHOTO_ID).status == 404


def test_the_sweep_removes_only_the_folders_of_gone_tasks(hass, tmp_path):
    root = tmp_path / manuals.TASK_PHOTOS_SUBDIR
    for name in ("live", "gone", ".incoming"):
        (root / name).mkdir(parents=True)
        (root / name / "x").write_bytes(b"x")

    asyncio.run(manuals.async_sweep_task_photos(hass, {"live": {"id": "live"}}))

    assert sorted(p.name for p in root.iterdir()) == [".incoming", "live"]


def test_the_sweep_removes_stray_files_of_a_live_task(hass, tmp_path):
    folder = _task_dir(tmp_path)
    folder.mkdir(parents=True)
    names = [
        "a__gap.jpg",
        "thumb_a__thumb.jpg",
        "old__x.jpg",
        "thumb_old__thumb.jpg",
        "busy__y.jpg",
        "thumb_busy__thumb.jpg",
    ]
    for name in names:
        (folder / name).write_bytes(b"x")
    # An upload with the id "busy" is in flight: its files stay.
    hass.data[manuals._PHOTO_UPLOADS_KEY] = {("t1", "busy")}
    task = {"id": "t1", "photos": [{"id": "a", "filename": "gap.jpg"}]}

    asyncio.run(manuals.async_sweep_task_photos(hass, {"t1": task}))

    assert sorted(p.name for p in folder.iterdir()) == [
        "a__gap.jpg",
        "busy__y.jpg",
        "thumb_a__thumb.jpg",
        "thumb_busy__thumb.jpg",
    ]


def test_the_sweep_keeps_the_folder_of_an_upload_in_flight(hass, tmp_path):
    folder = _task_dir(tmp_path, "new")
    folder.mkdir(parents=True)
    (folder / "busy__y.jpg").write_bytes(b"x")
    hass.data[manuals._PHOTO_UPLOADS_KEY] = {("new", "busy")}

    asyncio.run(manuals.async_sweep_task_photos(hass, {}))

    assert (folder / "busy__y.jpg").is_file()


def test_the_sweep_with_no_photo_folder_does_nothing(hass, tmp_path):
    asyncio.run(manuals.async_sweep_task_photos(hass, {"live": {"id": "live"}}))
    assert not (tmp_path / manuals.TASK_PHOTOS_SUBDIR).exists()


def test_deleting_a_task_photo_removes_the_file_and_the_thumbnail(hass, tmp_path):
    hass.coord = types.SimpleNamespace(store=_TaskStore({"t1": {"id": "t1"}}))
    _post_photo(hass, "a.png", _png())

    asyncio.run(manuals.async_delete_task_photo(hass, "t1", PHOTO_ID, "a.png"))

    assert list(_task_dir(tmp_path).iterdir()) == []


def test_uninstall_removes_the_photo_tree(hass, tmp_path):
    hass.coord = types.SimpleNamespace(store=_TaskStore({"t1": {"id": "t1"}}))
    _post_photo(hass, "a.png", _png())

    asyncio.run(manuals.async_delete_all_documents(hass))

    assert not (tmp_path / manuals.TASK_PHOTOS_SUBDIR).exists()
