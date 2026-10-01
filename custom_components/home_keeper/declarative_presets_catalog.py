"""The integration presets: what each integration reports and which key reports it.

Pure data, no Home Assistant import. declarative_presets.py turns each entry into
presets for the picker, one per trigger shape and entity platform. Each entry has:

* domain: the integration domain. It is the preset's target_integration and
  its requires_integration.
* brand: the name a person knows the integration by. It is not translated.
* icon: the card icon.
* source: the integration's English translation file, as a raw GitHub URL on a
  branch. ci/check_preset_keys.py reads it to confirm that each key is still there.
* verified: the commit of that branch we last read (``ref``) and the date
  (``date``). ci/check_preset_keys.py --report lists the keys added and removed
  upstream since that commit, and --pin moves it forward after a check.
* duties: one entry per task a device of the integration can need.

A duty has:

* duty: the id of its task name in declarative_preset_text.DUTY_NAMES.
* shape: how its reading becomes a task (see SHAPES in
  declarative_presets.py).
* platform: the entity platform, sensor when it is not given.
* keys: the translation_key values of the entities that report it. Every key
  was read from the integration's own translation file, so the integration names its
  entity with that key.
* limit: the number the reading is compared with. A percentage for
  percent_low, hours for life_low and wear_high, and the entity's own unit
  for reading_low and reading_high.
* state: the alert state, for alert.

Each entry's ``verified`` says when its keys were last checked. The preset-upkeep
skill (.claude/skills/preset-upkeep) runs the check each week, fixes or adds presets,
and moves the pins.
"""

from __future__ import annotations

from typing import Any

INTEGRATIONS: list[dict[str, Any]] = [
    # ── air ───────────────────────────────────────────────────────────────────────────
    {
        "domain": "dantherm",
        "brand": "Dantherm ventilation",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/Tvalley71/dantherm/main/custom_components/dantherm/translations/en.json",
        "verified": {
            "ref": "62a6ceb9b258b003b775c57ef7f9e3a18d0158fd",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ventilation_filter",
                "shape": "life_low",
                "keys": ["filter_remain"],
                "limit": 168,
            },
        ],
    },
    {
        "domain": "dreo",
        "brand": "Dreo",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/JeffSteinbok/hass-dreo/main/custom_components/dreo/translations/en.json",
        "verified": {
            "ref": "38e28eb78b59862e9dd49bb8bea276be74292ccf",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["filter_life"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "duco",
        "brand": "Duco ventilation",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/duco/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ventilation_filter",
                "shape": "life_low",
                "keys": ["filter_remaining"],
                "limit": 168,
            },
        ],
    },
    {
        "domain": "duux",
        "brand": "Duux",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/SSmale/Duux-Home-Assistant/master/custom_components/duux/translations/en.json",
        "verified": {
            "ref": "981b619f92c9da4b0278b32e83eb0fa2e0d968a8",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["filter_life"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "hass_dyson",
        "brand": "Dyson",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/cmgrayb/hass-dyson/main/custom_components/hass_dyson/translations/en.json",
        "verified": {
            "ref": "3dde06ec1d89b1fd12737da1a5c187036b290b7e",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["hepa_filter_life", "carbon_filter_life"],
                "limit": 10,
            },
            {
                "duty": "descale_appliance",
                "shape": "life_low",
                "keys": ["next_cleaning_cycle"],
                "limit": 24,
            },
        ],
    },
    {
        "domain": "flexit",
        "brand": "Flexit (Modbus)",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/flexit/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ventilation_filter",
                "shape": "wear_high",
                "keys": ["air_filter_operating_time"],
                "limit": 4380,
            },
        ],
    },
    {
        "domain": "flexit_bacnet",
        "brand": "Flexit Nordic",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/flexit_bacnet/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ventilation_filter",
                "shape": "wear_high",
                "keys": ["air_filter_operating_time"],
                "limit": 4380,
            },
        ],
    },
    {
        "domain": "genvex_connect",
        "brand": "Genvex Connect / Nilan gateway",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/superrob/genvexconnect/main/custom_components/genvex_connect/translations/en.json",
        "verified": {
            "ref": "70a1c5527ff35c6604265044ac246a785b4af3f9",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ventilation_filter",
                "shape": "life_low",
                "keys": ["filter_days_left"],
                "limit": 168,
            },
            {
                "duty": "replace_ventilation_filter",
                "shape": "wear_high",
                "keys": ["filter_days"],
                "limit": 4380,
            },
        ],
    },
    {
        "domain": "govee",
        "brand": "Govee (purifiers)",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/lasswellt/govee-homeassistant/main/custom_components/govee/translations/en.json",
        "verified": {
            "ref": "2d7184d408530c6c565c4d607753bef8c327bcc4",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["sensor_filter_life"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "tradfri",
        "brand": "IKEA Trådfri (STARKVIND)",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/tradfri/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "life_low",
                "keys": ["filter_life_remaining"],
                "limit": 72,
            },
        ],
    },
    {
        "domain": "nest_legacy",
        "brand": "Nest (legacy API)",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/tronikos/nest_legacy/main/custom_components/nest_legacy/translations/en.json",
        "verified": {
            "ref": "17b98a8c6930a619ea06b5e302052bea2c374d71",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "wear_high",
                "keys": ["filter_runtime"],
                "limit": 300,
            },
        ],
    },
    {
        "domain": "nilan",
        "brand": "Nilan (CTS602 Modbus)",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/veista/nilan/master/custom_components/nilan/translations/en.json",
        "verified": {
            "ref": "6cdbbfef87b4da6eb5a96c0fe2b74b724cf147ad",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ventilation_filter",
                "shape": "life_low",
                "keys": ["days_to_air_filter_change"],
                "limit": 168,
            },
        ],
    },
    {
        "domain": "philips_airpurifier_coap",
        "brand": "Philips AirPurifier (CoAP)",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/kongo09/philips-airpurifier-coap/master/custom_components/philips_airpurifier_coap/translations/en.json",
        "verified": {
            "ref": "964ef214fc7de1aa6d98f9e392b7c404426f6ee5",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "filter_cleaning",
                "shape": "life_low",
                "keys": ["pre_filter"],
                "limit": 72,
            },
            {
                "duty": "replace_filter",
                "shape": "life_low",
                "keys": ["hepa_filter", "active_carbon_filter", "nanoprotect_filter"],
                "limit": 72,
            },
            {
                "duty": "replace_wick",
                "shape": "life_low",
                "keys": ["wick"],
                "limit": 72,
            },
        ],
    },
    {
        "domain": "pluggit",
        "brand": "Pluggit ventilation",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/Tvalley71/pluggit/main/custom_components/pluggit/translations/en.json",
        "verified": {
            "ref": "ee0e13df35f6feedcb14a9d23bfc292c2f531988",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ventilation_filter",
                "shape": "life_low",
                "keys": ["filter_remain"],
                "limit": 168,
            },
        ],
    },
    {
        "domain": "pura",
        "brand": "Pura fragrance diffusers",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/natekspencer/ha-pura/main/custom_components/pura/translations/en.json",
        "verified": {
            "ref": "f6aabcb5ab7dd2ca6a845dbcdb45815b31766346",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_air_freshener",
                "shape": "percent_low",
                "keys": ["fragrance_remaining", "bay_fragrance_remaining"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "renson",
        "brand": "Renson Endura Delta",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/renson/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ventilation_filter",
                "shape": "life_low",
                "keys": ["filter_change"],
                "limit": 168,
            },
        ],
    },
    {
        "domain": "localthings",
        "brand": "Samsung (Local Things)",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/mbillow/localthings/main/custom_components/localthings/translations/en.json",
        "verified": {
            "ref": "bda68e216dc6910a4d1783a70666aaa30220a4f5",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "reading_high",
                "keys": ["hepa_filter_usage", "filter_progress"],
                "limit": 90,
            },
            {
                "duty": "clean_grease_filter",
                "shape": "reading_high",
                "keys": ["hood_filter_usage"],
                "limit": 90,
            },
        ],
    },
    {
        "domain": "tuya_local",
        "brand": "Tuya Local",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/make-all/tuya-local/main/custom_components/tuya_local/translations/en.json",
        "verified": {
            "ref": "ba74533cec979494b5b70fa1d5965d5c1a38a0ee",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["filter_life"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "venstar",
        "brand": "Venstar thermostat",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/venstar/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "wear_high",
                "keys": ["filter_install_time"],
                "limit": 300,
            },
        ],
    },
    {
        "domain": "vesync",
        "brand": "VeSync (Levoit)",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/vesync/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["filter_life"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "winix",
        "brand": "Winix",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/iprak/winix/main/custom_components/winix/translations/en.json",
        "verified": {
            "ref": "fbcb3416f56655631701dba5bd84f0fd28139f27",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["filter_life"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "ha_comfoconnectpro",
        "brand": "Zehnder ComfoConnect Pro (Modbus)",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/hstrohmaier/ha_comfoconnectpro/main/custom_components/ha_comfoconnectpro/translations/en.json",
        "verified": {
            "ref": "e03e4b627bcdcd8c1049ed25f8f97a24c5d37aa5",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ventilation_filter",
                "shape": "life_low",
                "keys": ["filter_days_remaining"],
                "limit": 168,
            },
        ],
    },
    # ── cars ──────────────────────────────────────────────────────────────────────────
    {
        "domain": "ha_bosch_ebike",
        "brand": "Bosch eBike (Smart System & eBike System 2)",
        "icon": "mdi:car-wrench",
        "source": "https://raw.githubusercontent.com/Xunil99/ha-bosch-ebike/main/custom_components/ha_bosch_ebike/translations/en.json",
        "verified": {
            "ref": "ac6ddc44081c7e750da00fa00dd72feab2eaf8c2",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "bike_service",
                "shape": "life_low",
                "keys": ["service_due_in_days"],
                "limit": 336,
            },
        ],
    },
    {
        "domain": "fordconnect_query",
        "brand": "FordConnect Query",
        "icon": "mdi:car-wrench",
        "source": "https://raw.githubusercontent.com/marq24/ha-fordconnect-query/main/custom_components/fordconnect_query/translations/en.json",
        "verified": {
            "ref": "27ef56136831e8cafd2fb834ef09e273a55ac90f",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "oil_service",
                "shape": "percent_low",
                "keys": ["oil"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "porscheconnect",
        "brand": "Porsche Connect",
        "icon": "mdi:car-wrench",
        "source": "https://raw.githubusercontent.com/CJNE/ha-porscheconnect/main/custom_components/porscheconnect/translations/en.json",
        "verified": {
            "ref": "fce41adc1ebb38f35eacd8f353b472cfc565310f",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "annual_service",
                "shape": "life_low",
                "keys": ["main_service_time"],
                "limit": 336,
            },
            {
                "duty": "oil_service",
                "shape": "life_low",
                "keys": ["oil_service_time"],
                "limit": 336,
            },
        ],
    },
    {
        "domain": "smarthashtag",
        "brand": "Smart #1 / #3 (Hello Smart)",
        "icon": "mdi:car-wrench",
        "source": "https://raw.githubusercontent.com/DasBasti/SmartHashtag/main/custom_components/smarthashtag/translations/en.json",
        "verified": {
            "ref": "e18d336313f6345c2386874c4cc21752a1d30b80",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "annual_service",
                "shape": "life_low",
                "keys": ["days_to_service"],
                "limit": 336,
            },
        ],
    },
    {
        "domain": "stellantis_vehicles",
        "brand": "Stellantis (Peugeot/Citroën/DS/Opel/Fiat…)",
        "icon": "mdi:car-wrench",
        "source": "https://raw.githubusercontent.com/andreadegiovine/homeassistant-stellantis-vehicles/develop/custom_components/stellantis_vehicles/translations/en.json",
        "verified": {
            "ref": "c3b8c88bf7dde9c48ee9e7d8f71ff2369351f050",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "annual_service",
                "shape": "life_low",
                "keys": ["days_before_maintenance"],
                "limit": 336,
            },
        ],
    },
    {
        "domain": "myskoda",
        "brand": "Škoda (MySkoda)",
        "icon": "mdi:car-wrench",
        "source": "https://raw.githubusercontent.com/skodaconnect/homeassistant-myskoda/main/custom_components/myskoda/translations/en.json",
        "verified": {
            "ref": "e374c346d8a02c7f128e711e0463fc5f217cac12",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "annual_service",
                "shape": "life_low",
                "keys": ["inspection"],
                "limit": 336,
            },
            {
                "duty": "oil_service",
                "shape": "life_low",
                "keys": ["oil_service_in_days"],
                "limit": 336,
            },
        ],
    },
    # ── garden ────────────────────────────────────────────────────────────────────────
    {
        "domain": "hotspring",
        "brand": "Hot Spring spas",
        "icon": "mdi:robot-mower",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/hotspring/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_salt_cartridge",
                "shape": "wear_high",
                "keys": ["water_care_120_day_timer"],
                "limit": 2880,
            },
            {
                "duty": "water_test",
                "shape": "life_low",
                "keys": ["water_care_10_day_timer"],
                "limit": 24,
            },
        ],
    },
    {
        "domain": "husqvarna_automower",
        "brand": "Husqvarna Automower",
        "icon": "mdi:robot-mower",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/husqvarna_automower/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_blades",
                "shape": "wear_high",
                "keys": ["cutting_blade_usage_time"],
                "limit": 100,
            },
        ],
    },
    {
        "domain": "mammotion",
        "brand": "Mammotion (Luba)",
        "icon": "mdi:robot-mower",
        "source": "https://raw.githubusercontent.com/mikey0000/Mammotion-HA/main/custom_components/mammotion/translations/en.json",
        "verified": {
            "ref": "b16b5f4f2f73e91e93c3070c9bbfd420afef1378",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_blades",
                "shape": "wear_high",
                "keys": ["blade_used_time"],
                "limit": 100,
            },
        ],
    },
    {
        "domain": "ondilo_ico",
        "brand": "Ondilo ICO",
        "icon": "mdi:robot-mower",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/ondilo_ico/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_pool_salt",
                "shape": "reading_low",
                "keys": ["salt"],
                "limit": 2700,
            },
        ],
    },
    {
        "domain": "screenlogic",
        "brand": "Pentair ScreenLogic",
        "icon": "mdi:robot-mower",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/screenlogic/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_pool_salt",
                "shape": "reading_low",
                "keys": ["salt_ppm"],
                "limit": 2700,
            },
        ],
    },
    {
        "domain": "robonect",
        "brand": "Robonect (Husqvarna/Gardena/Flymo)",
        "icon": "mdi:robot-mower",
        "source": "https://raw.githubusercontent.com/geertmeersman/robonect/main/custom_components/robonect/translations/en.json",
        "verified": {
            "ref": "59b60eaef18e7459f7aaed00c4551b1f3e61c594",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_blades",
                "shape": "wear_high",
                "keys": ["mower_blades_hours"],
                "limit": 100,
            },
        ],
    },
    {
        "domain": "sunseeker",
        "brand": "Sunseeker mowers",
        "icon": "mdi:robot-mower",
        "source": "https://raw.githubusercontent.com/Sdahl1234/Sunseeker-lawn-mower/main/custom_components/sunseeker/translations/en.json",
        "verified": {
            "ref": "659ef1366b0dba4ec5b5a6f3e3de04e8e19eeb9b",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_blades",
                "shape": "life_low",
                "keys": ["sunseeker_blade_time_left"],
                "limit": 24,
            },
            {
                "duty": "replace_blades",
                "shape": "percent_low",
                "keys": ["sunseeker_blade_health"],
                "limit": 10,
            },
            {
                "duty": "replace_cutting_disc",
                "shape": "percent_low",
                "keys": ["sunseeker_cutterplade_health"],
                "limit": 10,
            },
            {
                "duty": "replace_edge_trimmer_blade",
                "shape": "percent_low",
                "keys": ["sunseeker_small_blade_health"],
                "limit": 10,
            },
            {
                "duty": "replace_edge_trimmer_disc",
                "shape": "percent_low",
                "keys": ["sunseeker_small_cutterplade_health"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "landroid_cloud",
        "brand": "Worx Landroid",
        "icon": "mdi:robot-mower",
        "source": "https://raw.githubusercontent.com/MTrab/landroid_cloud/master/custom_components/landroid_cloud/translations/en.json",
        "verified": {
            "ref": "f30af7ffc87d3e1881e23c3a91ca3b715a52cb25",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_blades",
                "shape": "wear_high",
                "keys": ["blade_runtime_current"],
                "limit": 100,
            },
        ],
    },
    {
        "domain": "worx_vision_cloud",
        "brand": "Worx Landroid Vision",
        "icon": "mdi:robot-mower",
        "source": "https://raw.githubusercontent.com/ADNPolymerase/ha-landroid-vision/main/custom_components/worx_vision_cloud/translations/en.json",
        "verified": {
            "ref": "bec736bb2f9a6a3b44b3ff7e1c20110475601191",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_blades",
                "shape": "wear_high",
                "keys": ["blade_runtime_current"],
                "limit": 100,
            },
        ],
    },
    # ── heating ───────────────────────────────────────────────────────────────────────
    {
        "domain": "aquacell",
        "brand": "AquaCell softener",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/aquacell/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_softener_salt",
                "shape": "percent_low",
                "keys": ["salt_left_side_percentage", "salt_right_side_percentage"],
                "limit": 10,
            },
            {
                "duty": "refill_softener_salt",
                "shape": "life_low",
                "keys": [
                    "salt_left_side_time_remaining",
                    "salt_right_side_time_remaining",
                ],
                "limit": 168,
            },
        ],
    },
    {
        "domain": "bwt_aqa_perla_ble",
        "brand": "BWT AQA Perla (BLE)",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/Micka41/bwt-aqa-perla-ble/main/custom_components/bwt_aqa_perla_ble/translations/en.json",
        "verified": {
            "ref": "b20bd342d0afe85d4d7d20608d1d2eecab0277c0",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_softener_salt",
                "shape": "percent_low",
                "keys": ["salt_pct"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "bwt_perla",
        "brand": "BWT Perla",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/dkarv/ha-bwt-perla/main/custom_components/bwt_perla/translations/en.json",
        "verified": {
            "ref": "0fb31ba8986696a16b61db7355737020cd781224",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_softener_salt",
                "shape": "percent_low",
                "keys": ["regenerativ_level"],
                "limit": 10,
            },
            {
                "duty": "refill_softener_salt",
                "shape": "life_low",
                "keys": ["regenerativ_days"],
                "limit": 168,
            },
        ],
    },
    {
        "domain": "drop_connect",
        "brand": "DROP (water treatment)",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/drop_connect/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_water_filter",
                "shape": "percent_low",
                "keys": ["cart1", "cart2", "cart3"],
                "limit": 10,
            },
            {
                "duty": "refill_softener_salt",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["salt"],
                "state": "on",
            },
        ],
    },
    {
        "domain": "fumis",
        "brand": "Fumis (pellet stoves)",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/fumis/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "annual_service",
                "shape": "life_low",
                "keys": ["time_to_service"],
                "limit": 24,
            },
        ],
    },
    {
        "domain": "iqua_softener",
        "brand": "iQua softener",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/mutilator/homeassistant-iqua-softener/master/custom_components/iqua_softener/translations/en.json",
        "verified": {
            "ref": "031c18c0be30c52bc9e2bae5226753389e6bf9ea",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_softener_salt",
                "shape": "percent_low",
                "keys": ["salt_level"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "opentherm_gw",
        "brand": "OpenTherm Gateway",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/opentherm_gw/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_heating_water",
                "shape": "reading_low",
                "keys": ["central_heating_pressure"],
                "limit": 1,
            },
        ],
    },
    {
        "domain": "plugwise",
        "brand": "Plugwise (Anna/Adam)",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/plugwise/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_heating_water",
                "shape": "reading_low",
                "keys": ["water_pressure"],
                "limit": 1,
            },
        ],
    },
    {
        "domain": "rehlko",
        "brand": "Rehlko / Kohler generators",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/rehlko/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "oil_service",
                "shape": "wear_high",
                "keys": ["runtime_since_last_maintenance"],
                "limit": 100,
            },
        ],
    },
    {
        "domain": "salt_sentry",
        "brand": "Salt Sentry",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/Lemcke-solutions/Salt-sentry-ha-integration/main/custom_components/salt_sentry/translations/en.json",
        "verified": {
            "ref": "5ab09eb1968817f61a78e79befc2d7143317a52c",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_softener_salt",
                "shape": "percent_low",
                "keys": ["salt_level"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "stiebel_eltron_isg",
        "brand": "Stiebel Eltron ISG (LWZ)",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/pail23/stiebel_eltron_isg_component/main/custom_components/stiebel_eltron_isg/translations/en.json",
        "verified": {
            "ref": "7f28e759bc84b65a994eb3238db51c4614e5f6ed",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ventilation_filter",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["filter", "filter_extract_air", "filter_ventilation_air"],
                "state": "on",
            },
        ],
    },
    {
        "domain": "syr_connect",
        "brand": "SYR Connect (softeners)",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/alexhass/syr_connect/main/custom_components/syr_connect/translations/en.json",
        "verified": {
            "ref": "0b62e21f24aaf32794e2275870cd6c2476d4c823",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_softener_salt",
                "shape": "reading_low",
                "keys": ["getss1"],
                "limit": 2,
            },
        ],
    },
    {
        "domain": "unique_waterontharder",
        "brand": "Unique Waterontharder",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/mirkin-pixel/ha-unique-waterontharders/main/custom_components/unique_waterontharder/translations/en.json",
        "verified": {
            "ref": "18d19833b07938eb3bacacb0cc0800a574a531ec",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_softener_salt",
                "shape": "percent_low",
                "keys": ["salt_level"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "victron_gx",
        "brand": "Victron GX (generator)",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/victron_gx/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "oil_service",
                "shape": "life_low",
                "keys": ["generator_service_counter"],
                "limit": 24,
            },
        ],
    },
    {
        "domain": "vicare",
        "brand": "Viessmann ViCare",
        "icon": "mdi:radiator",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/vicare/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "life_low",
                "keys": ["filter_remaining_hours"],
                "limit": 24,
            },
        ],
    },
    # ── home it ───────────────────────────────────────────────────────────────────────
    {
        "domain": "mos",
        "brand": "MOS NAS",
        "icon": "mdi:nas",
        "source": "https://raw.githubusercontent.com/anym001/ha-mos/main/custom_components/mos/translations/en.json",
        "verified": {
            "ref": "202c76209a0e9f2cd8d43060393407532796035b",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "storage_cleanup",
                "shape": "reading_high",
                "keys": ["pool_usage"],
                "limit": 85,
            },
        ],
    },
    {
        "domain": "qnap",
        "brand": "QNAP NAS",
        "icon": "mdi:nas",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/qnap/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "storage_cleanup",
                "shape": "reading_high",
                "keys": ["volume_percentage_used"],
                "limit": 85,
            },
        ],
    },
    {
        "domain": "synology_dsm",
        "brand": "Synology NAS",
        "icon": "mdi:nas",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/synology_dsm/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "storage_cleanup",
                "shape": "reading_high",
                "keys": ["volume_percentage_used"],
                "limit": 85,
            },
        ],
    },
    {
        "domain": "unifi_unas_rest",
        "brand": "UniFi UNAS (REST)",
        "icon": "mdi:nas",
        "source": "https://raw.githubusercontent.com/LayerTM/unifi-unas-ha/main/custom_components/unifi_unas_rest/translations/en.json",
        "verified": {
            "ref": "e18cb611b1893bd8887ea4375332ca6aecd01b42",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "storage_cleanup",
                "shape": "reading_high",
                "keys": ["storage_usage"],
                "limit": 85,
            },
        ],
    },
    {
        "domain": "unraid",
        "brand": "Unraid",
        "icon": "mdi:nas",
        "source": "https://raw.githubusercontent.com/ruaan-deysel/ha-unraid/main/custom_components/unraid/translations/en.json",
        "verified": {
            "ref": "b95a595b418ca5235b6806590c23b49598dd49dd",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "storage_cleanup",
                "shape": "reading_high",
                "keys": ["array_usage"],
                "limit": 85,
            },
        ],
    },
    {
        "domain": "unraid_api",
        "brand": "Unraid API",
        "icon": "mdi:nas",
        "source": "https://raw.githubusercontent.com/chris-mc1/unraid_api/main/custom_components/unraid_api/translations/en.json",
        "verified": {
            "ref": "8b0041f893c8e58c44e6029dc857cdf99ed7bbe0",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "storage_cleanup",
                "shape": "reading_high",
                "keys": ["array_usage"],
                "limit": 85,
            },
        ],
    },
    {
        "domain": "unraid_management_agent",
        "brand": "Unraid Management Agent",
        "icon": "mdi:nas",
        "source": "https://raw.githubusercontent.com/ruaan-deysel/ha-unraid-management-agent/main/custom_components/unraid_management_agent/translations/en.json",
        "verified": {
            "ref": "4688658973fe719b02dd07586edf48daba7ba2c8",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "storage_cleanup",
                "shape": "reading_high",
                "keys": ["array_usage"],
                "limit": 85,
            },
        ],
    },
    # ── kitchen ───────────────────────────────────────────────────────────────────────
    {
        "domain": "candy",
        "brand": "Candy Simply-Fi",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/bigmoby/home-assistant-candy/main/custom_components/candy/translations/en.json",
        "verified": {
            "ref": "beb0933c0f018a490b73299d33e2023c42d9af84",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "descaling",
                "shape": "reading_low",
                "keys": ["wash_maint_limescale"],
                "limit": 1,
            },
            {
                "duty": "filter_cleaning",
                "shape": "reading_low",
                "keys": ["wash_maint_filter"],
                "limit": 1,
            },
        ],
    },
    {
        "domain": "connectlife",
        "brand": "ConnectLife (Hisense / Gorenje / ASKO)",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/oyvindwe/connectlife-ha/main/custom_components/connectlife/translations/en.json",
        "verified": {
            "ref": "fa830d2f2ba2d13fa234fa5ea11feb128141b70e",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "clean_grease_filter",
                "shape": "wear_high",
                "keys": ["greasefilterusedhours", "grease_filter_used_hours"],
                "limit": 30,
            },
            {
                "duty": "replace_filter",
                "shape": "wear_high",
                "keys": [
                    "recirculationfilter1usedhours",
                    "recirculationfilter2usedhours",
                    "recirculation_filter_1_used_hours",
                ],
                "limit": 120,
            },
            {
                "duty": "clean_appliance",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["alarm_run_selfcleaning"],
                "state": "on",
            },
        ],
    },
    {
        "domain": "electrolux",
        "brand": "Electrolux (OCP API)",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/TTLucian/ha-electrolux/main/custom_components/electrolux/translations/en.json",
        "verified": {
            "ref": "89415c73b4bd80e33140a5f13b3cea528dd31e34",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["filterlife", "filterlife_1", "filterlife_2"],
                "limit": 10,
            },
            {
                "duty": "replace_water_filter",
                "shape": "alert",
                "keys": ["waterfilterstate"],
                "state": "Change",
            },
            {
                "duty": "replace_filter",
                "shape": "alert",
                "keys": ["airfilterstate", "hepafilterstate"],
                "state": "Change",
            },
        ],
    },
    {
        "domain": "hon",
        "brand": "Haier hOn (Haier/Candy/Hoover)",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/Andre0512/hon/main/custom_components/hon/translations/en.json",
        "verified": {
            "ref": "70eb6c0111436b5f83fb20ee9dad69fe8407bb31",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "reading_high",
                "keys": ["filter_life"],
                "limit": 90,
            },
            {
                "duty": "filter_cleaning",
                "shape": "reading_high",
                "keys": ["filter_cleaning"],
                "limit": 90,
            },
        ],
    },
    {
        "domain": "home_connect",
        "brand": "Home Connect",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/home_connect/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_salt",
                "shape": "alert",
                "keys": ["salt_nearly_empty", "salt_lack", "program_blocked_salt_lack"],
                "state": "present",
            },
            {
                "duty": "refill_rinse_aid",
                "shape": "alert",
                "keys": ["rinse_aid_nearly_empty", "rinse_aid_lack"],
                "state": "present",
            },
            {
                "duty": "descale_appliance",
                "shape": "alert",
                "keys": [
                    "device_should_be_descaled",
                    "device_descaling_overdue",
                    "device_descaling_blockage",
                    "device_should_be_calc_n_cleaned",
                    "device_calc_n_clean_overdue",
                    "device_calc_n_clean_blockage",
                ],
                "state": "present",
            },
            {
                "duty": "clean_appliance",
                "shape": "alert",
                "keys": [
                    "device_should_be_cleaned",
                    "device_cleaning_overdue",
                    "machine_care_reminder",
                    "machine_care_and_filter_cleaning_reminder",
                    "machine_care_and_low_maintenance_filter_cleaning_reminder",
                ],
                "state": "present",
            },
            {
                "duty": "filter_cleaning",
                "shape": "alert",
                "keys": ["smart_filter_cleaning_reminder"],
                "state": "present",
            },
            {
                "duty": "clean_grease_filter",
                "shape": "alert",
                "keys": ["grease_filter_max_saturation_reached"],
                "state": "present",
            },
            {
                "duty": "refill_detergent",
                "shape": "alert",
                "keys": ["poor_i_dos_1_fill_level", "poor_i_dos_2_fill_level"],
                "state": "present",
            },
            {
                "duty": "empty_dustbin",
                "shape": "alert",
                "keys": ["empty_dust_box_and_clean_filter"],
                "state": "present",
            },
        ],
    },
    {
        "domain": "homeconnect_ws",
        "brand": "Home Connect Local",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/chris-mc1/homeconnect_local_hass/main/custom_components/homeconnect_ws/translations/en.json",
        "verified": {
            "ref": "853d01569ba7173b65e9c0f6ee848552e7c65bf7",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "clean_grease_filter",
                "shape": "reading_high",
                "keys": ["sensor_grease_filter_saturation"],
                "limit": 90,
            },
            {
                "duty": "replace_filter",
                "shape": "reading_high",
                "keys": ["sensor_carbon_filter_saturation"],
                "limit": 90,
            },
            {
                "duty": "descale_appliance",
                "shape": "reading_low",
                "keys": ["sensor_countdown_descaling"],
                "limit": 10,
            },
            {
                "duty": "clean_appliance",
                "shape": "reading_low",
                "keys": ["sensor_countdown_cleaning"],
                "limit": 10,
            },
            {
                "duty": "replace_water_filter",
                "shape": "reading_low",
                "keys": ["sensor_countdown_water_filter"],
                "limit": 10,
            },
            {
                "duty": "replace_water_filter",
                "shape": "reading_high",
                "keys": ["sensor_water_filter_saturation"],
                "limit": 90,
            },
        ],
    },
    {
        "domain": "homewhiz",
        "brand": "HomeWhiz (Beko / Grundig / Arçelik)",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/home-assistant-HomeWhiz/home-assistant-HomeWhiz/main/custom_components/homewhiz/translations/en.json",
        "verified": {
            "ref": "05f8cd010a9a853e2b7637c42f9b0b3ca74eb7c0",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_salt",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["dishwasher_warning_no_salt"],
                "state": "on",
            },
            {
                "duty": "refill_rinse_aid",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["dishwasher_warning_no_rinse_aid"],
                "state": "on",
            },
            {
                "duty": "filter_cleaning",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["dishwasher_warning_check_the_filter"],
                "state": "on",
            },
            {
                "duty": "refill_detergent",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["dishwasher_liquid_detergent_low"],
                "state": "on",
            },
            {
                "duty": "lint_filter_cleaning",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["dryer_warning_check_the_filter"],
                "state": "on",
            },
            {
                "duty": "condenser_cleaning",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["dryer_warning_check_the_condenser_filter"],
                "state": "on",
            },
        ],
    },
    {
        "domain": "lg_thinq",
        "brand": "LG ThinQ",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/lg_thinq/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["top_filter_remain_percent"],
                "limit": 10,
            },
            {
                "duty": "replace_filter",
                "shape": "life_low",
                "keys": ["filter_lifetime"],
                "limit": 24,
            },
            {
                "duty": "replace_water_filter",
                "shape": "percent_low",
                "keys": [
                    "water_filter_1_remain_percent",
                    "water_filter_2_remain_percent",
                    "water_filter_3_remain_percent",
                ],
                "limit": 10,
            },
            {
                "duty": "replace_filter",
                "shape": "alert",
                "keys": ["fresh_air_filter"],
                "state": "replace",
            },
        ],
    },
    {
        "domain": "midea",
        "brand": "Midea (core)",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/midea/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_softener_salt",
                "shape": "percent_low",
                "keys": ["salt_available"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "miele",
        "brand": "Miele",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/miele/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_salt",
                "shape": "percent_low",
                "keys": ["salt_level"],
                "limit": 10,
            },
            {
                "duty": "refill_rinse_aid",
                "shape": "percent_low",
                "keys": ["rinse_aid_level"],
                "limit": 10,
            },
            {
                "duty": "refill_detergent",
                "shape": "percent_low",
                "keys": ["power_disk_level", "twin_dos_1_level", "twin_dos_2_level"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "whirlpool",
        "brand": "Whirlpool",
        "icon": "mdi:dishwasher",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/whirlpool/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "refill_detergent",
                "shape": "alert",
                "keys": ["whirlpool_tank"],
                "state": "empty",
            },
        ],
    },
    # ── personal ──────────────────────────────────────────────────────────────────────
    {
        "domain": "philips_shaver",
        "brand": "Philips shaver",
        "icon": "mdi:toothbrush-electric",
        "source": "https://raw.githubusercontent.com/mtheli/philips_shaver/main/custom_components/philips_shaver/translations/en.json",
        "verified": {
            "ref": "31bedaa4a5abffe19c4ca63c7d03f2ed2d84097e",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_shaver_head",
                "shape": "percent_low",
                "keys": ["head_remaining"],
                "limit": 10,
            },
            {
                "duty": "replace_cleaning_cartridge",
                "shape": "reading_low",
                "keys": ["cleaning_cycles_remaining"],
                "limit": 3,
            },
        ],
    },
    {
        "domain": "philips_sonicare_ble",
        "brand": "Philips Sonicare (BLE)",
        "icon": "mdi:toothbrush-electric",
        "source": "https://raw.githubusercontent.com/mtheli/philips_sonicare_ble/master/custom_components/philips_sonicare_ble/translations/en.json",
        "verified": {
            "ref": "93c42572ddbd41e55047c1299c3ecffa7e3d206b",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_brush_head",
                "shape": "reading_high",
                "keys": ["brushhead_wear"],
                "limit": 90,
            },
        ],
    },
    # ── pets ──────────────────────────────────────────────────────────────────────────
    {
        "domain": "eheimdigital",
        "brand": "EHEIM Digital (aquarium)",
        "icon": "mdi:paw",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/eheimdigital/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "filter_cleaning",
                "shape": "life_low",
                "keys": ["service_hours"],
                "limit": 24,
            },
        ],
    },
    {
        "domain": "litterrobot",
        "brand": "Litter-Robot",
        "icon": "mdi:paw",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/litterrobot/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "empty_waste_drawer",
                "shape": "reading_high",
                "keys": ["waste_drawer"],
                "limit": 90,
            },
            {
                "duty": "refill_litter",
                "shape": "percent_low",
                "keys": ["litter_level"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "petkit",
        "brand": "PetKit",
        "icon": "mdi:paw",
        "source": "https://raw.githubusercontent.com/Jezza34000/homeassistant_petkit/main/custom_components/petkit/translations/en.json",
        "verified": {
            "ref": "d9885b134d7e524caf073e178decc957613ef58f",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_desiccant",
                "shape": "life_low",
                "keys": ["desiccant_left_days"],
                "limit": 48,
            },
            {
                "duty": "replace_water_filter",
                "shape": "percent_low",
                "keys": ["filter_percent"],
                "limit": 10,
            },
            {
                "duty": "replace_odor_eliminator",
                "shape": "life_low",
                "keys": [
                    "odor_eliminator_n50_left_days",
                    "odor_eliminator_n60_left_days",
                ],
                "limit": 48,
            },
        ],
    },
    {
        "domain": "petlibro",
        "brand": "PETLIBRO",
        "icon": "mdi:paw",
        "source": "https://raw.githubusercontent.com/jjjonesjr33/petlibro/dev/custom_components/petlibro/translations/en.json",
        "verified": {
            "ref": "7ee757fa8f76f628af2e845a301335656e9919a1",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_desiccant",
                "shape": "life_low",
                "keys": ["remaining_desiccant"],
                "limit": 48,
            },
            {
                "duty": "replace_water_filter",
                "shape": "life_low",
                "keys": ["remaining_filter_days"],
                "limit": 48,
            },
            {
                "duty": "clean_appliance",
                "shape": "life_low",
                "keys": ["remaining_cleaning_days"],
                "limit": 48,
            },
        ],
    },
    # ── printers ──────────────────────────────────────────────────────────────────────
    {
        "domain": "brother",
        "brand": "Brother printer",
        "icon": "mdi:printer",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/brother/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ink_or_toner",
                "shape": "percent_low",
                "keys": [
                    "black_ink_remaining",
                    "cyan_ink_remaining",
                    "magenta_ink_remaining",
                    "yellow_ink_remaining",
                ],
                "limit": 10,
            },
            {
                "duty": "replace_maintenance_box",
                "shape": "percent_low",
                "keys": ["ink_capture_box_remaining_life"],
                "limit": 10,
            },
            {
                "duty": "replace_laser_unit",
                "shape": "percent_low",
                "keys": ["laser_remaining_life"],
                "limit": 10,
            },
            {
                "duty": "replace_paper_feed_kit",
                "shape": "percent_low",
                "keys": ["pf_kit_1_remaining_life", "pf_kit_mp_remaining_life"],
                "limit": 10,
            },
            {
                "duty": "replace_toner",
                "shape": "percent_low",
                "keys": [
                    "black_toner_remaining",
                    "cyan_toner_remaining",
                    "magenta_toner_remaining",
                    "yellow_toner_remaining",
                ],
                "limit": 10,
            },
            {
                "duty": "replace_drum_unit",
                "shape": "percent_low",
                "keys": [
                    "drum_remaining_life",
                    "black_drum_remaining_life",
                    "cyan_drum_remaining_life",
                    "magenta_drum_remaining_life",
                    "yellow_drum_remaining_life",
                ],
                "limit": 10,
            },
            {
                "duty": "replace_belt_unit",
                "shape": "percent_low",
                "keys": ["belt_unit_remaining_life"],
                "limit": 10,
            },
            {
                "duty": "replace_fuser",
                "shape": "percent_low",
                "keys": ["fuser_remaining_life"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "hpprinter",
        "brand": "HP printer",
        "icon": "mdi:printer",
        "source": "https://raw.githubusercontent.com/elad-bar/ha-hpprinter/master/custom_components/hpprinter/translations/en.json",
        "verified": {
            "ref": "f534fdae96e645f42f58092e37bef38b04623fef",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_ink_or_toner",
                "shape": "percent_low",
                "keys": ["consumable_percentage_level_remaining"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "syncthru",
        "brand": "Samsung SyncThru printer",
        "icon": "mdi:printer",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/syncthru/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_toner",
                "shape": "percent_low",
                "keys": ["toner_black", "toner_cyan", "toner_magenta", "toner_yellow"],
                "limit": 10,
            },
            {
                "duty": "replace_drum_unit",
                "shape": "percent_low",
                "keys": ["drum_black", "drum_cyan", "drum_magenta", "drum_yellow"],
                "limit": 10,
            },
        ],
    },
    # ── matter and zigbee (air purifier filters) ──────────────────────────────────────
    {
        "domain": "matter",
        "brand": "Matter",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/matter/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["hepa_filter_condition"],
                "limit": 10,
            },
            {
                "duty": "replace_activated_carbon",
                "shape": "percent_low",
                "keys": ["activated_carbon_filter_condition"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "zha",
        "brand": "Zigbee (ZHA)",
        "icon": "mdi:air-filter",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/zha/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "wear_high",
                "keys": ["filter_run_time"],
                "limit": 4320,
            },
        ],
    },
    # ── vacuums ───────────────────────────────────────────────────────────────────────
    {
        "domain": "ecovacs",
        "brand": "Ecovacs",
        "icon": "mdi:robot-vacuum",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/ecovacs/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_main_brush",
                "shape": "percent_low",
                "keys": ["lifespan_brush", "lifespan_main_brush"],
                "limit": 10,
            },
            {
                "duty": "replace_side_brush",
                "shape": "percent_low",
                "keys": ["lifespan_side_brush"],
                "limit": 10,
            },
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["lifespan_filter", "lifespan_hand_filter"],
                "limit": 10,
            },
            {
                "duty": "replace_dust_bag",
                "shape": "percent_low",
                "keys": ["lifespan_dust_bag"],
                "limit": 10,
            },
            {
                "duty": "replace_mop_pads",
                "shape": "percent_low",
                "keys": ["lifespan_round_mop"],
                "limit": 10,
            },
            {
                "duty": "refill_detergent",
                "shape": "percent_low",
                "keys": ["lifespan_cleaning_solution"],
                "limit": 10,
            },
            {
                "duty": "empty_dirty_water_tank",
                "shape": "percent_low",
                "keys": ["lifespan_sewage_box"],
                "limit": 10,
            },
            {
                "duty": "clean_mop_tray",
                "shape": "percent_low",
                "keys": ["lifespan_water_sink"],
                "limit": 10,
            },
            {
                "duty": "replace_air_freshener",
                "shape": "percent_low",
                "keys": ["lifespan_air_freshener"],
                "limit": 10,
            },
            {
                "duty": "replace_uv_lamp",
                "shape": "percent_low",
                "keys": ["lifespan_uv_sanitizer"],
                "limit": 10,
            },
            {
                "duty": "replace_blades",
                "shape": "percent_low",
                "keys": ["lifespan_blade"],
                "limit": 10,
            },
            {
                "duty": "replace_lens_brush",
                "shape": "percent_low",
                "keys": ["lifespan_lens_brush"],
                "limit": 10,
            },
            {
                "duty": "replace_trimmer_brush",
                "shape": "percent_low",
                "keys": ["lifespan_trimmer_brush"],
                "limit": 10,
            },
            {
                "duty": "replace_trimmer_line",
                "shape": "percent_low",
                "keys": ["lifespan_weed_rope"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "roomba",
        "brand": "iRobot Roomba",
        "icon": "mdi:robot-vacuum",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/roomba/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "empty_dustbin",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["bin_full"],
                "state": "on",
            },
        ],
    },
    {
        "domain": "mydolphin_plus",
        "brand": "Maytronics Dolphin",
        "icon": "mdi:robot-vacuum",
        "source": "https://raw.githubusercontent.com/sh00t2kill/dolphin-robot/main/custom_components/mydolphin_plus/translations/en.json",
        "verified": {
            "ref": "50fe915b705e10f0dd74747a542825bdde1c4be5",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "filter_cleaning",
                "shape": "alert",
                "keys": ["filter_status"],
                "state": "full",
            },
        ],
    },
    {
        "domain": "roborock",
        "brand": "Roborock",
        "icon": "mdi:robot-vacuum",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/roborock/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_main_brush",
                "shape": "life_low",
                "keys": ["main_brush_time_left", "brush_remaining"],
                "limit": 24,
            },
            {
                "duty": "replace_side_brush",
                "shape": "life_low",
                "keys": ["side_brush_time_left"],
                "limit": 24,
            },
            {
                "duty": "replace_filter",
                "shape": "life_low",
                "keys": ["filter_time_left"],
                "limit": 24,
            },
            {
                "duty": "clean_sensors",
                "shape": "life_low",
                "keys": ["sensor_time_left"],
                "limit": 24,
            },
            {
                "duty": "replace_mop_pads",
                "shape": "life_low",
                "keys": ["mop_life_time_left"],
                "limit": 24,
            },
            {
                "duty": "replace_dock_strainer",
                "shape": "life_low",
                "keys": ["strainer_time_left"],
                "limit": 24,
            },
            {
                "duty": "replace_maintenance_brush",
                "shape": "life_low",
                "keys": ["cleaning_brush_time_left"],
                "limit": 24,
            },
            {
                "duty": "clean_tub",
                "shape": "wear_high",
                "keys": ["times_after_clean"],
                "limit": 30,
            },
        ],
    },
    {
        "domain": "roomba_plus",
        "brand": "Roomba+ (local MQTT)",
        "icon": "mdi:robot-vacuum",
        "source": "https://raw.githubusercontent.com/johnnyh1975/ha_roomba_plus/main/custom_components/roomba_plus/translations/en.json",
        "verified": {
            "ref": "bbb01502f40b086428c0c1f16bc96d0d07348f97",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_filter",
                "shape": "life_low",
                "keys": ["filter_remaining_hours"],
                "limit": 6,
            },
            {
                "duty": "replace_main_brush",
                "shape": "life_low",
                "keys": ["brush_remaining_hours"],
                "limit": 20,
            },
            {
                "duty": "replace_side_brush",
                "shape": "life_low",
                "keys": ["part_edge_brush"],
                "limit": 15,
            },
            {
                "duty": "replace_dust_bag",
                "shape": "life_low",
                "keys": ["part_dirt_bag"],
                "limit": 3,
            },
        ],
    },
    {
        "domain": "smartthings",
        "brand": "SmartThings",
        "icon": "mdi:robot-vacuum",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/smartthings/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_water_filter",
                "shape": "reading_high",
                "keys": ["water_filter_usage"],
                "limit": 90,
            },
            {
                "duty": "clean_grease_filter",
                "shape": "reading_high",
                "keys": ["hood_filter_usage"],
                "limit": 90,
            },
            {
                "duty": "replace_dust_bag",
                "shape": "alert",
                "platform": "binary_sensor",
                "keys": ["robot_cleaner_dust_bag"],
                "state": "on",
            },
        ],
    },
    {
        "domain": "tplink",
        "brand": "TP-Link Tapo vacuum",
        "icon": "mdi:robot-vacuum",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/tplink/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_main_brush",
                "shape": "life_low",
                "keys": ["main_brush_remaining"],
                "limit": 24,
            },
            {
                "duty": "replace_side_brush",
                "shape": "life_low",
                "keys": ["side_brush_remaining"],
                "limit": 24,
            },
            {
                "duty": "replace_filter",
                "shape": "life_low",
                "keys": ["filter_remaining"],
                "limit": 24,
            },
            {
                "duty": "clean_sensors",
                "shape": "life_low",
                "keys": ["sensor_remaining"],
                "limit": 6,
            },
            {
                "duty": "clean_charging_contacts",
                "shape": "life_low",
                "keys": ["charging_contacts_remaining"],
                "limit": 6,
            },
        ],
    },
    {
        "domain": "tuya",
        "brand": "Tuya",
        "icon": "mdi:robot-vacuum",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/tuya/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_main_brush",
                "shape": "percent_low",
                "keys": ["rolling_brush_life"],
                "limit": 10,
            },
            {
                "duty": "replace_side_brush",
                "shape": "percent_low",
                "keys": ["side_brush_life"],
                "limit": 10,
            },
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["filter_life"],
                "limit": 10,
            },
            {
                "duty": "replace_mop_pads",
                "shape": "percent_low",
                "keys": ["duster_cloth_life"],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "xiaomi_miio",
        "brand": "Xiaomi Miio",
        "icon": "mdi:robot-vacuum",
        "source": "https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/xiaomi_miio/strings.json",
        "verified": {
            "ref": "75c314edf0013bff046106015ab6cfb0b8c6b452",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_main_brush",
                "shape": "life_low",
                "keys": ["main_brush_left"],
                "limit": 24,
            },
            {
                "duty": "replace_side_brush",
                "shape": "life_low",
                "keys": ["side_brush_left"],
                "limit": 24,
            },
            {
                "duty": "replace_filter",
                "shape": "life_low",
                "keys": ["filter_left"],
                "limit": 24,
            },
            {
                "duty": "clean_sensors",
                "shape": "life_low",
                "keys": ["sensor_dirty_left"],
                "limit": 24,
            },
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": [
                    "filter_life_remaining",
                    "dust_filter_life_remaining",
                    "upper_filter_life_remaining",
                ],
                "limit": 10,
            },
        ],
    },
    {
        "domain": "xiaomi_vacuum",
        "brand": "Xiaomi Vacuum (cloud)",
        "icon": "mdi:robot-vacuum",
        "source": "https://raw.githubusercontent.com/roquerodrigo/ha-xiaomi-vacuum/main/custom_components/xiaomi_vacuum/translations/en.json",
        "verified": {
            "ref": "d951d0d567780b8eb506999847d094758502dcf6",
            "date": "2026-10-01",
        },
        "duties": [
            {
                "duty": "replace_main_brush",
                "shape": "percent_low",
                "keys": ["main_brush_life"],
                "limit": 10,
            },
            {
                "duty": "replace_side_brush",
                "shape": "percent_low",
                "keys": ["side_brush_life"],
                "limit": 10,
            },
            {
                "duty": "replace_filter",
                "shape": "percent_low",
                "keys": ["filter_life"],
                "limit": 10,
            },
            {
                "duty": "replace_mop_pads",
                "shape": "percent_low",
                "keys": ["mop_life"],
                "limit": 10,
            },
        ],
    },
]
