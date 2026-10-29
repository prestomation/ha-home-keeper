"""Deprecated input forms: 1 warning per form per Home Assistant run (#493).

A user who still sends an old input form gets told to change it, so a later release
can remove that form. The warning names the new form, and a second call in the same
run stays quiet, so an automation that runs every minute does not fill the log.
"""

import logging

import hk_deprecations as dep
import pytest


@pytest.fixture(autouse=True)
def _fresh_run():
    """Each test starts a new run: no form has warned yet."""
    dep._warned.clear()
    yield
    dep._warned.clear()


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING]


@pytest.mark.parametrize(
    "key", [dep.SERVICE_SINGLE_CONSUMABLE_LINK, dep.WS_SINGLE_CONSUMABLE_LINK]
)
def test_the_old_link_form_warns_once_and_names_parts(caplog, key):
    old = {"task_id": "t", "asset_id": "a", "part_id": "p"}
    with caplog.at_level(logging.WARNING):
        assert dep.warn_single_consumable_link(old, key) is True
        assert dep.warn_single_consumable_link(old, key) is False
    [record] = _warnings(caplog)
    assert record.getMessage() == dep.DEPRECATIONS[key]
    assert "`parts`" in record.getMessage()
    assert "removed in a later release" in record.getMessage()


def test_the_parts_form_never_warns(caplog):
    with caplog.at_level(logging.WARNING):
        for data in ({"task_id": "t", "parts": []}, {"parts": [{"asset_id": "a"}]}):
            assert (
                dep.warn_single_consumable_link(
                    data, dep.SERVICE_SINGLE_CONSUMABLE_LINK
                )
                is False
            )
    assert not _warnings(caplog)
    # The quiet call does not use up the warning for a later old-form call.
    with caplog.at_level(logging.WARNING):
        assert dep.warn_single_consumable_link(
            {"task_id": "t"}, dep.SERVICE_SINGLE_CONSUMABLE_LINK
        )
    assert len(_warnings(caplog)) == 1


def test_a_clear_with_no_link_fields_is_the_old_form_too():
    # Only task_id cleared the link before the list existed. The new form is parts: [].
    assert dep.warn_single_consumable_link(
        {"task_id": "t"}, dep.WS_SINGLE_CONSUMABLE_LINK
    )


def test_each_surface_warns_on_its_own(caplog):
    old = {"task_id": "t", "asset_id": "a", "part_id": "p"}
    with caplog.at_level(logging.WARNING):
        dep.warn_single_consumable_link(old, dep.SERVICE_SINGLE_CONSUMABLE_LINK)
        dep.warn_single_consumable_link(old, dep.WS_SINGLE_CONSUMABLE_LINK)
        dep.warn_single_consumable_link(old, dep.SERVICE_SINGLE_CONSUMABLE_LINK)
    messages = [r.getMessage() for r in _warnings(caplog)]
    assert messages == [
        dep.DEPRECATIONS[dep.SERVICE_SINGLE_CONSUMABLE_LINK],
        dep.DEPRECATIONS[dep.WS_SINGLE_CONSUMABLE_LINK],
    ]
    assert messages[0] != messages[1]
    assert "home_keeper.set_task_consumable" in messages[0]
    assert "home_keeper/set_task_consumable" in messages[1]


def test_warn_once_refuses_an_unknown_key():
    with pytest.raises(KeyError):
        dep.warn_once("no_such_form")


def test_the_warning_goes_to_the_integration_logger():
    assert dep._LOGGER.name == "custom_components.home_keeper"
