"""Unit tests for resolving a service call's ``*_id`` field by id or by name.

These cover the contract ``__init__.py``'s service handlers depend on: an id
always wins, an exact name beats a case-folded one, and a name several objects
share is an error rather than a coin flip.
"""

import hk_resolve as r
import pytest


def task(tid, name):
    return {"id": tid, "name": name}


def tasks(*pairs):
    return {tid: task(tid, name) for tid, name in pairs}


# ── ids ─────────────────────────────────────────────────────────────────────────


def test_resolves_an_id_verbatim():
    store = tasks(("a1", "Replace furnace filter"), ("b2", "Descale kettle"))
    assert r.resolve_task_id(store, "b2") == "b2"


def test_an_id_beats_a_name_that_collides_with_it():
    """A task perversely *named* another task's id must not shadow that task."""
    store = tasks(("a1", "b2"), ("b2", "Descale kettle"))
    assert r.resolve_task_id(store, "b2") == "b2"


# ── names ───────────────────────────────────────────────────────────────────────


def test_resolves_an_exact_name():
    store = tasks(("a1", "Replace furnace filter"), ("b2", "Descale kettle"))
    assert r.resolve_task_id(store, "Descale kettle") == "b2"


def test_resolves_a_name_ignoring_case_and_surrounding_space():
    store = tasks(("a1", "Replace furnace filter"))
    assert r.resolve_task_id(store, "  replace FURNACE filter ") == "a1"


def test_an_exact_name_beats_a_case_folded_rival():
    """Two names differing only in case are told apart by typing one exactly."""
    store = tasks(("a1", "Filter"), ("b2", "filter"))
    assert r.resolve_task_id(store, "Filter") == "a1"
    assert r.resolve_task_id(store, "filter") == "b2"


def test_case_folded_rivals_are_ambiguous_when_neither_is_typed_exactly():
    store = tasks(("a1", "Filter"), ("b2", "filter"))
    with pytest.raises(r.AmbiguousName) as err:
        r.resolve_task_id(store, "FILTER")
    assert err.value.ids == ["a1", "b2"]


# ── failure modes ───────────────────────────────────────────────────────────────


def test_a_shared_name_is_ambiguous_and_names_every_candidate():
    store = tasks(("a1", "Change filter"), ("b2", "Change filter"), ("c3", "Other"))
    with pytest.raises(r.AmbiguousName) as err:
        r.resolve_task_id(store, "Change filter")
    assert err.value.ids == ["a1", "b2"]
    assert err.value.key == "Change filter"


def test_ambiguous_ids_are_sorted_regardless_of_store_order():
    store = tasks(("z9", "Change filter"), ("a1", "Change filter"))
    with pytest.raises(r.AmbiguousName) as err:
        r.resolve_task_id(store, "Change filter")
    assert err.value.ids == ["a1", "z9"]


def test_an_unknown_reference_is_not_found():
    store = tasks(("a1", "Replace furnace filter"))
    with pytest.raises(r.NotFound) as err:
        r.resolve_task_id(store, "Wash the dog")
    assert err.value.key == "Wash the dog"


def test_an_empty_store_finds_nothing():
    with pytest.raises(r.NotFound):
        r.resolve_task_id({}, "Anything")


@pytest.mark.parametrize("key", ["", "   "])
def test_a_blank_reference_is_not_found_even_beside_a_blank_name(key):
    """A task with no name must not become the catch-all for an empty field."""
    with pytest.raises(r.NotFound):
        r.resolve_task_id(tasks(("a1", "")), key)


def test_not_found_and_ambiguous_are_both_resolve_errors():
    assert issubclass(r.NotFound, r.ResolveError)
    assert issubclass(r.AmbiguousName, r.ResolveError)


def test_the_error_text_names_what_could_not_be_resolved():
    """A traceback has to say which reference failed, not just that one did."""
    with pytest.raises(r.NotFound) as err:
        r.resolve_task_id({}, "Wash the dog")
    assert "Wash the dog" in str(err.value)


# ── assets ──────────────────────────────────────────────────────────────────────


def test_resolves_an_asset_by_name():
    assets = {"a1": {"id": "a1", "name": "Dishwasher"}}
    assert r.resolve_asset_id(assets, "Dishwasher") == "a1"
    assert r.resolve_asset_id(assets, "a1") == "a1"


def test_an_asset_name_shared_by_two_appliances_is_ambiguous():
    assets = {
        "a1": {"id": "a1", "name": "Dishwasher"},
        "b2": {"id": "b2", "name": "Dishwasher"},
    }
    with pytest.raises(r.AmbiguousName):
        r.resolve_asset_id(assets, "Dishwasher")


# ── parts and documents (scoped to one asset) ───────────────────────────────────


ASSET = {
    "id": "a1",
    "name": "Dishwasher",
    "parts": [
        {"id": "p1", "name": "Rinse aid"},
        {"id": "p2", "name": "Salt"},
    ],
    "documents": [
        {"id": "d1", "name": "Manual"},
        {"id": "d2", "name": "Warranty"},
    ],
}


def test_resolves_a_part_by_name_and_by_id():
    assert r.resolve_part_id(ASSET, "Rinse aid") == "p1"
    assert r.resolve_part_id(ASSET, "p2") == "p2"


def test_resolves_a_document_by_its_name():
    assert r.resolve_document_id(ASSET, "Warranty") == "d2"
    assert r.resolve_document_id(ASSET, "d1") == "d1"


def test_a_part_name_does_not_resolve_against_the_document_list():
    """The two collections are separate namespaces on the same appliance."""
    with pytest.raises(r.NotFound):
        r.resolve_part_id(ASSET, "Manual")
    with pytest.raises(r.NotFound):
        r.resolve_document_id(ASSET, "Rinse aid")


def test_scoping_means_the_same_part_name_on_two_appliances_is_unambiguous():
    other = {"id": "b2", "name": "Washer", "parts": [{"id": "p9", "name": "Rinse aid"}]}
    assert r.resolve_part_id(ASSET, "Rinse aid") == "p1"
    assert r.resolve_part_id(other, "Rinse aid") == "p9"


def test_two_parts_sharing_a_name_on_one_appliance_are_ambiguous():
    asset = {"parts": [{"id": "p1", "name": "Filter"}, {"id": "p2", "name": "Filter"}]}
    with pytest.raises(r.AmbiguousName) as err:
        r.resolve_part_id(asset, "Filter")
    assert err.value.ids == ["p1", "p2"]


@pytest.mark.parametrize("collection", [None, "not a list", []])
def test_a_missing_or_malformed_collection_finds_nothing(collection):
    with pytest.raises(r.NotFound):
        r.resolve_part_id({"parts": collection}, "Filter")


def test_entries_without_an_id_are_skipped():
    """A half-built part must not be resolvable, nor crash the lookup."""
    asset = {"parts": [{"name": "Filter"}, {"id": "p2", "name": "Salt"}]}
    with pytest.raises(r.NotFound):
        r.resolve_part_id(asset, "Filter")
    assert r.resolve_part_id(asset, "Salt") == "p2"


def test_non_mapping_entries_are_skipped():
    asset = {"parts": ["nonsense", {"id": "p2", "name": "Salt"}]}
    assert r.resolve_part_id(asset, "Salt") == "p2"


def test_an_asset_that_is_not_a_mapping_yields_no_entries():
    with pytest.raises(r.NotFound):
        r.resolve_part_id(None, "Filter")


@pytest.mark.parametrize("key", [None, 42, object()])
def test_a_non_string_reference_matches_nothing(key):
    """Not just bad input: a non-string key must not collide with a non-string name.

    Folding both sides through one function that returns a fixed value for
    anything non-string would make exactly that pair match.
    """
    store = {"a1": {"id": "a1", "name": None}, "b2": {"id": "b2", "name": "Real"}}
    with pytest.raises(r.NotFound):
        r.resolve_task_id(store, key)


def test_a_non_string_name_never_matches():
    """Bad stored data must not blow up the case-folded pass."""
    store = {"a1": {"id": "a1", "name": None}, "b2": {"id": "b2", "name": "Real"}}
    with pytest.raises(r.NotFound):
        r.resolve_task_id(store, "Real task")
    assert r.resolve_task_id(store, "real") == "b2"
