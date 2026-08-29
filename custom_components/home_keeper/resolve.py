"""Resolve a service call's ``*_id`` field from either an id or a name.

Home Keeper's ids are ``uuid4`` strings (``models.build_task``,
``assets.build_asset``). They are exactly right for an integration holding a
reference across restarts and exactly wrong for a person writing YAML: nothing in
the panel shows them, so ``complete_task`` used to mean "go dig a uuid out of a
``list_tasks`` dump first".

Home Assistant's own answer to this is one field that takes either form, with the
id winning — ``todo.update_item``'s ``item`` is labelled "Item name or UID" and
resolved by ``_find_by_uid_or_summary``. This module is that resolution, kept
free of Home Assistant imports so ``tests/unit`` can drive it directly. The
callers in ``__init__.py`` translate the two exceptions below into a localized
``ServiceValidationError``.

One deliberate departure from core: core takes the *first* name match and never
mentions the others. Home Keeper raises :class:`AmbiguousName` instead, because
names here are not unique by design (``docs/INTEGRATING.md`` tells contributors to
expect collisions) and the services reached this way include ``delete_task`` and
``delete_asset``. Silently deleting one of two identically named tasks is a worse
outcome than an error naming both ids.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


class ResolveError(Exception):
    """Base for a reference that named no object, or more than one."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class NotFound(ResolveError):
    """No object carries this id or name."""


class AmbiguousName(ResolveError):
    """Several objects share this name, so the caller must use an id."""

    def __init__(self, key: str, ids: Iterable[str]) -> None:
        super().__init__(key)
        self.ids = sorted(ids)


def _norm(value: Any) -> str:
    """Fold a name for the last-chance match: trimmed and case-insensitive."""
    if not isinstance(value, str):
        # Equivalent under mutation: this pass only ever compares the result against
        # an already-casefolded key, which no sentinel string could match either.
        return ""  # pragma: no mutate
    return value.strip().casefold()


def _by_name(candidates: Sequence[tuple[str, Any]], key: str, field: str) -> str | None:
    """The single id whose *field* equals *key*, exactly then case-folded.

    Takes a sequence, not an iterator: it makes two passes over the candidates.
    Returns ``None`` when nothing matched at either strength, so the caller can
    distinguish "no such name" from "too many". Ambiguity is judged per pass: two
    tasks named "Filter" and "filter" are told apart by the exact pass and only
    collide if the caller types neither exactly.
    """
    wanted = _norm(key)
    if not wanted:
        return None
    for match_exact in (True, False):
        hits = [
            obj_id
            for obj_id, obj in candidates
            if (
                (obj.get(field) == key)
                if match_exact
                else (_norm(obj.get(field)) == wanted)
            )
        ]
        if hits:
            if len(hits) == 1:
                return hits[0]
            raise AmbiguousName(key, hits)
    return None


def _resolve(objects: Iterable[tuple[str, Any]], key: str, field: str) -> str:
    """The id of the one object *key* names, by id first and then by *field*."""
    pairs = list(objects)
    for obj_id, _obj in pairs:
        if obj_id == key:
            return obj_id
    if (found := _by_name(pairs, key, field)) is not None:
        return found
    raise NotFound(key)


def resolve_task_id(tasks: Mapping[str, Any], key: str) -> str:
    """The id of the task *key* refers to, by id or by name."""
    return _resolve(tasks.items(), key, "name")


def resolve_asset_id(assets: Mapping[str, Any], key: str) -> str:
    """The id of the appliance *key* refers to, by id or by name."""
    return _resolve(assets.items(), key, "name")


def _entries(asset: Any, collection: str) -> list[tuple[str, Any]]:
    """The ``(id, entry)`` pairs of one of an asset's nested collections."""
    raw = asset.get(collection) if isinstance(asset, Mapping) else None
    if not isinstance(raw, (list, tuple)):
        return []
    return [
        (str(entry.get("id")), entry)
        for entry in raw
        if isinstance(entry, Mapping) and entry.get("id")
    ]


def resolve_part_id(asset: Any, key: str) -> str:
    """The id of a part *key* refers to, scoped to one appliance.

    Scoping is what makes the name form workable here: two appliances may each
    have a "Filter", but one appliance rarely has two.
    """
    return _resolve(_entries(asset, "parts"), key, "name")


def resolve_document_id(asset: Any, key: str) -> str:
    """The id of a document *key* refers to, scoped to one appliance.

    A document's name is never blank — ``assets._normalize_document_entry`` falls
    back to the link's host or the uploaded filename — so every document is
    reachable by name.
    """
    return _resolve(_entries(asset, "documents"), key, "name")
