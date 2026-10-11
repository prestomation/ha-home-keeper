"""Fakes for the Home Assistant half of the import and export.

``transfer_runner.py`` and ``transfer_http.py`` import Home Assistant. Like
``test_manuals_uploads.py``, this module loads the real files under the synthetic
``hk`` package, with fakes for their HA-coupled siblings (``devices``,
``coordinator``, ``companions``) put in ``sys.modules`` only while they load. The
fakes here then stand in for the parts of Home Assistant that the runner calls: the
service registry (with fake companion services), the bus, the config folder, the
states, the config entries and the store.

The service registry runs each companion handler with the caller's context, so a
test can prove that a companion sees the admin user, and a fake companion can raise
``Unauthorized`` for a non-admin context the way a real one does.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import hk_assets as assets_model
import hk_task_photos as task_photos
from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)
TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def _fake(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


# ── Companions ───────────────────────────────────────────────────────────────


class FakeCompanions:
    """The companion registry: rows as ``companions.async_list_companions`` gives."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def register(self, domain: str, *capabilities: str) -> None:
        self.rows.append(
            {
                "domain": domain,
                "name": domain.title(),
                "status": "connected",
                "source": "registered",
                "capabilities": list(capabilities),
            }
        )

    def module(self) -> types.ModuleType:
        return _fake(
            "hk.companions",
            async_list_companions=lambda hass: [dict(r) for r in self.rows],
            async_registration_order=lambda hass: [r["domain"] for r in self.rows],
        )


# ── Loading ──────────────────────────────────────────────────────────────────


def _load(module_name: str, file_name: str, extra: dict[str, Any]) -> types.ModuleType:
    install_ha_stubs()
    fake_devices = _fake("hk.devices", area_names=lambda hass: {})

    async def _reconcile(hass, entry, store):
        return None

    fake_devices.async_reconcile_assets = _reconcile
    fakes: dict[str, Any] = {
        "hk.devices": fake_devices,
        "hk.coordinator": _fake(
            "hk.coordinator",
            HomeKeeperCoordinator=object,
            find_coordinator=lambda hass: getattr(hass, "coord", None),
        ),
        "hk.companions": FakeCompanions().module(),
        **extra,
    }
    saved = {name: sys.modules.get(name) for name in fakes}
    package = sys.modules["hk"]
    attrs = ("devices", "coordinator", "companions")
    saved_attrs = {name: getattr(package, name, None) for name in attrs}
    sys.modules.update(fakes)
    for name in attrs:
        setattr(package, name, fakes[f"hk.{name}"])
    try:
        spec = importlib.util.spec_from_file_location(
            module_name, str(_COMPONENT_DIR / file_name)
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        for name, previous in saved_attrs.items():
            if previous is None:
                if hasattr(package, name):
                    delattr(package, name)
            else:
                setattr(package, name, previous)
    return module


def load_runner() -> types.ModuleType:
    """Load ``transfer_runner.py`` with fake siblings and a pinned clock."""
    module = _load("hk.transfer_runner", "transfer_runner.py", {})
    # Other suites put fakes of some pure siblings (``hk.options``) in
    # ``sys.modules`` at import time. Bind the real ones, as ``test_device_heal`` does.
    for name in ("options", "transfer", "transfer_bundle", "events", "documents"):
        setattr(module, name, sys.modules[f"hk_{name}"])
    module.task_photos = sys.modules["hk_task_photos"]
    module.dt_util = types.SimpleNamespace(now=lambda: NOW)
    module.ar = types.SimpleNamespace(
        async_get=lambda hass: types.SimpleNamespace(async_list_areas=lambda: [])
    )
    module.dr = types.SimpleNamespace(async_get=lambda hass: _Registry())
    return module


class _Registry:
    def async_get(self, device_id):
        return None


# ── Home Assistant ───────────────────────────────────────────────────────────

Handler = Callable[[dict[str, Any], Any], Awaitable[Any]]


class FakeServices:
    """The service registry, with the companion services that a test registers."""

    def __init__(self) -> None:
        self.handlers: dict[tuple[str, str], Handler] = {}
        self.calls: list[tuple[str, str, dict[str, Any], Any]] = []
        self.notify: set[str] = set()

    def register(self, domain: str, service: str, handler: Handler) -> None:
        self.handlers[(domain, service)] = handler

    def has_service(self, domain: str, service: str) -> bool:
        if domain == "notify":
            return service in self.notify
        return (domain, service) in self.handlers

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        blocking: bool = False,
        context: Any = None,
        return_response: bool = False,
    ) -> Any:
        assert blocking and return_response
        self.calls.append((domain, service, dict(data), context))
        return await self.handlers[(domain, service)](dict(data), context)


class FakeBus:
    def __init__(self) -> None:
        self.fired: list[tuple[str, dict[str, Any], Any]] = []

    def async_fire(self, event: str, data: dict[str, Any], context: Any = None):
        self.fired.append((event, data, context))


class FakeStates:
    def __init__(self) -> None:
        self.entities: set[str] = set()

    def get(self, entity_id: str) -> Any:
        return object() if entity_id in self.entities else None


class FakeEntries:
    def __init__(self) -> None:
        self.reloads = 0

    async def async_reload(self, entry_id: str) -> bool:
        self.reloads += 1
        return True

    def async_update_entry(self, entry: Any, *, options: dict[str, Any]) -> None:
        entry.options = dict(options)


class FakeHass:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = types.SimpleNamespace(
            language="en", path=lambda *parts: str(root.joinpath(*parts))
        )
        self.services = FakeServices()
        self.bus = FakeBus()
        self.states = FakeStates()
        self.config_entries = FakeEntries()
        self.data: dict[str, Any] = {}
        self.coord: Any = None

    async def async_add_executor_job(self, func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)


# ── The store ────────────────────────────────────────────────────────────────


class FakeStore:
    """The store methods that an import calls, on plain dicts."""

    def __init__(self, tasks=None, assets=None) -> None:
        self._tasks: dict[str, dict[str, Any]] = tasks or {}
        self._assets: dict[str, dict[str, Any]] = assets or {}
        self.writes: list[str] = []

    def get_tasks(self):
        return self._tasks

    def get_assets(self):
        return self._assets

    def get_task(self, task_id):
        return self._tasks.get(task_id)

    def get_asset(self, asset_id):
        return self._assets.get(asset_id)

    def list_tasks(self):
        return list(self._tasks.values())

    def list_assets(self):
        return list(self._assets.values())

    async def async_import_records(self, *, assets_to_write, tasks_to_write):
        for asset_id, record, _is_new in assets_to_write:
            self._assets[asset_id] = {**record, "id": asset_id}
            self.writes.append(f"asset:{asset_id}")
        for task_id, record, _is_new in tasks_to_write:
            self._tasks[task_id] = {**record, "id": task_id}
            self.writes.append(f"task:{task_id}")
        await asyncio.sleep(0)

    async def reconcile_part_tasks(self):
        return False

    async def reconcile_buy_tasks(self):
        return False

    async def add_asset_document(self, asset_id, document):
        asset = self._assets[asset_id]
        entry = assets_model.append_document(asset, document, created=NOW.isoformat())
        self.writes.append(f"document:{entry['id']}")
        return entry

    async def set_part_file(self, asset_id, part_id, meta):
        asset = self._assets[asset_id]
        part = assets_model.set_part_file(asset, part_id, meta)
        if part is None:
            raise KeyError(part_id)
        self.writes.append(f"part_file:{part_id}")
        return part

    async def add_task_photo(self, task_id, photo):
        task = self._tasks[task_id]
        entry = task_photos.append_photo(task, photo, created=NOW.isoformat())
        self.writes.append(f"photo:{entry['id']}")
        return entry


def coordinator(store: FakeStore | None = None, options: dict | None = None) -> Any:
    entry = types.SimpleNamespace(entry_id="entry", options=dict(options or {}))
    return types.SimpleNamespace(store=store or FakeStore(), entry=entry)


# ── The HTTP views ───────────────────────────────────────────────────────────


class FakeView:
    """``HomeAssistantView``: a reply is a tuple that a test can read."""

    def json_message(self, message, status=200):
        return ("message", message, int(status))

    def json(self, data):
        return ("json", data)


class FakeStreamResponse:
    def __init__(self, status: int = 200, headers: dict | None = None, **_kw) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self.body = bytearray()
        self.prepared = False
        self.ended = False

    async def prepare(self, request) -> None:
        self.prepared = True

    async def write(self, data: bytes) -> None:
        self.body += data

    async def write_eof(self) -> None:
        self.ended = True


class FakeTooLarge(Exception):
    pass


class FakePart:
    """A multipart body part: a file part when *filename* is set, else a text field."""

    def __init__(self, name: str, data: bytes, filename: str | None = None) -> None:
        self.name = name
        self.filename = filename
        self._chunks = [data[i : i + 7] for i in range(0, len(data), 7)] or [b""]

    async def read_chunk(self, size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    async def text(self) -> str:
        return b"".join(self._chunks).decode()


class FakeReader:
    def __init__(self, parts) -> None:
        self._parts = list(parts)

    async def next(self):
        return self._parts.pop(0) if self._parts else None


class FakeRequest:
    def __init__(self, hass, *, user=None, parts=(), query=None) -> None:
        self.app = {"hass": hass}
        self._data = {"hass_user": user}
        self._reader = FakeReader(parts)
        self.query = dict(query or {})
        self._client_max_size = 0

    def get(self, key):
        return self._data.get(key)

    async def multipart(self):
        return self._reader


def user(*, admin: bool = True, system: bool = False) -> Any:
    return types.SimpleNamespace(
        id="admin-user" if admin else "plain-user",
        is_admin=admin,
        system_generated=system,
    )


def load_http(runner: types.ModuleType) -> types.ModuleType:
    """Load ``transfer_http.py`` with fake aiohttp and HTTP helpers."""
    extra = {
        "aiohttp": _fake(
            "aiohttp",
            BodyPartReader=FakePart,
            hdrs=types.SimpleNamespace(
                CONTENT_DISPOSITION="Content-Disposition",
                CONTENT_TYPE="Content-Type",
                CONTENT_LENGTH="Content-Length",
            ),
            web=types.SimpleNamespace(
                Response=FakeStreamResponse,
                StreamResponse=FakeStreamResponse,
                Request=object,
                HTTPRequestEntityTooLarge=FakeTooLarge,
            ),
        ),
        "homeassistant.components.http": _fake(
            "homeassistant.components.http",
            HomeAssistantView=FakeView,
            require_admin=lambda func: func,
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
        "hk.transfer_runner": runner,
    }
    module = _load("hk.transfer_http", "transfer_http.py", extra)
    module.transfer_runner = runner
    module.transfer_bundle = sys.modules["hk_transfer_bundle"]
    module.documents = sys.modules["hk_documents"]
    module.dt_util = types.SimpleNamespace(now=lambda: NOW)
    # The view finds the coordinator at call time. The fake hass holds it.
    module._coordinator = lambda hass: hass.coord
    return module
