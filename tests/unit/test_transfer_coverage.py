"""Drift guards that keep the import/export document honest as Home Keeper grows.

``test_transfer_roundtrip.py`` catches a new *field* that fails to travel. These
catch the two things a round-trip cannot see:

* a whole new **storage section** — which is how ``declarative_companions`` and
  ``todo_list_items`` arrived — appearing in neither the document nor the
  deliberately-excluded table;
* the document and the **services** drifting apart, which would quietly falsify the
  one sentence the whole design rests on: "a record's fields are the service's
  fields".

Both use the technique ``test_api_surface.py`` already uses — parse the component's
own source and compare it to the model — because a list nobody derives is a list
somebody forgets.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import hk_transfer as tr
import pytest
import yaml
from transfer_records import AREA_NAMES, NOW, _maximal_asset, _maximal_task

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"

NOW_FOR_PARTS = datetime(2026, 6, 13, 10, tzinfo=timezone(timedelta(hours=-4)))

_FIX = (
    "Give it a section in transfer.SECTIONS, or name it in the matching EXCLUDED_* "
    "table in custom_components/home_keeper/transfer.py with a one-sentence reason."
)


def _store_document_keys() -> set[str]:
    """The top-level keys ``HomeKeeperStore._save`` writes, read from its source.

    Read from the source rather than from a live store: a key added to ``_save`` but
    never populated in a test fixture would be invisible to a runtime probe, and that
    is exactly the key most likely to be forgotten.
    """
    tree = ast.parse((_COMPONENT / "store.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.AsyncFunctionDef) and node.name == "_save"):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if not call.args or not isinstance(call.args[0], ast.Dict):
                continue
            return {
                key.value
                for key in call.args[0].keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    raise AssertionError("could not find the storage document literal in store._save")


def test_every_storage_key_is_carried_or_deliberately_left_behind():
    stored = _store_document_keys()
    # ``appliances`` is the document's name for the ``assets`` key.
    carried = {"tasks", "assets"}
    excluded = {key for key, _reason in tr.EXCLUDED_STORE_KEYS}
    unclassified = stored - carried - excluded
    assert not unclassified, {
        "storage keys the import/export document ignores silently": sorted(
            unclassified
        ),
        "fix": _FIX,
    }
    # And nothing is excluded that is no longer stored, so the table cannot rot into
    # a list of reasons for keys that stopped existing.
    stale = excluded - stored
    assert not stale, {"excluded keys that are no longer stored": sorted(stale)}


@pytest.mark.parametrize(
    "table",
    [tr.EXCLUDED_TASK_KEYS, tr.EXCLUDED_ASSET_KEYS, tr.EXCLUDED_STORE_KEYS],
    ids=["tasks", "appliances", "storage"],
)
def test_every_exclusion_states_a_reason(table):
    # An exclusion without a reason is indistinguishable from an oversight six months
    # later, so the reason is part of the data, not a comment beside it.
    missing = [key for key, reason in table if not reason.strip()]
    assert not missing, {"exclusions with no reason": missing}


@pytest.mark.parametrize(
    ("service", "known", "extras"),
    [
        ("add_task", tr._known_task_keys, tr._TASK_EXTRA_KEYS),
        ("add_asset", tr._known_asset_keys, tr._ASSET_EXTRA_KEYS),
    ],
)
def test_the_document_accepts_every_field_its_service_takes(service, known, extras):
    """The README's claim, made checkable.

    "A record's fields are the service's fields" is the whole answer to "how do I
    write one of these" — and it is what lets ``services.yaml`` and the generated API
    reference document the format for free. A service field the importer silently
    drops turns that sentence into a lie the moment somebody trusts it.
    """
    services = yaml.safe_load(
        (_COMPONENT / "services.yaml").read_text(encoding="utf-8")
    )
    fields = set(services[service].get("fields") or {})
    # ``*_id`` selector fields address an existing record; the document says which
    # record it means with its own key, so they are not record fields.
    fields -= {"task_id", "asset_id"}
    ignored = fields - known() - extras
    assert not ignored, {
        f"{service} fields an imported record would silently drop": sorted(ignored),
        "fix": (
            "Accept them in transfer.py (usually free — they pass straight through "
            "to the normalizer), or add them to the _*_EXTRA_KEYS set if they are "
            "document-only."
        ),
    }


# ── the part sub-schema, which no other gate can see ─────────────────────────
#
# A part's fields sit one level down, inside `appliances[].parts[]`, and every gate
# above this one reads only a record's *top level*. `test_transfer_roundtrip.py` never
# touches voluptuous, and both structural tests in `test_generate_schema.py` compare
# `record["properties"]` — so a part field added to `assets._normalize_part` and to
# `transfer_records._maximal_asset` but not to `_PART_SCHEMA` travelled fine, validated
# fine, and was still invisible to an editor *and* refused by `home_keeper.update_asset`
# for any automation replaying an exported appliance. `carried_uses` is the field that
# found this hole.

EXCLUDED_PART_KEYS = tr.EXCLUDED_PART_KEYS
"""The exporter's own table, read rather than restated.

The keys the document leaves out and the keys ``_PART_SCHEMA`` refuses are the same
3 keys for the same reason — a part's uploaded file cannot travel as text. Keeping a
second copy here would let the two halves drift, which is the defect this file exists
to catch.
"""


def _part_schema_keys() -> set[str]:
    """The keys ``_PART_SCHEMA`` accepts, read from ``__init__.py``'s source.

    Parsed rather than imported, for the reason the whole module is: ``__init__.py``
    imports Home Assistant, and this lane does not have it.
    """
    tree = ast.parse((_COMPONENT / "__init__.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "_PART_SCHEMA" for t in node.targets
        ):
            continue
        keys: set[str] = set()
        for call in ast.walk(node.value):
            # vol.Optional("x") / vol.Required("x")
            if not isinstance(call, ast.Call) or not isinstance(
                call.func, ast.Attribute
            ):
                continue
            if call.func.attr not in {"Optional", "Required"}:
                continue
            if (
                call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
            ):
                keys.add(call.args[0].value)
        return keys
    raise AssertionError("could not find _PART_SCHEMA in __init__.py")


def _built_part_keys() -> set[str]:
    """Every key ``assets._normalize_part`` really writes, through the real builder."""
    part = tr.assets_model.build_asset(
        {"name": "Probe", "parts": [{"name": "Filter", "type": "consumable"}]},
        now=NOW_FOR_PARTS,
    )["parts"][0]
    return set(part) - {"id"}


def test_every_part_field_the_model_builds_is_a_field_the_service_takes():
    built = _built_part_keys()
    accepted = _part_schema_keys()
    excluded = {key for key, _reason in EXCLUDED_PART_KEYS}
    missing = built - accepted - excluded
    assert not missing, (
        f"_PART_SCHEMA does not accept {sorted(missing)}, which assets._normalize_part "
        "builds. Add it to _PART_SCHEMA in custom_components/home_keeper/__init__.py, "
        "or name it in EXCLUDED_PART_KEYS here with a reason. Without this the field "
        "is invisible to an editor, and update_asset refuses the parts array "
        "list_assets just returned."
    )


def test_no_part_exclusion_is_stale():
    """An exclusion for a key the model no longer builds is a decision nobody made."""
    built = _built_part_keys()
    stale = {key for key, _reason in EXCLUDED_PART_KEYS} - built
    assert not stale, f"EXCLUDED_PART_KEYS names {sorted(stale)}, which is not built"


def test_every_part_exclusion_states_a_reason():
    for key, reason in EXCLUDED_PART_KEYS:
        assert reason.strip(), f"{key} is excluded with no reason"


# ── the document says only what is true, at every depth ──────────────────────


def test_no_exported_value_is_null():
    """``_strip`` drops a meaningless empty; nothing below the record's top level did.

    That was invisible to every gate in the plain lane. The one test that saw it,
    ``test_a_maximal_export_validates``, lives behind ``HK_SCHEMA_GATE`` and needs
    jsonschema, so an exported part carrying ten nulls sat red in that lane alone
    while every other check was green. This walks the whole document instead, so the
    next nested record is covered before somebody writes it.
    """
    asset = tr.assets_model.build_asset(_maximal_asset(), now=NOW)
    task = tr.models.build_task(_maximal_task(), now=NOW)
    document = tr.build_document([task], [asset], area_names=AREA_NAMES, now=NOW)
    nulls = sorted(_null_paths(document))
    assert not nulls, (
        f"{nulls} export as null. A reader cannot tell a stated nothing from an "
        "absent key, and the published JSON Schema types most of these, so the file "
        "fails the schema Home Keeper writes for it. Export the record through "
        "transfer._strip."
    )


def _null_paths(value: object, path: str = "") -> list[str]:
    """Every path in *value* whose leaf is ``None``, named for the error message."""
    if isinstance(value, dict):
        return [
            found
            for key, item in value.items()
            for found in _null_paths(item, f"{path}/{key}")
        ]
    if isinstance(value, list):
        return [
            found
            for index, item in enumerate(value)
            for found in _null_paths(item, f"{path}/{index}")
        ]
    return [path] if value is None else []
