"""Integration test: the dashboard card is registered as a Lovelace resource (#228).

Home Keeper used to hand its card bundle to the frontend with
``frontend.add_extra_js_url`` alone. That only ever reaches a browser as a
``<script type="module">`` tag baked into the app-shell HTML — and Home Assistant's
own service worker serves dashboard navigations ``StaleWhileRevalidate``, so a shell
cached before the integration was installed has no such tag and
``home-keeper-card`` is never defined. #228 is what that looks like:
"Configuration error: Custom element doesn't exist: home-keeper-card", fixed by a
cache-bypassing reload and back on the next normal one.

A Lovelace **resource** is immune, because the frontend fetches the resource list
over the websocket on every dashboard load. That is why the reporter's HACS cards
worked on the very same stale shell. These assertions pin the registration itself;
``tests/e2e/tests/card-registration.spec.ts`` pins the behaviour it buys.
"""

import time

from conftest import HA_URL
from ha_registry import ws_command, ws_send

CARD_FILENAME = "home-keeper-card.js"
# Where panel.py mounts the built bundles. The resource must point *here* — a copy
# under `/local` would not be served by the integration.
CARD_PATH = f"/home_keeper_panel/{CARD_FILENAME}"


def _card_resources(ha) -> list[dict]:
    """Every Lovelace resource pointing at the Home Keeper card bundle."""
    return [
        r
        for r in ws_command(ha, "lovelace/resources")
        if r.get("url", "").partition("?")[0] == CARD_PATH
    ]


def _await_card_resources(ha, timeout: int = 30) -> list[dict]:
    """Poll for the resource: card.py writes it from an ``async_when_setup`` task,
    deliberately off the config-entry setup path, so it can land just after setup."""
    deadline = time.monotonic() + timeout
    while True:
        found = _card_resources(ha)
        if found or time.monotonic() > deadline:
            return found
        time.sleep(1)


def test_the_card_bundle_is_registered_as_a_lovelace_resource(ha):
    # The whole point of #228: the card reaches the browser through the resource
    # list, not through whatever HTML the service worker happened to cache.
    assert _await_card_resources(ha), (
        "no Lovelace resource for the card bundle — the dashboard card only loads "
        "from a freshly-fetched app shell, which is issue #228"
    )


def test_exactly_one_card_resource_is_registered(ha):
    # Registration runs on every config-entry setup, and the `?v=` token changes
    # whenever the bundle is rebuilt. Neither may leave a second entry behind.
    found = _await_card_resources(ha)
    assert len(found) == 1, f"expected a single card resource, got {found}"


def test_the_card_resource_is_a_module_with_a_cache_busting_token(ha):
    resource = _await_card_resources(ha)[0]
    # `js` is the legacy non-module type; it would load the bundle in a way that
    # never defines the element.
    assert resource["type"] == "module"
    # The `?v=` content hash is what makes a rebuilt bundle a fresh URL, so an
    # upgraded install stops serving the previous card out of the browser cache.
    token = resource["url"].partition("?")[2]
    assert token.startswith("v="), (
        f"card resource has no cache-busting token: {resource['url']}"
    )
    assert token.removeprefix("v="), "card resource has an empty cache-busting token"


def test_the_card_resource_survives_a_config_entry_reload(ha):
    # A reload must neither drop the row nor add a second one. Reloads are routine
    # in a live install (an options change is one), so a create-without-checking
    # would grow the resource list every time, and each extra row is another copy of
    # the bundle the browser fetches on every dashboard load.
    before = _await_card_resources(ha)
    assert len(before) == 1

    token = ha.headers["Authorization"].split(" ", 1)[1]
    entries = ws_send(token, {"type": "config_entries/get", "domain": "home_keeper"})
    assert entries.get("success"), entries
    entry_id = entries["result"][0]["entry_id"]

    reload = ha.post(f"{HA_URL}/api/config/config_entries/entry/{entry_id}/reload")
    reload.raise_for_status()

    # The reload is synchronous, so registration has already re-run by the time the
    # POST returns. Hold the invariant for a few seconds anyway: a duplicate would be
    # written by a task racing just behind it, and asserting once could miss that.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        after = _card_resources(ha)
        assert len(after) == 1, f"a reload duplicated the card resource: {after}"
        assert after[0]["url"] == before[0]["url"]
        time.sleep(1)
