"""The presets that companions register, and the rule that checks a catalog row.

A companion calls ``home_keeper.register_presets`` with rows in the format of
``declarative_presets_catalog.INTEGRATIONS``. :func:`validate_row` is the 1 check for
that format: the shipped catalog passes it in ``tests/unit/test_preset_registry.py``,
and every companion row passes it at registration. The presets of a row are built by
``declarative_presets._integration_presets``, the same code that builds the shipped
ones, so a row holds no Jinja: the shape gives the trigger and the task templates.

The registry is memory for the Home Assistant run. It is never stored. A companion
registers again at each start, so a companion that is gone leaves no rows.
:func:`transition` is the 1 way to change it. It returns the new state and the bus
events to fire, so the state machine test checks the same function that runs.

Pure: no Home Assistant import.
"""

from __future__ import annotations

import math
import re
from collections import ChainMap
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import declarative_companions, declarative_presets, events
from .const import (
    EVENT_PRESETS_REGISTERED,
    EVENT_PRESETS_REMOVED,
    MAX_COMPANIONS,
)
from .declarative_preset_text import DUTY_NAMES
from .declarative_presets import LANGS, SHAPES, PresetDefinition

SOURCE_BUILTIN = "builtin"
SOURCE_COMPANION = "companion"

# The separator between the companion domain and the preset id. A shipped preset id
# never holds it, so a companion preset can never have the id of a shipped one.
ID_SEPARATOR = "/"

MAX_ROWS = 20
MAX_DUTIES = 20
MAX_KEYS = 20
MAX_DUTY_NAMES = 50
MAX_TEXT_LEN = 100
MAX_BRAND_LEN = 50
MAX_LIMIT = 1_000_000
MAX_PRESET_ID_LEN = 100

_DOMAIN = re.compile(r"[a-z0-9_]{1,50}")
_KEY = re.compile(r"[a-z0-9_]{1,64}")
_DEVICE_CLASS = re.compile(r"[a-z0-9_]{1,32}")
_STATE = re.compile(r"[A-Za-z0-9_-]{1,32}")
_ICON = re.compile(r"mdi:[a-z0-9-]{1,60}")
# Text that a user reads. Braces are refused, so the text can never hold a template
# or a format field, and control characters are refused.
_BAD_TEXT = re.compile(r"[{}\x00-\x1f\x7f]")

PLATFORMS = ("sensor", "binary_sensor")
_ROW_KEYS = frozenset({"domain", "brand", "icon", "duties"})
# The shipped catalog also pins the upstream file it was read from. A companion keeps
# its own rows current, so its rows have no pin.
_BUILTIN_ROW_KEYS = _ROW_KEYS | {"source", "verified"}
_DUTY_KEYS = frozenset(
    {
        "duty",
        "shape",
        "platform",
        "keys",
        "limit",
        "state",
        "counted",
        "device_class",
        "per_instance",
    }
)


class PresetRowError(ValueError):
    """A row, a duty name or a registration that the rules refuse.

    ``path`` names the bad field, such as ``rows[0].duties[1].limit``.
    """

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def _match(pattern: re.Pattern[str], value: Any, path: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise PresetRowError(path, f"must match {pattern.pattern}")
    return value


def _text(value: Any, path: str, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PresetRowError(path, "must be text")
    if len(value) > max_len:
        raise PresetRowError(path, f"must be at most {max_len} characters")
    if _BAD_TEXT.search(value):
        raise PresetRowError(path, "must not hold braces or control characters")
    return value


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PresetRowError(path, "must be a mapping")
    return value


def _list(value: Any, path: str, max_len: int) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise PresetRowError(path, "must be a list that is not empty")
    if len(value) > max_len:
        raise PresetRowError(path, f"must have at most {max_len} items")
    return value


def _only(raw: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    unknown = sorted(str(k) for k in raw if k not in allowed)
    if unknown:
        raise PresetRowError(f"{path}.{unknown[0]}", "is not a known key")


def _limit(duty: Mapping[str, Any], shape: str, path: str) -> float | None:
    value = duty.get("limit")
    if shape == "alert":
        if value is not None:
            raise PresetRowError(f"{path}.limit", "an alert has no limit")
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PresetRowError(f"{path}.limit", "must be a number")
    if not math.isfinite(value) or not 0 < value <= MAX_LIMIT:
        raise PresetRowError(
            f"{path}.limit", f"must be above 0 and {MAX_LIMIT} at most"
        )
    if shape == "percent_low" and value >= 100:
        raise PresetRowError(f"{path}.limit", "a percentage must be below 100")
    return value


def _flag(duty: Mapping[str, Any], key: str, path: str) -> None:
    if key in duty and not isinstance(duty[key], bool):
        raise PresetRowError(f"{path}.{key}", "must be true or false")


def validate_duty(
    duty_raw: Any, path: str, duty_ids: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a clean copy of 1 duty of a catalog row, or raise ``PresetRowError``."""
    duty = _mapping(duty_raw, path)
    _only(duty, _DUTY_KEYS, path)
    duty_id = duty.get("duty")
    if not isinstance(duty_id, str) or duty_id not in duty_ids:
        raise PresetRowError(f"{path}.duty", "must name a known duty")
    shape = duty.get("shape")
    if shape not in SHAPES:
        raise PresetRowError(f"{path}.shape", "must be one of " + ", ".join(SHAPES))
    platform = duty.get("platform", "sensor")
    if platform not in PLATFORMS:
        raise PresetRowError(f"{path}.platform", "must be sensor or binary_sensor")
    keys = _list(duty.get("keys"), f"{path}.keys", MAX_KEYS)
    for index, key in enumerate(keys):
        _match(_KEY, key, f"{path}.keys[{index}]")
    if len(set(keys)) < len(keys):
        raise PresetRowError(f"{path}.keys", "must not repeat a key")
    clean: dict[str, Any] = {"duty": duty_id, "shape": shape, "keys": list(keys)}
    if "platform" in duty:
        clean["platform"] = platform
    limit = _limit(duty, shape, path)
    if limit is not None:
        clean["limit"] = limit
    if shape == "alert":
        clean["state"] = _match(_STATE, duty.get("state"), f"{path}.state")
    elif "state" in duty:
        raise PresetRowError(f"{path}.state", "only an alert has a state")
    if "device_class" in duty:
        clean["device_class"] = _match(
            _DEVICE_CLASS, duty["device_class"], f"{path}.device_class"
        )
    for flag in ("counted", "per_instance"):
        _flag(duty, flag, path)
        if flag in duty:
            clean[flag] = duty[flag]
    return clean


def validate_row(
    row_raw: Any,
    path: str = "row",
    duty_ids: Mapping[str, Any] = DUTY_NAMES,
    *,
    builtin: bool = False,
) -> dict[str, Any]:
    """Return a clean copy of 1 catalog row, or raise ``PresetRowError``.

    *duty_ids* holds the duty ids that a duty can name. A shipped row (*builtin*)
    also carries its upstream ``source`` and ``verified`` pin, which this check
    keeps and does not read.
    """
    row = _mapping(row_raw, path)
    _only(row, _BUILTIN_ROW_KEYS if builtin else _ROW_KEYS, path)
    clean: dict[str, Any] = {
        "domain": _match(_DOMAIN, row.get("domain"), f"{path}.domain"),
        "brand": _text(row.get("brand"), f"{path}.brand", MAX_BRAND_LEN),
        "icon": _match(_ICON, row.get("icon"), f"{path}.icon"),
    }
    duties = _list(row.get("duties"), f"{path}.duties", MAX_DUTIES)
    clean["duties"] = [
        validate_duty(duty, f"{path}.duties[{index}]", duty_ids)
        for index, duty in enumerate(duties)
    ]
    # 1 entity gets 1 task: a key is in 1 duty of its platform.
    seen: set[tuple[str, str]] = set()
    for index, duty in enumerate(clean["duties"]):
        for key in duty["keys"]:
            owner = (duty.get("platform", "sensor"), key)
            if owner in seen:
                raise PresetRowError(
                    f"{path}.duties[{index}].keys", f"key {key} is in 2 duties"
                )
            seen.add(owner)
    if builtin:
        clean.update({k: row[k] for k in ("source", "verified") if k in row})
    return clean


def validate_duty_names(
    raw: Any, path: str = "duty_names"
) -> dict[str, dict[str, str]]:
    """Return a clean copy of a companion's duty names, or raise ``PresetRowError``.

    Each duty has an English name. The other languages are optional, and a language
    that a duty does not have gets the English name.
    """
    if raw is None:
        return {}
    table = _mapping(raw, path)
    if len(table) > MAX_DUTY_NAMES:
        raise PresetRowError(path, f"must have at most {MAX_DUTY_NAMES} duties")
    clean: dict[str, dict[str, str]] = {}
    for duty_id, names_raw in table.items():
        where = f"{path}.{duty_id}"
        _match(_DOMAIN, duty_id, where)
        names = _mapping(names_raw, where)
        unknown = sorted(str(lang) for lang in names if lang not in LANGS)
        if unknown:
            raise PresetRowError(f"{where}.{unknown[0]}", "is not a known language")
        if "en" not in names:
            raise PresetRowError(f"{where}.en", "is required")
        clean[duty_id] = {
            lang: _text(text, f"{where}.{lang}", MAX_TEXT_LEN)
            for lang, text in names.items()
        }
    return clean


@dataclass(frozen=True)
class Registration:
    """The checked presets of 1 companion."""

    domain: str
    rows: tuple[dict[str, Any], ...]
    duty_names: Mapping[str, dict[str, str]]
    presets: tuple[PresetDefinition, ...]
    texts: Mapping[str, dict[str, dict[str, Any]]]

    @property
    def preset_ids(self) -> list[str]:
        """The ids of the presets of this registration, in row order."""
        return [preset["id"] for preset in self.presets]


def build_registration(domain: Any, rows: Any, duty_names: Any = None) -> Registration:
    """Check a registration and build its presets, or raise ``PresetRowError``.

    Each built preset also passes ``normalize_declarative_companion``, the check of
    a declarative companion spec. So the spec that a user adds from a companion
    preset is a spec that the add service takes.
    """
    domain = _match(_DOMAIN, domain, "domain")
    names = validate_duty_names(duty_names)
    lookup: Mapping[str, dict[str, str]] = ChainMap(names, DUTY_NAMES)
    raw_rows = _list(rows, "rows", MAX_ROWS)
    clean = [
        validate_row(row, f"rows[{index}]", lookup)
        for index, row in enumerate(raw_rows)
    ]
    seen: set[str] = set()
    for index, row in enumerate(clean):
        if row["domain"] in seen:
            raise PresetRowError(f"rows[{index}].domain", "must not repeat a domain")
        seen.add(row["domain"])
    built, texts = declarative_presets._integration_presets(
        clean, lookup, prefix=domain + ID_SEPARATOR
    )
    ids: set[str] = set()
    for preset in built:
        if len(preset["id"]) > MAX_PRESET_ID_LEN:
            raise PresetRowError(
                "rows",
                f"preset id {preset['id']} is over {MAX_PRESET_ID_LEN} characters",
            )
        if preset["id"] in ids:
            raise PresetRowError("rows", f"preset id {preset['id']} is made twice")
        ids.add(preset["id"])
        try:
            declarative_companions.normalize_declarative_companion(
                preset["default_spec"]
            )
        except ValueError as err:
            raise PresetRowError("rows", f"preset {preset['id']}: {err}") from err
        preset["source"] = SOURCE_COMPANION
        preset["provided_by"] = domain
    return Registration(domain, tuple(clean), names, tuple(built), texts)


@dataclass(frozen=True)
class Register:
    """Replace the presets of a companion with a checked registration."""

    registration: Registration


@dataclass(frozen=True)
class Unregister:
    """Remove the presets of the companion with *domain*."""

    domain: str


@dataclass(frozen=True)
class PresetRegistry:
    """The registered presets, by companion domain, in order of first registration."""

    registrations: Mapping[str, Registration] = field(default_factory=dict)


@dataclass(frozen=True)
class Transition:
    """The result of 1 action: the new registry and the bus events to fire."""

    registry: PresetRegistry
    events: tuple[tuple[str, dict[str, Any]], ...]


def transition(registry: PresetRegistry, action: Register | Unregister) -> Transition:
    """Apply *action* to *registry*.

    A registration that changes nothing, and a removal of a domain with no presets,
    fire no event. A new domain past ``MAX_COMPANIONS`` raises ``PresetRowError``.
    """
    current = dict(registry.registrations)
    if isinstance(action, Unregister):
        old = current.pop(action.domain, None)
        if old is None:
            return Transition(registry, ())
        removed = events.presets_event_data(old.domain, old.preset_ids)
        return Transition(PresetRegistry(current), ((EVENT_PRESETS_REMOVED, removed),))
    new = action.registration
    old = current.get(new.domain)
    if old is None and len(current) >= MAX_COMPANIONS:
        raise PresetRowError(
            "domain", f"the {MAX_COMPANIONS}-companion limit is reached"
        )
    if old is not None and old.presets == new.presets:
        return Transition(registry, ())
    current[new.domain] = new
    added = events.presets_event_data(new.domain, new.preset_ids)
    return Transition(PresetRegistry(current), ((EVENT_PRESETS_REGISTERED, added),))


def merged_presets(registry: PresetRegistry) -> list[PresetDefinition]:
    """The shipped presets, then each companion's presets in order of registration.

    A shipped preset gets ``source`` ``builtin``. The shipped list is not changed.
    """
    merged: list[PresetDefinition] = [
        {**preset, "source": SOURCE_BUILTIN}
        for preset in declarative_presets.CATALOG_PRESETS
    ]
    for registration in registry.registrations.values():
        merged.extend(registration.presets)
    return merged


__all__ = [
    "ID_SEPARATOR",
    "MAX_DUTIES",
    "MAX_DUTY_NAMES",
    "MAX_KEYS",
    "MAX_ROWS",
    "SOURCE_BUILTIN",
    "SOURCE_COMPANION",
    "PresetRegistry",
    "PresetRowError",
    "Register",
    "Registration",
    "Transition",
    "Unregister",
    "build_registration",
    "merged_presets",
    "transition",
    "validate_duty",
    "validate_duty_names",
    "validate_row",
]
