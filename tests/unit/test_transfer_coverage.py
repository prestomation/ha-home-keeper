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
from pathlib import Path

import hk_transfer as tr
import pytest

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised by the skip
    yaml = None

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"

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
    if yaml is None:
        pytest.skip("PyYAML is not installed")
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
