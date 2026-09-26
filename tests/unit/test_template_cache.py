"""The compiled-template cache in ``template_context``.

Home Assistant caches compiled template code on a shared environment, but
``TemplateEnvironment.template_cache`` is a **WeakValueDictionary**: the only strong
reference to the compiled code is the ``Template`` object's own ``_compiled_code``.
Build a fresh ``Template`` per entity and each one re-parses the Jinja source, which
measures ~90x the cost of the render it precedes. A companion at the 500-entity cap
therefore spent about a quarter of a second of event-loop time per pass parsing one
expression that never changed.

These pin the reuse itself rather than the timing: a benchmark in CI would be a flaky
gate, while "the same source gives back the same object" is the property that makes
Home Assistant's own cache stay warm, and it is the one a later refactor can silently
drop.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# Skip on the exact modules `template_context` imports, never on bare
# `homeassistant`. `tests/unit/ha_stubs.py` hand-builds a `homeassistant` module tree
# for the HA-shaped unit tests, so in a lane without the real thing — the mutation
# lane, which installs `requirements-test.txt` only — `import homeassistant` succeeds
# against that stub and `importorskip("homeassistant")` sails straight through. The
# deeper import then fails at collection with "'homeassistant.helpers' is not a
# package", which stops the whole run rather than skipping this file.
pytest.importorskip("homeassistant.helpers.template")
pytest.importorskip("homeassistant.util.hass_dict")

from custom_components.home_keeper import template_context

SRC = "{{ state | float(0) >= 500 }}"


def _hass():
    """The slice of Home Assistant the cache touches: a ``data`` mapping."""
    return SimpleNamespace(data={})


def test_the_same_source_gives_back_the_same_template():
    hass = _hass()
    first = template_context.cached_template(hass, SRC)
    assert template_context.cached_template(hass, SRC) is first


def test_strict_and_lax_never_share_a_template():
    # `Template` asserts that `strict` never changes for one object, and the two
    # callers disagree: a trigger renders strict so a typo cannot read as false, a
    # task name renders lax so `{{ attributes.foo or 'x' }}` keeps working. Share one
    # object between them and the first user who writes the same text in both boxes
    # trips that assertion.
    hass = _hass()
    assert template_context.cached_template(hass, SRC, strict=True) is not (
        template_context.cached_template(hass, SRC)
    )
    # Each side is still cached on its own.
    assert template_context.cached_template(hass, SRC, strict=True) is (
        template_context.cached_template(hass, SRC, strict=True)
    )


def test_a_different_source_gives_a_different_template():
    # Identity, not equality: two templates that merely compare equal would still be
    # two compiles, which is the whole thing this cache exists to avoid.
    hass = _hass()
    assert template_context.cached_template(hass, SRC) is not (
        template_context.cached_template(hass, "{{ state == 'on' }}")
    )


def test_each_home_assistant_keeps_its_own_cache():
    # The cache lives on ``hass.data`` so it cannot outlive the Home Assistant it is
    # bound to. A module-level dict would hand a reloaded entry templates bound to the
    # instance it replaced.
    assert template_context.cached_template(_hass(), SRC) is not (
        template_context.cached_template(_hass(), SRC)
    )


def test_the_cache_is_capped_so_a_preview_cannot_grow_it_forever():
    # The companion preview renders on every keystroke, and each draft is a different
    # source. Without a bound, typing one template would leave a compiled copy of
    # every prefix of it behind for the life of the process.
    hass = _hass()
    cap = template_context._TEMPLATE_CACHE_MAX
    for i in range(cap * 2):
        template_context.cached_template(hass, f"{{{{ {i} }}}}")
    assert len(hass.data[template_context._TEMPLATE_CACHE]) == cap


def test_the_oldest_entry_is_the_one_evicted():
    # FIFO: the newest drafts are the ones a preview is still typing, and a saved
    # companion that renders every pass is re-added on its next render.
    hass = _hass()
    cap = template_context._TEMPLATE_CACHE_MAX
    oldest = "{{ 'first' }}"
    template_context.cached_template(hass, oldest)
    for i in range(cap):
        template_context.cached_template(hass, f"{{{{ {i} }}}}")
    cache = hass.data[template_context._TEMPLATE_CACHE]
    assert (False, oldest) not in cache
    assert (False, f"{{{{ {cap - 1} }}}}") in cache


# ── the registry projection a template-mode task renders against ─────────────


def _registries(monkeypatch, *, entity_area, device_area):
    entity = SimpleNamespace(
        entity_id="sensor.probe",
        device_id="dev1",
        area_id=entity_area,
        platform="mqtt",
        name=None,
        original_name="Probe",
    )
    device = SimpleNamespace(area_id=device_area)
    monkeypatch.setattr(
        template_context.er,
        "async_get",
        lambda hass: SimpleNamespace(async_get=lambda eid: entity),
    )
    monkeypatch.setattr(
        template_context.dr,
        "async_get",
        lambda hass: SimpleNamespace(async_get=lambda did: device),
    )


def test_the_projection_takes_the_area_of_the_device(monkeypatch):
    # Most entities have no area of their own and sit in their device's. A companion's
    # selection pass projects that effective area, so the trigger must see it too, or
    # `{{ area_id == 'garage' }}` reads true in the preview and false in the watcher.
    _registries(monkeypatch, entity_area=None, device_area="garage")
    projection = template_context.registry_projection(_hass(), "sensor.probe")
    assert projection["area_id"] == "garage"


def test_the_projection_prefers_the_area_of_the_entity(monkeypatch):
    _registries(monkeypatch, entity_area="attic", device_area="garage")
    projection = template_context.registry_projection(_hass(), "sensor.probe")
    assert projection["area_id"] == "attic"
