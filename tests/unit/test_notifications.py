"""Unit tests for the pure notification (delivery) helpers."""

from datetime import datetime, timedelta, timezone

import hk_notifications as n

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def task(tid, name, next_due, **extra):
    base = {
        "id": tid,
        "name": name,
        "next_due": next_due.isoformat() if next_due else None,
    }
    base.update(extra)
    return base


# ── action encode / decode ──────────────────────────────────────────────────


def test_encode_decode_roundtrip():
    a = n.encode_action(n.ACTION_SNOOZE, "task123", "notif456")
    assert n.decode_action(a) == (n.ACTION_SNOOZE, "task123", "notif456")


def test_decode_rejects_foreign_and_malformed():
    assert n.decode_action(None) is None
    assert n.decode_action("") is None
    assert n.decode_action("OTHER_APP::complete::t::x") is None
    assert n.decode_action("home_keeper::complete::t") is None  # too few parts
    assert n.decode_action("home_keeper::bogus::t::x") is None  # unknown verb
    assert n.decode_action("home_keeper::complete::::x") is None  # empty task id


# ── notification normalization ───────────────────────────────────────────────


def test_normalize_notification_defaults_and_id():
    notif = n.normalize_notification({"name": "Me", "profile_id": "p1"})
    assert notif["name"] == "Me"
    assert notif["id"]  # generated
    assert notif["profile_id"] == "p1"
    assert notif["actions"] == n.DEFAULT_ACTIONS
    assert notif["style"] == n.STYLE_WALK
    assert notif["snooze_hours"] == n.DEFAULT_SNOOZE_HOURS
    assert notif["auto"] == {"overdue": False, "due_soon": False}


def test_normalize_notification_missing_profile_is_none():
    assert n.normalize_notification({"name": "x"})["profile_id"] is None


def test_normalize_notification_clamps_actions_and_dedupes():
    notif = n.normalize_notification(
        {"id": "x", "actions": ["skip", "bogus", "complete", "skip"]}
    )
    assert notif["actions"] == ["skip", "complete"]
    assert notif["id"] == "x"


def test_normalize_notification_bad_snooze_falls_back():
    assert n.normalize_notification({"snooze_hours": "nope"})["snooze_hours"] == 24
    assert n.normalize_notification({"snooze_hours": 0})["snooze_hours"] == 24
    assert n.normalize_notification({"snooze_hours": 6})["snooze_hours"] == 6


def test_split_targets_partitions_by_prefix():
    accepted, rejected = n.split_targets(
        ["mobile_app_phone", "smtp_family", "mobile_app_tablet", "telegram"]
    )
    assert accepted == ["mobile_app_phone", "mobile_app_tablet"]
    assert rejected == ["smtp_family", "telegram"]


def test_split_targets_on_junk_input():
    # A bare string, None, and non-string members all normalize to "nothing valid"
    # rather than raising into the send loop.
    assert n.split_targets(None) == ([], [])
    assert n.split_targets("mobile_app_phone") == ([], [])
    assert n.split_targets(["mobile_app_phone", None, ""]) == (["mobile_app_phone"], [])


def test_split_targets_allows_the_in_instance_sink():
    # `persistent_notification` is the one non-companion target that never leaves the
    # instance, so it is allowlisted alongside the mobile_app_* services.
    accepted, rejected = n.split_targets(["persistent_notification", "smtp_family"])
    assert accepted == ["persistent_notification"]
    assert rejected == ["smtp_family"]
    assert n.is_allowed_target("persistent_notification")
    assert not n.is_allowed_target("persistent_notification_extra")


def test_split_targets_rejects_a_lookalike_prefix():
    # The check is a prefix, not a substring: a service that merely *contains* the
    # token is a different service and must not slip through.
    accepted, rejected = n.split_targets(["notify_mobile_app_phone", "MOBILE_APP_x"])
    assert accepted == []
    assert rejected == ["notify_mobile_app_phone", "MOBILE_APP_x"]


def test_normalize_notification_drops_unsupported_targets(caplog):
    # The confused-deputy fix: a stored notification cannot route Home-Keeper-authored
    # text through an admin's SMTP/Telegram service just because something wrote that
    # name into the options blob.
    notif = n.normalize_notification(
        {"name": "Me", "targets": ["mobile_app_phone", "smtp_family", "telegram"]}
    )
    assert notif["targets"] == ["mobile_app_phone"]
    # The warning has to be actionable on its own: which targets were dropped (as a
    # readable list) and what would have been accepted instead.
    assert "Home Keeper dropped notify target(s)" in caplog.text
    assert "smtp_family, telegram" in caplog.text
    assert n.TARGET_PREFIX in caplog.text
    assert n.TARGET_PERSISTENT in caplog.text


def test_normalize_notification_keeps_quiet_when_every_target_is_valid(caplog):
    # No warning on the ordinary path — an alarm that cries wolf gets filtered out.
    with_valid = n.normalize_notification({"targets": ["mobile_app_phone"]})
    assert with_valid["targets"] == ["mobile_app_phone"]
    assert "dropped notify target" not in caplog.text


def test_normalize_notification_snooze_of_one_hour_is_kept():
    # 1 is the documented floor (services.yaml's selector minimum), not a value to
    # round up: the guard rejects what is *below* it.
    assert n.normalize_notification({"snooze_hours": 1})["snooze_hours"] == 1


def test_normalize_notification_keeps_a_known_style():
    # A stored style must survive normalization; only an unknown one falls back.
    digest = n.normalize_notification({"style": n.STYLE_DIGEST})
    assert digest["style"] == n.STYLE_DIGEST
    unknown = n.normalize_notification({"style": "carrier-pigeon"})
    assert unknown["style"] == n.STYLE_WALK


def test_normalize_notification_default_name():
    # The fallback is user-visible (it labels the notification in Settings), so it is
    # a specific string, not just "something truthy".
    assert n.normalize_notification({})["name"] == "Notification"
    assert n.normalize_notification({"name": "Kitchen"})["name"] == "Kitchen"


def test_normalize_notification_auto_triggers_round_trip():
    # Both auto triggers are read independently and default off. A notification that
    # silently lost its "overdue" flag would simply stop firing.
    both = n.normalize_notification({"auto": {"overdue": True, "due_soon": True}})
    assert both["auto"] == {"overdue": True, "due_soon": True}
    one = n.normalize_notification({"auto": {"overdue": True}})
    assert one["auto"] == {"overdue": True, "due_soon": False}
    assert n.normalize_notification({})["auto"] == {"overdue": False, "due_soon": False}


def test_normalize_notifications_filters_each_entry():
    notifs = n.normalize_notifications(
        [{"targets": ["smtp_family"]}, {"targets": ["mobile_app_phone"]}]
    )
    assert [notif["targets"] for notif in notifs] == [[], ["mobile_app_phone"]]


def test_resolve_notification_by_id_then_name():
    notifs = [n.normalize_notification({"id": "a", "name": "Me"})]
    assert n.resolve_notification(notifs, "a")["name"] == "Me"
    assert n.resolve_notification(notifs, "Me")["id"] == "a"
    assert n.resolve_notification(notifs, "nope") is None
    assert n.resolve_notification(notifs, None) is None


# ── payload building ────────────────────────────────────────────────────────


def test_build_notification_walk_actions_and_tag():
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification(
        {
            "id": "n1",
            "name": "Me",
            "profile_id": "p1",
            "actions": ["complete", "snooze", "open"],
            "snooze_hours": 6,
        }
    )
    t = task("t1", "Furnace filter", dt(2026, 6, 10))
    payload = n.build_notification(t, notification=notif, now=now)
    assert payload["title"] == "Furnace filter"
    assert "Overdue by 3 days" in payload["message"]
    assert payload["data"]["tag"] == "home_keeper_n1"
    actions = payload["data"]["actions"]
    assert [a["title"] for a in actions] == ["Mark done", "Snooze 6h", "Open"]
    assert actions[0]["action"] == "home_keeper::complete::t1::n1"
    assert actions[2]["uri"] == "/home-keeper/tasks/t1"


def test_overdue_phrase_singular_and_due_now():
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "p", "actions": ["complete"]})
    one = n.build_notification(
        task("t", "X", dt(2026, 6, 12, 12)), notification=notif, now=now
    )
    assert "Overdue by 1 day." in one["message"]
    same = n.build_notification(
        task("t", "X", dt(2026, 6, 13, 12)), notification=notif, now=now
    )
    assert same["message"] == "Due now."


def test_build_digest_lists_and_truncates():
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "p", "style": "digest"})
    q = [task(str(i), f"Task {i}", dt(2026, 6, 1)) for i in range(7)]
    payload = n.build_digest(q, notification=notif, now=now)
    assert payload["title"] == "7 tasks due"
    assert "…and 2 more" in payload["message"]
    assert payload["data"]["tag"] == "home_keeper_p"


def test_build_all_clear_default_english():
    notif = n.normalize_notification({"id": "p"})
    payload = n.build_all_clear(notif)
    assert payload["title"] == "All caught up"
    assert payload["message"] == "No tasks due right now. 🎉"
    assert payload["data"]["tag"] == "home_keeper_p"


# ── translated payload text (#150) ──────────────────────────────────────────


def test_action_titles_translate_by_lang():
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification(
        {
            "id": "n1",
            "actions": ["complete", "snooze", "skip", "open"],
            "snooze_hours": 6,
        }
    )
    t = task("t1", "Furnace filter", dt(2026, 6, 10))
    payload = n.build_notification(t, notification=notif, now=now, lang="es")
    titles = [a["title"] for a in payload["data"]["actions"]]
    assert titles == ["Marcar como hecho", "Posponer 6 h", "Omitir", "Abrir"]


def test_overdue_phrase_translates_and_pluralizes():
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "p", "actions": ["complete"]})
    one = n.build_notification(
        task("t", "X", dt(2026, 6, 12, 12)), notification=notif, now=now, lang="es"
    )
    assert one["message"] == "Vencida hace 1 día."
    many = n.build_notification(
        task("t", "X", dt(2026, 6, 10, 12)), notification=notif, now=now, lang="es"
    )
    assert many["message"] == "Vencida hace 3 días."


def test_digest_and_all_clear_translate():
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "p", "style": "digest"})
    q = [task("t", "X", dt(2026, 6, 1))]
    payload = n.build_digest(q, notification=notif, now=now, lang="es")
    assert payload["title"] == "1 tarea pendiente"
    clear = n.build_all_clear(notif, lang="es")
    assert clear["title"] == "Todo al día"


def test_unknown_language_falls_back_to_english():
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "p", "actions": ["complete"]})
    payload = n.build_notification(
        task("t", "X", dt(2026, 6, 13, 12)),
        notification=notif,
        now=now,
        lang="xx-not-real",
    )
    assert payload["message"] == "Due now."
    assert payload["data"]["actions"][0]["title"] == "Mark done"


def test_plural_category_boundaries_match_cldr():
    # Polish: one / few (2-4) / many (5+, 11-14, ...) — a real 3-way plural split,
    # distinct from the English one/other binary.
    assert n._tn("pl", "digest_title", 1, count=1) == "1 zadanie do zrobienia"
    assert n._tn("pl", "digest_title", 2, count=2) == "2 zadania do zrobienia"
    assert n._tn("pl", "digest_title", 5, count=5) == "5 zadań do zrobienia"
    assert n._tn("pl", "digest_title", 12, count=12) == "12 zadań do zrobienia"
    assert n._tn("pl", "digest_title", 22, count=22) == "22 zadania do zrobienia"
