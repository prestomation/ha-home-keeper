"""The translation of store exceptions into localized service errors.

* B02-6: a missing document gives ``unknown_document`` with the document id, not
  ``asset_not_found`` with the appliance id.
* B02-3: the declarative companion services give ``invalid_declarative_companion``
  and ``declarative_companion_not_found``, as their websocket twins do, and not a
  raw ``TaskValidationError`` or ``KeyError``.

``service_errors.py`` imports only Home Assistant's exception classes, so it loads
over the shared stub tree. The handlers in ``__init__.py`` that use it are checked
on the source, as ``test_lifecycle_handlers.py`` does.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest
from ha_stubs import install_ha_stubs

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"


def _load():
    install_ha_stubs()
    spec = importlib.util.spec_from_file_location(
        "hk.service_errors", str(_COMPONENT / "service_errors.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.service_errors"] = module
    spec.loader.exec_module(module)
    return module


errors = _load()
TaskValidationError = sys.modules["hk.models"].TaskValidationError
AssetValidationError = sys.modules["hk.assets"].AssetValidationError
ServiceValidationError = errors.ServiceValidationError


def _raised(manager, exc: BaseException) -> ServiceValidationError:
    with pytest.raises(ServiceValidationError) as info, manager:
        raise exc
    return info.value


def _shape(err: ServiceValidationError) -> tuple:
    return (
        err.translation_domain,
        err.translation_key,
        err.translation_placeholders,
    )


# ── store_errors ─────────────────────────────────────────────────────────────
def test_b02_6_a_missing_document_names_the_document():
    err = _raised(
        errors.store_errors(asset_id="a1", document_id="Manaul"), KeyError("Manaul")
    )
    assert _shape(err) == (
        "home_keeper",
        "unknown_document",
        {"document_id": "Manaul"},
    )


def test_a_missing_part_names_the_appliance_and_the_part():
    err = _raised(
        errors.store_errors(asset_id="a1", part_id="p1", document_id="d1"),
        KeyError("p1"),
    )
    assert _shape(err) == (
        "home_keeper",
        "unknown_part",
        {"asset_id": "a1", "part_id": "p1"},
    )


def test_a_missing_appliance_names_the_appliance():
    err = _raised(errors.store_errors(asset_id="a1", task_id="t1"), KeyError("a1"))
    assert _shape(err) == ("home_keeper", "asset_not_found", {"asset_id": "a1"})


def test_a_missing_task_names_the_task():
    err = _raised(errors.store_errors(task_id="t1"), KeyError("t1"))
    assert _shape(err) == ("home_keeper", "task_not_found", {"task_id": "t1"})


def test_a_key_error_with_no_id_goes_to_the_caller():
    with pytest.raises(KeyError), errors.store_errors():
        raise KeyError("x")


def test_a_task_validation_error_is_invalid_task():
    err = _raised(errors.store_errors(task_id="t1"), TaskValidationError("bad"))
    assert _shape(err) == ("home_keeper", "invalid_task", {"error": "bad"})
    assert isinstance(err.__cause__, TaskValidationError)


def test_an_asset_validation_error_is_invalid_asset():
    err = _raised(errors.store_errors(asset_id="a1"), AssetValidationError("bad"))
    assert _shape(err) == ("home_keeper", "invalid_asset", {"error": "bad"})


def test_a_call_with_no_error_passes():
    with errors.store_errors(task_id="t1"):
        value = 1
    assert value == 1


def test_service_error_with_no_placeholders_has_none():
    assert _shape(errors.service_error("integration_not_loaded")) == (
        "home_keeper",
        "integration_not_loaded",
        None,
    )


# ── declarative_companion_errors ─────────────────────────────────────────────
def test_b02_3_an_invalid_spec_is_invalid_declarative_companion():
    err = _raised(
        errors.declarative_companion_errors(), TaskValidationError("name is required")
    )
    assert _shape(err) == (
        "home_keeper",
        "invalid_declarative_companion",
        {"error": "name is required"},
    )
    assert isinstance(err.__cause__, TaskValidationError)


def test_b02_3_an_unknown_spec_is_declarative_companion_not_found():
    err = _raised(errors.declarative_companion_errors(spec_id="abc"), KeyError("abc"))
    assert _shape(err) == (
        "home_keeper",
        "declarative_companion_not_found",
        {"spec_id": "abc"},
    )
    assert err.__cause__ is None


def test_b02_3_a_key_error_with_no_spec_goes_to_the_caller():
    with pytest.raises(KeyError), errors.declarative_companion_errors():
        raise KeyError("x")


# ── the handlers use them ────────────────────────────────────────────────────
def _handler(name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse((_COMPONENT / "__init__.py").read_text())
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def _with_items(func: ast.AsyncFunctionDef) -> list[str]:
    return [
        ast.unparse(item.context_expr)
        for node in ast.walk(func)
        if isinstance(node, ast.With)
        for item in node.items
    ]


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (
            "handle_add_declarative_companion",
            "declarative_companion_errors()",
        ),
        (
            "handle_update_declarative_companion",
            "declarative_companion_errors(spec_id=spec_id)",
        ),
    ],
)
def test_b02_3_the_companion_handlers_translate_store_errors(handler, expected):
    assert expected in _with_items(_handler(handler))


@pytest.mark.parametrize(
    "handler", ["handle_remove_asset_document", "handle_update_asset_document"]
)
def test_b02_6_the_document_handlers_name_the_document(handler):
    func = _handler(handler)
    assert "_store_errors(document_id=document_id)" in _with_items(func)
    # The appliance is checked first, so its absence keeps its own message.
    assert "_require_asset(coord, asset_id)" in ast.unparse(func)


def _source(handler: str) -> str:
    return ast.unparse(_handler(handler))


@pytest.mark.parametrize(
    ("handler", "check"),
    [
        (
            "handle_delete_task",
            '_require_known("task", coord.store.get_tasks(), task_id)',
        ),
        (
            "handle_delete_asset",
            '_require_known("asset", coord.store.get_assets(), asset_id)',
        ),
    ],
)
def test_b02_7_a_delete_rejects_a_name_that_matches_no_record(handler, check):
    assert check.replace('"', "'") in _source(handler)


def test_b02_7_require_known_uses_the_id_form():
    source = ast.unparse(_handler("handle_delete_task"))
    assert "_require_known" in source
    tree = ast.parse((_COMPONENT / "__init__.py").read_text())
    helper = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_require_known"
    )
    assert "if key not in objects and (not looks_like_id(key)):" in ast.unparse(helper)


def test_b02_8_and_b02_9_set_task_meter_uses_translated_errors():
    source = _source("handle_set_task_meter")
    assert "service_error('meter_requires_usage_task')" in source
    assert "service_error('meter_has_no_reading')" in source
    assert "_store_errors(task_id=task_id)" in _with_items(
        _handler("handle_set_task_meter")
    )
    assert "'error':" not in source


def test_b02_9_add_asset_document_uses_link_documents_only():
    source = _source("handle_add_asset_document")
    assert "service_error('link_documents_only')" in source
    assert "'error':" not in source


def test_b21_3_delete_archived_completion_resolves_against_the_history():
    source = _source("handle_delete_archived_completion")
    assert (
        "_ref('task', resolve_archived_task_id, asset, call.data['task_id'])" in source
    )
    assert "_task_ref(" not in source
    assert "if not has_archived_completion(asset, task_id, ts):" in source
    assert "'archived_completion_not_found'" in source
