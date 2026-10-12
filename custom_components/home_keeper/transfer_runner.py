"""Running the portable document against a live Home Assistant.

``transfer.py`` decides *what* an import does, with no Home Assistant in sight so the
whole decision is unit-testable. This module is the half that needs the running
system: the registries a document's names resolve against, the device provisioning a
new appliance triggers, and the entry reload that rebuilds the entity set afterwards.

It also calls the companions. A companion with the ``import_export`` capability
exports and imports its own top-level section through its ``export_data`` and
``import_data`` services (docs/INTEGRATING.md §11). A bundle (a zip file) adds the
uploaded files and the settings, which ``transfer_bundle.py`` plans.

It lives apart from ``__init__.py`` for one reason: the service and its websocket twin
must run the *same* code, and ``websocket_api`` cannot import ``__init__`` — the same
split, and the same reason, as ``notifications.py`` (pure) and ``notifier.py``.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import shutil
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from . import (
    companions,
    device_compat,
    devices,
    documents,
    events,
    options,
    task_photos,
    transfer,
    transfer_bundle,
)
from .assets import AssetValidationError
from .const import (
    BUNDLE_FILES_DIR,
    COMPANION_CAPABILITY_IMPORT_EXPORT,
    COMPANION_TRANSFER_TIMEOUT_S,
    DOMAIN,
    EVENT_DATA_EXPORTED,
    EVENT_DATA_IMPORTED,
    EXPORTS_SUBDIR,
    IMPORT_EXPORT_SUBDIR,
    MANUALS_SUBDIR,
    PANEL_VERSION,
    TASK_PHOTOS_SUBDIR,
)
from .coordinator import HomeKeeperCoordinator
from .models import StoreClosedError, TaskValidationError

_LOGGER = logging.getLogger(__name__)

# A run folder older than this is stale: no export or import runs for so long.
_RUN_MAX_AGE_S = 24 * 60 * 60

KIND_DATA = "data"
KIND_BUNDLE = "bundle"


# ── Run folders ──────────────────────────────────────────────────────────────


def runs_root(hass: HomeAssistant) -> Path:
    """The folder that holds 1 work folder for each bundle export or import."""
    return Path(hass.config.path(IMPORT_EXPORT_SUBDIR))


def _make_run(root: Path) -> Path:
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _purge_runs(root: Path, max_age_s: float) -> None:
    """Delete the run folders that are older than *max_age_s*. Blocking."""
    if not root.is_dir():
        return
    cutoff = time.time() - max_age_s
    for path in root.iterdir():
        try:
            if path.stat().st_mtime < cutoff:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
        except OSError:
            continue


async def async_new_run(hass: HomeAssistant) -> Path:
    """Make a new, empty run folder and return its path."""
    return await hass.async_add_executor_job(_make_run, runs_root(hass))


async def async_remove_run(hass: HomeAssistant, path: Path) -> None:
    """Delete a run folder, also if the caller is cancelled."""
    await asyncio.shield(hass.async_add_executor_job(_remove_tree, path))


async def async_cleanup_runs(hass: HomeAssistant) -> None:
    """Delete the run folders that a restart left (called at setup).

    Age-based, like ``manuals.async_cleanup_temp_uploads``: setup runs again on each
    entry reload, and a run in flight must keep its folder.
    """
    await hass.async_add_executor_job(_purge_runs, runs_root(hass), _RUN_MAX_AGE_S)


# ── Companions ───────────────────────────────────────────────────────────────


def companion_states(hass: HomeAssistant, service: str) -> dict[str, str]:
    """The state of each installed, registered companion, in registration order.

    ``ready`` means that the companion has the ``import_export`` capability and the
    service ``<domain>.<service>``. A companion with a domain that Home Keeper uses
    for its own sections is left out.
    """
    rows = {
        row.get("domain"): row
        for row in companions.async_list_companions(hass)
        if row.get("source") == "registered"
    }
    states: dict[str, str] = {}
    for domain in companions.async_registration_order(hass):
        row = rows.get(domain)
        if row is None or domain in transfer.RESERVED_SECTIONS:
            continue
        if COMPANION_CAPABILITY_IMPORT_EXPORT not in (row.get("capabilities") or []):
            states[domain] = transfer.COMPANION_NO_CAPABILITY
        elif not hass.services.has_service(domain, service):
            states[domain] = transfer.COMPANION_NO_SERVICE
        else:
            states[domain] = transfer.COMPANION_READY
    return states


async def _call_companion(
    hass: HomeAssistant,
    domain: str,
    service: str,
    data: dict[str, Any],
    context: Context | None,
) -> tuple[Any, str | None]:
    """Call a companion service and return ``(response, error message)``.

    The call carries the caller's context, so the admin check of the companion sees
    the user. A failure or a timeout gives an error message and no response.
    """
    try:
        async with asyncio.timeout(COMPANION_TRANSFER_TIMEOUT_S):
            response = await hass.services.async_call(
                domain,
                service,
                data,
                blocking=True,
                context=context,
                return_response=True,
            )
    except TimeoutError:
        return None, (
            f"the companion {domain} did not answer in "
            f"{COMPANION_TRANSFER_TIMEOUT_S} seconds"
        )
    except Exception as err:  # a companion can raise any error
        _LOGGER.warning("The %s.%s service failed: %s", domain, service, err)
        return None, f"the companion {domain} failed: {err}"
    return response, None


def _is_export(response: Any) -> bool:
    """Whether a companion export response has the shape of §11."""
    if not isinstance(response, dict):
        return False
    declared = response.get("format")
    return isinstance(declared, int) and not isinstance(declared, bool)


def _record_count(value: Any) -> int:
    """The number of records in a section, for the event payload."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sum(len(item) for item in value.values() if isinstance(item, list))
    return 0


# ── Export ───────────────────────────────────────────────────────────────────


async def _async_build_export(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    data: dict[str, Any],
    context: Context | None,
    *,
    run_dir: Path | None,
) -> tuple[dict[str, Any], list[transfer_bundle.BundledFile], dict[str, Path]]:
    """Build the document of an export, with the companion sections.

    *run_dir* is set for a bundle. Then each companion gets a ``files_dir`` in it,
    and the document gets the uploaded files of Home Keeper.
    """
    bundle = run_dir is not None
    states = companion_states(hass, "export_data")
    sections, domains, settings, unknown = transfer.resolve_include(
        data.get("include"), companions=list(states), bundle=bundle
    )
    if unknown:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_export_section",
            translation_placeholders={"sections": ", ".join(unknown)},
        )
    document = transfer.build_document(
        coord.store.list_tasks(),
        coord.store.list_assets(),
        area_names=devices.area_names(hass),
        version=PANEL_VERSION,
        now=dt_util.now(),
        include=sections,
        files_travel=bundle,
    )
    if settings:
        document.update(
            transfer_bundle.settings_sections(options.current_options(coord.entry))
        )
    files: list[transfer_bundle.BundledFile] = []
    if bundle:
        files = [
            item
            for item in transfer_bundle.bundled_files(
                coord.store.list_assets(), coord.store.list_tasks()
            )
            if ("tasks" if item.kind == "task_photo" else "appliances") in sections
        ]
    skipped: dict[str, str] = {}
    folders: dict[str, Path] = {}
    for domain in domains:
        if states[domain] != transfer.COMPANION_READY:
            skipped[domain] = states[domain]
            continue
        payload: dict[str, Any] = {}
        if run_dir is not None:
            folder = run_dir / domain
            await hass.async_add_executor_job(folder.mkdir)
            payload["files_dir"] = str(folder)
            folders[domain] = folder
        response, error = await _call_companion(
            hass, domain, "export_data", payload, context
        )
        if error is not None or not _is_export(response):
            skipped[domain] = transfer.COMPANION_FAILED
            folders.pop(domain, None)
            continue
        document[domain] = dict(response)
    if skipped:
        document["home_keeper"].setdefault("skipped", {})["companions"] = skipped
    return document, files, folders


def _export_sections(document: dict[str, Any]) -> dict[str, int]:
    """The record count of each section of an export, for the event."""
    found: dict[str, int] = {}
    for key, value in document.items():
        if key == "home_keeper":
            continue
        if key not in transfer.RESERVED_SECTIONS and isinstance(value, dict):
            # A companion section: the records are in its ``data``.
            value = value.get("data")
        found[key] = _record_count(value)
    return found


async def async_export_document(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    data: dict[str, Any],
    *,
    context: Context | None = None,
) -> dict[str, Any]:
    """Build the portable document. Shared by the service and its websocket twin.

    The YAML is written in the executor (B03-3). PyYAML is pure Python here, and a
    household with a long history takes seconds to write, which would stop the event
    loop for that time. The executor gets a deep copy, because the document can share
    nested values with the live store, which the loop can change in the meantime.
    """
    document, _files, _folders = await _async_build_export(
        hass, coord, data, context, run_dir=None
    )
    text = await hass.async_add_executor_job(
        transfer.document_to_yaml, copy.deepcopy(document)
    )
    hass.bus.async_fire(
        EVENT_DATA_EXPORTED,
        events.data_transfer_event_data(KIND_DATA, _export_sections(document)),
        context=context,
    )
    return {"document": document, "yaml": text}


def default_bundle_path(hass: HomeAssistant) -> Path:
    """Where the ``export_data`` service writes a bundle: 1 file for each day."""
    name = f"home-keeper-{dt_util.now().date().isoformat()}.zip"
    return Path(hass.config.path(EXPORTS_SUBDIR)) / name


def _sources(
    files: list[transfer_bundle.BundledFile], documents_root: Path, photos_root: Path
) -> list[tuple[transfer_bundle.BundledFile, Path]]:
    """The files that are on disk, with their paths. Blocking."""
    found: list[tuple[transfer_bundle.BundledFile, Path]] = []
    for item in files:
        try:
            source = item.source(documents_root, photos_root)
        except AssetValidationError:
            continue
        if source.is_file() and not source.is_symlink():
            found.append((item, source))
    return found


async def async_export_bundle(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    data: dict[str, Any],
    *,
    context: Context | None = None,
    zip_path: Path | None = None,
) -> dict[str, Any]:
    """Write a bundle to *zip_path*, or to :func:`default_bundle_path`.

    Returns ``{path, size, skipped}``. The companions fill their folders in a new run
    folder, and the run folder is deleted at the end, also after an error.
    """
    target = zip_path or default_bundle_path(hass)
    run_dir = await async_new_run(hass)
    try:
        document, files, folders = await _async_build_export(
            hass, coord, data, context, run_dir=run_dir
        )
        documents_root = Path(hass.config.path(MANUALS_SUBDIR))
        photos_root = Path(hass.config.path(TASK_PHOTOS_SUBDIR))
        present = await hass.async_add_executor_job(
            _sources, files, documents_root, photos_root
        )
        if files:
            document[transfer.FILES_SECTION] = [item.entry for item, _ in present]
        if missing := len(files) - len(present):
            document["home_keeper"].setdefault("skipped", {})["missing_files"] = missing
        text = await hass.async_add_executor_job(
            transfer.document_to_yaml, copy.deepcopy(document)
        )

        def _write() -> int:
            partial = target.with_name(f".{target.name}.part")
            transfer_bundle.write_bundle(
                partial,
                text,
                files=[(source, item.entry["path"]) for item, source in present],
                companion_dirs=folders,
            )
            os.replace(partial, target)
            return target.stat().st_size

        size = await hass.async_add_executor_job(_write)
    finally:
        await async_remove_run(hass, run_dir)
    hass.bus.async_fire(
        EVENT_DATA_EXPORTED,
        events.data_transfer_event_data(KIND_BUNDLE, _export_sections(document)),
        context=context,
    )
    return {
        "path": str(target),
        "size": size,
        "skipped": dict(document["home_keeper"].get("skipped") or {}),
    }


async def async_export(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    data: dict[str, Any],
    *,
    context: Context | None = None,
) -> dict[str, Any]:
    """The ``export_data`` service: a YAML document, or a bundle on disk."""
    if data.get("kind") == KIND_BUNDLE:
        return await async_export_bundle(hass, coord, data, context=context)
    return await async_export_document(hass, coord, data, context=context)


# ── Import ───────────────────────────────────────────────────────────────────


class _Entities:
    """``in`` answers whether an entity id has a state on this install."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def __contains__(self, entity_id: object) -> bool:
        return self._hass.states.get(str(entity_id)) is not None


class _NotifyServices:
    """``in`` answers whether ``notify.<name>`` exists on this install."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def __contains__(self, name: object) -> bool:
        return self._hass.services.has_service("notify", str(name))


def _bundle_by_name(hass: HomeAssistant, name: Any) -> Path | None:
    """The bundle called *name* in the exports folder, or ``None``. Blocking.

    *name* is a file name only, so a caller cannot read a file outside that folder.
    """
    text = str(name or "")
    if not text or text != PurePosixPath(text).name or "\\" in text:
        return None
    if text.startswith("."):
        return None
    path = Path(hass.config.path(EXPORTS_SUBDIR)) / text
    return path if path.is_file() and not path.is_symlink() else None


def _present_files(root: Path) -> set[str]:
    """The names of the Home Keeper files in an extracted bundle. Blocking."""
    base = root / transfer_bundle.HOME_KEEPER_FILES
    if not base.is_dir():
        return set()
    return {
        path.relative_to(root).as_posix()
        for path in base.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _check_file(root: Path, action: transfer_bundle.FileAction) -> tuple[str, str, int]:
    """Check the type and size of a bundled file. Blocking.

    Returns ``(content_type, safe file name, size)``, or raises ``ValueError`` with
    the reason. The type comes from the first bytes, as for an upload.
    """
    path = root / action.path
    size = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(documents.SNIFF_BYTES)
    name = PurePosixPath(action.path).name
    if action.kind == "task_photo":
        content_type, safe = task_photos.validate_photo_upload(name, header, size)
    else:
        content_type, safe = documents.validate_upload_stream(name, header, size)
    return content_type, safe, size


async def _async_check_files(
    hass: HomeAssistant, root: Path, plan: transfer_bundle.FilesPlan
) -> tuple[transfer_bundle.FilesPlan, list[transfer.Problem]]:
    """Drop the actions whose file has a bad type or size, with a warning each."""
    kept: list[transfer_bundle.FileAction] = []
    problems: list[transfer.Problem] = []
    for action in plan.actions:
        try:
            await hass.async_add_executor_job(_check_file, root, action)
        except (ValueError, OSError) as err:
            problems.append(_file_problem(action, str(err)))
            continue
        kept.append(action)
    return (
        transfer_bundle.FilesPlan(tuple(kept), plan.unchanged, plan.problems),
        problems,
    )


def _file_problem(action: transfer_bundle.FileAction, reason: str) -> transfer.Problem:
    return transfer.Problem(
        section=transfer.FILES_SECTION,
        index=action.index,
        path=f"{transfer.FILES_SECTION}[{action.index}].path",
        message=f'the file "{action.path}" was not imported: {reason}',
        severity="warning",
    )


def _id_maps(
    document: dict[str, Any], plan: transfer.ImportPlan
) -> tuple[dict[str, str], dict[str, str]]:
    """Map each id that the document states to the id of its planned record."""
    maps: dict[str, dict[str, str]] = {"appliances": {}, "tasks": {}}
    for record in plan.records:
        rows = document.get(record.section)
        if not isinstance(rows, list) or record.index >= len(rows):
            continue
        row = rows[record.index]
        if isinstance(row, dict):
            for key in ("id", "external_id", "name"):
                if row.get(key):
                    maps[record.section].setdefault(str(row[key]), record.record_id)
        maps[record.section].setdefault(record.record_id, record.record_id)
    return maps["appliances"], maps["tasks"]


def _plan_files(
    coord: HomeKeeperCoordinator,
    files: Any,
    document: dict[str, Any],
    plan: transfer.ImportPlan,
    present: set[str],
) -> transfer_bundle.FilesPlan:
    appliance_ids, task_ids = _id_maps(document, plan)
    return transfer_bundle.plan_files(
        files,
        appliance_ids=appliance_ids,
        task_ids=task_ids,
        find_asset=coord.store.get_asset,
        find_task=coord.store.get_task,
        present=present,
    )


def _place_file(source: Path, target: Path) -> None:
    transfer_bundle.copy_file(source, target)


def _place_photo(source: Path, target: Path, thumb: Path) -> None:
    from .photo_thumbs import make_thumbnail  # lazy: Pillow only when needed

    make_thumbnail(source, thumb)
    try:
        transfer_bundle.copy_file(source, target)
    except OSError:
        thumb.unlink(missing_ok=True)
        raise


async def _async_apply_file(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    root: Path,
    action: transfer_bundle.FileAction,
) -> None:
    """Copy 1 bundled file into place and save its record through the store.

    The file goes in place before the record is saved, as for an upload, so the
    event of the store never names a file that is not on disk.
    """
    content_type, safe, size = await hass.async_add_executor_job(
        _check_file, root, action
    )
    source = root / action.path
    name = action.name or documents.display_filename(PurePosixPath(action.path).name)
    if action.kind == "task_photo":
        photos_root = Path(hass.config.path(TASK_PHOTOS_SUBDIR))
        task = coord.store.get_task(action.owner_id) or {}
        photo_id = documents.upload_document_id(
            action.item_id, (str(p.get("id")) for p in task_photos.photos_of(task))
        )
        target = task_photos.photo_path(photos_root, action.owner_id, photo_id, safe)
        thumb = task_photos.thumb_path(photos_root, action.owner_id, photo_id)
        await hass.async_add_executor_job(_place_photo, source, target, thumb)
        try:
            await coord.store.add_task_photo(
                action.owner_id,
                {
                    "id": photo_id,
                    "name": name,
                    "filename": safe,
                    "content_type": content_type,
                    "size": size,
                },
            )
        except (KeyError, TaskValidationError, StoreClosedError):
            await hass.async_add_executor_job(_unlink_all, target, thumb)
            raise
        return
    documents_root = Path(hass.config.path(MANUALS_SUBDIR))
    if action.kind == "part_file":
        target = documents.document_path(
            documents_root, action.owner_id, f"part_{action.item_id}", safe
        )
        await hass.async_add_executor_job(_place_file, source, target)
        try:
            await coord.store.set_part_file(
                action.owner_id,
                action.item_id,
                {"filename": safe, "content_type": content_type, "size": size},
            )
        except (KeyError, AssetValidationError):
            await hass.async_add_executor_job(_unlink_all, target)
            raise
        return
    asset = coord.store.get_asset(action.owner_id) or {}
    document_id = documents.upload_document_id(
        action.item_id, (str(d.get("id")) for d in asset.get("documents") or [])
    )
    target = documents.document_path(documents_root, action.owner_id, document_id, safe)
    await hass.async_add_executor_job(_place_file, source, target)
    try:
        await coord.store.add_asset_document(
            action.owner_id,
            {
                "id": document_id,
                "kind": "file",
                "name": name,
                "filename": safe,
                "content_type": content_type,
                "size": size,
            },
        )
    except (KeyError, AssetValidationError):
        await hass.async_add_executor_job(_unlink_all, target)
        raise


def _make_dirs(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _unlink_all(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


async def _async_apply_files(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    root: Path,
    plan: transfer_bundle.FilesPlan,
) -> tuple[int, list[transfer.Problem]]:
    """Apply the file actions. A file that fails is a warning, never an error.

    The records are already written when the files are applied, so a failure here
    cannot stop the import any more.
    """
    created = 0
    problems: list[transfer.Problem] = []
    for action in plan.actions:
        try:
            await _async_apply_file(hass, coord, root, action)
        except (
            KeyError,
            ValueError,
            OSError,
            StoreClosedError,
        ) as err:
            problems.append(_file_problem(action, str(err) or type(err).__name__))
            continue
        created += 1
    return created, problems


async def _async_apply_records(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    document: dict[str, Any],
    plan: transfer.ImportPlan,
    *,
    area_ids: dict[str, str],
    device_ids: Any,
    match: str,
) -> tuple[transfer.ImportPlan, list[transfer.Problem]]:
    """Write a clean plan of the Home Keeper sections. No reload.

    The applying pass is ordered by a dependency the panel never has to think about:
    a task attaches to an appliance's *device*, and a virtual appliance has no device
    until it is provisioned. So appliances are written first, ``async_reconcile_assets``
    runs once for the whole batch (it writes each new device id back onto its asset),
    and only then are the tasks written with their placeholder device references
    resolved. Returns the plan that was written and the problems of the write.
    """
    planned_assets = plan.for_section("appliances")
    if planned_assets:
        await coord.store.async_import_records(
            assets_to_write=[
                (r.record_id, r.payload, r.action == "create") for r in planned_assets
            ],
            tasks_to_write=[],
        )
        # Provisions a device for every virtual appliance and writes its id back onto
        # the asset — the only moment those ids come into existence.
        await devices.async_reconcile_assets(hass, coord.entry, coord.store)
        # The 2 steps above wait for saves, and a task can change in that time. Plan
        # the tasks again against the store as it is now, so that the write below
        # loses no change (X03-6). Nothing between this and the write waits.
        replanned = transfer.replan_tasks(
            document,
            plan,
            tasks=coord.store.get_tasks(),
            assets=coord.store.get_assets(),
            area_ids=area_ids,
            device_ids=device_ids,
            match=match,
            now=dt_util.now(),
        )
        # A new error (a name that a new task made ambiguous) keeps the first plan.
        if replanned.ok:
            plan = replanned

    planned_tasks = plan.for_section("tasks")
    unattached: list[transfer.Problem] = []
    if planned_tasks:
        # Build the write list rather than editing the plan. `PlannedRecord` is
        # frozen, and the plan stays the record of what was *planned*, so a report
        # that reads it back sees the same thing the preview showed.
        tasks_to_write: list[tuple[str, dict[str, Any], bool]] = []
        for record in planned_tasks:
            payload = record.payload
            asset_id = transfer.planned_asset_id(payload.get("device_id"))
            if asset_id is not None:
                device_id = (coord.store.get_asset(asset_id) or {}).get("device_id")
                payload = {**payload, "device_id": device_id}
                if not device_id:
                    # Provisioning is the one step that can still fail after
                    # validation passed, and the appliances are already written by
                    # now, so there is nothing to roll back to. Import the task
                    # standalone and say so.
                    unattached.append(
                        transfer.Problem(
                            section="tasks",
                            index=record.index,
                            path=f"tasks[{record.index}].appliance",
                            message=(
                                f'"{record.name}" was imported without its appliance: '
                                "Home Assistant did not give that appliance a device. "
                                "Open the appliance, then set the task's appliance "
                                "again."
                            ),
                            severity="warning",
                        )
                    )
            tasks_to_write.append(
                (record.record_id, payload, record.action == "create")
            )
        await coord.store.async_import_records(
            assets_to_write=[], tasks_to_write=tasks_to_write
        )
    return plan, unattached


def _companion_error(domain: str, message: str, *, dry_run: bool) -> dict[str, Any]:
    """The report of a companion call that failed, in the companion's shape."""
    return {
        "ok": False,
        "dry_run": dry_run,
        "counts": {},
        "records": [],
        "problems": [{"level": "error", "path": "", "message": message}],
    }


async def _async_companion_imports(
    hass: HomeAssistant,
    sections: dict[str, Any],
    *,
    dry_run: bool,
    files_root: Path | None,
    context: Context | None,
) -> tuple[dict[str, Any], list[transfer.Problem]]:
    """Call ``<domain>.import_data`` for each companion section, in order."""
    reports: dict[str, Any] = {}
    problems: list[transfer.Problem] = []
    for domain, section in sections.items():
        payload: dict[str, Any] = {"document": section, "dry_run": dry_run}
        if files_root is not None:
            folder = files_root / BUNDLE_FILES_DIR / domain
            await hass.async_add_executor_job(_make_dirs, folder)
            payload["files_dir"] = str(folder)
        report, error = await _call_companion(
            hass, domain, "import_data", payload, context
        )
        if error is not None:
            report = _companion_error(domain, error, dry_run=dry_run)
        reports[domain] = report
        problems.extend(transfer.companion_problems(domain, report))
    return reports, problems


def _import_sections(report: dict[str, Any]) -> dict[str, Any]:
    """The counts of each section of an applied import, for the event."""
    counts = report.get("counts") or {}
    found: dict[str, Any] = {
        key: counts[key] for key in (*transfer.SECTIONS, "files") if key in counts
    }
    for key, value in (counts.get("settings") or {}).items():
        found[key] = value
    for domain, section in (report.get("sections") or {}).items():
        found[domain] = section.get("counts", {}) if isinstance(section, dict) else {}
    return found


async def async_import_document(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    data: dict[str, Any],
    *,
    context: Context | None = None,
    files_root: Path | None = None,
) -> dict[str, Any]:
    """Plan an import, then apply it unless this is a dry run.

    The whole document is checked first: the Home Keeper plan, the settings, the
    files, and a dry run of each companion section. Only a document with no error
    in any of them is applied. Then the Home Keeper sections are written, then the
    files, then the settings, then each companion section in the order of
    registration. *files_root* is the extracted folder of a bundle.

    ``transfer.plan_import`` is pure and touches nothing: it decides every record's
    fate against the live store and reports *every* problem at once, each with a
    path. So a document that is wrong anywhere writes nothing.
    """
    if data.get("bundle") and files_root is None:
        path = await hass.async_add_executor_job(_bundle_by_name, hass, data["bundle"])
        if path is None:
            problem = transfer_bundle.BundleError(
                f'the folder {EXPORTS_SUBDIR} has no bundle "{data["bundle"]}"'
            ).as_problem()
            return transfer.merge_reports(
                transfer.ImportPlan(problems=(problem,)).as_report(
                    dry_run=bool(data.get("dry_run"))
                ),
                sections={},
            )
        return await async_import_bundle(hass, coord, path, data, context=context)

    dry_run = bool(data.get("dry_run"))
    document = data.get("document")
    if isinstance(document, str):
        # Read the text in the executor (B03-3): PyYAML is pure Python here, and a
        # large file takes seconds to read. The plan itself stays on the loop,
        # because it reads the live store.
        try:
            document = await hass.async_add_executor_job(
                transfer.parse_document, document
            )
        except transfer.DocumentSyntaxError as err:
            return transfer.merge_reports(
                transfer.ImportPlan(problems=(err.as_problem(),)).as_report(
                    dry_run=dry_run
                ),
                sections={},
            )
    registry = dr.async_get(hass)
    area_ids = {area.name: area.id for area in ar.async_get(hass).async_list_areas()}
    # A stated device_id is only kept when the device really is on this install. Ask
    # the registry for each id rather than iterate ``devices``, which yields ids
    # before Home Assistant 2026.9 and omits child devices from 2026.9 on (B04-1).
    device_ids = device_compat.RegistryDeviceIds(registry)
    match = data.get("match", "auto")

    hk_document: Any = document
    parts = transfer.DocumentParts(home_keeper={}, companions={}, settings={})
    if isinstance(document, dict):
        parts = transfer.split_document(
            document, companions=companion_states(hass, "import_data")
        )
        hk_document = parts.home_keeper
    # Else ``plan_import`` reports the bad document, and no other reader can read it.
    plan = transfer.plan_import(
        hk_document,
        tasks=coord.store.get_tasks(),
        assets=coord.store.get_assets(),
        area_ids=area_ids,
        device_ids=device_ids,
        match=match,
        now=dt_util.now(),
    )
    extra: list[transfer.Problem] = list(parts.problems)
    counts: dict[str, Any] = {}

    settings_plan: transfer_bundle.SettingsPlan | None = None
    if parts.settings and data.get("include_settings"):
        settings_plan = transfer_bundle.plan_settings(
            parts.settings,
            current=options.current_options(coord.entry),
            option_keys=options.ALL_OPTIONS,
            notify_services=_NotifyServices(hass),
            entity_ids=_Entities(hass),
        )
        extra.extend(settings_plan.problems)
        counts["settings"] = settings_plan.counts
    elif parts.settings:
        extra.extend(transfer_bundle.settings_skipped(parts.settings))

    files_plan: transfer_bundle.FilesPlan | None = None
    present: set[str] = set()
    if parts.files is not None and files_root is None:
        extra.append(
            transfer.Problem(
                transfer.FILES_SECTION,
                None,
                transfer.FILES_SECTION,
                'only a bundle can import the "files" section, so it was skipped',
                severity="warning",
            )
        )
    elif parts.files is not None and files_root is not None:
        present = await hass.async_add_executor_job(_present_files, files_root)
        files_plan = _plan_files(coord, parts.files, hk_document, plan, present)
        files_plan, bad_files = await _async_check_files(hass, files_root, files_plan)
        extra.extend((*files_plan.problems, *bad_files))
        counts["files"] = files_plan.counts()

    reports, companion_problems = await _async_companion_imports(
        hass, parts.companions, dry_run=True, files_root=files_root, context=context
    )
    report = plan.as_report(dry_run=dry_run)
    report["counts"].update(counts)
    merged = transfer.merge_reports(
        report, sections=reports, problems=[*extra, *companion_problems]
    )
    if dry_run or not merged["ok"]:
        return merged

    plan, unattached = await _async_apply_records(
        hass,
        coord,
        hk_document,
        plan,
        area_ids=area_ids,
        device_ids=device_ids,
        match=match,
    )
    file_problems: list[transfer.Problem] = []
    files_created = 0
    if files_plan is not None and files_root is not None:
        # Plan the files again with the ids that the write gave the records.
        final = _plan_files(coord, parts.files, hk_document, plan, present)
        final, bad_files = await _async_check_files(hass, files_root, final)
        files_created, file_problems = await _async_apply_files(
            hass, coord, files_root, final
        )
        file_problems = [*final.problems, *bad_files, *file_problems]
        counts["files"] = {"created": files_created, "unchanged": final.unchanged}
    else:
        file_problems = [p for p in extra if p.section == transfer.FILES_SECTION]
    if plan.records or files_created:
        # Imported parts may imply derived tasks, and the entity set has to be rebuilt
        # for everything that arrived — the same finish an asset mutation does.
        await coord.store.reconcile_part_tasks()
        await coord.store.reconcile_buy_tasks()
        await hass.config_entries.async_reload(coord.entry.entry_id)
    if settings_plan is not None and settings_plan.updates:
        try:
            await options.async_set_options(hass, coord.entry, settings_plan.updates)
        except options.ProfileInUseError as err:
            extra.append(
                transfer.Problem(
                    "profiles",
                    None,
                    "profiles",
                    f"the settings were not imported: {err}",
                )
            )

    applied, applied_problems = await _async_companion_imports(
        hass, parts.companions, dry_run=False, files_root=files_root, context=context
    )
    report = plan.as_report(dry_run=False)
    report["counts"].update(counts)
    kept = [p for p in extra if p.section != transfer.FILES_SECTION]
    final_report = transfer.merge_reports(
        report,
        sections=applied,
        problems=[*unattached, *kept, *file_problems, *applied_problems],
    )
    # The check passed and the write started, so an error now leaves the data that
    # was written before it.
    final_report["partial"] = not final_report["ok"]
    hass.bus.async_fire(
        EVENT_DATA_IMPORTED,
        events.data_transfer_event_data(
            KIND_BUNDLE if files_root is not None else KIND_DATA,
            _import_sections(final_report),
        ),
        context=context,
    )
    return final_report


async def async_import_bundle(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    zip_path: Path,
    data: dict[str, Any],
    *,
    context: Context | None = None,
) -> dict[str, Any]:
    """Extract a bundle safely, then import it as :func:`async_import_document` does.

    The bundle is extracted into a new run folder, which is deleted at the end, also
    after an error. A bundle that is not safe to extract is an error row.
    """
    dry_run = bool(data.get("dry_run"))
    run_dir = await async_new_run(hass)
    try:
        root = run_dir / "bundle"
        try:
            await hass.async_add_executor_job(
                transfer_bundle.safe_extract, zip_path, root
            )
            text = await hass.async_add_executor_job(
                transfer_bundle.read_document_text, root
            )
        except transfer_bundle.BundleError as err:
            return transfer.merge_reports(
                transfer.ImportPlan(problems=(err.as_problem(),)).as_report(
                    dry_run=dry_run
                ),
                sections={},
            )
        payload = {key: value for key, value in data.items() if key != "bundle"}
        payload["document"] = text
        return await async_import_document(
            hass, coord, payload, context=context, files_root=root
        )
    finally:
        await async_remove_run(hass, run_dir)
