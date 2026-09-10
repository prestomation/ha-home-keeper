"""The portable Home Keeper document: one YAML shape export writes and import reads.

Home Keeper's data has always been easy to *reach* — every action is a service — and
hard to *move*. Somebody arriving from a spreadsheet, from a dead app, or from years of
notes in OneNote had no way in but the panel, one task at a time; somebody moving to a
new Home Assistant had no way out at all. This module is that road, in both directions.

Three properties are the whole design, and each one is load-bearing:

**Symmetry.** Export emits exactly what import accepts. Hand somebody (or something)
one exported file and "make me twelve more like this" is a complete instruction — the
example *is* the schema.

**The record is the service payload.** A ``tasks`` record is an ``add_task`` payload
plus a handful of document-only keys; an ``appliances`` record is an ``add_asset``
payload. So ``services.yaml`` — and the API reference generated from it — already
documents every field, and keeps doing so for free.

**Derive, never restate.** The export names the fields it *excludes*, not the ones it
emits (:data:`EXCLUDED_TASK_KEYS`, :data:`EXCLUDED_ASSET_KEYS`). Add a field to
``models.build_task`` tomorrow and it travels in both directions with no edit here,
because import feeds the record straight back into ``models.normalize_fields``, which
already knows it. A hand-maintained allowlist would have been stale by the second
release; the only way a new field fails to travel is if somebody deliberately excludes
it, with a reason, in one line. ``tests/unit/test_transfer_roundtrip.py`` is what makes
that enforceable.

Pure, like ``inventory.py``: imports nothing from Home Assistant, so the whole
planning pass — validation, matching, id remapping, history folding — is unit-testable
with an injected clock and runs to completion *before* anything reaches disk.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any

from . import assets as assets_model
from . import models, recurrence, resolve
from .const import (
    COMPLETION_ENTRY_FIELDS,
    MAX_IMPORT_BYTES,
    MAX_IMPORT_RECORDS,
    SKIP_ENTRY_FIELDS,
    TASK_SOURCE_BUY,
    TASK_SOURCE_DECLARATIVE_COMPANION,
    TASK_SOURCE_PART,
    TASK_SOURCE_PROBLEM_SENSOR,
    TRANSFER_FORMAT,
    TRANSFER_SCHEMA_URL,
)

# ── What does not travel ─────────────────────────────────────────────────────
#
# The only field lists in this module. Everything not named here rides along, in
# both directions, with no code change — see the module docstring.

EXCLUDED_TASK_KEYS: tuple[tuple[str, str], ...] = (
    ("id", "carried in the envelope's own slot, not as an ordinary field"),
    (
        "created",
        "stamped fresh on import; a copied timestamp would claim the record "
        "was made on another install's clock",
    ),
    ("next_due", "derived from the schedule and the history, recomputed on import"),
    ("last_completed", "derived from the history, restated by replaying it"),
    ("completions", "re-shaped as `history`, keyed like the complete_task service"),
    ("skips", "re-shaped as `skips`, keyed like the completion entries"),
    ("source", "reconciler-owned provenance; a task carrying one is not exported"),
    ("managed_by", "an owning integration's block; such a task is not exported"),
)
"""``(key, reason)`` for every stored task key the document deliberately drops.

A reason is mandatory, and ``tests/unit/test_transfer_coverage.py`` enforces it: the
next person to exclude a field has to say why, in the place the decision lives.
"""

EXCLUDED_ASSET_KEYS: tuple[tuple[str, str], ...] = (
    ("id", "carried in the envelope's own slot, not as an ordinary field"),
    ("created", "stamped fresh on import, like a task's"),
    (
        "identifiers",
        "a registry snapshot of *this* install's device, meaningless on "
        "another one; provisioning rebuilds it",
    ),
    ("connections", "the same registry snapshot"),
    (
        "device_id",
        "re-resolved on import — restated readably as `appliance`/`area` "
        "and re-emitted as `device_id` only so a same-install re-import is exact",
    ),
    (
        "task_history",
        "completions archived from deleted tasks; the tasks that made "
        "them are gone, so there is nothing on the other side to attach them to",
    ),
)

EXCLUDED_STORE_KEYS: tuple[tuple[str, str], ...] = (
    (
        "problem_notes",
        "keyed by a live entity_id, which names nothing on another install",
    ),
    (
        "shopping_items",
        "bookkeeping for a mirror on someone else's to-do list, rebuilt by the sync",
    ),
    ("todo_list_items", "the same — a mirror's bookkeeping, rebuilt by the sync"),
    (
        "declarative_companions",
        "deferred to a later `recipes:` section rather than "
        "dropped; format 1 leaves the top level open for it",
    ),
)
"""Top-level keys of the storage document that no section covers, and why.

``tests/unit/test_transfer_coverage.py`` parses ``store._save`` and fails when a new
key appears in neither this table nor :data:`SECTIONS`. That is the gate for a whole
new *feature* — which is how ``declarative_companions`` and ``todo_list_items``
arrived — rather than for a new field on an existing one.
"""

SECTIONS: tuple[str, ...] = ("appliances", "tasks")
"""The document's data sections, in the order import applies them.

Appliances first: a task points at an appliance's *device*, and a virtual appliance
has no device id until it is provisioned.
"""

# Reserved ``source`` namespaces. A task carrying one belongs to a reconciler that
# regenerates it from a part, a sensor or a recipe — all of which the document either
# carries (parts) or deliberately does not (recipes). Exporting such a task would
# promise to restore something the reconciler would immediately overwrite or delete.
_RECONCILER_SOURCES = frozenset(
    {
        TASK_SOURCE_PART,
        TASK_SOURCE_BUY,
        TASK_SOURCE_PROBLEM_SENSOR,
        TASK_SOURCE_DECLARATIVE_COMPANION,
    }
)

# Document-only keys on a record: everything that is not simply a service field.
_TASK_EXTRA_KEYS = frozenset(
    {"external_id", "appliance", "area", "enabled", "history", "skips"}
)
_ASSET_EXTRA_KEYS = frozenset({"external_id", "area", "archived"})

# The two ``add_task`` fields the published schema does not offer. ``normalize_fields``
# accepts either, so a document setting one is not refused — but the task it creates is
# one :func:`is_portable_task` then declines to export, which makes it a trap rather
# than a feature. The schema is permissive, so leaving them out hides them from an
# editor's completions without rejecting a file that has them.
UNPORTABLE_TASK_KEYS: tuple[str, ...] = ("source", "managed_by")


# ── Results ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Problem:
    """One reason a document, or one record in it, cannot be applied as written."""

    section: str
    index: int | None
    path: str
    message: str
    severity: str = "error"
    """``"error"`` blocks the whole import; ``"warning"`` is reported and applied.

    Forward compatibility rides on this distinction. A key this version has never
    heard of is a warning — an older Home Keeper must be able to read a newer
    document — but it is a *named* warning, because silently discarding something the
    author wrote is how a migration loses data without anybody noticing.
    """

    def as_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "index": self.index,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class PlannedRecord:
    """One record's resolved fate: what it will become, and why it matched."""

    section: str
    index: int
    record_id: str
    external_id: str
    name: str
    action: str
    """``"create"`` or ``"update"``."""
    matched_by: str | None
    """``"id"`` / ``"external_id"`` / ``"name"``, or ``None`` for a create."""
    payload: dict[str, Any]
    """The built record (create) or the updates mapping (update)."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "index": self.index,
            "id": self.record_id,
            "external_id": self.external_id,
            "name": self.name,
            "action": self.action,
            "matched_by": self.matched_by,
        }


@dataclass(frozen=True, slots=True)
class ImportPlan:
    """Everything the applier needs, decided before a single write happens."""

    records: tuple[PlannedRecord, ...] = ()
    problems: tuple[Problem, ...] = ()
    completions: int = 0
    skips: int = 0

    @property
    def ok(self) -> bool:
        """Whether the plan may be applied: no problem at ``error`` severity."""
        return not any(p.severity == "error" for p in self.problems)

    def for_section(self, section: str) -> tuple[PlannedRecord, ...]:
        return tuple(r for r in self.records if r.section == section)

    def as_report(self, *, dry_run: bool) -> dict[str, Any]:
        """The service response: counts, per-record outcomes, and every problem."""
        counts: dict[str, Any] = {}
        for section in SECTIONS:
            planned = self.for_section(section)
            counts[section] = {
                "created": sum(1 for r in planned if r.action == "create"),
                "updated": sum(1 for r in planned if r.action == "update"),
            }
        counts["completions"] = self.completions
        counts["skips"] = self.skips
        return {
            "ok": self.ok,
            "dry_run": dry_run,
            "counts": counts,
            "records": [r.as_dict() for r in self.records],
            "problems": [p.as_dict() for p in self.problems],
        }


# ── Export ───────────────────────────────────────────────────────────────────


def is_portable_task(task: dict[str, Any]) -> bool:
    """Whether *task* is the user's to move, rather than an integration's to rebuild.

    A reconciler-owned task (a wear part's replacement reminder, a buy reminder, a
    problem-sensor mirror, a recipe's task) and a task an integration declares itself
    the owner of are both regenerated on the other side from the things that *are* in
    the document — the appliance and its parts — or by the integration itself. Copying
    them across would restore a record that the next reconcile pass deletes.
    """
    source = task.get("source")
    if isinstance(source, dict) and _RECONCILER_SOURCES & set(source):
        return False
    return not task.get("managed_by")


def _strip(
    record: dict[str, Any], excluded: tuple[tuple[str, str], ...]
) -> dict[str, Any]:
    """*record* minus the excluded keys, with empty-but-meaningless values dropped.

    Dropping ``""``/``[]``/``None`` keeps a hand-edited file readable — a task that
    sets nothing optional exports as four lines rather than thirty — and costs
    nothing on the way back in, because every normalizer already treats an absent key
    and an empty one the same way.
    """
    drop = {key for key, _reason in excluded}
    return {
        key: value
        for key, value in record.items()
        if key not in drop and value not in (None, "", [], {})
    }


def _entry_out(
    entry: dict[str, Any], *, when_key: str, allowed: list[str]
) -> dict[str, Any]:
    """One completion/skip log entry in document form: ``ts`` renamed, rest verbatim."""
    out: dict[str, Any] = {when_key: entry.get("ts")}
    for key in allowed:
        value = entry.get(key)
        if value not in (None, ""):
            out[key] = value
    return out


def _task_out(
    task: dict[str, Any],
    *,
    area_names: dict[str, str],
    asset_by_device: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """One stored task as a document record."""
    out = _strip(task, EXCLUDED_TASK_KEYS)
    out["id"] = task["id"]
    if external_id := task.get("external_id"):
        out["external_id"] = external_id
    if area_id := task.get("area_id"):
        # Both, deliberately: the id makes a same-install re-import exact, the name
        # makes the file mean something on an install that has never seen that id.
        # Import prefers the id and falls back to the name, so stripping the ids out
        # of a hand-written copy still works.
        out["area"] = area_names.get(area_id, area_id)
    if (device_id := task.get("device_id")) and (
        owner := asset_by_device.get(device_id)
    ):
        out["appliance"] = owner.get("external_id") or owner.get("name") or device_id
    if history := task.get("completions"):
        out["history"] = [
            _entry_out(e, when_key="completed_at", allowed=COMPLETION_ENTRY_FIELDS)
            for e in history
        ]
    if skips := task.get("skips"):
        out["skips"] = [
            _entry_out(e, when_key="skipped_at", allowed=SKIP_ENTRY_FIELDS)
            for e in skips
        ]
    return out


def _asset_out(asset: dict[str, Any], *, area_names: dict[str, str]) -> dict[str, Any]:
    """One stored appliance as a document record, link documents only."""
    out = _strip(asset, EXCLUDED_ASSET_KEYS)
    out["id"] = asset["id"]
    if external_id := asset.get("external_id"):
        out["external_id"] = external_id
    if area_id := asset.get("area_id"):
        out["area"] = area_names.get(area_id, area_id)
    if device_id := asset.get("device_id"):
        # Only meaningful for an ``existing``-kind appliance decorating somebody
        # else's device; a virtual one is re-provisioned and gets a new id anyway.
        out["device_id"] = device_id
    if asset.get("archived_at"):
        out["archived"] = True
    out.pop("archived_at", None)
    documents = [
        dict(doc) for doc in asset.get("documents") or [] if doc.get("kind") == "link"
    ]
    if documents:
        out["documents"] = documents
    else:
        out.pop("documents", None)
    return out


def count_file_documents(assets: list[dict[str, Any]]) -> int:
    """How many uploaded files the document leaves behind.

    Reported in the envelope rather than passed over in silence: a text document has no
    room for a blob, and somebody restoring onto a new install needs to know that
    three manuals are waiting to be re-uploaded, not discover it a month later.
    """
    return sum(
        1
        for asset in assets
        for doc in asset.get("documents") or []
        if doc.get("kind") == "file"
    )


def build_document(
    tasks: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    *,
    area_names: dict[str, str] | None = None,
    version: str = "",
    now: datetime,
    include: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Render the store's tasks and appliances as one portable document."""
    wanted = tuple(include) if include else SECTIONS
    names = area_names or {}
    document: dict[str, Any] = {
        "home_keeper": {
            "format": TRANSFER_FORMAT,
            "version": version,
            "exported_at": now.isoformat(),
        }
    }
    portable_assets = [a for a in assets if a.get("id")]
    if "appliances" in wanted:
        document["appliances"] = [
            _asset_out(a, area_names=names) for a in portable_assets
        ]
        if skipped := count_file_documents(portable_assets):
            document["home_keeper"]["skipped"] = {"file_documents": skipped}
    if "tasks" in wanted:
        by_device = {a["device_id"]: a for a in portable_assets if a.get("device_id")}
        document["tasks"] = [
            _task_out(t, area_names=names, asset_by_device=by_device)
            for t in tasks
            if is_portable_task(t)
        ]
    return document


# The implicit resolver the loader drops. Spelled out rather than reached for
# through yaml.resolver, so the reason sits next to the name.
_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"


@lru_cache(maxsize=1)
def _yaml_dialect() -> tuple[Any, Any]:
    """The ``(Dumper, Loader)`` pair this document is written and read with.

    Built once, and PyYAML is imported here rather than at module scope for the same
    reason ``ci/generate_api_docs.py`` does it: the pure modules are loaded at test
    collection, and ``pytest PyYAML Babel hypothesis`` is documented as four *optional*
    installs. A top-level import would make every transfer test need PyYAML to run.

    PyYAML is not in ``manifest.json``. Home Assistant reads ``configuration.yaml``
    with it, so it cannot boot without it — the same class as ``voluptuous``, which
    this integration also imports and does not declare. Declaring it would only add a
    pip resolution at setup that could move Home Assistant's own pinned version.
    """
    import yaml

    class _Dumper(yaml.SafeDumper):
        """Block YAML that reads like the worked example in the README."""

        def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
            # PyYAML writes ``tasks:\n- name:``. Forcing ``indentless`` off puts the
            # dash under its key, which is how a person writes YAML by hand.
            return super().increase_indent(flow=flow, indentless=False)

        def ignore_aliases(self, data: Any) -> bool:
            # Never emit ``&a``/``*a``. The loader below refuses an alias, so a
            # document that used one would be unreadable by the code that wrote it.
            return True

    def _represent_str(dumper: Any, data: str) -> Any:
        # A multi-line note as a literal block instead of a quoted scalar with blank
        # lines in it. PyYAML falls back to a quoted form by itself when a line has
        # trailing whitespace, which a block scalar cannot hold, so this needs no guard.
        style = "|" if "\n" in data else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)

    _Dumper.add_representer(str, _represent_str)

    class _Loader(yaml.SafeLoader):
        """Safe YAML, minus two behaviours this format has no use for.

        **Aliases are refused.** The format never needed anchors, and refusing them is
        what stops a billion-laughs expansion bomb: the attack is pure alias expansion,
        and :data:`MAX_IMPORT_RECORDS` cannot see it because a document is already
        expanded in memory by the time there are records to count. Refusing an alias
        also removes merge keys (``<<: *base``), which the format has never used.

        **Bare timestamps stay text.** The rule is that the document's scalars are
        JSON's scalars. Stock ``SafeLoader`` reads ``completed_at: 2026-03-04`` as a
        ``date`` and ``due: 2026-01-15T09:00:00`` as a ``datetime``; the second reaches
        ``datetime.fromisoformat`` and raises ``TypeError``, and either one inside a
        free-form ``metadata`` value would reach the store, where ``json.dumps`` cannot
        write it. Dropping the resolver makes both load as the exact strings the same
        document carried when it was JSON.

        The YAML 1.1 *boolean* resolver stays. Home Assistant's own loader keeps it and
        people write Home Assistant YAML every day, so ``enabled: no`` meaning false is
        what a reader expects; dropping it would make ``"no"`` a truthy string, which
        fails in the more surprising direction. The cost falls only on a hand-written
        file, because the exporter quotes such a value by itself.
        """

        def compose_node(self, parent: Any, index: Any) -> Any:
            if self.check_event(yaml.events.AliasEvent):
                event = self.peek_event()
                raise yaml.constructor.ConstructorError(
                    None,
                    None,
                    "a Home Keeper document cannot use an anchor or an alias",
                    event.start_mark,
                )
            return super().compose_node(parent, index)

    _Loader.yaml_implicit_resolvers = {
        first: [(tag, regexp) for tag, regexp in resolvers if tag != _TIMESTAMP_TAG]
        for first, resolvers in _Loader.yaml_implicit_resolvers.items()
    }

    return _Dumper, _Loader


def document_to_yaml(document: dict[str, Any]) -> str:
    """The document as a file a person can read and an assistant can copy.

    The first line is a ``yaml-language-server`` modeline naming the published schema,
    so an exported file validates and completes itself in an editor. It is a comment,
    so every parser skips it and the round trip is unaffected.
    """
    import yaml

    dumper, _loader = _yaml_dialect()
    body = yaml.dump(
        document,
        Dumper=dumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        indent=2,
        # Only affects where a long scalar wraps; every width round-trips, so no
        # assertion can tell one from another.
        width=100,  # pragma: no mutate
    )
    return f"# yaml-language-server: $schema={TRANSFER_SCHEMA_URL}\n{body}"


class DocumentSyntaxError(ValueError):
    """The text is not YAML at all, so there is no document to validate."""

    def __init__(self, message: str, *, line: int | None, column: int | None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.column = column

    def as_problem(self) -> Problem:
        """The failure as an ordinary problem row, with somewhere to look."""
        where = "home_keeper"
        if self.line is not None and self.column is not None:
            where = f"line {self.line}, column {self.column}"
        return Problem(
            section="home_keeper", index=None, path=where, message=self.message
        )


def parse_document(text: str) -> Any:
    """Read a document from text. The partner of :func:`document_to_yaml`.

    Every JSON document is also YAML, so a file written before the format was YAML
    still reads — with one exception worth stating: YAML forbids a tab as indentation,
    so hand-written tab-indented JSON is refused. No exported file was ever indented
    that way.

    Returns whatever the text held, which is not necessarily a mapping.
    :func:`plan_import` is what rejects a list or a scalar, so there is one rule about
    that and not two.
    """
    import yaml

    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise DocumentSyntaxError(
            f"this file is larger than {MAX_IMPORT_BYTES // (1024 * 1024)} MB, "
            "so it was not read. Split the migration into several documents.",
            line=None,
            column=None,
        )

    _dumper, loader = _yaml_dialect()
    try:
        return yaml.load(text, Loader=loader)
    # RecursionError is a RuntimeError, not a YAMLError: deeply nested flow
    # collections exhaust PyYAML's recursive-descent parser, and catching only
    # YAMLError would let that escape into the websocket handler.
    except (yaml.YAMLError, RecursionError) as err:
        mark = getattr(err, "problem_mark", None)
        detail = getattr(err, "problem", None) or "the file could not be read"
        # PyYAML counts from zero; a person's editor counts from one.
        # The message carries PyYAML's own complaint and stops. It used to append
        # "Check the indentation.", which is good advice for exactly one class of
        # failure and wrong for the rest: an anchor refusal read "a Home Keeper
        # document cannot use an anchor or an alias. Check the indentation." and sent
        # the reader to look at the one thing that was fine.
        raise DocumentSyntaxError(
            f"this file is not valid YAML: {detail}.",
            line=mark.line + 1 if mark is not None else None,
            column=mark.column + 1 if mark is not None else None,
        ) from err


# ── Import ───────────────────────────────────────────────────────────────────


@dataclass
class _Matcher:
    """The primary-key ladder for one section, over the records already stored.

    id, then ``external_id``, then name — first hit wins, and the steps are
    independent: a record that states an id nobody has is a *create*, not a
    fall-through to a name match that would quietly write over a different record.
    """

    stored: dict[str, dict[str, Any]]
    claimed: set[str] = field(default_factory=set)
    """Ids already taken by an earlier record in this document, so two records
    cannot both upsert onto the same stored one."""

    def match(self, record: dict[str, Any]) -> tuple[str | None, str | None]:
        """``(stored_id, matched_by)``, or ``(None, None)`` when this is new."""
        # A record already claimed by an earlier record in this document is out of
        # the running. Otherwise two rows sharing a name would both upsert onto the
        # same stored record, and the file would silently import as one — the second
        # row overwriting the first rather than becoming its own task.
        available = {
            key: obj for key, obj in self.stored.items() if key not in self.claimed
        }
        if (record_id := record.get("id")) and record_id in available:
            return record_id, "id"
        if record_id:
            return None, None
        if external_id := record.get("external_id"):
            hits = [
                key
                for key, obj in available.items()
                if obj.get("external_id") == external_id
            ]
            if len(hits) == 1:
                return hits[0], "external_id"
            if hits:
                raise resolve.AmbiguousName(external_id, hits)
        if name := record.get("name"):
            # The same exact-then-folded ladder the *_id service fields use, so
            # "Furnace filter" means the same thing in a document as in a service
            # call — including that two matches raise rather than pick one.
            found = resolve.match_by_name(available, str(name))
            if found is not None:
                return found, "name"
        return None, None


def _iso(value: Any, *, tz: Any) -> datetime:
    """Parse a document timestamp, qualifying a bare date with the caller's zone.

    ``2026-03-04`` is what a person writes and what a spreadsheet exports, so it has
    to work — and it has to land aware, because one naive datetime in the history
    poisons every later comparison in the store.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=tz)


def apply_history(
    task: dict[str, Any],
    history: list[dict[str, Any]],
    skips: list[dict[str, Any]],
    *,
    now: datetime,
) -> tuple[int, int]:
    """Fold a record's past onto a freshly built *task*.

    Returns ``(completions, skips)``.

    **Chronologically**, and that is not a detail. ``recurrence.apply_completion``
    stamps ``last_completed`` from whichever entry it is handed, and the history cap
    keeps the *tail* of the list — so replaying 2019 last would leave a task claiming
    it was serviced seven years ago and, past 500 entries, would keep the oldest half
    of the log instead of the newest.

    Completions replay through the live recurrence math, so the final one computes
    ``next_due`` exactly as it would have. Skips are *logged* in place
    (``recurrence.record_skip``) without moving the due date: a skip from 2019 says an
    occurrence was passed over then, and running its schedule math against today's
    clock would invent a date nobody ever saw.

    No event is fired for any of this, by design. Backfilling a decade is not a
    decade of completions happening now, and firing one per entry would replay
    through notifications and to-do sync as if it were.
    """
    events: list[tuple[datetime, bool, dict[str, Any]]] = []
    records_reading = models.task_records_reading(task)
    for entry in history:
        when = _iso(entry["completed_at"], tz=now.tzinfo)
        metadata = models.normalize_completion_metadata(
            {k: v for k, v in entry.items() if k != "completed_at"},
            allow_reading=records_reading,
        )
        events.append((when, True, metadata))
    for entry in skips:
        when = _iso(entry["skipped_at"], tz=now.tzinfo)
        metadata = models.normalize_completion_metadata(
            {k: v for k, v in entry.items() if k != "skipped_at"},
            allow_reading=records_reading,
        )
        events.append((when, False, metadata))
    # Sort on the timestamp alone (never on the metadata dict, which is unorderable);
    # a completion and a skip at the same instant keep their relative document order.
    events.sort(key=lambda item: item[0])
    for when, is_completion, metadata in events:
        if is_completion:
            recurrence.apply_completion(task, when, now=now, metadata=metadata)
        else:
            recurrence.record_skip(task, when, metadata=metadata)
    return len(history), len(skips)


_PROBE_NOW = datetime(2026, 1, 1, tzinfo=None).replace(
    tzinfo=datetime.now().astimezone().tzinfo
)
"""A fixed clock for the key probes below. Never used for a stored value."""

# One minimal record per shape, so the probes below see every field that only exists
# for one of them — a floating task never grows a ``freq``, and a virtual appliance
# never grows a ``device_id``. Derived by *building* records rather than by listing
# keys, for the same reason the export is a denylist: a list would go stale.
_TASK_PROBES: tuple[dict[str, Any], ...] = (
    {"name": "probe", "recurrence_type": "floating", "interval": 1, "unit": "days"},
    {
        "name": "probe",
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "MONTHLY",
        "anchor": "2026-01-15T09:00:00",
    },
    {"name": "probe", "recurrence_type": "one-off", "due": "2026-01-15T09:00:00"},
    {"name": "probe", "recurrence_type": "triggered"},
    {
        "name": "probe",
        "recurrence_type": "sensor",
        "sensor": {"entity_id": "sensor.probe", "mode": "usage", "target": 1},
    },
)

_ASSET_PROBES: tuple[dict[str, Any], ...] = (
    {"name": "probe"},
    {"name": "probe", "kind": "existing", "device_id": "probe"},
)


@lru_cache(maxsize=1)
def _known_task_keys() -> frozenset[str]:
    """Every key a task record may carry: the service's fields plus the extras.

    Probed, not enumerated, so a field added to ``models.build_task`` is recognized
    here the moment it exists — otherwise import would greet each new field with a
    "this is not a field Home Keeper reads" warning and drop it.
    """
    keys: set[str] = set()
    for probe in _TASK_PROBES:
        keys |= set(models.build_task(probe, now=_PROBE_NOW))
        keys |= set(probe)
    return frozenset(keys) | _TASK_EXTRA_KEYS


@lru_cache(maxsize=1)
def _known_asset_keys() -> frozenset[str]:
    """Every key an appliance record may carry, probed the same way."""
    keys: set[str] = set()
    for probe in _ASSET_PROBES:
        keys |= set(assets_model.build_asset(probe, now=_PROBE_NOW))
        keys |= set(probe)
    return frozenset(keys) | _ASSET_EXTRA_KEYS


def _is_uuid(value: Any) -> bool:
    """Whether *value* is a well-formed uuid we can safely reuse as a record id."""
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def plan_import(
    document: Any,
    *,
    tasks: dict[str, dict[str, Any]],
    assets: dict[str, dict[str, Any]],
    area_ids: dict[str, str] | None = None,
    device_ids: frozenset[str] | set[str] | None = None,
    match: str = "auto",
    now: datetime,
) -> ImportPlan:
    """Validate a document against the current store and decide every record's fate.

    Nothing is written and nothing is mutated: the whole pass runs on copies, so the
    caller can show the result as a preview and apply exactly the same plan
    afterwards. A single ``error`` problem means the store is left untouched — which
    is what makes a plain (non-dry-run) import safe to hand a generated file, and
    gives whoever generated it a clean fix-and-retry loop.
    """
    problems: list[Problem] = []
    # Reading the text is part of validating it. The panel and the service both hand
    # over whatever the user pasted, so a syntax error arrives as an ordinary problem
    # row with a line and a column, through the same report as every other problem.
    if isinstance(document, str):
        try:
            document = parse_document(document)
        except DocumentSyntaxError as err:
            return ImportPlan(problems=(err.as_problem(),))
    if not isinstance(document, dict):
        return ImportPlan(problems=(_bad("the document must be a mapping"),))

    envelope = document.get("home_keeper")
    if not isinstance(envelope, dict):
        return ImportPlan(
            problems=(
                _bad('the document needs a "home_keeper" block naming its format'),
            )
        )
    declared = envelope.get("format", TRANSFER_FORMAT)
    # ``bool`` is an ``int`` in Python, and YAML 1.1 reads a bare ``yes`` as one — so
    # ``format: yes`` arrived as ``True``, which is ``1``, and passed for format 1.
    if isinstance(declared, bool) or not isinstance(declared, int):
        # A separate message, because the advice is different. "Update Home Keeper"
        # answers a document from a later version; it answers nothing for a value that
        # is not a version at all, which is the one a hand-written file produces.
        return ImportPlan(
            problems=(
                _bad(
                    f"this document declares format {declared!r}, which is not a "
                    f"format number. Write `format: {TRANSFER_FORMAT}`."
                ),
            )
        )
    if declared > TRANSFER_FORMAT:
        return ImportPlan(
            problems=(
                _bad(
                    f"this document declares format {declared!r}, and this version of "
                    f"Home Keeper reads format {TRANSFER_FORMAT}. Update Home Keeper."
                ),
            )
        )
    if match not in ("auto", "none"):
        return ImportPlan(problems=(_bad(f"unknown match mode: {match!r}"),))

    for key in document:
        if key != "home_keeper" and key not in SECTIONS:
            problems.append(
                Problem(
                    section=key,
                    index=None,
                    path=key,
                    message=(
                        f'"{key}" is not a section this version of Home Keeper '
                        "reads, so it was left alone"
                    ),
                    severity="warning",
                )
            )

    areas = area_ids or {}
    # ``None`` means "do not check"; an empty set means "this install has no
    # devices", which must reject a stated id rather than wave it through.
    known_devices = None if device_ids is None else set(device_ids)
    asset_matcher = _Matcher(dict(assets))
    task_matcher = _Matcher(dict(tasks))
    planned: list[PlannedRecord] = []
    completions = skips = 0

    # Appliances first, and their planned ids are what a task's ``appliance``
    # reference resolves against — so a document can describe an appliance and the
    # tasks on it in one go, before either exists.
    doc_assets = _section(document, "appliances", problems)
    asset_refs: dict[str, str] = {}
    planned_assets: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(doc_assets):
        entry = _plan_asset(
            record,
            index=index,
            matcher=asset_matcher,
            stored=assets,
            areas=areas,
            asset_refs=asset_refs,
            match=match,
            now=now,
            problems=problems,
        )
        if entry is None:
            continue
        planned.append(entry)
        planned_assets[entry.record_id] = entry.payload
        for ref in (record.get("external_id"), record.get("name")):
            if ref:
                asset_refs.setdefault(str(ref), entry.record_id)

    # Both post-passes need the whole section decided before they can see anything:
    # one collision and one loop each look like an ordinary record on its own.
    if clashed := _colliding_external_ids(planned, "appliances", doc_assets, problems):
        planned = [r for r in planned if r.record_id not in clashed]
        planned_assets = {k: v for k, v in planned_assets.items() if k not in clashed}
        asset_refs = {k: v for k, v in asset_refs.items() if v not in clashed}

    # Only now, with every parent link in the document decided, can a loop be seen.
    if looped := _looping_parents(planned, assets, problems):
        planned = [r for r in planned if r.record_id not in looped]
        planned_assets = {k: v for k, v in planned_assets.items() if k not in looped}
        asset_refs = {k: v for k, v in asset_refs.items() if v not in looped}

    doc_tasks = _section(document, "tasks", problems)
    for index, record in enumerate(doc_tasks):
        entry, counted = _plan_task(
            record,
            index=index,
            matcher=task_matcher,
            stored=tasks,
            areas=areas,
            known_devices=known_devices,
            asset_refs=asset_refs,
            planned_assets=planned_assets,
            stored_assets=assets,
            match=match,
            now=now,
            problems=problems,
        )
        if entry is None:
            continue
        planned.append(entry)
        completions += counted[0]
        skips += counted[1]

    if clashed := _colliding_external_ids(planned, "tasks", doc_tasks, problems):
        planned = [r for r in planned if r.record_id not in clashed]

    return ImportPlan(
        records=tuple(planned),
        problems=tuple(problems),
        completions=completions,
        skips=skips,
    )


def _colliding_external_ids(
    planned: list[PlannedRecord],
    section: str,
    raw: list[dict[str, Any]],
    problems: list[Problem],
) -> set[str]:
    """Record ids to drop because two records in one document claim one key.

    ``external_id`` is the author's own primary key, and the reason a migration script
    can be run twice: step 2 of the ladder matches on it so the second run *updates*.
    That promise only holds while the key is unique, and nothing else enforces it —
    :attr:`_Matcher.claimed` stops two records upserting onto the same *stored* record,
    but two records that are both new, or one update beside one create, each looked
    harmless alone and wrote two records carrying one key.

    The cost landed on the *next* run rather than this one, which is what made it worth
    catching here: with two stored records answering to the key, every later import of
    that document failed with "matches several tasks" and could not be repaired by
    re-running it. So a collision is an error, not a warning — the document is asking
    for one record twice, and the document is what has to say which.

    Checked against the plan rather than the text, so it sees the key a record arrives
    with *and* the key it inherits from the stored record it matched.

    **Only when the key is what a later run would have to match on.** A shared key is
    harmless while every record in the group also states its own ``id``, because the
    ladder tries the id first and never reaches step 2. That is not a corner case: an
    export writes an ``id`` on every record, and a store is free to hold two tasks
    with one ``external_id`` already (nothing upstream makes it unique). Refusing the
    group outright made an export of such a store impossible to import again, which
    broke restoring a backup — the one job this format exists for. A property test
    caught it, having generated exactly that store.

    So the rule is the damage rather than the shape: refuse when at least one record
    in the group would fall through to the key, and leave the rest alone.
    """
    by_key: dict[str, list[PlannedRecord]] = {}
    for record in planned:
        if record.section == section and record.external_id:
            by_key.setdefault(record.external_id, []).append(record)
    dropped: set[str] = set()
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        # A stated uuid is what `_claim_id` keeps, so it is also what a re-run matches
        # on. Anything else (absent, or not a uuid) is replaced by a fresh id the
        # document does not carry, leaving `external_id` as the only way back.
        if all(_is_uuid(raw[r.index].get("id")) for r in group):
            continue
        where = ", ".join(f"{section}[{r.index}]" for r in group)
        for record in group:
            problems.append(
                Problem(
                    section=section,
                    index=record.index,
                    path=f"{section}[{record.index}].external_id",
                    message=(
                        f'"{key}" is the external_id of {len(group)} records in this '
                        f"document ({where}). An external_id names one record, so "
                        "give each of these one of its own."
                    ),
                )
            )
            dropped.add(record.record_id)
    return dropped


def _bad(message: str) -> Problem:
    """A problem with the document as a whole, rather than with one record."""
    return Problem(
        section="home_keeper", index=None, path="home_keeper", message=message
    )


def _section(
    document: dict[str, Any], name: str, problems: list[Problem]
) -> list[dict[str, Any]]:
    """One section's records, or an empty list with a problem logged."""
    raw = document.get(name)
    if raw is None:
        return []
    if not isinstance(raw, list):
        problems.append(Problem(name, None, name, f'"{name}" must be a list'))
        return []
    if len(raw) > MAX_IMPORT_RECORDS:
        problems.append(
            Problem(
                name,
                None,
                name,
                f'"{name}" has {len(raw)} records; at most {MAX_IMPORT_RECORDS} can '
                "be imported at once. Split the document.",
            )
        )
        return []
    records: list[dict[str, Any]] = []
    for index, record in enumerate(raw):
        if not isinstance(record, dict):
            problems.append(
                Problem(
                    name, index, f"{name}[{index}]", "each record must be a mapping"
                )
            )
            continue
        records.append(record)
    return records


def _warn_unknown(
    record: dict[str, Any],
    known: frozenset[str],
    *,
    section: str,
    index: int,
    problems: list[Problem],
) -> None:
    """Report — but do not reject — keys this version does not recognize."""
    for key in sorted(set(record) - known):
        problems.append(
            Problem(
                section=section,
                index=index,
                path=f"{section}[{index}].{key}",
                message=(
                    f'"{key}" is not a field this version of Home Keeper reads, so '
                    "it was ignored"
                ),
                severity="warning",
            )
        )


def _resolve_area(
    record: dict[str, Any],
    areas: dict[str, str],
    *,
    section: str,
    index: int,
    problems: list[Problem],
) -> str | None:
    """The record's area id: a stated ``area_id`` first, then ``area`` by name.

    A name that matches no area on this install is kept verbatim, because the panel
    falls back to showing an unknown area id as its own text and the author's word for
    the room is better text than nothing. But it is *named*, the way an unresolvable
    ``device_id`` is: the record reads as filed under that area in the panel while Home
    Assistant has no such area, so nothing scoped to areas outside Home Keeper — an
    automation, a dashboard filter — will ever see it. Saying so is the difference
    between a migration the reader can finish and one that looks complete.
    """
    if area_id := record.get("area_id"):
        return str(area_id)
    key = record.get("area")
    if not key:
        return None
    key = str(key)
    if key in areas.values():
        return key
    for name, area_id in areas.items():
        if name.strip().casefold() == key.strip().casefold():
            return area_id
    problems.append(
        Problem(
            section=section,
            index=index,
            path=f"{section}[{index}].area",
            message=(
                f'no area called "{key}" exists here, so the record keeps the name as '
                "written. Create the area and set it again to attach it."
            ),
            severity="warning",
        )
    )
    return key


def _claim_id(record: dict[str, Any], taken: set[str]) -> str:
    """The id a new record takes: its own when it is a free uuid, else a fresh one.

    Keeping the stated id is what makes a restore onto an empty install a true
    restore — entity unique_ids are anchored to the task id, so a remap would hand
    every task new entities and orphan every automation pointing at the old ones.
    """
    stated = record.get("id")
    if _is_uuid(stated) and str(stated) not in taken:
        return str(stated)
    return str(uuid.uuid4())


def _plan_asset(
    record: dict[str, Any],
    *,
    index: int,
    matcher: _Matcher,
    stored: dict[str, dict[str, Any]],
    areas: dict[str, str],
    asset_refs: dict[str, str],
    match: str,
    now: datetime,
    problems: list[Problem],
) -> PlannedRecord | None:
    """Decide one appliance record, or log why it cannot be applied."""
    _warn_unknown(
        record,
        _known_asset_keys(),
        section="appliances",
        index=index,
        problems=problems,
    )
    payload = {k: v for k, v in record.items() if k not in ("area", "archived", "id")}
    if (
        area_id := _resolve_area(
            record, areas, section="appliances", index=index, problems=problems
        )
    ) is not None:
        payload["area_id"] = area_id
    # A subdevice names its parent the same readable way a task names its appliance,
    # and against the same two places: this document first, then the store. Without
    # this a document describing a nested appliance tree would carry the *author's*
    # parent key straight through as an id, and `_clean_relationship_links` would
    # quietly null it on the next load — losing the tree with nothing said.
    if parent := payload.get("parent_asset_id"):
        resolved = _parent_id(str(parent), asset_refs, stored)
        if resolved is None:
            problems.append(
                Problem(
                    "appliances",
                    index,
                    f"appliances[{index}].parent_asset_id",
                    f'no appliance called "{parent}" is in this document or in Home '
                    "Keeper, so this one has nothing to sit under. List the parent "
                    "before its children.",
                )
            )
            return None
        payload["parent_asset_id"] = resolved

    try:
        matched, matched_by = (None, None) if match == "none" else matcher.match(record)
    except resolve.AmbiguousName as err:
        problems.append(
            Problem(
                "appliances",
                index,
                f"appliances[{index}]",
                f'"{err.key}" matches several appliances ({", ".join(err.ids)}). '
                "Give the record an id, or a name that is not shared.",
            )
        )
        return None

    try:
        if matched is not None:
            matcher.claimed.add(matched)
            merged = assets_model.merge_update(stored[matched], payload, now=now)
            return PlannedRecord(
                "appliances",
                index,
                matched,
                str(merged.get("external_id") or ""),
                str(merged.get("name") or ""),
                "update",
                matched_by,
                # The *merged record*, never the updates that made it. The applier
                # writes a payload into the store as-is, so handing it a bare updates
                # mapping would replace a whole appliance with a fragment that has no
                # id — and the next device reconcile would trip over it.
                merged,
            )
        built = assets_model.build_asset(payload, now=now)
    except assets_model.AssetValidationError as err:
        problems.append(Problem("appliances", index, f"appliances[{index}]", str(err)))
        return None

    built["id"] = _claim_id(record, set(stored) | matcher.claimed)
    if built["kind"] == assets_model.ASSET_KIND_VIRTUAL:
        # The identifier is derived from the id, which we may have just replaced.
        built["identifiers"] = [list(assets_model.asset_device_identifier(built["id"]))]
    if record.get("archived"):
        built["archived_at"] = now.isoformat()
    matcher.claimed.add(built["id"])
    return PlannedRecord(
        "appliances",
        index,
        built["id"],
        str(built.get("external_id") or ""),
        str(built.get("name") or ""),
        "create",
        None,
        built,
    )


def _plan_task(
    record: dict[str, Any],
    *,
    index: int,
    matcher: _Matcher,
    stored: dict[str, dict[str, Any]],
    areas: dict[str, str],
    known_devices: set[str] | None,
    asset_refs: dict[str, str],
    planned_assets: dict[str, dict[str, Any]],
    stored_assets: dict[str, dict[str, Any]],
    match: str,
    now: datetime,
    problems: list[Problem],
) -> tuple[PlannedRecord | None, tuple[int, int]]:
    """Decide one task record, or log why it cannot be applied."""
    path = f"tasks[{index}]"
    _warn_unknown(
        record, _known_task_keys(), section="tasks", index=index, problems=problems
    )

    if isinstance(record.get("source"), dict) and _RECONCILER_SOURCES & set(
        record["source"]
    ):
        problems.append(
            Problem(
                "tasks",
                index,
                f"{path}.source",
                "this task claims a source Home Keeper's own reconcilers own. Import "
                "the appliance and its parts instead; the task is rebuilt from them.",
            )
        )
        return None, (0, 0)
    if record.get("managed_by"):
        problems.append(
            Problem(
                "tasks",
                index,
                f"{path}.managed_by",
                "this task declares another integration as its owner, so that "
                "integration creates it rather than an import.",
            )
        )
        return None, (0, 0)

    payload = {
        k: v
        for k, v in record.items()
        if k not in ("area", "appliance", "history", "skips", "id")
    }
    if (
        area_id := _resolve_area(
            record, areas, section="tasks", index=index, problems=problems
        )
    ) is not None:
        payload["area_id"] = area_id
    # A task attaches to an *appliance*, but stores the appliance's device id — which
    # is this install's id and means nothing on another one. So a stated device_id is
    # kept only when it is real here (that is what makes a same-install re-import
    # exact), and otherwise the readable ``appliance`` reference decides.
    stated_device = payload.get("device_id")
    device_known = stated_device and (
        known_devices is None or stated_device in known_devices
    )
    if stated_device and not device_known:
        payload.pop("device_id")
    if not payload.get("device_id") and (appliance := record.get("appliance")):
        device_id = _appliance_device(
            str(appliance), asset_refs, planned_assets, stored_assets
        )
        if device_id is None:
            problems.append(
                Problem(
                    "tasks",
                    index,
                    f"{path}.appliance",
                    f'no appliance called "{appliance}" is in this document or in '
                    "Home Keeper, so the task has nothing to attach to.",
                )
            )
            return None, (0, 0)
        payload["device_id"] = device_id
    elif stated_device and not device_known:
        # No appliance to fall back on: import the task standalone rather than
        # pointing it at a device that is not here, and say so.
        problems.append(
            Problem(
                "tasks",
                index,
                f"{path}.device_id",
                f'no device "{stated_device}" exists here, so the task was imported '
                "without an appliance. Name the appliance instead.",
                severity="warning",
            )
        )

    history = _entries(
        record,
        "history",
        "completed_at",
        "tasks",
        index,
        problems,
        allowed=COMPLETION_ENTRY_FIELDS,
    )
    skip_entries = _entries(
        record,
        "skips",
        "skipped_at",
        "tasks",
        index,
        problems,
        allowed=SKIP_ENTRY_FIELDS,
    )

    try:
        matched, matched_by = (None, None) if match == "none" else matcher.match(record)
    except resolve.AmbiguousName as err:
        problems.append(
            Problem(
                "tasks",
                index,
                path,
                f'"{err.key}" matches several tasks ({", ".join(err.ids)}). Give the '
                "record an id, or a name that is not shared.",
            )
        )
        return None, (0, 0)

    try:
        if matched is not None:
            matcher.claimed.add(matched)
            merged = models.merge_update(stored[matched], payload, now=now)
            counted = apply_history(merged, history, skip_entries, now=now)
            return (
                PlannedRecord(
                    "tasks",
                    index,
                    matched,
                    str(merged.get("external_id") or ""),
                    str(merged.get("name") or ""),
                    "update",
                    matched_by,
                    merged,
                ),
                counted,
            )
        built = models.build_task(payload, now=now)
        counted = apply_history(built, history, skip_entries, now=now)
    except (models.TaskValidationError, ValueError) as err:
        problems.append(Problem("tasks", index, path, str(err)))
        return None, (0, 0)

    built["id"] = _claim_id(record, set(stored) | matcher.claimed)
    matcher.claimed.add(built["id"])
    return (
        PlannedRecord(
            "tasks",
            index,
            built["id"],
            str(built.get("external_id") or ""),
            str(built.get("name") or ""),
            "create",
            None,
            built,
        ),
        counted,
    )


def _parent_id(
    key: str,
    asset_refs: dict[str, str],
    stored_assets: dict[str, dict[str, Any]],
) -> str | None:
    """The asset id a ``parent_asset_id`` reference names, document before store.

    Unlike a task's ``appliance`` this resolves to the *asset* id rather than a
    device id, so a parent planned earlier in the same document needs no placeholder
    — its id is already decided by the time its children are read. Which is also why
    a parent has to be listed before its children: ``asset_refs`` only holds what has
    been planned so far.
    """
    if asset_id := asset_refs.get(key):
        return asset_id
    for asset_id, asset in stored_assets.items():
        if key in (asset_id, asset.get("external_id")):
            return asset_id
    return resolve.match_by_name(stored_assets, key)


def _looping_parents(
    planned_assets: list[PlannedRecord],
    stored: dict[str, dict[str, Any]],
    problems: list[Problem],
) -> set[str]:
    """The ids whose ``parent_asset_id`` closes a loop once the document is applied.

    Every other write path refuses a loop through ``store._validate_parent``, and
    ``devices`` walks the parent chain to provision parents before their children.
    An import writes built records straight into the store, so without this it is the
    one path that can break that invariant — and the damage outlives the import:
    ``_clean_relationship_links`` only nulls a parent that does not *exist*, so a loop
    between two real appliances is kept, and every later reconcile logs a cyclic-chain
    error against a tree the user cannot see is broken.

    The check has to run against the *projected* graph rather than the stored one,
    because a single document can re-parent both halves of a loop in the same run:
    taken one at a time, each edge looks harmless, and only the pair is wrong. Both
    ends are reported, because either one can be changed to open the loop.

    The store's own definition of a loop is reused rather than restated, so the two
    can never come to disagree about what one is.
    """
    projected: dict[str, dict[str, Any]] = {
        asset_id: {"parent_asset_id": asset.get("parent_asset_id")}
        for asset_id, asset in stored.items()
    }
    for record in planned_assets:
        projected[record.record_id] = {
            "parent_asset_id": record.payload.get("parent_asset_id")
        }
    looped: set[str] = set()
    for record in planned_assets:
        parent = record.payload.get("parent_asset_id")
        if not parent or not assets_model.would_create_cycle(
            projected, record.record_id, str(parent)
        ):
            continue
        looped.add(record.record_id)
        problems.append(
            Problem(
                "appliances",
                record.index,
                f"appliances[{record.index}].parent_asset_id",
                f'"{record.name}" would sit under itself through this parent link, '
                "and an appliance cannot be its own parent. Point one appliance in "
                "the loop at a different parent.",
            )
        )
    return looped


def _appliance_device(
    key: str,
    asset_refs: dict[str, str],
    planned_assets: dict[str, dict[str, Any]],
    stored_assets: dict[str, dict[str, Any]],
) -> str | None:
    """The device id a task's ``appliance`` reference points at.

    The document wins over the store, so a file describing an appliance and its tasks
    together attaches them to each other rather than to a same-named appliance that
    happens to already exist. A planned virtual appliance has no device id yet — the
    applier provisions it and fills this in — so returning its *asset* id would be
    wrong; the applier resolves the placeholder instead.
    """
    if asset_id := asset_refs.get(key):
        return _PLANNED_ASSET_PREFIX + asset_id
    for asset_id, asset in stored_assets.items():
        if key in (asset_id, asset.get("external_id")) and asset.get("device_id"):
            return str(asset["device_id"])
    found = resolve.match_by_name(stored_assets, key)
    if found is not None and stored_assets[found].get("device_id"):
        return str(stored_assets[found]["device_id"])
    return None


_PLANNED_ASSET_PREFIX = "hk-planned-asset:"
"""Marks a ``device_id`` that is really "the device of the appliance this document is
about to create". The applier swaps it for the real one after provisioning, which is
the only moment a virtual appliance's device id exists."""


def planned_asset_id(device_id: Any) -> str | None:
    """The asset id behind a placeholder ``device_id``, or ``None`` if it is real."""
    if isinstance(device_id, str) and device_id.startswith(_PLANNED_ASSET_PREFIX):
        return device_id[len(_PLANNED_ASSET_PREFIX) :]
    return None


def _entries(
    record: dict[str, Any],
    key: str,
    when_key: str,
    section: str,
    index: int,
    problems: list[Problem],
    *,
    allowed: list[str],
) -> list[dict[str, Any]]:
    """A record's history/skip list, with malformed entries reported and dropped.

    An entry's unrecognized keys are *named*, the same way a record's are. They are
    still dropped — ``models.normalize_completion_metadata`` keeps only the fields it
    knows — but silence here was the one place the document broke its own promise that
    "a field nobody read is data that did not arrive, and it is named". A migration
    writing ``notes`` for ``note``, or ``price`` for ``cost``, lost a whole column of
    a spreadsheet with nothing said, on the one import that was meant to carry it.
    """
    raw = record.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        problems.append(
            Problem(
                section, index, f"{section}[{index}].{key}", f'"{key}" must be a list'
            )
        )
        return []
    out: list[dict[str, Any]] = []
    for position, entry in enumerate(raw):
        path = f"{section}[{index}].{key}[{position}]"
        if not isinstance(entry, dict) or entry.get(when_key) in (None, ""):
            problems.append(
                Problem(section, index, path, f'each entry needs a "{when_key}" date')
            )
            continue
        try:
            datetime.fromisoformat(str(entry[when_key]))
        except ValueError:
            problems.append(
                Problem(
                    section,
                    index,
                    f"{path}.{when_key}",
                    f'"{entry[when_key]}" is not a date. Use 2026-03-04, or a full '
                    "timestamp.",
                )
            )
            continue
        for unknown in sorted(set(entry) - {when_key} - set(allowed)):
            problems.append(
                Problem(
                    section=section,
                    index=index,
                    path=f"{path}.{unknown}",
                    message=(
                        f'"{unknown}" is not a field this version of Home Keeper '
                        "reads, so it was ignored"
                    ),
                    severity="warning",
                )
            )
        out.append(entry)
    return out
