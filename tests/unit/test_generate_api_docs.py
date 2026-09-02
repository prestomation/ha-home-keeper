"""Tests for the Developer Guide's API-reference generator.

The rendering helpers are exercised against **synthetic** sources, so a test can
say something the real repo happens not to demonstrate — most importantly that
when ``services.yaml`` and ``strings.json`` disagree about an action's wording,
the localized string wins. That is the whole promise of the page: it says what
Home Assistant's own dialogs say.

One test runs against the real repo, asserting every modelled surface actually
reaches the output. It is the check that catches a broken generator on a pull
request that never touches ``website/`` and so never builds the site.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import hk_api_surface as api_surface
import pytest

_ROOT = Path(__file__).resolve().parents[2]

pytest.importorskip("yaml", reason="PyYAML parses services.yaml")


def _load_generator():
    """Import ``ci/generate_api_docs.py`` by path, as the other ci/ tests do."""
    spec = importlib.util.spec_from_file_location(
        "generate_api_docs", _ROOT / "ci" / "generate_api_docs.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


# ── Table cells ──────────────────────────────────────────────────────────────


def test_cell_collapses_newlines() -> None:
    """A folded YAML description is one cell, not three broken rows."""
    assert gen.cell("first line\n  second\n\nthird") == "first line second third"


def test_cell_escapes_pipes() -> None:
    """An unescaped pipe would end the cell early and shift every column."""
    assert gen.cell("str | None") == r"str \| None"


def test_cell_renders_missing_text_as_empty() -> None:
    assert gen.cell(None) == ""


# ── Selectors ────────────────────────────────────────────────────────────────


def test_selector_summary_lists_select_options() -> None:
    selector = {"select": {"options": ["floating", "fixed"]}}
    assert gen.selector_summary(selector) == "select (floating, fixed)"


def test_selector_summary_handles_labelled_select_options() -> None:
    """HA also allows ``{value, label}`` options; the value is what you pass."""
    selector = {"select": {"options": [{"value": "days", "label": "Days"}]}}
    assert gen.selector_summary(selector) == "select (days)"


def test_selector_summary_reports_number_bounds() -> None:
    assert gen.selector_summary({"number": {"min": 1, "max": 10}}) == (
        "number (min 1, max 10)"
    )


def test_selector_summary_marks_multiline_text_and_multiple() -> None:
    assert gen.selector_summary({"text": {"multiline": True}}) == "text (multiline)"
    assert gen.selector_summary({"label": {"multiple": True}}) == "label (multiple)"


def test_selector_summary_of_a_bare_selector_is_its_kind() -> None:
    assert gen.selector_summary({"text": None}) == "text"


def test_selector_summary_of_no_selector_is_empty() -> None:
    assert gen.selector_summary(None) == ""


# ── Services ─────────────────────────────────────────────────────────────────


def _sources(**overrides):
    """A one-service, one-event fixture, overridable per test."""
    surface = SimpleNamespace(
        SERVICES=(api_surface.ServiceSpec("demo", admin_only=True, response="only"),),
        SURFACE_KINDS=(),
        EVENTS=(),
        PAYLOAD_SPINES={},
        DEVICE_TRIGGERS=(),
        ENTITY_PLATFORMS=(),
        OPTIONS=(),
        events_by_payload=lambda shape: (),
    )
    services_yaml = {
        "demo": {
            "name": "Yaml title",
            "description": "Yaml description.",
            "fields": {
                "task_id": {
                    "name": "Yaml field label",
                    "description": "Yaml field description.",
                    "required": True,
                    "selector": {"text": None},
                }
            },
        }
    }
    strings = {
        "services": {
            "demo": {
                "name": "Localized title",
                "description": "Localized description.",
                "fields": {
                    "task_id": {
                        "name": "Localized field label",
                        "description": "Localized field description.",
                    }
                },
            }
        },
        "device_automation": {"trigger_type": {}},
        "entity": {},
        "options": {"step": {"init": {"data": {}, "data_description": {}}}},
        "exceptions": {},
    }
    return gen.Sources(
        surface=overrides.get("surface", surface),
        services_yaml=overrides.get("services_yaml", services_yaml),
        strings=overrides.get("strings", strings),
    )


def test_service_prose_comes_from_strings_json_not_services_yaml() -> None:
    """The localized string wins over the YAML copy, for the action and its fields.

    This is the point of generating the page: Home Assistant renders its service
    dialog from ``strings.json``, so a reference that read ``services.yaml``
    instead could describe the same action differently from the UI. Both files
    are populated here, deliberately disagreeing.
    """
    rendered = "\n".join(gen.render_services(_sources()))
    assert "Localized title" in rendered
    assert "Localized description." in rendered
    assert "Localized field label" in rendered
    assert "Localized field description." in rendered
    assert "Yaml" not in rendered


def test_service_structure_comes_from_services_yaml() -> None:
    """Required-ness and the selector are only in the YAML, and are rendered."""
    rendered = "\n".join(gen.render_services(_sources()))
    assert "| `task_id` **(required)** | Localized field label | text |" in rendered


def test_service_badges_report_admin_and_response() -> None:
    rendered = "\n".join(gen.render_services(_sources()))
    assert "**Admin only**" in rendered
    assert "**Returns a response**" in rendered


def test_a_service_with_no_fields_says_so() -> None:
    sources = _sources(services_yaml={"demo": {"fields": {}}})
    assert "Takes no fields." in "\n".join(gen.render_services(sources))


# ── Events ───────────────────────────────────────────────────────────────────


def test_events_render_a_spine_table_per_payload_shape() -> None:
    spec = api_surface.EventSpec(
        "home_keeper_demo_fired",
        "EVENT_DEMO_FIRED",
        "fired",
        "demo",
        "something demonstrable happens",
        extra=(api_surface.Field("extra_key", "int"),),
    )
    surface = SimpleNamespace(
        EVENTS=(spec,),
        PAYLOAD_SPINES={"demo": (api_surface.Field("demo_id", "str"),)},
        events_by_payload=lambda shape: (spec,) if shape == "demo" else (),
    )
    rendered = "\n".join(gen.render_events(_sources(surface=surface)))
    assert "something demonstrable happens" in rendered
    assert "[demo](#demo-payload)" in rendered
    assert "`extra_key`" in rendered
    assert "#### Demo payload" in rendered
    assert "| `demo_id` | `str` |" in rendered


def test_listened_events_are_listed_apart_from_fired_ones() -> None:
    """An event Home Keeper only reacts to isn't something to subscribe to."""
    listened = api_surface.EventSpec(
        "tag_scanned", "EVENT_HA_TAG_SCANNED", "listened", "none", "a tag was scanned"
    )
    surface = SimpleNamespace(
        EVENTS=(listened,), PAYLOAD_SPINES={}, events_by_payload=lambda shape: ()
    )
    rendered = "\n".join(gen.render_events(_sources(surface=surface)))
    assert "Home Keeper also listens for events it does not own" in rendered
    assert "Home Keeper's reaction" in rendered


# ── Whole page ───────────────────────────────────────────────────────────────


def test_render_is_deterministic() -> None:
    """Two renders are byte-identical.

    Anything iterating a ``set`` would reorder rows between runs, which turns a
    docs diff into noise and a preview build into a false alarm.
    """
    sources = gen.load_sources()
    assert gen.render(sources) == gen.render(sources)


def test_render_covers_every_modelled_surface() -> None:
    """Nothing in the model is silently dropped on the way to the page.

    This is the one check against the real repo, and the reason a pull request
    that adds a service but never touches ``website/`` still can't ship a
    reference missing it.
    """
    page = gen.render(gen.load_sources())
    missing: dict[str, list[str]] = {}

    def absent(label: str, names) -> None:
        gone = [name for name in names if name not in page]
        if gone:
            missing[label] = gone

    absent("services", (f"home_keeper.{n}" for n in api_surface.SERVICE_NAMES))
    absent("events", (s.name for s in api_surface.EVENTS))
    absent("device_triggers", (s.type for s in api_surface.DEVICE_TRIGGERS))
    absent("entity_platforms", (s.platform for s in api_surface.ENTITY_PLATFORMS))
    absent("options", (s.key for s in api_surface.OPTIONS))
    absent("surface_kinds", (s.kind for s in api_surface.SURFACE_KINDS))
    absent(
        "payload_fields",
        (f.name for fields in api_surface.PAYLOAD_SPINES.values() for f in fields),
    )
    assert not missing, {
        "modelled_but_not_rendered": missing,
        "fix": "Render it in ci/generate_api_docs.py.",
    }


def test_page_carries_docusaurus_frontmatter() -> None:
    page = gen.render(gen.load_sources())
    assert page.startswith("---\n")
    # CommonMark, not MDX: payload types and selector summaries contain literal
    # braces that MDX would try to parse as JSX.
    assert "format: md" in page.split("---")[1]


def test_frontmatter_matches_the_doc_map_entry() -> None:
    """The generator and ``doc-map.mjs`` agree on where this page sits.

    ``doc-map.mjs`` tells the PR-preview comment the page's route and title; the
    generator writes its sidebar position. They are in different languages and
    can't import each other, so compare the source text.
    """
    doc_map = (_ROOT / "website" / "scripts" / "doc-map.mjs").read_text(
        encoding="utf-8"
    )
    entry = re.search(
        r"export const GENERATED_DEV_PAGES = \[(.*?)\];", doc_map, re.DOTALL
    )
    assert entry, "GENERATED_DEV_PAGES is missing from doc-map.mjs"
    block = entry.group(1)
    assert f"pos: {gen.PAGE_POSITION}" in block
    assert f"title: '{gen.PAGE_TITLE}'" in block
    assert "route: '/developer/api'" in block
    assert f"out: '{gen.DEFAULT_OUT.name}'" in block


def test_main_writes_the_page(tmp_path: Path) -> None:
    out = tmp_path / "api.md"
    assert gen.main(["--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("---\n")
