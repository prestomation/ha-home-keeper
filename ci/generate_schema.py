#!/usr/bin/env python3
"""Publish the JSON Schema for the import/export document, derived from the validator.

Every exported file names this schema on its first line, so an editor checks a
document against it as somebody types. That only earns its keep if the schema and the
running code cannot disagree — so nothing here describes a field. The schema is a
mechanical transform, by ``voluptuous_openapi``, of
``custom_components.home_keeper.TRANSFER_DOCUMENT_SCHEMA``, which is itself
``ADD_TASK_SCHEMA`` and ``ADD_ASSET_SCHEMA`` — the shapes the ``add_task`` and
``add_asset`` actions validate with — extended by the eight keys a document carries
that no action takes. Add a field to an action tomorrow and it appears here, typed,
with no edit to this file.

Unlike ``generate_api_docs.py``, this **imports Home Assistant**: a service schema is
written in ``cv.string`` / ``cv.boolean`` / ``cv.datetime``, so there is no reading it
without the library that defines them. The docs workflows install it for this reason.

``tests/unit/test_generate_schema.py`` is the gate. It compares the schema's field set
against the records ``models.build_task`` and ``assets.build_asset`` really build, and
validates a real export against it, so a schema that has drifted from the code fails
before it is published.

**Bumping ``TRANSFER_FORMAT`` must ADD a file, never replace one.** The version is in
the filename, and every file exported before the bump still points at the old name. The
production deploy runs with ``clean: true`` and only excludes the two preview
umbrellas, so the moment this generator stops writing ``home-keeper-1.schema.json`` that
file leaves the site and every document written this year stops validating. Add
``schema/`` to ``clean-exclude`` in ``docs-deploy.yml``, or emit the frozen older
formats alongside the current one.

Run it by hand with::

    python3 ci/generate_schema.py            # write website/static/schema/
    python3 ci/generate_schema.py --stdout   # print instead, for a quick look
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "website" / "static" / "schema"

# JSON Schema, not OpenAPI 3.0. The two dialects differ where it matters here: 3.0
# spells a nullable value ``{"nullable": true}``, which no JSON Schema validator reads.
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

TITLE = "Home Keeper portable document"

# Why the schema is permissive where it is. JSON has no comments, so the reasoning has
# to ride in the document itself or it is not in front of the person reading the file.
COMMENT = (
    "Generated from custom_components/home_keeper by ci/generate_schema.py — do not "
    "edit, and do not commit. Unknown fields and unknown sections are allowed on "
    "purpose: an import reports one as a named warning and carries on, so a schema "
    "that refused them would send people to fix files that import cleanly."
)


def load_component() -> Any:
    """The integration, imported for real.

    ``generate_api_docs.py`` goes to some length to load ``api_surface`` *without*
    Home Assistant, because it only needs names. This one needs the validators, and a
    validator is Home Assistant code.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        # Home Assistant must be imported FIRST, before anything pulls in voluptuous.
        # Since 2026.3 its package ``__init__`` calls ``install_as_voluptuous()`` to put
        # probatio in voluptuous's place, and it warns when something imported
        # voluptuous already: references then resolve to two different ``Schema``
        # classes, and ``voluptuous_openapi``'s ``schema in TYPES_MAP`` raises
        # ``TypeError: unhashable type: 'Schema'`` on the wrong one. The component's own
        # first third-party import is ``import voluptuous as vol``, which under Home
        # Assistant is harmless (Home Assistant loaded itself long before) and here is
        # not — so this line is load-bearing, not tidying. CI found it; a local Home
        # Assistant old enough to still use voluptuous cannot.
        import homeassistant  # noqa: F401

        import custom_components.home_keeper as component
    except ImportError as err:  # pragma: no cover - a setup problem, not a code path
        raise SystemExit(
            f"ci/generate_schema.py cannot import the integration: {err}.\n"
            "It reads the voluptuous service schemas, which are written in Home "
            "Assistant validators, so it needs Home Assistant on a Python at Home "
            "Assistant's own floor:\n"
            "    pip install homeassistant voluptuous-openapi Babel"
        ) from err

    return component


def _serialize(schema: Any) -> Any:
    """The handful of validators ``voluptuous_openapi`` cannot read for itself.

    It returns ``UNSUPPORTED`` for anything else, which hands the value back to the
    library's own inference — so this stays a list of exceptions rather than a second
    type table.
    """
    import voluptuous as vol
    from homeassistant.helpers import config_validation as cv
    from voluptuous_openapi import UNSUPPORTED, OpenApiVersion, convert

    if (
        isinstance(schema, vol.All)
        and schema.validators
        and schema.validators[0] is cv.ensure_list
    ):
        # ``vol.All(cv.ensure_list, [X])`` takes a bare X *or* a list of them, and
        # ``labels: kitchen`` is the obvious thing to write by hand. The library renders
        # only the list, so an editor would flag a document that imports cleanly — the
        # one thing a published schema must never do.
        as_list = convert(
            vol.Schema(schema.validators[1]),
            custom_serializer=_serialize,
            openapi_version=OpenApiVersion.V3_1,
        )
        item = as_list.get("items")
        return {"anyOf": [item, as_list]} if item else UNSUPPORTED
    if schema is cv.string:
        # Inferred correctly on its own, but not inside a ``vol.Any``, where the
        # library emits an empty (anything-goes) branch instead.
        return {"type": "string"}
    if schema is cv.boolean:
        # ``cv.boolean`` also accepts "on", "yes" and 1, so the library infers a
        # string. A *document* only ever holds a real boolean: that is what an export
        # writes and what YAML reads back.
        return {"type": "boolean"}
    if schema is cv.datetime:
        # Inferred as a string already, but say so rather than depend on it: the
        # document carries an ISO timestamp, never a datetime object.
        return {"type": "string"}
    return UNSUPPORTED


def _tidy(node: Any) -> Any:
    """Drop the artefacts of the conversion, in place of nothing else.

    Only two, and neither says anything about a field: an empty ``required`` list
    (which means "nothing is required", the same as leaving it out) and OpenAPI's
    ``nullable`` flag if a future version of the library emits one under the 3.1
    dialect.
    """
    if isinstance(node, dict):
        node = {key: _tidy(value) for key, value in node.items()}
        if node.get("required") == []:
            node.pop("required")
        if node.pop("nullable", None) and "type" in node:
            node["type"] = [node["type"], "null"]
        return node
    if isinstance(node, list):
        return [_tidy(item) for item in node]
    return node


def build_schema(component: Any | None = None) -> dict[str, Any]:
    """The published schema, as a dict."""
    from voluptuous_openapi import OpenApiVersion, convert

    component = component or load_component()
    body = convert(
        component.TRANSFER_DOCUMENT_SCHEMA,
        custom_serializer=_serialize,
        openapi_version=OpenApiVersion.V3_1,
    )
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": component.const.TRANSFER_SCHEMA_URL,
        "title": TITLE,
        "$comment": COMMENT,
        **_tidy(body),
    }


def filenames(component: Any) -> tuple[str, str]:
    """``(versioned, current)``.

    The versioned name is what an exported file points at, so it must never move. The
    unversioned one is a convenience for somebody writing a document by hand today.
    """
    versioned = component.const.TRANSFER_SCHEMA_URL.rsplit("/", 1)[-1]
    return versioned, "home-keeper.schema.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="where to write the schema files",
    )
    parser.add_argument(
        "--stdout", action="store_true", help="print the schema instead of writing it"
    )
    args = parser.parse_args(argv)

    component = load_component()
    text = json.dumps(build_schema(component), indent=2, ensure_ascii=False) + "\n"
    if args.stdout:
        sys.stdout.write(text)
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name in filenames(component):
        path = args.out_dir / name
        path.write_text(text, encoding="utf-8")
        print(f"[generate-schema] wrote {os.path.relpath(path, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
