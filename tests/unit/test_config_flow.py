"""The options flow's form, and the save that must not clobber what it can't see.

``config_flow.py`` imports Home Assistant and voluptuous, so the whole module is
skipped when those aren't installed; CI's full unit suite installs them
(``ci/install-deps.sh``). The HA-free half of the same contract — the merge rules and
the ``strings.json`` drift guard — lives in ``test_options.py`` and always runs.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import hk_const as const  # type: ignore[import-not-found]
import hk_options as opts  # type: ignore[import-not-found]
import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("voluptuous")

_COMPONENT_DIR = (
    Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"
)

# A package of its own, not ``hk``: loading ``config_flow`` pulls in a real
# ``shopping_sync`` sibling through ``from .shopping_sync import …``, which would
# collide with the fake ``hk.shopping_sync`` that ``test_shopping_sync.py`` installs
# (whichever test ran first would win). ``hk_cf.*`` can't clash with anything.
_PKG = "hk_cf"

_FULL: dict[str, Any] = {
    const.OPTION_SYNC_PROBLEM_SENSORS: True,
    const.OPTION_ONE_OFF_RETENTION_DAYS: 30,
    const.OPTION_SHOPPING_LIST_ENTITY: "todo.kitchen_list",
    const.OPTION_DISMISSED_COMPANIONS: ["acme_vacuum"],
    const.OPTION_PROFILES: [
        {"id": "p1", "name": "My chores", "filter": {"status": "overdue"}}
    ],
    const.OPTION_NOTIFICATIONS: [
        {"id": "n1", "name": "Walk", "profile_id": "p1", "targets": []}
    ],
}


def _config_flow() -> types.ModuleType:
    """Load ``config_flow.py`` under ``hk_cf``, with a stubbed ``shopping_sync``.

    The stub is only there to keep the to-do exclusion list out of an entity
    registry — nothing here is testing which lists get excluded.
    """
    module = sys.modules.get(f"{_PKG}.config_flow")
    if module is not None:
        return module

    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(_COMPONENT_DIR)]  # type: ignore[attr-defined]
    sys.modules[_PKG] = pkg

    shopping_sync = types.ModuleType(f"{_PKG}.shopping_sync")
    shopping_sync.own_todo_entity_ids = lambda hass: []  # type: ignore[attr-defined]
    sys.modules[f"{_PKG}.shopping_sync"] = shopping_sync
    # Alias rather than let a second copy of options.py load under this package, so
    # the flow merges through the very module these tests assert against.
    sys.modules[f"{_PKG}.options"] = opts

    spec = importlib.util.spec_from_file_location(
        f"{_PKG}.config_flow", str(_COMPONENT_DIR / "config_flow.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{_PKG}.config_flow"] = module
    spec.loader.exec_module(module)
    return module


def _entry(options: dict[str, Any]) -> Any:
    return types.SimpleNamespace(options=options)


def test_form_schema_matches_flow_options() -> None:
    """The form's fields are exactly ``options.FLOW_OPTIONS``, in order.

    Both directions lose data, which is why this is an equality and not a subset. A
    field the tuple omits is discarded by ``merge_flow_input`` the moment it's saved;
    a tuple key with no field is treated as *cleared* and reset on every save.
    """
    cf = _config_flow()

    schema = cf._options_schema(object(), opts.current_options(_entry({})))

    assert [str(key) for key in schema.schema] == list(opts.FLOW_OPTIONS)


def test_form_defaults_come_from_the_normalized_options() -> None:
    """Garbage on disk must not reach the form as a default."""
    cf = _config_flow()
    current = opts.current_options(
        _entry({const.OPTION_ONE_OFF_RETENTION_DAYS: "not-a-number"})
    )

    schema = cf._options_schema(object(), current)
    # An unset ``default`` is voluptuous' ``UNDEFINED`` sentinel; a set one is a
    # factory. The shopping picker deliberately has none — see ``merge_flow_input``.
    defaults = {
        str(key): key.default()
        for key in schema.schema
        if callable(getattr(key, "default", None))
    }

    assert defaults[const.OPTION_ONE_OFF_RETENTION_DAYS] == 0


def test_the_shopping_picker_has_no_default() -> None:
    """Clearing the mirror depends on the key dropping out of the submission.

    Give this field a ``default`` and voluptuous fills the old entity id back in on a
    cleared picker, so ``merge_flow_input`` never sees it as cleared and the mirror
    can't be turned off from the Configure dialog. The ``suggested_value`` in its
    ``description`` is what pre-fills the picker instead.
    """
    cf = _config_flow()
    current = opts.current_options(_entry(_FULL))

    schema = cf._options_schema(object(), current)
    picker = next(
        key for key in schema.schema if str(key) == const.OPTION_SHOPPING_LIST_ENTITY
    )

    assert not callable(getattr(picker, "default", None))
    assert picker.description == {"suggested_value": "todo.kitchen_list"}


def test_saving_the_form_preserves_the_panel_options() -> None:
    """The bug, at the flow: a save must not delete what the form never rendered.

    ``OptionsFlow.config_entry`` is a property whose backing has changed across Home
    Assistant versions, so this overrides it on a subclass rather than assigning to
    it or reaching into the real class.
    """
    cf = _config_flow()
    entry = _entry(_FULL)

    class _Flow(cf.HomeKeeperOptionsFlow):  # type: ignore[misc, name-defined]
        @property
        def config_entry(self) -> Any:
            return entry

    flow = _Flow()
    flow.async_create_entry = lambda **kwargs: kwargs  # type: ignore[method-assign]

    result = asyncio.run(
        flow.async_step_init(
            {
                const.OPTION_SYNC_PROBLEM_SENSORS: False,
                const.OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES: [],
                const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: [],
                const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS: [],
                const.OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS: [],
                const.OPTION_ONE_OFF_RETENTION_DAYS: 7,
                # shopping_list_entity omitted: the cleared-picker case.
            }
        )
    )

    saved = result["data"]
    expected = opts.current_options(entry)
    assert saved[const.OPTION_PROFILES] == expected[const.OPTION_PROFILES]
    assert saved[const.OPTION_NOTIFICATIONS] == expected[const.OPTION_NOTIFICATIONS]
    assert saved[const.OPTION_DISMISSED_COMPANIONS] == ["acme_vacuum"]
    assert saved[const.OPTION_ONE_OFF_RETENTION_DAYS] == 7
    assert saved[const.OPTION_SYNC_PROBLEM_SENSORS] is False
    assert saved[const.OPTION_SHOPPING_LIST_ENTITY] == ""
    # Home Assistant stores this dict as the whole of ``entry.options``.
    assert set(saved) == set(opts.ALL_OPTIONS)
