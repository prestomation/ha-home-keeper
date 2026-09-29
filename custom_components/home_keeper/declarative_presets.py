"""Shipped declarative-companion presets.

A **preset** is a partial declarative-companion spec plus a bit of catalog
metadata (name/description i18n keys, icon, ``requires_integration`` gate). The
panel lists them under Settings → Companions → Declarative → *Add from preset*;
picking one seeds the Add dialog with the preset's ``default_spec``, the user
reviews, then Save persists a full spec (which the reconciler then materializes
into managed sensor tasks).

Three general presets ship:

* ``device_pulse`` — targets the standalone Device Pulse integration
  (studiobts/home-assistant-device-pulse) and watches its per-device
  ``sensor.*_total_failed_pings`` sensors via the existing ``threshold`` mode.
  Requires the Device Pulse integration to be installed.
* ``firmware_update_available`` — watches every ``update.*`` entity reporting
  ``on`` (HA's built-in firmware/software-update surface). Covers UniFi, ESPHome,
  HACS, Reolink, Bambu Lab firmware updates in one declarative companion.
* ``device_stopped_reporting`` — watches every ``sensor.*_last_seen`` entity through the
  ``template`` mode and opens a task once one is a day stale. Needs no upstream
  integration, and it is the worked example for what a template trigger is for.

The **integration presets** follow them: one preset for each integration in
``declarative_presets_catalog.INTEGRATIONS`` and each way its readings become a task
(``SHAPES``). They select entities by their ``translation_key``, and each key gets
the task name of its duty from ``declarative_preset_text.DUTY_NAMES``. They are built
when this module loads, by :func:`_integration_presets`.

No shipped preset uses the ``availability`` sensor mode. That mode is a general
capability for user-authored companions ("watch my MQTT devices go offline"), not a
preset the panel installs. See ``declarative_companions.py`` for spec shape and
``docs/EVENTS.md`` / ``docs/INTEGRATING.md`` for the surface.

Pure — no HA imports (the panel resolves ``name_key`` / ``description_key``
through ``backend_i18n.resolve_string`` at request time).
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from .declarative_preset_text import DUTY_NAMES
from .declarative_presets_catalog import INTEGRATIONS


class PresetDefinition(TypedDict):
    """One shipped declarative-companion preset.

    ``requires_integration`` names the HA integration domain the panel should
    check for before enabling the preset card — ``None`` for presets that work
    without a specific upstream (Firmware Update). The panel greys out cards whose
    requirement isn't installed and shows a "Requires <integration>" tooltip.
    """

    id: str
    name_key: str
    description_key: str
    icon: str
    requires_integration: str | None
    default_spec: dict[str, Any]
    # Values for the placeholders in the name and description strings. An integration
    # preset names its integration here, so one string per shape serves every one.
    name_args: NotRequired[dict[str, str]]


CATALOG_PRESETS: list[PresetDefinition] = [
    {
        "id": "device_pulse",
        "name_key": "declarative_preset.device_pulse.name",
        "description_key": "declarative_preset.device_pulse.description",
        "icon": "mdi:heart-pulse",
        "requires_integration": "device_pulse",
        "default_spec": {
            "name": "Device Pulse",
            "description": "",
            "enabled": True,
            "preset_id": "device_pulse",
            "selection": {
                "target_integration": "device_pulse",
                "domain": "sensor",
                "entity_regex": r".*_total_failed_pings$",
                "area_ids": [],
                "label_ids": [],
                "exclude_entity_ids": [],
                "exclude_device_ids": [],
                "exclude_area_ids": [],
                "exclude_label_ids": [],
            },
            "trigger": {
                "mode": "threshold",
                "comparison": ">",
                "value": 0,
                "for_seconds": 3600,
                "clear_on_recover": True,
            },
            "task_template": {
                "name_template": "Check on {{ device_name or friendly_name }}",
                "notes_template": (
                    "Device Pulse reports {{ state }} failed pings "
                    "for {{ friendly_name }}."
                ),
                "labels": [],
            },
            "per_entity_overrides": {},
        },
    },
    {
        "id": "firmware_update_available",
        "name_key": "declarative_preset.firmware_update_available.name",
        "description_key": ("declarative_preset.firmware_update_available.description"),
        "icon": "mdi:update",
        "requires_integration": None,
        "default_spec": {
            "name": "Firmware update available",
            "description": "",
            "enabled": True,
            "preset_id": "firmware_update_available",
            "selection": {
                "domain": "update",
                "area_ids": [],
                "label_ids": [],
                "exclude_entity_ids": [],
                "exclude_device_ids": [],
                "exclude_area_ids": [],
                "exclude_label_ids": [],
            },
            "trigger": {
                "mode": "state",
                "state": "on",
                "clear_on_recover": True,
            },
            "task_template": {
                "name_template": "Update {{ friendly_name }}",
                "notes_template": (
                    "Latest version: {{ attributes.latest_version or 'unknown' }}"
                ),
                "labels": [],
            },
            "per_entity_overrides": {},
        },
    },
    {
        "id": "device_stopped_reporting",
        "name_key": "declarative_preset.device_stopped_reporting.name",
        "description_key": "declarative_preset.device_stopped_reporting.description",
        "icon": "mdi:access-point-off",
        "requires_integration": None,
        "default_spec": {
            "name": "Device stopped reporting",
            "description": "",
            "enabled": True,
            "preset_id": "device_stopped_reporting",
            "selection": {
                "domain": "sensor",
                "entity_regex": r".*_last_seen$",
                "area_ids": [],
                "label_ids": [],
                "exclude_entity_ids": [],
                "exclude_device_ids": [],
                "exclude_area_ids": [],
                "exclude_label_ids": [],
            },
            # The worked example for the ``template`` mode (#346): a Zigbee or MQTT
            # device that has dropped off the mesh still has a ``_last_seen`` sensor,
            # holding the timestamp it went quiet. No other mode can compare that
            # timestamp with the clock.
            #
            # The template has no guard for ``unknown`` or ``unavailable`` on purpose.
            # A guard such as ``state not in [...] and ...`` renders **false** for
            # those states, and false with ``clear_on_recover`` completes the task.
            # A Zigbee2MQTT device that drops off the mesh makes its ``_last_seen``
            # sensor unavailable, and after a restart the sensor of a dead device
            # stays unknown. So a guard would close the tasks this preset exists
            # to keep open. Without it, ``as_datetime`` cannot read the state, the
            # render fails, and a failed render is *indeterminate*: it opens no
            # task and closes no task.
            "trigger": {
                "mode": "template",
                "template": (
                    "{{ (now() - as_datetime(state)) >= timedelta(hours=24) }}"
                ),
                "clear_on_recover": True,
            },
            "task_template": {
                "name_template": "Check on {{ device_name or friendly_name }}",
                "notes_template": "This device last reported at {{ state }}.",
                "labels": [],
            },
            "per_entity_overrides": {},
        },
    },
]


def preset_by_id(preset_id: str) -> PresetDefinition | None:
    """Return the shipped preset with *preset_id*, or ``None`` if unknown.

    Used by the panel WS endpoint to hand a preset's default spec back to the
    frontend when the user picks a preset card; also used by the store to check
    an incoming spec's ``preset_id`` against the catalog for badge rendering.
    """
    for preset in CATALOG_PRESETS:
        if preset["id"] == preset_id:
            return preset
    return None


# "Check on <device>", which two presets use as their task name.
_DEVICE_CHECK_NAMES: dict[str, str] = {
    "en": "Check on {{ device_name or friendly_name }}",
    "ca": "Comprovar {{ device_name or friendly_name }}",
    "cs": "Zkontrolovat {{ device_name or friendly_name }}",
    "da": "Tjek {{ device_name or friendly_name }}",
    "de": "{{ device_name or friendly_name }} prüfen",
    "es": "Revisar {{ device_name or friendly_name }}",
    "fi": "Tarkista {{ device_name or friendly_name }}",
    "fr": "Vérifier {{ device_name or friendly_name }}",
    "it": "Controllare {{ device_name or friendly_name }}",
    "nb": "Sjekk {{ device_name or friendly_name }}",
    "nl": "{{ device_name or friendly_name }} controleren",
    "pl": "Sprawdź {{ device_name or friendly_name }}",
    "pt-BR": "Verificar {{ device_name or friendly_name }}",
    "ru": "Проверить {{ device_name or friendly_name }}",
    "sv": "Kontrollera {{ device_name or friendly_name }}",
    "zh-Hans": "检查 {{ device_name or friendly_name }}",
}


# The task text each preset seeds, per language. A preset's ``default_spec`` holds the
# English; the panel is handed the household's language (``localized_default_spec``),
# and a saved companion whose template is still one of these, in any language, renders
# in the current language (``localized_task_template``). A template the user edited
# matches none of them and is rendered as written. Translators: keep every Jinja
# expression between ``{{ }}`` exactly as it is, except the quoted fallback word.
PRESET_TASK_TEXT: dict[str, dict[str, dict[str, Any]]] = {
    "device_pulse": {
        "name_template": _DEVICE_CHECK_NAMES,
        "notes_template": {
            "en": (
                "Device Pulse reports {{ state }} failed pings for {{ friendly_name }}."
            ),
            "ca": (
                "Device Pulse informa de {{ state }} "
                "pings fallits per a {{ friendly_name }}."
            ),
            "cs": (
                "Device Pulse hlásí {{ state }} "
                "neúspěšných pingů pro {{ friendly_name }}."
            ),
            "da": (
                "Device Pulse rapporterer {{ state }} "
                "mislykkede ping for {{ friendly_name }}."
            ),
            "de": (
                "Device Pulse meldet {{ state }} "
                "fehlgeschlagene Pings für {{ friendly_name }}."
            ),
            "es": (
                "Device Pulse informa de {{ state }} "
                "pings fallidos para {{ friendly_name }}."
            ),
            "fi": (
                "Device Pulse ilmoittaa {{ state }} epäonnistunutta "
                "pingiä kohteelle {{ friendly_name }}."
            ),
            "fr": (
                "Device Pulse signale {{ state }} pings "
                "échoués pour {{ friendly_name }}."
            ),
            "it": (
                "Device Pulse segnala {{ state }} ping falliti per {{ friendly_name }}."
            ),
            "nb": (
                "Device Pulse rapporterer {{ state }} "
                "mislykkede ping for {{ friendly_name }}."
            ),
            "nl": (
                "Device Pulse meldt {{ state }} mislukte "
                "pings voor {{ friendly_name }}."
            ),
            "pl": (
                "Device Pulse zgłasza {{ state }} "
                "nieudanych pingów dla {{ friendly_name }}."
            ),
            "pt-BR": (
                "O Device Pulse informa {{ state }} pings "
                "com falha para {{ friendly_name }}."
            ),
            "ru": (
                "Device Pulse сообщает: {{ state }} "
                "неудачных пингов для {{ friendly_name }}."
            ),
            "sv": (
                "Device Pulse rapporterar {{ state }} "
                "misslyckade ping för {{ friendly_name }}."
            ),
            "zh-Hans": (
                "Device Pulse 报告 {{ friendly_name }} 有 {{ state }} 次 ping 失败。"
            ),
        },
    },
    # The name is the Device Pulse name on purpose: both presets ask the user to go
    # and look at a device, and one wording per language keeps the task lists alike.
    "device_stopped_reporting": {
        "name_template": _DEVICE_CHECK_NAMES,
        "notes_template": {
            "en": "This device last reported at {{ state }}.",
            "ca": "Aquest dispositiu va informar per última vegada a les {{ state }}.",
            "cs": "Toto zařízení se naposledy ozvalo v {{ state }}.",
            "da": "Denne enhed rapporterede sidst {{ state }}.",
            "de": "Dieses Gerät hat zuletzt um {{ state }} gemeldet.",
            "es": "Este dispositivo informó por última vez a las {{ state }}.",
            "fi": "Tämä laite raportoi viimeksi {{ state }}.",
            "fr": "Cet appareil a communiqué pour la dernière fois à {{ state }}.",
            "it": "Questo dispositivo ha comunicato l'ultima volta alle {{ state }}.",
            "nb": "Denne enheten rapporterte sist {{ state }}.",
            "nl": "Dit apparaat meldde zich voor het laatst om {{ state }}.",
            "pl": "To urządzenie ostatnio zgłosiło się o {{ state }}.",
            "pt-BR": "Este dispositivo se comunicou pela última vez às {{ state }}.",
            "ru": "Это устройство последний раз выходило на связь в {{ state }}.",
            "sv": "Den här enheten rapporterade senast {{ state }}.",
            "zh-Hans": "此设备最后一次报告的时间为 {{ state }}。",
        },
    },
    "firmware_update_available": {
        "name_template": {
            "en": "Update {{ friendly_name }}",
            "ca": "Actualitzar {{ friendly_name }}",
            "cs": "Aktualizovat {{ friendly_name }}",
            "da": "Opdater {{ friendly_name }}",
            "de": "{{ friendly_name }} aktualisieren",
            "es": "Actualizar {{ friendly_name }}",
            "fi": "Päivitä {{ friendly_name }}",
            "fr": "Mettre à jour {{ friendly_name }}",
            "it": "Aggiornare {{ friendly_name }}",
            "nb": "Oppdater {{ friendly_name }}",
            "nl": "{{ friendly_name }} bijwerken",
            "pl": "Zaktualizuj {{ friendly_name }}",
            "pt-BR": "Atualizar {{ friendly_name }}",
            "ru": "Обновить {{ friendly_name }}",
            "sv": "Uppdatera {{ friendly_name }}",
            "zh-Hans": "更新 {{ friendly_name }}",
        },
        "notes_template": {
            "en": "Latest version: {{ attributes.latest_version or 'unknown' }}",
            "ca": "Darrera versió: {{ attributes.latest_version or 'desconeguda' }}",
            "cs": "Nejnovější verze: {{ attributes.latest_version or 'neznámá' }}",
            "da": "Nyeste version: {{ attributes.latest_version or 'ukendt' }}",
            "de": "Neueste Version: {{ attributes.latest_version or 'unbekannt' }}",
            "es": "Última versión: {{ attributes.latest_version or 'desconocida' }}",
            "fi": "Uusin versio: {{ attributes.latest_version or 'tuntematon' }}",
            "fr": "Dernière version : {{ attributes.latest_version or 'inconnue' }}",
            "it": "Ultima versione: {{ attributes.latest_version or 'sconosciuta' }}",
            "nb": "Nyeste versjon: {{ attributes.latest_version or 'ukjent' }}",
            "nl": "Nieuwste versie: {{ attributes.latest_version or 'onbekend' }}",
            "pl": "Najnowsza wersja: {{ attributes.latest_version or 'nieznana' }}",
            "pt-BR": (
                "Versão mais recente: {{ attributes.latest_version or 'desconhecida' }}"
            ),
            "ru": "Последняя версия: {{ attributes.latest_version or 'неизвестна' }}",
            "sv": "Senaste version: {{ attributes.latest_version or 'okänd' }}",
            "zh-Hans": "最新版本：{{ attributes.latest_version or '未知' }}",  # noqa: RUF001
        },
    },
}
# ``task_names`` is a table (entity key -> task name) rather than a string, and it is
# localized the same way: a table still equal to one of the preset's own tables, in
# any language, is replaced by the table for the current language.
_TEMPLATE_FIELDS = ("name_template", "notes_template", "task_names")
_DEFAULT_LANG = "en"


def _pick(table: dict[str, Any], lang: str | None) -> Any:
    """*table*'s text for *lang*: exact, then the base language, then English."""
    if lang:
        if lang in table:
            return table[lang]
        base = lang.split("-")[0].lower()
        for key, value in table.items():
            if key.lower() == lang.lower() or key.lower() == base:
                return value
    return table[_DEFAULT_LANG]


def localized_task_template(spec: dict[str, Any], lang: str | None) -> dict[str, Any]:
    """*spec*'s task template, with unchanged preset text put into *lang*.

    A field is replaced only when the spec names a known preset and the field still
    reads as that preset's text in **some** language — so a companion saved in English
    renders in German after the household switches, and back again. A field the user
    edited matches none of them and is returned as written. The input is not mutated.
    """
    template = dict(spec.get("task_template") or {})
    texts = PRESET_TASK_TEXT.get(str(spec.get("preset_id") or ""))
    if not texts:
        return template
    for field in _TEMPLATE_FIELDS:
        variants = texts.get(field)
        if variants and template.get(field) in variants.values():
            template[field] = _pick(variants, lang)
    return template


def localized_default_spec(
    preset: PresetDefinition, lang: str | None, name: str
) -> dict[str, Any]:
    """A copy of *preset*'s ``default_spec`` in *lang*, named *name*.

    This is what the panel seeds the Add dialog with, so a new companion is saved in
    the household's language from the start.
    """
    spec = dict(preset["default_spec"])
    spec["name"] = name
    spec["task_template"] = localized_task_template(spec, lang)
    return spec


# ── Integration presets ──────────────────────────────────────────────────────
#
# One preset per integration and per *shape*: the way a kind of reading becomes a
# task. Each shape has one name string and one description string in
# ``backend_strings/`` with an ``{integration}`` placeholder, so 6 strings serve every
# integration. The English name here seeds ``default_spec["name"]``; the panel shows the
# localized one, and a test keeps the two equal.
SHAPES: dict[str, str] = {
    "percent_low": "{integration}: parts and supplies running low",
    "life_low": "{integration}: parts near the end of their life",
    "wear_high": "{integration}: wear counters",
    "reading_low": "{integration}: readings too low",
    "reading_high": "{integration}: readings too high",
    "alert": "{integration}: service alerts",
}

# Hours in one of each time unit an entity can report. The time templates multiply the
# reading by this to compare it in hours, so the preset does not care whether the
# integration counts in seconds or days. A unit not in the table makes the ``life_low``
# template fail to render, which decides nothing (a failed render neither opens nor
# closes a task), so a reading in an unknown unit is never compared as hours.
_TIME_FACTORS = (
    "{'s': 1 / 3600, 'sec': 1 / 3600, 'min': 1 / 60, 'h': 1, 'hr': 1, "
    "'hours': 1, 'd': 24, 'day': 24, 'days': 24, 'w': 168}"
)

# The level below which a part or supply reported as a percentage is low.
_PERCENT_FLOOR = 10

# Every integration preset shares these two templates. ``{{ task_name }}`` is the duty,
# and the device says which appliance. When one preset has 2 keys with the same task
# name (the colour cartridges of a printer), the device alone cannot tell the tasks
# apart, so those presets name the entity instead.
_NAME_BY_DEVICE = "{{ task_name }}: {{ device_name or friendly_name }}"
_NAME_BY_ENTITY = "{{ task_name }}: {{ friendly_name }}"
_NOTES = (
    "{{ friendly_name }}: {{ state }}"
    "{{ ' ' ~ attributes.unit_of_measurement "
    "if attributes.unit_of_measurement else '' }}"
)


def _limit(duties: list[dict[str, Any]]) -> tuple[float | None, str]:
    """The limit of *duties*: one number, or a per-key table for a template.

    Returns ``(number, "")`` when every duty has the same limit, else ``(None,
    expression)`` where the expression looks the limit up by ``translation_key``.
    """
    limits = {d["limit"] for d in duties}
    if len(limits) == 1:
        return next(iter(limits)), ""
    table = ", ".join(f"'{key}': {d['limit']}" for d in duties for key in d["keys"])
    return None, "{" + table + "}[translation_key]"


def _trigger(shape: str, duties: list[dict[str, Any]]) -> dict[str, Any]:
    """The trigger block for *duties*, which share *shape*.

    Every integration preset closes its task itself when the reading recovers, so a
    reset on the device or a refill is what completes it.
    """
    if shape == "alert":
        return {"mode": "state", "state": duties[0]["state"], "clear_on_recover": True}
    number, table = _limit(duties)
    limit = table or f"{number:g}"
    if shape == "life_low":
        # Some models of one integration report the life left as a percentage and
        # others as a time, under the same key. A percentage is compared with the
        # percentage floor, and a time in hours.
        template = (
            f"{{{{ state | float < {_PERCENT_FLOOR} "
            "if attributes.unit_of_measurement == '%' "
            f"else state | float * {_TIME_FACTORS}[attributes.unit_of_measurement]"
            f" < {limit} }}}}"
        )
        return {"mode": "template", "template": template, "clear_on_recover": True}
    if shape == "wear_high":
        # A counter in a unit that is not a time (washes, cycles) is compared as it is.
        template = (
            f"{{{{ state | float * {_TIME_FACTORS}"
            f".get(attributes.get('unit_of_measurement'), 1) > {limit} }}}}"
        )
        return {"mode": "template", "template": template, "clear_on_recover": True}
    comparison = "<" if shape in ("percent_low", "reading_low") else ">"
    if table:
        template = f"{{{{ state | float {comparison} {table} }}}}"
        return {"mode": "template", "template": template, "clear_on_recover": True}
    return {
        "mode": "threshold",
        "comparison": comparison,
        "value": number,
        "clear_on_recover": True,
    }


def _integration_presets() -> tuple[
    list[PresetDefinition], dict[str, dict[str, dict[str, Any]]]
]:
    """Build the integration presets and their task text from the catalog."""
    built: list[PresetDefinition] = []
    texts: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in INTEGRATIONS:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for duty in entry["duties"]:
            platform = duty.get("platform", "sensor")
            group = (duty["shape"], platform, duty.get("state", ""))
            groups.setdefault(group, []).append(duty)
        for (shape, platform, state), duties in groups.items():
            preset_id = "_".join(
                part
                for part in (
                    entry["domain"],
                    shape,
                    "" if platform == "sensor" else platform,
                    state,
                )
                if part
            )
            names = [DUTY_NAMES[d["duty"]]["en"] for d in duties for _ in d["keys"]]
            name_template = (
                _NAME_BY_ENTITY if len(set(names)) < len(names) else _NAME_BY_DEVICE
            )
            keys = [key for d in duties for key in d["keys"]]
            task_names = {
                lang: {
                    key: DUTY_NAMES[d["duty"]][lang]
                    for d in duties
                    for key in d["keys"]
                }
                for lang in DUTY_NAMES[duties[0]["duty"]]
            }
            built.append(
                {
                    "id": preset_id,
                    "name_key": f"declarative_preset.shape.{shape}.name",
                    "description_key": f"declarative_preset.shape.{shape}.description",
                    "name_args": {"integration": entry["brand"]},
                    "icon": entry["icon"],
                    "requires_integration": entry["domain"],
                    "default_spec": {
                        "name": SHAPES[shape].format(integration=entry["brand"]),
                        "description": "",
                        "enabled": True,
                        "preset_id": preset_id,
                        "selection": {
                            "target_integration": entry["domain"],
                            "domain": platform,
                            "translation_keys": keys,
                            "area_ids": [],
                            "label_ids": [],
                            "exclude_entity_ids": [],
                            "exclude_device_ids": [],
                            "exclude_area_ids": [],
                            "exclude_label_ids": [],
                        },
                        "trigger": _trigger(shape, duties),
                        "task_template": {
                            "name_template": name_template,
                            "notes_template": _NOTES,
                            "labels": [],
                            "task_names": task_names[_DEFAULT_LANG],
                        },
                        "per_entity_overrides": {},
                    },
                }
            )
            texts[preset_id] = {
                "name_template": dict.fromkeys(task_names, name_template),
                "notes_template": dict.fromkeys(task_names, _NOTES),
                "task_names": task_names,
            }
    return built, texts


_BUILT, _BUILT_TEXT = _integration_presets()
CATALOG_PRESETS.extend(_BUILT)
PRESET_TASK_TEXT.update(_BUILT_TEXT)
