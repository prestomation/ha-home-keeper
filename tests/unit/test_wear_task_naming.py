"""Unit tests for the localized wear-part task name tables and resolver.

The reconciler-generated task name (``Replace {part} ({asset})``) is baked into
storage in Home Assistant's configured language. These cover the pure resolution
logic (``const.resolve_wear_task_naming``) and guard the translation tables the way
the frontend/backend i18n parity tests guard their locale files.
"""

import hk_const as const


def test_resolve_exact_language():
    template, fallback = const.resolve_wear_task_naming("pl")
    assert template == "Wymień {part} ({asset})"
    assert fallback == "Urządzenie"


def test_resolve_is_case_insensitive_and_matches_region_forms():
    # Exact region tag (pt-BR) and a case-variant both resolve.
    assert const.resolve_wear_task_naming("pt-BR")[0] == "Trocar {part} ({asset})"
    assert const.resolve_wear_task_naming("PL")[0] == "Wymień {part} ({asset})"


def test_resolve_falls_back_to_base_language():
    # A region we don't ship (de-AT) falls back to its base language (de).
    template, fallback = const.resolve_wear_task_naming("de-AT")
    assert template == "{part} ersetzen ({asset})"
    assert fallback == "Gerät"


def test_resolve_falls_back_to_english_for_unknown_or_none():
    for lang in ("xx", "", None):
        template, fallback = const.resolve_wear_task_naming(lang)
        assert template == "Replace {part} ({asset})"
        assert fallback == "Appliance"


def test_tables_have_identical_language_coverage():
    assert set(const.WEAR_TASK_NAME_TEMPLATES) == set(const.APPLIANCE_FALLBACK_NAMES)
    assert const.DEFAULT_LANGUAGE in const.WEAR_TASK_NAME_TEMPLATES


def test_every_template_has_both_placeholders():
    for lang, template in const.WEAR_TASK_NAME_TEMPLATES.items():
        assert "{part}" in template, lang
        assert "{asset}" in template, lang


def test_no_untranslated_leaks():
    # Every non-English value must actually be translated (mirrors the i18n
    # parity/leak discipline enforced on the panel and backend locale files).
    en_template = const.WEAR_TASK_NAME_TEMPLATES[const.DEFAULT_LANGUAGE]
    en_fallback = const.APPLIANCE_FALLBACK_NAMES[const.DEFAULT_LANGUAGE]
    for lang, template in const.WEAR_TASK_NAME_TEMPLATES.items():
        if lang == const.DEFAULT_LANGUAGE:
            continue
        assert template != en_template, lang
        assert const.APPLIANCE_FALLBACK_NAMES[lang] != en_fallback, lang
