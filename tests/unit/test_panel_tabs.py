"""The companion panel tab contract (``panel_tabs.py``).

A tab is JavaScript that runs in the admin panel, so the validation is the security
boundary for what a companion can put there. Each rule has a test that names the
value it refuses and a test that names a value close to it that it accepts, so a
mutant that moves a boundary fails. ``panel_tabs`` imports Home Assistant only for
type annotations, so these tests need no Home Assistant.
"""

from __future__ import annotations

import types
from dataclasses import replace
from typing import Any

import hk_const as const  # type: ignore[import-not-found]
import hk_panel_tabs as pt  # type: ignore[import-not-found]
import pytest


def _tab(**changes: Any) -> Any:
    base = pt.PanelTab(
        companion="home_keeper_library",
        id="library",
        titles={"en": "Library", "de": "Bibliothek"},
        icon="mdi:bookshelf",
        module_url="/home_keeper_library_static/library-tab.js?v=abc",
        element="home-keeper-library-tab",
    )
    return replace(base, **changes)


def _hass() -> Any:
    return types.SimpleNamespace(data={})


def _reason(tab: Any, registered: dict | None = None) -> str:
    with pytest.raises(ValueError) as err:
        pt.validate_panel_tab(tab, registered or {})
    return str(err.value)


# ── defaults and a valid tab ─────────────────────────────────────────────────


def test_the_defaults_are_host_api_1_and_order_100() -> None:
    tab = _tab()
    assert tab.host_api == 1
    assert tab.order == 100


def test_a_valid_tab_comes_back_with_a_read_only_copy_of_its_titles() -> None:
    titles = {"en": " Library ", "de": "Bibliothek"}
    checked = pt.validate_panel_tab(_tab(titles=titles), {})

    titles["en"] = "Changed"
    assert checked.titles == {"en": "Library", "de": "Bibliothek"}
    with pytest.raises(TypeError):
        checked.titles["en"] = "x"  # type: ignore[index]
    assert checked.id == "library"
    assert checked.module_url == "/home_keeper_library_static/library-tab.js?v=abc"


def test_validate_refuses_an_object_that_is_not_a_panel_tab() -> None:
    assert "PanelTab" in _reason({"id": "library"})


# ── companion ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("companion", ["", "Home_Keeper", "my-lib", "a" * 101, 5])
def test_companion_must_be_a_domain(companion: Any) -> None:
    assert "companion" in _reason(_tab(companion=companion))


def test_companion_accepts_a_long_domain_at_the_limit() -> None:
    assert pt.validate_panel_tab(_tab(companion="a" * 100), {}).companion == "a" * 100


# ── id ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tab_id",
    ["l", "Library", "1lib", "-lib", "lib_tab", "lib/tab", "a" * 32, "", 7, "lib tab"],
)
def test_id_must_match_the_pattern(tab_id: Any) -> None:
    assert "id must match" in _reason(_tab(id=tab_id))


@pytest.mark.parametrize("tab_id", ["ab", "a" * 31, "book-shelf-2"])
def test_id_accepts_the_pattern_bounds(tab_id: str) -> None:
    assert pt.validate_panel_tab(_tab(id=tab_id), {}).id == tab_id


@pytest.mark.parametrize("tab_id", sorted(pt.RESERVED_TAB_IDS))
def test_id_refuses_a_home_keeper_route(tab_id: str) -> None:
    assert "reserved by Home Keeper" in _reason(_tab(id=tab_id))


def test_reserved_ids_hold_the_routes_and_the_later_pages() -> None:
    assert {"tasks", "appliances", "settings"} == pt.ROUTED_TAB_IDS
    assert {"apps", "more", "companions", "search", "help"} <= pt.FUTURE_TAB_IDS
    assert {"dashboard", "overview"} <= pt.FUTURE_TAB_IDS
    assert {"profiles", "notifications", "history", "calendar"} <= pt.FUTURE_TAB_IDS
    assert len(pt.FUTURE_TAB_IDS) == 11
    assert pt.RESERVED_TAB_IDS == pt.ROUTED_TAB_IDS | pt.FUTURE_TAB_IDS
    assert "library" not in pt.RESERVED_TAB_IDS


def test_id_refuses_an_id_that_is_registered() -> None:
    other = pt.validate_panel_tab(_tab(element="home-keeper-other"), {})
    assert "already registered" in _reason(_tab(), {"library": other})


# ── element ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "element",
    ["library-tab", "home-keeper-", "Home-Keeper-lib", "home-keeper-lib_tab", "", 3],
)
def test_element_must_have_the_home_keeper_prefix(element: Any) -> None:
    assert "element must match" in _reason(_tab(element=element))


@pytest.mark.parametrize(
    "element", ["home-keeper-panel", "home-keeper-card", "home-keeper-card-editor"]
)
def test_element_refuses_a_home_keeper_element(element: str) -> None:
    assert "Home Keeper element" in _reason(_tab(element=element))


def test_element_refuses_an_element_that_another_tab_uses() -> None:
    other = pt.validate_panel_tab(_tab(id="other"), {})
    assert "element" in _reason(_tab(), {"other": other})


# ── module_url ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "",
        None,
        "https://evil.example/tab.js",
        "javascript:alert(1)",
        "//evil.example/tab.js",
        "relative/tab.js",
        "/static\\tab.js",
        "/static/../secret.js",
        "/static/%2e%2e/secret.js",
        "/%2Fevil.example/tab.js",
        "/static/ tab.js",
        "/static/tab.js\n",
        "/static/\x7ftab.js",
        "/" + "a" * 500,
    ],
)
def test_module_url_refuses_a_path_that_is_not_safe(url: Any) -> None:
    reason = _reason(_tab(module_url=url))
    assert "module_url" in reason


def test_module_url_refusal_names_the_rule() -> None:
    assert "single '/'" in _reason(_tab(module_url="//evil.example/x.js"))
    assert "backslash" in _reason(_tab(module_url="/a\\b.js"))
    assert "'..'" in _reason(_tab(module_url="/a/../b.js"))
    assert "control" in _reason(_tab(module_url="/a b.js"))
    assert "500" in _reason(_tab(module_url="/" + "a" * 500))
    assert "non-empty" in _reason(_tab(module_url=""))


@pytest.mark.parametrize(
    "url",
    [
        "/home_keeper_library_static/library-tab.js",
        "/a.js?v=1&next=../x",
        "/a/..b/c.js",
        "/a/b..js#frag",
        "/" + "a" * 499,
    ],
)
def test_module_url_accepts_a_same_origin_path(url: str) -> None:
    assert pt.validate_panel_tab(_tab(module_url=url), {}).module_url == url


# ── titles ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "titles",
    [
        {},
        {"de": "Bibliothek"},
        {"en": ""},
        {"en": "   "},
        {"en": 5},
        {"en": "x" * 51},
        {"en": "Library", "english": "Library"},
        {"en": "Library", 3: "x"},
        ["en", "Library"],
    ],
)
def test_titles_must_have_a_valid_en_title(titles: Any) -> None:
    assert "titles" in _reason(_tab(titles=titles))


def test_titles_accepts_regional_codes_and_the_length_limit() -> None:
    titles = {"en": "x" * 50, "pt-BR": "Biblioteca", "zh-Hans": "图书馆", "nb_NO": "B"}
    checked = pt.validate_panel_tab(_tab(titles=titles), {})
    assert checked.titles == titles


def _many_titles(extra: int) -> dict[str, str]:
    codes = [f"x{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(extra)]
    return {"en": "Library", **dict.fromkeys(codes, "t")}


def test_titles_refuses_more_than_the_language_limit() -> None:
    assert "at most 50" in _reason(_tab(titles=_many_titles(50)))


def test_titles_accepts_the_language_limit() -> None:
    titles = _many_titles(49)
    assert len(titles) == 50
    assert pt.validate_panel_tab(_tab(titles=titles), {}).titles["en"] == "Library"


# ── icon, host_api, order ────────────────────────────────────────────────────


@pytest.mark.parametrize("icon", ["", None, "mdi:" + "a" * 97, "mdi:book shelf", 4])
def test_icon_must_be_a_short_string(icon: Any) -> None:
    assert "icon" in _reason(_tab(icon=icon))


def test_icon_accepts_the_length_limit() -> None:
    icon = "mdi:" + "a" * 96
    assert pt.validate_panel_tab(_tab(icon=icon), {}).icon == icon


@pytest.mark.parametrize("host_api", [0, -1, True, "1", 1.0, None])
def test_host_api_must_be_an_integer_of_1_or_more(host_api: Any) -> None:
    assert "host_api" in _reason(_tab(host_api=host_api))


def test_host_api_accepts_a_newer_version() -> None:
    assert pt.validate_panel_tab(_tab(host_api=3), {}).host_api == 3


@pytest.mark.parametrize("order", [True, "1", 1.5, None])
def test_order_must_be_an_integer(order: Any) -> None:
    assert "order" in _reason(_tab(order=order))


@pytest.mark.parametrize("order", [-5, 0, 1000])
def test_order_accepts_any_integer(order: int) -> None:
    assert pt.validate_panel_tab(_tab(order=order), {}).order == order


# ── titles for a language ────────────────────────────────────────────────────


_TITLES = {"en": "Library", "de": "Bibliothek", "pt-BR": "Biblioteca", "pt": "Livros"}


@pytest.mark.parametrize(
    ("language", "title"),
    [
        ("de", "Bibliothek"),
        ("DE", "Bibliothek"),
        ("de-AT", "Bibliothek"),
        ("pt-BR", "Biblioteca"),
        ("pt_br", "Biblioteca"),
        ("pt-PT", "Livros"),
        ("fr", "Library"),
        ("", "Library"),
        (None, "Library"),
        ("en-GB", "Library"),
    ],
)
def test_resolve_title_falls_back_to_the_base_language_then_en(
    language: str | None, title: str
) -> None:
    assert pt.resolve_title(_TITLES, language) == title


def test_resolve_title_reads_a_title_stored_with_an_underscore() -> None:
    assert (
        pt.resolve_title({"en": "Library", "nb_NO": "Bibliotek"}, "nb-NO")
        == "Bibliotek"
    )


# ── the projection the websocket command sends ───────────────────────────────


def test_project_sorts_by_order_then_title_then_id() -> None:
    tabs = [
        _tab(id="zeta", titles={"en": "Same"}, order=100),
        _tab(id="alpha", titles={"en": "Same"}, order=100),
        _tab(id="books", titles={"en": "books"}, order=100),
        _tab(id="first", titles={"en": "Zebra"}, order=10),
        _tab(id="late", titles={"en": "Apple"}, order=200),
    ]
    rows = pt.project_panel_tabs(tabs, "en")
    assert [r["id"] for r in rows] == ["first", "books", "alpha", "zeta", "late"]


def test_project_sends_every_field_with_the_title_for_the_language() -> None:
    row = pt.project_panel_tabs([_tab(host_api=2, order=7)], "de")[0]
    assert row == {
        "id": "library",
        "companion": "home_keeper_library",
        "title": "Bibliothek",
        "icon": "mdi:bookshelf",
        "module_url": "/home_keeper_library_static/library-tab.js?v=abc",
        "element": "home-keeper-library-tab",
        "host_api": 2,
        "order": 7,
    }


# ── the registry ─────────────────────────────────────────────────────────────


def test_register_adds_the_tab_and_unregister_removes_it() -> None:
    hass = _hass()
    unregister = pt.async_register_panel_tab(hass, _tab())
    assert [r["id"] for r in pt.async_list_panel_tabs(hass, "en")] == ["library"]
    assert isinstance(hass.data[const.DATA_PANEL_TABS], pt.PanelTabRegistry)

    unregister()
    assert pt.async_list_panel_tabs(hass, "en") == []


def test_unregister_is_idempotent_and_leaves_a_new_registration() -> None:
    hass = _hass()
    first = pt.async_register_panel_tab(hass, _tab())
    first()
    second = pt.async_register_panel_tab(hass, _tab(titles={"en": "New"}))
    first()
    first()
    assert [r["title"] for r in pt.async_list_panel_tabs(hass, "en")] == ["New"]
    second()
    second()
    assert pt.async_list_panel_tabs(hass, "en") == []


def test_register_refuses_a_second_tab_with_the_same_id() -> None:
    hass = _hass()
    pt.async_register_panel_tab(hass, _tab())
    with pytest.raises(ValueError, match="already registered"):
        pt.async_register_panel_tab(hass, _tab(element="home-keeper-other"))
    assert len(pt.async_list_panel_tabs(hass, "en")) == 1


def test_register_refuses_a_tab_that_is_not_valid_and_stores_nothing() -> None:
    hass = _hass()
    with pytest.raises(ValueError):
        pt.async_register_panel_tab(hass, _tab(module_url="https://x/y.js"))
    assert pt.async_list_panel_tabs(hass, "en") == []


def test_register_holds_at_most_the_limit() -> None:
    registry = pt.PanelTabRegistry()
    for n in range(const.MAX_PANEL_TABS):
        registry.register(_tab(id=f"tab-{n}", element=f"home-keeper-tab-{n}"))
    assert len(registry.tabs()) == const.MAX_PANEL_TABS
    with pytest.raises(ValueError, match=str(const.MAX_PANEL_TABS)):
        registry.register(_tab(id="one-more", element="home-keeper-one-more"))
    assert len(registry.tabs()) == const.MAX_PANEL_TABS


def test_tabs_keep_the_registration_order() -> None:
    registry = pt.PanelTabRegistry()
    registry.register(_tab(id="bbb", element="home-keeper-b"))
    registry.register(_tab(id="aaa", element="home-keeper-a"))
    assert [t.id for t in registry.tabs()] == ["bbb", "aaa"]


def test_the_registry_is_made_once_per_hass() -> None:
    hass = _hass()
    assert pt.async_get_registry(hass) is pt.async_get_registry(hass)
    hass.data[const.DATA_PANEL_TABS] = "not a registry"
    assert isinstance(pt.async_get_registry(hass), pt.PanelTabRegistry)


def test_clear_removes_every_tab() -> None:
    hass = _hass()
    pt.async_register_panel_tab(hass, _tab())
    pt.async_register_panel_tab(hass, _tab(id="other", element="home-keeper-other"))
    pt.async_clear_panel_tabs(hass)
    assert pt.async_list_panel_tabs(hass, "en") == []


def test_clear_with_no_registry_makes_none() -> None:
    hass = _hass()
    pt.async_clear_panel_tabs(hass)
    assert const.DATA_PANEL_TABS not in hass.data


def test_the_register_companion_service_takes_no_tab() -> None:
    """The service is open to any user with service access, so it must drop a tab."""
    vol = pytest.importorskip("voluptuous")
    pytest.importorskip("homeassistant")
    import importlib.util
    import sys
    from pathlib import Path

    module = sys.modules.get("hk.companions")
    if module is None or not hasattr(module, "REGISTER_COMPANION_SCHEMA"):
        path = Path(pt.__file__).with_name("companions.py")
        spec = importlib.util.spec_from_file_location("hk.companions", str(path))
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["hk.companions"] = module
        spec.loader.exec_module(module)
    out = module.REGISTER_COMPANION_SCHEMA(
        {
            "domain": "acme",
            "name": "Acme",
            "panel_tab": {"id": "acme", "module_url": "/x.js"},
            "module_url": "/x.js",
        }
    )
    assert out == {"domain": "acme", "name": "Acme"}
    assert vol is not None


# ── exact reasons, and the edges between 2 rules ─────────────────────────────


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"module_url": ""}, "module_url must be a non-empty string"),
        ({"module_url": "x.js"}, "module_url must start with a single '/'"),
        (
            {"module_url": "//evil.example/x.js"},
            "module_url must start with a single '/'",
        ),
        (
            {"module_url": "/%2Fevil.example/x.js"},
            "module_url must start with a single '/'",
        ),
        (
            {"module_url": "/a b.js"},
            "module_url must not contain a space or a control character",
        ),
        ({"module_url": "/a\\b.js"}, "module_url must not contain a backslash"),
        ({"module_url": "/a/../b.js"}, "module_url must not contain a '..' segment"),
        ({"titles": ["en"]}, "titles must be a mapping of language code to title"),
        ({"titles": {"de": "Bibliothek"}}, "titles must have a non-empty 'en' title"),
        ({"companion": "My-Lib"}, "companion must be an integration domain"),
        ({"icon": "mdi:book shelf"}, "icon must not contain a space"),
        ({"host_api": 0}, "host_api must be an integer of 1 or more"),
        ({"order": "1"}, "order must be an integer"),
    ],
)
def test_each_rule_gives_its_own_reason(changes: dict, reason: str) -> None:
    assert _reason(_tab(**changes)) == reason


def test_the_reason_for_an_object_that_is_not_a_tab() -> None:
    assert _reason("library") == "tab must be a PanelTab"


@pytest.mark.parametrize(
    "url",
    [
        "/a%5Cb.js",  # a backslash only after percent decoding
        "/a.js?x=\\y",  # a backslash only in the query
        "//evil.example/a.js",  # urlsplit reads this as a host, so it is checked first
    ],
)
def test_module_url_refuses_a_backslash_or_host_anywhere(url: str) -> None:
    with pytest.raises(ValueError):
        pt.validate_panel_tab(_tab(module_url=url), {})


@pytest.mark.parametrize("url", ["/a!b.js", "/a.js#/../#x", "/a.js#x?/../y"])
def test_module_url_reads_only_the_path_before_the_query_and_fragment(url: str) -> None:
    assert pt.validate_panel_tab(_tab(module_url=url), {}).module_url == url


def test_resolve_title_tries_the_first_subtag_as_the_base() -> None:
    titles = {"en": "Library", "zh": "A", "zh-hans": "B"}
    assert pt.resolve_title(titles, "zh-hans-cn") == "A"
    assert pt.resolve_title(titles, "zh-Hans") == "B"


def test_resolve_title_with_no_language_is_the_en_title() -> None:
    assert pt.resolve_title({"en": "Library", "xxxx": "Odd"}, None) == "Library"


def test_list_uses_the_language_it_gets() -> None:
    hass = _hass()
    pt.async_register_panel_tab(hass, _tab())
    assert pt.async_list_panel_tabs(hass, "de")[0]["title"] == "Bibliothek"
