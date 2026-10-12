"""The bundle: a zip file with the YAML document, the uploaded files and the settings.

A YAML document holds the tasks and the appliances. A bundle also holds what a text
file cannot hold: the uploaded appliance documents, the part files and the task
photos. It also holds the settings: the profiles, the notifications and the other
options. The layout of the zip file is:

- ``home_keeper.yaml`` at the root, the same document that ``export_data`` writes;
- ``files/home_keeper/...`` for the Home Keeper files that the ``files`` section names;
- ``files/<domain>/...`` for the files of each companion.

This module is pure. It reads and writes the zip file and plans the ``files`` and
settings sections, and it imports nothing from Home Assistant. ``transfer_runner.py``
calls it in the executor, and applies the plans through the store and the options.
"""

from __future__ import annotations

import os
import shutil
import stat
import zipfile
import zlib
from collections.abc import Callable, Container, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import documents, notifications, options, task_photos
from .const import (
    BUNDLE_DOCUMENT_NAME,
    BUNDLE_FILES_DIR,
    MAX_BUNDLE_BYTES,
    MAX_BUNDLE_ENTRIES,
    MAX_IMPORT_BYTES,
    OPTION_SHOPPING_LIST_ENTITY,
)
from .transfer import (
    FILES_SECTION,
    SETTINGS_SECTIONS,
    Problem,
    is_portable_asset,
    is_portable_task,
)

HOME_KEEPER_FILES = f"{BUNDLE_FILES_DIR}/home_keeper"
"""The folder of the Home Keeper files in a bundle."""

FILE_KINDS: tuple[str, ...] = ("document", "part_file", "task_photo")
"""The kinds of the entries of the ``files`` section."""

_KIND_FOLDERS = {
    "document": "documents",
    "part_file": "part_files",
    "task_photo": "task_photos",
}
_COPY_CHUNK = 1024 * 1024
_SYMLINK = stat.S_IFLNK


class BundleError(ValueError):
    """The zip file is not a bundle that Home Keeper can read safely."""

    def as_problem(self) -> Problem:
        """The failure as an error row of the import report."""
        return Problem(section="bundle", index=None, path="bundle", message=str(self))


# ── Read a bundle ────────────────────────────────────────────────────────────


def _entry_parts(name: str) -> tuple[str, ...]:
    """The path parts of a zip entry name, or raise for a name that is not safe.

    A name must be relative, use ``/`` only, and hold no ``..`` part. Such a name
    cannot point outside the folder that the bundle is extracted into.
    """
    if not name or "\\" in name or "\x00" in name:
        raise BundleError(f'the bundle has an entry with a bad name: "{name}"')
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise BundleError(f'the bundle has an entry with an absolute path: "{name}"')
    parts = tuple(part for part in name.split("/") if part not in ("", "."))
    if ".." in parts:
        raise BundleError(f'the bundle has an entry that goes up a folder: "{name}"')
    return parts


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """Whether the zip entry is a symbolic link (the Unix mode in the high bits)."""
    return stat.S_IFMT(info.external_attr >> 16) == _SYMLINK


def safe_extract(
    zip_path: Path,
    dest: Path,
    *,
    max_entries: int = MAX_BUNDLE_ENTRIES,
    max_bytes: int = MAX_BUNDLE_BYTES,
) -> list[str]:
    """Extract the bundle at *zip_path* into the empty folder *dest*. Blocking.

    Refuses the whole bundle before it writes a byte when an entry has an absolute
    path, a ``..`` part, a symbolic link, encryption, or when there are more than
    *max_entries* entries. Counts the real bytes that it writes, and stops when the
    sum is more than *max_bytes*, so a false size in a zip header does not help a zip
    bomb. The caller deletes *dest* after a failure. Returns the extracted file names.
    """
    try:
        archive = zipfile.ZipFile(zip_path)
    # A name that is marked UTF-8 but is not UTF-8 is UnicodeDecodeError, and an
    # entry that needs a newer zip version is NotImplementedError.
    except (
        zipfile.BadZipFile,
        OSError,
        UnicodeDecodeError,
        NotImplementedError,
    ) as err:
        raise BundleError(
            "the file is not a zip file that Home Keeper can read"
        ) from err
    with archive:
        infos = archive.infolist()
        if len(infos) > max_entries:
            raise BundleError(
                f"the bundle has {len(infos)} entries, and the limit is {max_entries}"
            )
        planned: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
        for info in infos:
            parts = _entry_parts(info.filename)
            if _is_symlink(info):
                raise BundleError(f'the bundle has a symbolic link: "{info.filename}"')
            if info.flag_bits & 0x1:
                raise BundleError(
                    f'the bundle has an encrypted entry: "{info.filename}"'
                )
            if parts and not info.is_dir():
                planned.append((info, parts))
        root = dest.resolve()
        written = 0
        names: list[str] = []
        for info, parts in planned:
            target = root.joinpath(*parts)
            if not target.resolve().is_relative_to(root):
                raise BundleError(
                    f'the bundle has an entry outside its folder: "{info.filename}"'
                )
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as sink:
                    while chunk := source.read(_COPY_CHUNK):
                        written += len(chunk)
                        if written > max_bytes:
                            raise BundleError(
                                "the bundle is larger than "
                                f"{max_bytes // (1024 * 1024)} MB when extracted"
                            )
                        sink.write(chunk)
            except BundleError:
                raise
            # An unsupported compression method (Deflate64) is NotImplementedError,
            # and a corrupt deflate stream is zlib.error.
            except (
                zipfile.BadZipFile,
                EOFError,
                ValueError,
                OSError,
                NotImplementedError,
                zlib.error,
            ) as err:
                raise BundleError(
                    f'the bundle entry "{info.filename}" cannot be read'
                ) from err
            names.append("/".join(parts))
    return names


def read_document_text(root: Path) -> str:
    """Read ``home_keeper.yaml`` from an extracted bundle. Blocking."""
    path = root / BUNDLE_DOCUMENT_NAME
    if not path.is_file() or path.is_symlink():
        raise BundleError(f"the bundle has no {BUNDLE_DOCUMENT_NAME} at its root")
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise BundleError(
            f"the {BUNDLE_DOCUMENT_NAME} in the bundle is larger than "
            f"{MAX_IMPORT_BYTES // (1024 * 1024)} MB"
        )
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:
        raise BundleError(
            f"the {BUNDLE_DOCUMENT_NAME} in the bundle is not UTF-8 text"
        ) from err


def is_zip_header(header: bytes) -> bool:
    """Whether the first bytes of a file are the start of a zip file."""
    return header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06")


# ── Write a bundle ───────────────────────────────────────────────────────────


def _companion_files(domain: str, folder: Path) -> list[tuple[Path, str]]:
    """The regular files below a companion's *folder*, with their names in the zip.

    A symbolic link is skipped and never followed, so a companion cannot put a file
    from outside its folder in the bundle.
    """
    found: list[tuple[Path, str]] = []
    if not folder.is_dir() or folder.is_symlink():
        return found
    for current, dirs, files in os.walk(folder, followlinks=False):
        here = Path(current)
        dirs[:] = sorted(d for d in dirs if not (here / d).is_symlink())
        for name in sorted(files):
            path = here / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(folder).as_posix()
            found.append((path, f"{BUNDLE_FILES_DIR}/{domain}/{relative}"))
    return found


def write_bundle(
    zip_path: Path,
    document_text: str,
    *,
    files: Iterable[tuple[Path, str]] = (),
    companion_dirs: dict[str, Path] | None = None,
) -> int:
    """Write a bundle to *zip_path*. Blocking. Returns the number of missing files.

    *files* are ``(source, name in the zip)`` pairs of the Home Keeper files. A
    source that is not on disk is skipped and counted. *companion_dirs* maps each
    companion domain to the folder that its export filled.
    """
    missing = 0
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(BUNDLE_DOCUMENT_NAME, document_text)
        for source, name in files:
            if source.is_symlink() or not source.is_file():
                missing += 1
                continue
            archive.write(source, name)
        for domain, folder in (companion_dirs or {}).items():
            for source, name in _companion_files(domain, folder):
                archive.write(source, name)
    return missing


def copy_file(source: Path, target: Path) -> None:
    """Copy *source* to *target*, with the folders it needs. Blocking."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


# ── The ``files`` section ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BundledFile:
    """1 Home Keeper file of an export: its entry in ``files`` and its source."""

    entry: dict[str, Any]
    """The entry of the ``files`` section."""
    kind: str
    owner_id: str
    """The appliance id, or the task id for a task photo."""
    item_id: str
    """The document id, the part id or the photo id."""
    filename: str
    """The stored file name."""

    def source(self, documents_root: Path, photos_root: Path) -> Path:
        """The path of the stored file. Blocking: it resolves the path."""
        if self.kind == "task_photo":
            return task_photos.photo_path(
                photos_root, self.owner_id, self.item_id, self.filename
            )
        key = self.item_id if self.kind == "document" else f"part_{self.item_id}"
        return documents.document_path(
            documents_root, self.owner_id, key, self.filename
        )


def _bundle_path(kind: str, owner_id: str, item_id: str, filename: str) -> str:
    """The name of a Home Keeper file in the zip."""
    segments = (
        documents.safe_segment(owner_id),
        documents.safe_segment(item_id),
        documents.safe_segment(filename),
    )
    return "/".join((HOME_KEEPER_FILES, _KIND_FOLDERS[kind], *segments))


def bundled_files(
    assets: list[dict[str, Any]], tasks: list[dict[str, Any]]
) -> list[BundledFile]:
    """The uploaded files of the records that the document carries.

    A record that :func:`transfer.is_portable_asset` or
    :func:`transfer.is_portable_task` keeps out does not carry its files either.
    A file whose id or name is not a safe path part is skipped.
    """
    found: list[BundledFile] = []

    def add(kind: str, owner: str, item: str, filename: str, extra: dict) -> None:
        try:
            path = _bundle_path(kind, owner, item, filename)
        except documents.AssetValidationError:
            return
        entry = {"kind": kind, **extra, "path": path}
        found.append(BundledFile(entry, kind, owner, item, filename))

    for asset in assets:
        if not asset.get("id") or not is_portable_asset(asset):
            continue
        asset_id = str(asset["id"])
        for doc in asset.get("documents") or []:
            if doc.get("kind") == "file" and doc.get("id") and doc.get("filename"):
                extra = {"appliance": asset_id, "id": str(doc["id"])}
                if doc.get("name"):
                    extra["name"] = str(doc["name"])
                add("document", asset_id, str(doc["id"]), str(doc["filename"]), extra)
        for part in asset.get("parts") or []:
            if part.get("id") and part.get("file_name"):
                extra = {"appliance": asset_id, "part": str(part["id"])}
                add(
                    "part_file",
                    asset_id,
                    str(part["id"]),
                    str(part["file_name"]),
                    extra,
                )
    for task in tasks:
        if not task.get("id") or not is_portable_task(task):
            continue
        task_id = str(task["id"])
        for photo in task_photos.photos_of(task):
            if photo.get("id") and photo.get("filename"):
                extra = {"task": task_id, "id": str(photo["id"])}
                if photo.get("name"):
                    extra["name"] = str(photo["name"])
                add(
                    "task_photo",
                    task_id,
                    str(photo["id"]),
                    str(photo["filename"]),
                    extra,
                )
    return found


@dataclass(frozen=True, slots=True)
class FileAction:
    """1 file that an import adds to a record."""

    index: int
    kind: str
    owner_id: str
    """The appliance id, or the task id, on this install."""
    item_id: str
    """The document id or the photo id from the file, or the part id."""
    name: str
    path: str
    """The name of the file in the zip, relative to the extracted folder."""


@dataclass(frozen=True, slots=True)
class FilesPlan:
    """The files that an import adds, and the problems of the ``files`` section."""

    actions: tuple[FileAction, ...] = ()
    unchanged: int = 0
    problems: tuple[Problem, ...] = ()

    def counts(self) -> dict[str, int]:
        return {"created": len(self.actions), "unchanged": self.unchanged}


def _file_warning(index: int, field_name: str, message: str) -> Problem:
    path = f"{FILES_SECTION}[{index}]"
    if field_name:
        path = f"{path}.{field_name}"
    return Problem(FILES_SECTION, index, path, message, severity="warning")


def _has_file(kind: str, owner: dict[str, Any] | None, item_id: str) -> bool:
    """Whether the stored record already has this file."""
    if owner is None:
        return False
    if kind == "document":
        return any(
            d.get("id") == item_id and d.get("kind") == "file"
            for d in owner.get("documents") or []
        )
    if kind == "part_file":
        return any(
            p.get("id") == item_id and p.get("file_name")
            for p in owner.get("parts") or []
        )
    return task_photos.find_photo(owner, item_id) is not None


def _has_part(owner: dict[str, Any] | None, part_id: str) -> bool:
    return any(p.get("id") == part_id for p in (owner or {}).get("parts") or [])


def plan_files(
    section: Any,
    *,
    appliance_ids: dict[str, str],
    task_ids: dict[str, str],
    find_asset: Callable[[str], dict[str, Any] | None],
    find_task: Callable[[str], dict[str, Any] | None],
    present: Container[str],
) -> FilesPlan:
    """Decide which entries of the ``files`` section an import adds.

    *appliance_ids* and *task_ids* map an id that the document states to the id of
    the record on this install, from the plan of the import. An id that the plan
    does not have is looked up with *find_asset* or *find_task*. *present* holds the
    file names that the bundle has. A record that already has the file keeps it. A
    bad entry, a missing file and an unknown record are warnings, and the import
    skips that entry. The type of each file is checked when it is read.
    """
    if section is None:
        return FilesPlan()
    if not isinstance(section, list):
        return FilesPlan(
            problems=(
                Problem(
                    FILES_SECTION,
                    None,
                    FILES_SECTION,
                    'the "files" section must be a list, so it was skipped',
                    severity="warning",
                ),
            )
        )
    actions: list[FileAction] = []
    problems: list[Problem] = []
    unchanged = 0
    seen: set[tuple[str, str, str]] = set()
    for index, entry in enumerate(section):
        if not isinstance(entry, dict):
            problems.append(_file_warning(index, "", "each entry must be a mapping"))
            continue
        kind = entry.get("kind")
        if kind not in FILE_KINDS:
            problems.append(
                _file_warning(index, "kind", f'"{kind}" is not a kind of file')
            )
            continue
        path = str(entry.get("path") or "")
        try:
            parts = _entry_parts(path)
        except BundleError:
            parts = ()
        if not parts or "/".join(parts[:2]) != HOME_KEEPER_FILES:
            problems.append(
                _file_warning(
                    index, "path", f"the path must start with {HOME_KEEPER_FILES}/"
                )
            )
            continue
        relative = "/".join(parts)
        if relative not in present:
            problems.append(
                _file_warning(index, "path", f'the bundle has no file "{relative}"')
            )
            continue
        if kind == "task_photo":
            owner_key, noun, ids, find = "task", "a task", task_ids, find_task
        else:
            owner_key, noun = "appliance", "an appliance"
            ids, find = appliance_ids, find_asset
        stated = str(entry.get(owner_key) or "")
        owner_id = ids.get(stated, stated)
        owner = find(owner_id) if owner_id else None
        if owner is None and stated not in ids:
            problems.append(
                _file_warning(
                    index,
                    owner_key,
                    f'"{stated}" is not {noun} in this import or on this install',
                )
            )
            continue
        item_key = "part" if kind == "part_file" else "id"
        item_id = str(entry.get(item_key) or "")
        if not item_id:
            problems.append(_file_warning(index, item_key, f'"{item_key}" is missing'))
            continue
        if kind == "part_file" and owner is not None and not _has_part(owner, item_id):
            problems.append(
                _file_warning(index, "part", f'the appliance has no part "{item_id}"')
            )
            continue
        key = (kind, owner_id, item_id)
        if key in seen or _has_file(kind, owner, item_id):
            unchanged += 1
            continue
        seen.add(key)
        actions.append(
            FileAction(
                index=index,
                kind=kind,
                owner_id=owner_id,
                item_id=item_id,
                name=str(entry.get("name") or ""),
                path=relative,
            )
        )
    return FilesPlan(tuple(actions), unchanged, tuple(problems))


# ── The settings sections ────────────────────────────────────────────────────


def settings_sections(current: dict[str, Any]) -> dict[str, Any]:
    """The settings sections of an export, from the normalized options *current*.

    ``profiles`` and ``notifications`` are lists. ``options`` holds every other
    option key.
    """
    profiles_key, notifications_key = SETTINGS_SECTIONS[0], SETTINGS_SECTIONS[1]
    return {
        profiles_key: list(current.get(profiles_key) or []),
        notifications_key: list(current.get(notifications_key) or []),
        SETTINGS_SECTIONS[2]: {
            key: value
            for key, value in current.items()
            if key not in (profiles_key, notifications_key)
        },
    }


@dataclass(frozen=True, slots=True)
class SettingsPlan:
    """The options update that a settings import makes, and its problems."""

    updates: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)
    problems: tuple[Problem, ...] = ()


def _upsert(
    section: str,
    raw: Any,
    current: list[dict[str, Any]],
    problems: list[Problem],
    ids: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, int]]:
    """Merge the records of a profiles or notifications section onto *current*.

    A record matches a stored record by ``id``, then by ``name``. A match replaces
    the stored record, and a record that matches none is added. A stored record that
    the section does not name stays. A record that matches by name keeps the stored
    ``id``. If *ids* is a dict, it gets the imported id and the stored id of each
    such record.
    """
    counts = {"created": 0, "updated": 0}
    if not isinstance(raw, list):
        problems.append(
            Problem(section, None, section, f'"{section}" must be a list', "error")
        )
        return None, counts
    merged = [dict(record) for record in current]
    for index, record in enumerate(raw):
        if not isinstance(record, dict):
            problems.append(
                Problem(
                    section,
                    index,
                    f"{section}[{index}]",
                    "each entry must be a mapping",
                    "error",
                )
            )
            continue
        position = next(
            (
                i
                for i, stored in enumerate(merged)
                if record.get("id") and stored.get("id") == record.get("id")
            ),
            None,
        )
        if position is None and record.get("name"):
            position = next(
                (
                    i
                    for i, stored in enumerate(merged)
                    if stored.get("name") == record.get("name")
                ),
                None,
            )
        if position is None:
            merged.append(dict(record))
            counts["created"] += 1
        else:
            stored_id = merged[position].get("id")
            if ids is not None and record.get("id") and stored_id:
                ids[str(record["id"])] = str(stored_id)
            merged[position] = {**dict(record), "id": stored_id}
            counts["updated"] += 1
    return merged, counts


def _repoint_profiles(raw: Any, ids: dict[str, str]) -> Any:
    """The notifications section *raw*, with each ``profile_id`` in *ids* replaced."""
    if not ids or not isinstance(raw, list):
        return raw
    return [
        {**item, "profile_id": ids[item["profile_id"]]}
        if isinstance(item, dict)
        and isinstance(item.get("profile_id"), str)
        and item["profile_id"] in ids
        else item
        for item in raw
    ]


def plan_settings(
    sections: dict[str, Any],
    *,
    current: dict[str, Any],
    option_keys: Iterable[str],
    notify_services: Container[str],
    entity_ids: Container[str],
) -> SettingsPlan:
    """Plan a settings import from the settings *sections* of a document.

    *current* is the normalized options of this install, and *option_keys* is every
    option key. *notify_services* holds the ``notify`` service names, and
    *entity_ids* holds the entity ids, of this install. A notify target or a to-do
    list that this install does not have is a warning: the setting is imported, and
    the user can fix it in the panel. A section with the wrong shape is an error.
    """
    profiles_key, notifications_key, options_key = SETTINGS_SECTIONS
    problems: list[Problem] = []
    updates: dict[str, Any] = {}
    counts: dict[str, Any] = {}
    # A profile that matches by name keeps the stored id. Its notifications follow it.
    profile_ids: dict[str, str] = {}
    if profiles_key in sections:
        merged, counts[profiles_key] = _upsert(
            profiles_key,
            sections[profiles_key],
            list(current.get(profiles_key) or []),
            problems,
            profile_ids,
        )
        if merged is not None:
            updates[profiles_key] = merged
            for index, profile in enumerate(sections[profiles_key]):
                sync = profile.get("sync") if isinstance(profile, dict) else None
                entity = sync.get("entity_id") if isinstance(sync, dict) else None
                if entity and entity not in entity_ids:
                    problems.append(
                        Problem(
                            profiles_key,
                            index,
                            f"{profiles_key}[{index}].sync.entity_id",
                            f'the to-do list "{entity}" is not on this install',
                            "warning",
                        )
                    )
    if notifications_key in sections:
        merged, counts[notifications_key] = _upsert(
            notifications_key,
            _repoint_profiles(sections[notifications_key], profile_ids),
            list(current.get(notifications_key) or []),
            problems,
        )
        if merged is not None:
            updates[notifications_key] = merged
            for index, item in enumerate(sections[notifications_key]):
                targets = item.get("targets") if isinstance(item, dict) else None
                for position, target in enumerate(
                    targets if isinstance(targets, list) else []
                ):
                    # ``notifications.split_targets`` drops a target outside the
                    # allowlist when the notification is stored.
                    if not notifications.is_allowed_target(str(target)):
                        problems.append(
                            Problem(
                                notifications_key,
                                index,
                                f"{notifications_key}[{index}].targets[{position}]",
                                "Home Keeper does not send to the notify service "
                                f'"notify.{target}", so it was not imported',
                                "warning",
                            )
                        )
                    elif str(target) not in notify_services:
                        problems.append(
                            Problem(
                                notifications_key,
                                index,
                                f"{notifications_key}[{index}].targets[{position}]",
                                f'the notify service "notify.{target}" is not on '
                                "this install",
                                "warning",
                            )
                        )
    if options_key in sections:
        raw = sections[options_key]
        known = set(option_keys) - {profiles_key, notifications_key}
        if not isinstance(raw, dict):
            problems.append(
                Problem(
                    options_key,
                    None,
                    options_key,
                    '"options" must be a mapping',
                    "error",
                )
            )
        else:
            changed = 0
            for key, value in raw.items():
                if key not in known:
                    problems.append(
                        Problem(
                            options_key,
                            None,
                            f"{options_key}.{key}",
                            f'"{key}" is not an option this version of Home Keeper '
                            "reads, so it was ignored",
                            "warning",
                        )
                    )
                    continue
                if options.value_refused(key, value):
                    problems.append(
                        Problem(
                            options_key,
                            None,
                            f"{options_key}.{key}",
                            f'"{value}" is not a valid value of "{key}", so it was '
                            "ignored",
                            "warning",
                        )
                    )
                    continue
                updates[key] = value
                if current.get(key) != options.coerce_value(key, value):
                    changed += 1
            counts[options_key] = {"changed": changed}
            shopping = raw.get(OPTION_SHOPPING_LIST_ENTITY)
            if shopping and shopping not in entity_ids:
                problems.append(
                    Problem(
                        options_key,
                        None,
                        f"{options_key}.{OPTION_SHOPPING_LIST_ENTITY}",
                        f'the to-do list "{shopping}" is not on this install',
                        "warning",
                    )
                )
    return SettingsPlan(updates=updates, counts=counts, problems=tuple(problems))


def settings_skipped(sections: dict[str, Any]) -> list[Problem]:
    """The warnings for settings sections that an import skips.

    An import reads the settings only when the caller sets ``include_settings``.
    """
    return [
        Problem(
            key,
            None,
            key,
            f'"{key}" was skipped, because include_settings is off',
            severity="warning",
        )
        for key in SETTINGS_SECTIONS
        if key in sections
    ]
