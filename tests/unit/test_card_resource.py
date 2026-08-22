"""Unit tests for reconciling the dashboard card's Lovelace resource.

Home Keeper ships its card bundle as a Lovelace resource so the frontend fetches
it over the websocket on every dashboard load. That has to survive an upgrade
(the ``?v=`` content hash changes), a restart (nothing should be rewritten), and
an install that already carries a hand-added entry (no duplicates). Deciding
*what* to change is pure, so it is pinned here rather than through a container.

See ``custom_components/home_keeper/card.py`` for the side-effecting half.
"""

import hk_card_resource as card_resource
from hk_card_resource import ResourcePlan

CARD_PATH = "/home_keeper_panel/home-keeper-card.js"
URL = f"{CARD_PATH}?v=abc123def456"
STALE = f"{CARD_PATH}?v=000000000000"

# A resource that isn't ours, of the kind a HACS install is full of. Nothing the
# planner returns may ever name it.
HACS = {
    "id": "hacs1",
    "type": "module",
    "url": "/hacsfiles/mini-graph-card/mini-graph-card-bundle.js?hacstag=123",
}


def _res(res_id, url, res_type="module"):
    return {"id": res_id, "type": res_type, "url": url}


def _plan(existing, desired=URL):
    return card_resource.plan_card_resource(existing, desired)


# ── nothing registered yet ───────────────────────────────────────────────────


def test_an_empty_collection_asks_for_a_create():
    assert _plan([]) == ResourcePlan(create=True, update_id=None, delete_ids=())


def test_a_collection_of_other_peoples_cards_asks_for_a_create():
    # The common case: a HACS-heavy install where ours has never been added.
    assert _plan([HACS]) == ResourcePlan(create=True, update_id=None, delete_ids=())


# ── already registered ───────────────────────────────────────────────────────


def test_an_up_to_date_resource_is_left_alone():
    # A restart must not rewrite .storage/lovelace_resources for nothing.
    assert _plan([HACS, _res("ours", URL)]) == ResourcePlan(
        create=False, update_id=None, delete_ids=()
    )


def test_a_stale_cache_token_is_updated_in_place():
    # The upgrade path: same bundle path, new content hash.
    assert _plan([_res("ours", STALE)]) == ResourcePlan(
        create=False, update_id="ours", delete_ids=()
    )


def test_a_resource_with_no_query_at_all_is_updated_to_the_tokened_url():
    # What a user gets if they added the card by hand, without a ?v=.
    assert _plan(
        [_res("ours", "/home_keeper_panel/home-keeper-card.js")]
    ) == ResourcePlan(create=False, update_id="ours", delete_ids=())


def test_a_resource_registered_with_the_wrong_type_is_repaired():
    # `js` (the legacy non-module type) would load the bundle in a way that never
    # defines the element. Same URL, so only the type tells us it is broken.
    assert _plan([_res("ours", URL, res_type="js")]) == ResourcePlan(
        create=False, update_id="ours", delete_ids=()
    )


# ── duplicates ───────────────────────────────────────────────────────────────


def test_duplicates_are_collapsed_onto_the_first_entry():
    existing = [_res("first", STALE), HACS, _res("second", URL), _res("third", URL)]
    # The first is the survivor and needs the new token; the other two go.
    assert _plan(existing) == ResourcePlan(
        create=False, update_id="first", delete_ids=("second", "third")
    )


def test_a_duplicate_of_an_already_correct_entry_is_still_removed():
    # The survivor needs no write, but the collection still has to end up with one.
    assert _plan([_res("keep", URL), _res("dupe", URL)]) == ResourcePlan(
        create=False, update_id=None, delete_ids=("dupe",)
    )


# ── matching is by path, not by string ───────────────────────────────────────


def test_a_copy_of_the_bundle_served_from_elsewhere_is_not_ours():
    # Someone who copied the file into `www/` owns that entry; we neither adopt
    # nor delete it — we just add our own, canonical one.
    strays = [_res("local", "/local/home-keeper-card.js")]
    assert _plan(strays) == ResourcePlan(create=True, update_id=None, delete_ids=())


def test_a_resource_without_a_url_is_ignored():
    # Defensive: the collection is user-writable storage, so don't assume shape.
    assert _plan([{"id": "broken", "type": "module"}]) == ResourcePlan(
        create=True, update_id=None, delete_ids=()
    )


def test_an_absolute_url_for_the_same_bundle_is_ours():
    # What a user gets if they typed the resource in with their full HA address.
    # Left unrecognised it would be joined by a second, relative row.
    absolute = "http://homeassistant.local:8123/home_keeper_panel/home-keeper-card.js"
    assert _plan([_res("typed", absolute)]) == ResourcePlan(
        create=False, update_id="typed", delete_ids=()
    )


# ── the payload, and the ids removal needs ───────────────────────────────────


def test_the_write_payload_names_the_type_res_type_not_type():
    # Lovelace's create/update schema takes `res_type` and renames it to `type` on
    # the way in. Writing `type` is rejected by the schema; reading `res_type` back
    # off a stored item finds nothing. Two halves of the same trap.
    assert card_resource.resource_payload(URL) == {"res_type": "module", "url": URL}


def test_matching_ids_finds_every_copy_of_the_bundle_whatever_its_token():
    existing = [
        HACS,
        _res("a", URL),
        _res("b", STALE),
        _res("c", "/local/home-keeper-card.js"),
    ]
    assert card_resource.matching_ids(existing, CARD_PATH) == ("a", "b")


def test_matching_ids_is_empty_when_nothing_serves_the_bundle():
    assert card_resource.matching_ids([HACS], CARD_PATH) == ()
