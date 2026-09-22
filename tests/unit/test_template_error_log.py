"""A broken trigger template is logged once, not once per evaluation pass.

A template that cannot render decides nothing — the task neither arms nor clears — so
a log line is the only thing that says why it is sitting there. But the watcher runs
on every state change of a bound entity and again on the coordinator's 5-minute pass,
and a recipe materializes one task per matched entity, up to 500. One typo therefore
wrote 500 identical warnings every 5 minutes, for as long as the recipe stayed broken,
and buried everything else in the log.

The bookkeeping is a plain dict on the watcher, so this drives it directly rather than
standing up Home Assistant: what is under test is "when does it log", not "does it
render".

The module under test is imported through ``importorskip`` rather than guarded on
``homeassistant`` itself. Guarding on the package name is not enough: ``conftest``
installs **stub** parent packages so the HA-importing ``__init__.py`` never runs, and
the mutation lane inherits them — so ``import homeassistant`` succeeds there while
``from homeassistant.helpers.event import async_track_point_in_time`` (which
``sensor_watcher`` does at module scope) raises. Asking for the real module is the only
guard that answers the question this file needs: can this import run *here*. A
collection error is not a skipped test — it aborts mutmut's stats pass and takes the
whole mutation gate with it.
"""

import logging

import pytest

sensor_watcher = pytest.importorskip("custom_components.home_keeper.sensor_watcher")

TASK = {"name": "Service the printer"}
CFG = {"entity_id": "sensor.demo_printer_hours"}


def _watcher() -> sensor_watcher.SensorTaskWatcher:
    """A watcher with only the field under test, and no Home Assistant behind it."""
    watcher = sensor_watcher.SensorTaskWatcher.__new__(sensor_watcher.SensorTaskWatcher)
    watcher._template_errors = {}
    return watcher


def _warnings(caplog) -> list[str]:
    return [r.message for r in caplog.records if r.levelno == logging.WARNING]


def test_the_same_error_is_reported_once(caplog):
    watcher = _watcher()
    with caplog.at_level(logging.WARNING, logger=sensor_watcher.__name__):
        for _ in range(5):
            watcher._report_template_error("t1", TASK, CFG, "'stat' is undefined")
    assert len(_warnings(caplog)) == 1


def test_the_message_names_the_task_the_entity_and_the_error(caplog):
    # The three things a reader needs to find the recipe that is broken.
    watcher = _watcher()
    with caplog.at_level(logging.WARNING, logger=sensor_watcher.__name__):
        watcher._report_template_error("t1", TASK, CFG, "'stat' is undefined")
    logged = _warnings(caplog)[0]
    assert "Service the printer" in logged
    assert "sensor.demo_printer_hours" in logged
    assert "'stat' is undefined" in logged


def test_a_different_error_is_reported_again(caplog):
    # A template that starts failing differently is new information.
    watcher = _watcher()
    with caplog.at_level(logging.WARNING, logger=sensor_watcher.__name__):
        watcher._report_template_error("t1", TASK, CFG, "'stat' is undefined")
        watcher._report_template_error("t1", TASK, CFG, "division by zero")
    assert len(_warnings(caplog)) == 2


def test_each_task_is_tracked_on_its_own(caplog):
    # A recipe's tasks share a template, so they share an error — but one task going
    # quiet must not silence its neighbours.
    watcher = _watcher()
    with caplog.at_level(logging.WARNING, logger=sensor_watcher.__name__):
        watcher._report_template_error("t1", TASK, CFG, "'stat' is undefined")
        watcher._report_template_error("t2", TASK, CFG, "'stat' is undefined")
    assert len(_warnings(caplog)) == 2


def test_a_good_render_clears_the_record_so_a_relapse_is_reported(caplog):
    # Breaking, being fixed, then breaking again is two separate events.
    watcher = _watcher()
    with caplog.at_level(logging.WARNING, logger=sensor_watcher.__name__):
        watcher._report_template_error("t1", TASK, CFG, "'stat' is undefined")
        watcher._report_template_error("t1", TASK, CFG, None)
        watcher._report_template_error("t1", TASK, CFG, "'stat' is undefined")
    assert len(_warnings(caplog)) == 2
    assert "t1" not in _watcher()._template_errors


def test_a_render_that_works_logs_nothing(caplog):
    watcher = _watcher()
    with caplog.at_level(logging.WARNING, logger=sensor_watcher.__name__):
        watcher._report_template_error("t1", TASK, CFG, None)
    assert _warnings(caplog) == []
