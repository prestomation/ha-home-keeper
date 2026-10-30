"""Which notify services the panel's "Send to" picker offers (issue #521).

``available_targets`` feeds ``notify_targets`` in ``home_keeper/get_options``. The
stored-target allowlist accepts ``mobile_app_*`` services and
``persistent_notification``, so the picker must offer the same set. It once offered
only ``mobile_app_*``, and a user with no phone could not choose
``persistent_notification``.
"""

from __future__ import annotations

import sys
import types

from notifier_harness import load_notifier

notifier = load_notifier()
notifications = sys.modules["hk.notifications"]


def _hass(*notify_services: str):
    """A ``hass`` whose registry holds *notify_services* under ``notify``."""
    services = {"notify": {name: object() for name in notify_services}}
    return types.SimpleNamespace(
        services=types.SimpleNamespace(async_services=lambda: services)
    )


def test_offers_persistent_notification_when_registered():
    hass = _hass("persistent_notification", "smtp_family")
    assert notifier.available_targets(hass) == ["persistent_notification"]


def test_lists_mobile_apps_then_persistent_in_sorted_order():
    hass = _hass("persistent_notification", "mobile_app_tablet", "mobile_app_phone")
    assert notifier.available_targets(hass) == [
        "mobile_app_phone",
        "mobile_app_tablet",
        "persistent_notification",
    ]


def test_omits_persistent_notification_when_service_is_missing():
    hass = _hass("mobile_app_phone")
    assert notifier.available_targets(hass) == ["mobile_app_phone"]


def test_offers_no_target_when_nothing_is_allowed():
    assert notifier.available_targets(_hass("smtp_family", "telegram")) == []
    assert notifier.available_targets(_hass()) == []


def test_every_offered_target_is_an_allowed_target():
    hass = _hass("persistent_notification", "mobile_app_phone", "smtp_family")
    for target in notifier.available_targets(hass):
        assert notifications.is_allowed_target(target)
