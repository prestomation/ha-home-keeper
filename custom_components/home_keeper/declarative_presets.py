"""Shipped declarative-companion presets.

A **preset** is a partial declarative-companion spec plus a bit of catalog
metadata (name/description i18n keys, icon, ``requires_integration`` gate). The
panel lists them under Settings → Companions → Declarative → *Add from preset*;
picking one seeds the Add dialog with the preset's ``default_spec``, the user
reviews, then Save persists a full spec (which the reconciler then materializes
into managed sensor tasks).

Three presets ship:

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

No shipped preset uses the ``availability`` sensor mode. That mode is a general
capability for user-authored companions ("watch my MQTT devices go offline"), not a
preset the panel installs. See ``declarative_companions.py`` for spec shape and
``docs/EVENTS.md`` / ``docs/INTEGRATING.md`` for the surface.

Pure — no HA imports (the panel resolves ``name_key`` / ``description_key``
through ``backend_i18n.resolve_string`` at request time).
"""

from __future__ import annotations

from typing import Any, TypedDict


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
PRESET_TASK_TEXT: dict[str, dict[str, dict[str, str]]] = {
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
_TEMPLATE_FIELDS = ("name_template", "notes_template")
_DEFAULT_LANG = "en"


def _pick(table: dict[str, str], lang: str | None) -> str:
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
        variants = texts[field]
        if template.get(field) in variants.values():
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
