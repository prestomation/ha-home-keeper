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
