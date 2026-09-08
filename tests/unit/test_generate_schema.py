"""The published JSON Schema, held against the code it claims to describe.

Every exported file names the schema on its first line, so an editor checks a document
against it as somebody types. A schema that has drifted from the importer is worse than
no schema at all: it sends people to fix files that would have imported, or blesses ones
that will not. This file is what makes that impossible to do quietly.

**The generator runs as a subprocess.** ``tests/conftest.py`` installs stub parent
packages so the pure core loads without Home Assistant, and its docstring states that
nothing in the suite imports the real ``custom_components.home_keeper`` in-process. A
fresh interpreter keeps that true, and has the side effect of testing the command the
docs build actually runs rather than a function next to it.

**This file runs only where ``HK_SCHEMA_GATE`` is set**, which is ``lint.yml``'s mypy
job. "Is Home Assistant importable?" is the wrong question, and an ``importorskip``
answered it wrongly: the unit lane installs ``pytest-homeassistant-custom-component``,
so Home Assistant *is* importable there — but on that job's Python pip backtracks to a
release old enough that the integration cannot import against it (``LOVELACE_DATA`` was
gone), and the gate failed for a reason that had nothing to do with the schema. That is
the #199 trap in a new place. The mypy job pins a Python at Home Assistant's floor and
runs ``ci/check-ha-version.py`` to prove what pip resolved, so it is the one job that
can answer this honestly — and it checks these tests really ran rather than skipped.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import hk_transfer as tr
import pytest

if not os.environ.get("HK_SCHEMA_GATE"):
    pytest.skip(
        "the published-schema gate needs Home Assistant at its own floor; "
        "lint.yml's mypy job sets HK_SCHEMA_GATE",
        allow_module_level=True,
    )

pytest.importorskip("voluptuous_openapi", reason="the converter")
jsonschema = pytest.importorskip("jsonschema", reason="nothing validates without it")

from transfer_records import (  # noqa: E402  (after the skips, on purpose)
    AREA_NAMES,
    NOW,
    _maximal_asset,
    _maximal_task,
)

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "home_keeper"


@pytest.fixture(scope="module")
def schema() -> dict:
    """What ``ci/generate_schema.py`` actually publishes."""
    done = subprocess.run(
        [sys.executable, str(ROOT / "ci" / "generate_schema.py"), "--stdout"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def validator(schema: dict):
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _service_fields(name: str) -> set[str]:
    yaml = pytest.importorskip("yaml", reason="the field list lives in services.yaml")
    document = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
    return set(document[name].get("fields", {}))


def _record(section: str, schema: dict) -> dict:
    return schema["properties"][section]["items"]


def _export() -> dict:
    """A maximal task and a maximal appliance, exported the way the service does."""
    task = tr.models.build_task(
        {k: v for k, v in _maximal_task().items() if v is not None}, now=NOW
    )
    tr.apply_history(
        task,
        [{"completed_at": "2026-03-04", "note": "n", "cost": 24.5, "who": "sensor.x"}],
        [{"skipped_at": "2025-09-01", "note": "away"}],
        now=NOW,
    )
    asset = tr.assets_model.build_asset(_maximal_asset(), now=NOW)
    return tr.build_document(
        [task], [asset], area_names=AREA_NAMES, version="test", now=NOW
    )


# ── The schema covers what the code has ──────────────────────────────────────


@pytest.mark.parametrize(
    ("section", "service", "extras", "withheld"),
    [
        ("tasks", "add_task", tr._TASK_EXTRA_KEYS, tr.UNPORTABLE_TASK_KEYS),
        ("appliances", "add_asset", tr._ASSET_EXTRA_KEYS, ()),
    ],
)
def test_the_schema_holds_every_field_the_action_takes(
    schema, section, service, extras, withheld
):
    """A field added to an action appears in the schema, typed, with no edit anywhere.

    That is the claim the whole generator rests on, so it is checked in both
    directions: a service field the schema forgot is a field an editor would flag as
    unknown, and a schema property with no service field behind it is a field that was
    typed by hand somewhere it should not have been.
    """
    expected = (_service_fields(service) - set(withheld)) | set(extras) | {"id"}
    assert set(_record(section, schema)["properties"]) == expected


@pytest.mark.parametrize("section", ["tasks", "appliances"])
def test_the_schema_holds_every_field_the_builders_really_build(schema, section):
    """The other source of truth, and the stricter one.

    ``services.yaml`` says what a caller may pass; ``models.build_task`` and
    ``assets.build_asset`` decide what a stored record *is*, and the export writes that.
    ``_known_*_keys`` probes the builders rather than listing their output, so a field
    added to a builder and to no service still has to be accounted for here.
    """
    known = tr._known_task_keys() if section == "tasks" else tr._known_asset_keys()
    excluded = {
        key
        for key, _reason in (
            tr.EXCLUDED_TASK_KEYS if section == "tasks" else tr.EXCLUDED_ASSET_KEYS
        )
    }
    missing = known - excluded - set(_record(section, schema)["properties"])
    assert not missing, (
        f"{sorted(missing)} survive the export but the schema does not name them. "
        "Add the field to services.yaml, or to the record schema's extras in "
        "custom_components/home_keeper/__init__.py."
    )


# ── The schema accepts what the export writes ────────────────────────────────


def test_a_maximal_export_validates(validator):
    """The one test that would catch a wrong *type* rather than a missing name."""
    errors = sorted(validator.iter_errors(_export()), key=lambda e: list(e.path))
    assert not errors, [
        f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors
    ]


def test_the_history_entry_shape_is_the_one_the_serializer_emits(schema):
    """Probed, not restated: ``completed_at`` and ``skipped_at`` are literals nowhere.

    ``_entry_out`` renames the stored ``ts``, so the document's key for "when" exists
    only in that function. Comparing against a real export is what pins it.
    """
    task = next(t for t in _export()["tasks"])
    properties = _record("tasks", schema)["properties"]
    for field, entries in (("history", task["history"]), ("skips", task["skips"])):
        declared = set(properties[field]["items"]["properties"])
        assert entries, f"the maximal task carries no {field} to compare against"
        assert set(entries[0]) <= declared
        assert set(entries[0]) & {"completed_at", "skipped_at"}


# ── The schema refuses what the importer refuses, and no more ────────────────

_ENVELOPE = {"home_keeper": {"format": 1}}


@pytest.mark.parametrize(
    ("document", "accepted", "why"),
    [
        ({}, False, "no envelope at all"),
        (_ENVELOPE, True, "an envelope and nothing else is a valid empty document"),
        ({**_ENVELOPE, "tasks": {}}, False, "a section is a list, not a mapping"),
        ({**_ENVELOPE, "tasks": [{}]}, False, "a task needs a name"),
        ({**_ENVELOPE, "tasks": [{"name": "A"}]}, True, "the smallest real task"),
        # The two forward-compatibility rows. An import reports either as a named
        # warning and carries on, so a schema that refused them would contradict the
        # code — which is why additionalProperties is left open at both levels.
        ({**_ENVELOPE, "tasks": [{"name": "A", "whatever": 1}]}, True, "unknown field"),
        ({**_ENVELOPE, "recipes": []}, True, "unknown section"),
    ],
)
def test_the_schema_and_the_importer_agree_on_these(validator, document, accepted, why):
    assert validator.is_valid(document) is accepted, why
    plan = tr.plan_import(document, tasks={}, assets={}, now=NOW)
    assert plan.ok is accepted, f"the importer disagrees: {why}"


def test_a_wrongly_typed_value_is_caught(validator):
    """The negative control. A gate that cannot fail is not a gate.

    Note this is the one place the schema is deliberately *stricter* than the importer:
    ``plan_import`` coerces ``"3"`` to 3, and the schema does not. That is not a lie,
    because no export ever writes a number as a string — it is the difference between
    what a forgiving importer tolerates and what a document should contain.
    """
    assert not validator.is_valid(
        {**_ENVELOPE, "tasks": [{"name": "A", "interval": "three"}]}
    )


# ── The published identity ───────────────────────────────────────────────────


def test_the_schema_url_names_the_format_and_matches_the_exported_file(schema):
    assert schema["$id"] == tr.TRANSFER_SCHEMA_URL
    assert f"home-keeper-{tr.TRANSFER_FORMAT}.schema.json" in schema["$id"]
    first_line = tr.document_to_yaml({"home_keeper": {"format": 1}}).splitlines()[0]
    assert first_line == f"# yaml-language-server: $schema={schema['$id']}"


def test_the_schema_declares_the_dialect_it_is_written_in(schema):
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
