"""A broken companion name or notes template is logged once, not once per pass.

``DeclarativeCompanionSync._render_one`` renders the name template and then the notes
template for each matched entity, on each reconcile pass. The record of what it
already logged is keyed by entity **and** template source. Keyed by entity alone, the
working notes template cleared the record of the broken name straight after it was
written, and the name logged again for every entity on every pass.

The render itself is replaced by a fake: what is under test is "when does it log",
not "does it render". The import guard is the one ``test_template_error_log.py``
explains.
"""

import logging
from types import SimpleNamespace

import pytest

try:
    from homeassistant.helpers.template import TemplateError

    from custom_components.home_keeper import declarative_companion_sync as sync_mod
except ImportError as err:  # pragma: no cover - the lane without a real HA
    pytest.skip(
        f"declarative_companion_sync needs a real Home Assistant: {err}",
        allow_module_level=True,
    )

BROKEN = "{{ stat }}"
WORKING = "{{ friendly_name }}"
VARIABLES = {"entity_id": "sensor.a", "friendly_name": "A"}


class _FakeTemplate:
    def __init__(self, source: str) -> None:
        self._source = source

    def async_render(self, variables, parse_result=False):
        if self._source == BROKEN:
            raise TemplateError("'stat' is undefined")
        return variables["friendly_name"]


@pytest.fixture
def sync(monkeypatch):
    monkeypatch.setattr(
        sync_mod.template_context,
        "cached_template",
        lambda hass, source, strict=False: _FakeTemplate(source),
    )
    obj = sync_mod.DeclarativeCompanionSync.__new__(sync_mod.DeclarativeCompanionSync)
    obj._hass = SimpleNamespace()
    obj._render_errors = {}
    return obj


def _warnings(caplog) -> list[str]:
    return [r.message for r in caplog.records if r.levelno == logging.WARNING]


def test_a_working_notes_template_does_not_clear_a_broken_name(sync, caplog):
    with caplog.at_level(logging.WARNING, logger=sync_mod.__name__):
        for _ in range(5):
            assert sync._render_one(BROKEN, VARIABLES) == BROKEN
            assert sync._render_one(WORKING, VARIABLES) == "A"
    assert len(_warnings(caplog)) == 1


def test_a_repaired_template_that_breaks_again_is_reported_again(sync, caplog):
    with caplog.at_level(logging.WARNING, logger=sync_mod.__name__):
        sync._render_one(BROKEN, VARIABLES)
        sync._render_errors.pop(("sensor.a", BROKEN))  # as a clean render of it does
        sync._render_one(BROKEN, VARIABLES)
    assert len(_warnings(caplog)) == 2


def test_the_record_stays_bounded(sync, monkeypatch):
    monkeypatch.setattr(sync_mod, "_RENDER_ERRORS_MAX", 3)
    for n in range(10):
        sync._render_one(BROKEN, {**VARIABLES, "entity_id": f"sensor.e{n}"})
    assert len(sync._render_errors) <= 3
