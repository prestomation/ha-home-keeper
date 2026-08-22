"""Pure decision logic for the dashboard card's Lovelace resource.

No Home Assistant imports: this is the "what should change" half of ``card.py``'s
resource registration, so it runs in the fast unit lane and is mutation-scored
(``[tool.mutmut] only_mutate`` in pyproject.toml). ``card.py`` owns the "how" —
talking to Lovelace's ``ResourceStorageCollection``.

The asymmetry this module exists to encapsulate: Lovelace's create and update
payloads name the resource type ``res_type``, but
``ResourceStorageCollection._process_create_data`` renames it on the way in, so
*stored* items carry ``type``. Read ``type``; write ``res_type``. Getting that
backwards matches nothing and quietly creates a duplicate on every restart.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

# Lovelace resource type for an ES module bundle. `js` is the legacy non-module
# loader, which would fetch the file without ever defining the custom element.
RESOURCE_TYPE = "module"


def resource_path(url: str) -> str:
    """The path part of a resource URL, without the ``?v=`` cache token.

    Matching on the path is what lets a rebuilt bundle *update* the existing row
    instead of adding a second one beside it. It also means the absolute form a
    user may have typed by hand (``http://homeassistant.local:8123/...``) is
    recognised as the same resource as the relative one we register.

    Ignoring scheme and host is deliberate: someone who hand-registered an absolute
    or proxied URL for *this* bundle wanted the card, so adopting that row and
    rewriting it to the canonical relative URL fixes it for every way they reach
    Home Assistant, rather than leaving a host-pinned entry beside ours. A copy
    served from a *different* path (``/local/home-keeper-card.js``) is somebody
    else's row and is left alone.
    """
    return urlsplit(url).path


@dataclass(frozen=True, slots=True)
class ResourcePlan:
    """What has to change to leave exactly one resource pointing at the card."""

    create: bool = False
    update_id: str | None = None
    delete_ids: tuple[str, ...] = ()


def _serves_bundle(item: Mapping[str, Any], wanted: str) -> bool:
    """True when *item* is a stored resource serving the bundle at *wanted*.

    The collection is user-writable storage, so don't assume the shape: a row
    without a string URL is somebody else's problem, not a match.
    """
    url = item.get("url")
    return isinstance(url, str) and resource_path(url) == wanted


def matching_ids(items: Iterable[Mapping[str, Any]], url: str) -> tuple[str, ...]:
    """Ids of every stored resource serving the card bundle, token ignored.

    What removal uses: it has no desired URL to reconcile against, only the path
    it has to clear.
    """
    wanted = resource_path(url)
    return tuple(str(item["id"]) for item in items if _serves_bundle(item, wanted))


def plan_card_resource(
    items: Iterable[Mapping[str, Any]], desired_url: str
) -> ResourcePlan:
    """Reconcile the stored resources with *desired_url*.

    * nothing matching             -> create
    * one match, url and type good -> no-op (a restart must not rewrite storage)
    * one match, stale url or type -> update it in place, never a second create
    * several matches              -> keep and fix the first, delete the rest
    """
    wanted = resource_path(desired_url)
    matches = [item for item in items if _serves_bundle(item, wanted)]
    if not matches:
        return ResourcePlan(create=True)

    # `keep` matched, so it has a string URL — no fallback needed reading it back.
    keep, *extra = matches
    stale = keep["url"] != desired_url or keep.get("type") != RESOURCE_TYPE
    return ResourcePlan(
        update_id=str(keep["id"]) if stale else None,
        delete_ids=tuple(str(item["id"]) for item in extra),
    )


def resource_payload(url: str) -> dict[str, str]:
    """The create/update body Lovelace expects — ``res_type``, never ``type``."""
    return {"res_type": RESOURCE_TYPE, "url": url}
