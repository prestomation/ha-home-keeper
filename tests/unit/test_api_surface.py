"""Drift guard for the integrator-facing API surface (no HA runtime).

``api_surface.py`` claims to be the single index of every surface an integrator can
build on. These checks make that claim enforceable: a service registered without a
``ServiceSpec``, an event named in ``const.py`` and never modelled, a websocket
command whose decorator and registration disagree, a payload field added to
``events.py`` and described nowhere — each fails here rather than shipping.

The technique is the one ``test_exception_translations.py`` already uses: parse the
component's own source with :mod:`ast` and compare it to the model. Static analysis
is brittle when it has to *infer*; here it only reads string literals out of a
handful of registration calls, and every one of them is a literal today. The half
static can't reach — that the running system really registers and really tears down
what the model says — is covered by ``tests/integration/test_api_surface.py``.

**Where these checks can be fooled.** They read literals, so they see what the
source says and not what it computes. A service registered with a name built at
runtime rather than written out, a websocket command whose decorator ``type`` is
not a string constant, or an ``HomeAssistantView`` whose ``url`` is not the
``PREFIX + "/…"`` shape ``_view_classes`` expects would each pass unnoticed.
``test_admin_only_services_verify_admin`` matches the text of the call, so a
``_verify_admin`` behind a condition that never runs still reads as gated. Every
one of those is a departure from how the component is written today, which is why
literal-reading is enough; if you introduce one, the runtime test is the backstop
and this file needs widening rather than trusting.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import hk_api_surface as api_surface
import hk_const as const
import hk_events as events
import hk_transitions as transitions
import pytest

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"
_INIT_TREE = ast.parse((_COMPONENT / "__init__.py").read_text(encoding="utf-8"))
_WS_TREE = ast.parse((_COMPONENT / "websocket_api.py").read_text(encoding="utf-8"))
_MANUALS_TREE = ast.parse((_COMPONENT / "manuals.py").read_text(encoding="utf-8"))
_STRINGS = json.loads((_COMPONENT / "strings.json").read_text(encoding="utf-8"))

_FIX = "Add or update its spec in custom_components/home_keeper/api_surface.py."


# ── Source introspection helpers ─────────────────────────────────────────────


def _kwarg(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _service_registrations() -> list[tuple[str, str, str]]:
    """``(service name, handler name, response kind)`` per ``async_register`` call."""
    found: list[tuple[str, str, str]] = []
    for node in ast.walk(_INIT_TREE):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "async_register"):
            continue
        owner = func.value
        if not (isinstance(owner, ast.Attribute) and owner.attr == "services"):
            continue
        if len(node.args) < 3 or not isinstance(node.args[1], ast.Constant):
            continue
        response = "none"
        if (supports := _kwarg(node, "supports_response")) is not None:
            # ``SupportsResponse.ONLY`` -> "only"
            response = ast.unparse(supports).rsplit(".", 1)[-1].lower()
        found.append(
            (node.args[1].value, ast.unparse(node.args[2]), response),
        )
    return found


def _handler_bodies() -> dict[str, str]:
    """Unparsed source of every ``handle_*`` function, nested ones included."""
    return {
        node.name: ast.unparse(node)
        for node in ast.walk(_INIT_TREE)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("handle_")
    }


def _websocket_commands() -> list[tuple[str, str, bool]]:
    """``(command type, function name, requires admin)`` per decorated handler."""
    found: list[tuple[str, str, bool]] = []
    for node in ast.walk(_WS_TREE):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        command: str | None = None
        admin = False
        for decorator in node.decorator_list:
            source = ast.unparse(decorator)
            if "require_admin" in source:
                admin = True
            if not (
                isinstance(decorator, ast.Call)
                and "websocket_command" in ast.unparse(decorator.func)
                and decorator.args
                and isinstance(decorator.args[0], ast.Dict)
            ):
                continue
            for value in decorator.args[0].values:
                if (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and value.value.startswith(f"{const.DOMAIN}/")
                ):
                    command = value.value
        if command is not None:
            found.append((command, node.name, admin))
    return found


def _view_classes() -> dict[str, dict[str, Any]]:
    """Class-level ``url`` / ``name`` / ``requires_auth`` per ``HomeAssistantView``."""
    found: dict[str, dict[str, Any]] = {}
    for node in ast.walk(_MANUALS_TREE):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any("HomeAssistantView" in ast.unparse(b) for b in node.bases):
            continue
        attrs: dict[str, Any] = {"methods": []}
        for statement in node.body:
            if isinstance(statement, ast.Assign) and isinstance(
                statement.targets[0], ast.Name
            ):
                attrs[statement.targets[0].id] = ast.unparse(statement.value)
            elif isinstance(
                statement, ast.FunctionDef | ast.AsyncFunctionDef
            ) and statement.name in ("get", "post", "put", "delete"):
                attrs["methods"].append(statement.name.upper())
        found[node.name] = attrs
    return found


# ── Services ─────────────────────────────────────────────────────────────────


def test_every_registered_service_is_modelled() -> None:
    """The services ``__init__.py`` registers are exactly the modelled ones."""
    registered = {name for name, _, _ in _service_registrations()}
    modelled = set(api_surface.SERVICE_NAMES)
    assert registered == modelled, {
        "registered_but_not_modelled": sorted(registered - modelled),
        "modelled_but_not_registered": sorted(modelled - registered),
        "fix": _FIX,
    }


def test_service_names_are_unique() -> None:
    names = list(api_surface.SERVICE_NAMES)
    assert len(names) == len(set(names)), "duplicate ServiceSpec name"


def test_service_teardown_iterates_the_model() -> None:
    """``async_unload_entry`` removes every modelled service, not a second list.

    ``set_task_meter`` was registered for releases while a hand-maintained
    ``_SERVICES`` tuple beside it went one short, so it was never removed on
    unload. A derived list can't be one short; this keeps the literal from
    coming back.
    """
    source = (_COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert "_SERVICES = (" not in source, (
        "A second, hand-written service list has reappeared in __init__.py. "
        "Iterate api_surface.SERVICE_NAMES instead — a list nobody derives is a "
        "list somebody forgets."
    )
    unload = next(
        node
        for node in ast.walk(_INIT_TREE)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_unload_entry"
    )
    assert "SERVICE_NAMES" in ast.unparse(unload)


def test_service_response_kind_matches_source() -> None:
    """``SupportsResponse`` at the registration site matches ``ServiceSpec``.

    Unmodelled services are skipped here so their single, clear failure stays in
    ``test_every_registered_service_is_modelled`` instead of echoing as a
    ``KeyError`` through every other service check.
    """
    modelled = {spec.name: spec for spec in api_surface.SERVICES}
    mismatched = {
        name: {"source": response, "model": modelled[name].response}
        for name, _, response in _service_registrations()
        if name in modelled and modelled[name].response != response
    }
    assert not mismatched, {"supports_response_mismatch": mismatched, "fix": _FIX}


def test_admin_only_services_verify_admin() -> None:
    """Every ``admin_only`` service gates its handler, and only those do.

    The panel is ``require_admin``, so an admin-only operation has to be gated in
    its service too or ``call_service`` walks straight around the panel (see
    docs/SECURITY.md). Modelling the flag is only worth something if it tracks the
    gate that actually runs.
    """
    bodies = _handler_bodies()
    modelled = {spec.name: spec for spec in api_surface.SERVICES}
    wrong: dict[str, str] = {}
    for name, handler, _ in _service_registrations():
        if name not in modelled:
            continue  # reported by test_every_registered_service_is_modelled
        gated = "_verify_admin" in bodies.get(handler, "")
        if gated != modelled[name].admin_only:
            wrong[name] = (
                "handler verifies admin but the model doesn't say admin_only"
                if gated
                else "model says admin_only but the handler never calls _verify_admin"
            )
    assert not wrong, {"admin_gate_mismatch": wrong, "fix": _FIX}


def test_services_yaml_matches_model() -> None:
    """``services.yaml`` describes exactly the modelled services."""
    yaml = pytest.importorskip("yaml", reason="PyYAML parses services.yaml")
    described = set(
        yaml.safe_load((_COMPONENT / "services.yaml").read_text(encoding="utf-8"))
    )
    modelled = set(api_surface.SERVICE_NAMES)
    assert described == modelled, {
        "in_services_yaml_only": sorted(described - modelled),
        "in_model_only": sorted(modelled - described),
    }


def test_service_strings_match_model() -> None:
    """``strings.json`` localizes exactly the modelled services.

    The generated reference reads its service and field prose from here, so a
    service missing an entry would render nameless.
    """
    localized = set(_STRINGS["services"])
    modelled = set(api_surface.SERVICE_NAMES)
    assert localized == modelled, {
        "in_strings_json_only": sorted(localized - modelled),
        "in_model_only": sorted(modelled - localized),
    }


def test_service_fields_match_between_yaml_and_strings() -> None:
    """Each service describes the same field set in both files.

    Only the service *names* were pinned to the model; the fields under them were
    left to hassfest. They matter here too: the reference takes a field's
    structure (required, selector) from ``services.yaml`` and its label and
    description from ``strings.json``, so a field present in one and missing from
    the other renders half-blank.
    """
    yaml = pytest.importorskip("yaml", reason="PyYAML parses services.yaml")
    described = yaml.safe_load((_COMPONENT / "services.yaml").read_text("utf-8"))
    localized = _STRINGS["services"]
    mismatched = {}
    for name in api_surface.SERVICE_NAMES:
        in_yaml = set((described.get(name) or {}).get("fields") or {})
        in_strings = set((localized.get(name) or {}).get("fields") or {})
        if in_yaml != in_strings:
            mismatched[name] = {
                "only_in_services_yaml": sorted(in_yaml - in_strings),
                "only_in_strings_json": sorted(in_strings - in_yaml),
            }
    assert not mismatched, {"service_field_mismatch": mismatched}


# ── Events ───────────────────────────────────────────────────────────────────


def _const_event_names() -> dict[str, str]:
    """``{const attribute: value}`` for every ``EVENT_*`` name in ``const.py``."""
    return {
        name: getattr(const, name)
        for name in dir(const)
        if name.startswith("EVENT_") and isinstance(getattr(const, name), str)
    }


def test_every_const_event_is_modelled() -> None:
    """Every ``const.EVENT_*`` appears once in the model, under its own name."""
    declared = _const_event_names()
    modelled = {spec.const_name: spec.name for spec in api_surface.EVENTS}
    assert set(modelled) == set(declared), {
        "in_const_only": sorted(set(declared) - set(modelled)),
        "in_model_only": sorted(set(modelled) - set(declared)),
        "fix": _FIX,
    }
    wrong_value = {
        name: {"const": declared[name], "model": value}
        for name, value in modelled.items()
        if declared[name] != value
    }
    assert not wrong_value, {"event_value_mismatch": wrong_value}

    names = [spec.name for spec in api_surface.EVENTS]
    assert len(names) == len(set(names)), "an event is modelled twice"


def test_every_fired_event_has_a_summary() -> None:
    """A fired event carries its own "fires when" line.

    This is the mechanical half of the "keep the catalog in sync" rule: the
    Developer Guide renders these, and an event with no summary would show up in
    the reference as a bare name.
    """
    missing = sorted(
        spec.name
        for spec in api_surface.EVENTS
        if spec.direction == "fired" and not spec.summary.strip()
    )
    assert not missing, {"events_without_a_summary": missing, "fix": _FIX}


def test_event_directions_and_payloads_are_known() -> None:
    bad = [
        spec.name
        for spec in api_surface.EVENTS
        if spec.direction not in ("fired", "listened")
        or (spec.payload != "none" and spec.payload not in api_surface.PAYLOAD_SPINES)
    ]
    assert not bad, {"unknown_direction_or_payload": bad}


# Every field the builders read, carrying a value. Deliberately wider than the
# spines so an unmodelled key that only appears "when set" has something to appear
# from.
_FULL_TASK: dict[str, Any] = {
    "id": "task-1",
    "name": "Replace filter",
    "device_id": "dev-1",
    "area_id": "area-1",
    "recurrence_type": "floating",
    "interval": 3,
    "unit": "months",
    "next_due": "2026-09-01T00:00:00+00:00",
    "last_completed": "2026-06-01T00:00:00+00:00",
    "enabled": True,
    "labels": ["label-1"],
    "source": {"demo": {"thing": 1}},
    "managed_by": {"integration": "demo"},
    "task_chips": [{"label": "chip"}],
    "tag_id": "tag-1",
    "completions": [{"ts": "2026-06-01T00:00:00+00:00", "note": "n"}],
    "sensor": {"entity_id": "sensor.demo", "mode": "usage"},
}
_FULL_ASSET: dict[str, Any] = {
    "id": "asset-1",
    "name": "Furnace",
    "device_id": "dev-2",
    "model": "X",
    "serial_number": "SN",
    "archived_at": "2026-07-01T00:00:00+00:00",
}
_FULL_PART: dict[str, Any] = {
    "id": "part-1",
    "name": "Filter",
    "part_number": "PN-1",
    "vendor": "Acme",
    "stock": 2.5,
    "reorder_at": 1,
    "stock_unit": "ml",
    "restock_quantity": 4,
}
_FULL_COMPANION: dict[str, Any] = {
    "domain": "demo",
    "name": "Demo",
    "status": "connected",
    "config_entry_id": "entry-1",
    "upstream_domain": "upstream",
    "docs_url": "https://example.com",
}
_FULL_DECLARATIVE_SPEC: dict[str, Any] = {
    "id": "spec-1",
    "name": "Firmware update available",
    "description": "One task per update entity",
    "enabled": True,
    "preset_id": "firmware_update_available",
    "selection": {"domain": "update"},
    "trigger": {"mode": "state", "state": "on"},
    "task_template": {"name_template": "{{ friendly_name }}"},
}


def test_payload_spines_match_the_event_builders() -> None:
    """Each modelled spine is exactly what ``events.py`` builds, in order.

    This is the hard guarantee. The builders are pure, so the test calls the
    shipping code rather than describing it: a field added to a payload and not
    documented fails here, and so does one documented but never sent.
    """
    # Probe twice: empty inputs, and inputs with every field populated. A builder
    # that adds a key only when some field carries a value would look complete
    # against empty dicts alone.
    probes = {
        "task": (events.task_event_data, ({},), (_FULL_TASK,)),
        "asset": (events.asset_event_data, ({},), (_FULL_ASSET,)),
        "stock": (events.stock_event_data, ({}, {}), (_FULL_ASSET, _FULL_PART)),
        "companion": (events.companion_event_data, ({},), (_FULL_COMPANION,)),
        "declarative_companion": (
            events.declarative_companion_event_data,
            ({},),
            (_FULL_DECLARATIVE_SPEC,),
        ),
    }
    assert set(probes) == set(api_surface.PAYLOAD_SPINES), (
        "a spine is modelled with no builder behind it"
    )
    for shape, (builder, empty, full) in probes.items():
        modelled = tuple(f.name for f in api_surface.PAYLOAD_SPINES[shape])
        for label, args in (("empty", empty), ("populated", full)):
            payload = builder(*args)
            assert modelled == tuple(payload), {
                "payload": shape,
                "inputs": label,
                "built_by_events_py": list(payload),
                "modelled": list(modelled),
                "fix": _FIX,
            }


def _extras(spec_name: str) -> set[str]:
    spec = next(s for s in api_surface.EVENTS if s.name == spec_name)
    return {f.name for f in spec.extra}


def test_completion_extras_match_the_builder() -> None:
    """``completion_event_data`` adds exactly the modelled completion keys."""
    spine = set(events.task_event_data({}))
    when = datetime(2026, 1, 1, tzinfo=UTC)
    metadata = {"note": "n", "cost": 1.0, "photo": "p", "who": "w", "reading": 2.0}
    built = set(events.completion_event_data({}, when, "origin", metadata=metadata))
    assert built - spine == _extras(const.EVENT_TASK_COMPLETED), {
        "built": sorted(built - spine),
        "modelled": sorted(_extras(const.EVENT_TASK_COMPLETED)),
        "fix": _FIX,
    }


def test_transition_extras_match_the_model() -> None:
    """The overdue / due-soon payloads carry the spine plus their declared extras."""
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    tasks = {
        "overdue": {
            "id": "overdue",
            "name": "Overdue",
            "enabled": True,
            "next_due": (now - timedelta(days=2)).isoformat(),
        },
        "soon": {
            "id": "soon",
            "name": "Soon",
            "enabled": True,
            "next_due": (now + timedelta(hours=12)).isoformat(),
        },
    }
    fired, _ = transitions.detect_transitions({}, tasks, now=now)
    assert fired, "the fixture should produce both transitions"
    spine = set(events.task_event_data({}))
    for name, payload in fired:
        assert set(payload) - spine == _extras(name), {
            "event": name,
            "built": sorted(set(payload) - spine),
            "modelled": sorted(_extras(name)),
            "fix": _FIX,
        }


# ── Device triggers ──────────────────────────────────────────────────────────


def test_device_triggers_match_strings_and_events() -> None:
    """Every trigger has a label, a modelled event, and a known scope."""
    labelled = set(_STRINGS["device_automation"]["trigger_type"])
    modelled = {spec.type for spec in api_surface.DEVICE_TRIGGERS}
    assert modelled == labelled, {
        "in_strings_json_only": sorted(labelled - modelled),
        "in_model_only": sorted(modelled - labelled),
        "fix": _FIX,
    }
    known_events = {spec.name for spec in api_surface.EVENTS}
    assert all(spec.event in known_events for spec in api_surface.DEVICE_TRIGGERS)
    assert {spec.scope for spec in api_surface.DEVICE_TRIGGERS} <= {"task", "asset"}


def test_trigger_scopes_partition_the_triggers() -> None:
    """``triggers_for`` hands ``device_trigger.py`` every trigger, once."""
    task = api_surface.triggers_for("task")
    asset = api_surface.triggers_for("asset")
    assert not set(task) & set(asset)
    assert len(task) + len(asset) == len(api_surface.DEVICE_TRIGGERS)


# ── Entities ─────────────────────────────────────────────────────────────────


def test_entity_platforms_match_const_and_strings() -> None:
    """Every platform is modelled, with the translation keys it really ships."""
    modelled = {spec.platform for spec in api_surface.ENTITY_PLATFORMS}
    assert modelled == set(const.PLATFORMS), {
        "in_const_platforms_only": sorted(set(const.PLATFORMS) - modelled),
        "in_model_only": sorted(modelled - set(const.PLATFORMS)),
        "fix": _FIX,
    }
    wrong = {
        spec.platform: {
            "strings_json": sorted(_STRINGS["entity"].get(spec.platform, {})),
            "modelled": sorted(spec.translation_keys),
        }
        for spec in api_surface.ENTITY_PLATFORMS
        if set(spec.translation_keys) != set(_STRINGS["entity"].get(spec.platform, {}))
    }
    assert not wrong, {"entity_translation_key_mismatch": wrong, "fix": _FIX}


# ── Config entry options ─────────────────────────────────────────────────────


def test_options_match_the_options_module() -> None:
    """``OPTIONS`` names exactly the keys ``options.py`` defines, flagged correctly.

    ``options._empty_options()`` stays the one definition of which keys exist and
    ``FLOW_OPTIONS`` of which the form renders; this pins the model's copy to both.
    The copy is deliberate — see the note beside ``OPTIONS``.
    """
    import hk_options as options

    assert {spec.key for spec in api_surface.OPTIONS} == set(options.ALL_OPTIONS)
    keys = [spec.key for spec in api_surface.OPTIONS]
    assert len(keys) == len(set(keys)), "an option is modelled twice"
    in_flow = {spec.key for spec in api_surface.OPTIONS if spec.in_flow}
    assert in_flow == set(options.FLOW_OPTIONS)


def test_api_surface_imports_stay_light() -> None:
    """The model imports nothing but ``const``.

    ``ci/generate_api_docs.py`` executes this module on a docs runner that installs
    no integration dependencies, so a heavier import breaks the site build rather
    than anything here. It did once: importing ``options`` for two tuples of
    strings reached ``notifications`` and then Babel.
    """
    tree = ast.parse((_COMPONENT / "api_surface.py").read_text(encoding="utf-8"))
    siblings = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 1
        for alias in node.names
    }
    assert siblings == {"const"}, {
        "unexpected_sibling_imports": sorted(siblings - {"const"}),
        "why": "keep api_surface importable without the integration's dependencies",
    }
    third_party = {
        node.names[0].name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
    }
    assert not third_party, {"unexpected_top_level_imports": sorted(third_party)}


def test_flow_options_are_rendered_by_the_options_form() -> None:
    """Every flow option has a label the generated reference can show."""
    data = _STRINGS["options"]["step"]["init"]["data"]
    missing = sorted(
        spec.key
        for spec in api_surface.OPTIONS
        if spec.in_flow and spec.key not in data
    )
    assert not missing, {"flow_options_without_a_label": missing}


# ── Internal surfaces: modelled and checked, not published ───────────────────


def test_every_websocket_command_is_modelled() -> None:
    declared = {command for command, _, _ in _websocket_commands()}
    modelled = {spec.type for spec in api_surface.WEBSOCKET_COMMANDS}
    assert declared == modelled, {
        "in_websocket_api_only": sorted(declared - modelled),
        "in_model_only": sorted(modelled - declared),
        "fix": _FIX,
    }


def test_every_websocket_command_is_registered() -> None:
    """A decorated handler that ``async_register`` never wires up is dead code.

    The decorator and the registration are two lists today, and nothing compared
    them — a command could be declared and unreachable, or registered twice.
    """
    register = next(
        node
        for node in ast.walk(_WS_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == "async_register"
    )
    body = ast.unparse(register)
    unregistered = sorted(
        handler for _, handler, _ in _websocket_commands() if handler not in body
    )
    assert not unregistered, {
        "declared_but_never_registered": unregistered,
        "fix": "Add websocket_api.async_register_command(hass, <handler>).",
    }


def test_websocket_admin_flags_match_source() -> None:
    """``require_admin`` on the handler matches the modelled flag."""
    modelled = {spec.type: spec.admin_only for spec in api_surface.WEBSOCKET_COMMANDS}
    wrong = {
        command: {"source": admin, "model": modelled[command]}
        for command, _, admin in _websocket_commands()
        if modelled[command] != admin
    }
    assert not wrong, {"require_admin_mismatch": wrong, "fix": _FIX}


def test_websocket_commands_name_a_real_service() -> None:
    """A command's declared service twin exists — the websocket never stands alone."""
    services = set(api_surface.SERVICE_NAMES)
    dangling = sorted(
        spec.type
        for spec in api_surface.WEBSOCKET_COMMANDS
        if spec.service is not None and spec.service not in services
    )
    assert not dangling, {"websocket_points_at_no_such_service": dangling}


def test_http_views_match_source() -> None:
    """Each ``HomeAssistantView``'s url, name, auth and methods are modelled."""
    modelled = {spec.name: spec for spec in api_surface.HTTP_VIEWS}
    found = _view_classes()
    names = {
        attrs["name"].strip("'\""): attrs for attrs in found.values() if "name" in attrs
    }
    assert set(names) == set(modelled), {
        "in_manuals_py_only": sorted(set(names) - set(modelled)),
        "in_model_only": sorted(set(modelled) - set(names)),
        "fix": _FIX,
    }
    wrong: dict[str, Any] = {}
    for name, attrs in names.items():
        spec = modelled[name]
        # ``url`` is written as ``PREFIX + '/{...}'``; compare the literal tail,
        # since the prefix constant is what the model already interpolates.
        tail = attrs["url"].split("+", 1)[-1].strip().strip("'\"")
        if not spec.url.endswith(tail):
            wrong[name] = {"source_url_tail": tail, "model_url": spec.url}
        if (attrs.get("requires_auth") == "True") != spec.requires_auth:
            wrong[name] = {
                **wrong.get(name, {}),
                "requires_auth": attrs.get("requires_auth"),
            }
        if set(attrs["methods"]) != set(spec.methods):
            wrong[name] = {
                **wrong.get(name, {}),
                "source_methods": sorted(attrs["methods"]),
                "model_methods": sorted(spec.methods),
            }
    assert not wrong, {"http_view_mismatch": wrong, "fix": _FIX}


# ── Surface coverage ─────────────────────────────────────────────────────────


def test_surface_kinds_are_complete() -> None:
    """Every surface kind carries a valid status and a reason.

    The rows that say *not_applicable* or *deferred* are the point of the table:
    a list of what we offer can't tell you what was forgotten, a list of the whole
    space with a reason on every absence can. An empty note is a row that has
    stopped doing that job.
    """
    kinds = [spec.kind for spec in api_surface.SURFACE_KINDS]
    assert len(kinds) == len(set(kinds)), "a surface kind is listed twice"
    bad = {
        spec.kind: {"status": spec.status, "note": spec.note}
        for spec in api_surface.SURFACE_KINDS
        if spec.status not in api_surface.STATUSES or not spec.note.strip()
    }
    assert not bad, {"invalid_surface_kind": bad}
