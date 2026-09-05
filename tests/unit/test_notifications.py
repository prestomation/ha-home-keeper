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
    a = n.encode_action(n.ACTION_SNOOZE, "task123", "notif456", "2026-06-16T10:00:00")
    assert a == "home_keeper::snooze::task123::notif456::2026-06-16T10:00:00"
    assert n.decode_action(a) == (
        n.ACTION_SNOOZE,
        "task123",
        "notif456",
        "2026-06-16T10:00:00",
    )


def test_decode_accepts_legacy_tokenless_action():
    # A notification delivered before the freshness token existed is still sitting on
    # someone's phone; its buttons must keep routing, with no token to check.
    assert n.decode_action("home_keeper::complete::task123::notif456") == (
        n.ACTION_COMPLETE,
        "task123",
        "notif456",
        None,
    )


def test_decode_keeps_an_offset_bearing_token_intact():
    # An aware ISO-8601 next_due carries '+'/'-' and single ':' but never the '::'
    # separator, so it survives the split verbatim and compares as an exact string.
    token = "2026-06-16T10:00:00+02:00"
    a = n.encode_action(n.ACTION_COMPLETE, "t", "x", token)
    assert n.decode_action(a) == (n.ACTION_COMPLETE, "t", "x", token)


def test_decode_rejects_foreign_and_malformed():
    assert n.decode_action(None) is None
    assert n.decode_action("") is None
    assert n.decode_action("OTHER_APP::complete::t::x") is None
    assert n.decode_action("home_keeper::complete::t") is None  # too few parts
    assert n.decode_action("home_keeper::bogus::t::x") is None  # unknown verb
    assert n.decode_action("home_keeper::complete::::x") is None  # empty task id
    assert n.decode_action("home_keeper::complete::t::") is None  # empty notif id
    assert n.decode_action("home_keeper::complete::t::x::") is None  # empty token
    assert n.decode_action("home_keeper::complete::t::x::d::extra") is None  # 6 parts


# ── freshness token ─────────────────────────────────────────────────────────


def test_due_token_is_the_raw_next_due():
    t = task("t", "T", dt(2026, 6, 16, 10))
    assert n.due_token(t) == "2026-06-16T10:00:00-04:00"


def test_due_token_of_an_undated_task_is_empty():
    assert n.due_token(task("t", "T", None)) == ""
    assert n.due_token({}) == ""


def test_is_current_action_accepts_a_matching_token():
    # The early-tap case from #216: the task is not yet due, but the button still
    # reflects its current schedule, so "Mark done" must act.
    t = task("t", "T", dt(2026, 6, 16, 10))
    assert n.is_current_action(t, n.due_token(t), tokenless_ok=False) is True


def test_is_current_action_rejects_a_moved_task():
    # The task advanced after the button was built (completed/snoozed/skipped
    # elsewhere, or a twin card for the same task was tapped first).
    t = task("t", "T", dt(2026, 6, 16, 10))
    stale = n.due_token(t)
    moved = task("t", "T", dt(2026, 6, 23, 10))
    assert n.is_current_action(moved, stale, tokenless_ok=True) is False


def test_is_current_action_defers_to_the_caller_when_tokenless():
    t = task("t", "T", dt(2026, 6, 16, 10))
    assert n.is_current_action(t, None, tokenless_ok=True) is True
    assert n.is_current_action(t, None, tokenless_ok=False) is False


def test_two_cards_for_one_task_encode_the_same_token():
    # Why one card invalidates the other: the token is keyed on the *task*, not on the
    # notification the tap came from, so independent cards agree on it.
    t = task("t", "T", dt(2026, 6, 16, 10))
    a = n.encode_action(n.ACTION_COMPLETE, t["id"], "notif_a", n.due_token(t))
    b = n.encode_action(n.ACTION_COMPLETE, t["id"], "notif_b", n.due_token(t))
    assert n.decode_action(a)[3] == n.decode_action(b)[3]


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


def test_normalize_notification_defaults_channel_and_urgency():
    notif = n.normalize_notification({"id": "x"})
    assert notif["channel"] == ""
    assert notif["urgency"] == "normal"
    assert n.DEFAULT_URGENCY == "normal"


def test_normalize_notification_strips_the_channel_name():
    # The channel name is echoed straight into the payload and Android creates a
    # channel per distinct string, so " Meds " and "Meds" must not become two.
    assert n.normalize_notification({"channel": "  Meds  "})["channel"] == "Meds"
    assert n.normalize_notification({"channel": None})["channel"] == ""
    assert n.normalize_notification({"channel": 7})["channel"] == "7"


def test_normalize_notification_clamps_an_unknown_urgency():
    # Urgency drives which keys reach the phone, so an unrecognised value has to land
    # on the quiet default rather than pass through and ask iOS for a critical alert.
    for bad in ("URGENT", "max", "", None, 3):
        assert n.normalize_notification({"urgency": bad})["urgency"] == "normal"
    for good in n.URGENCIES:
        assert n.normalize_notification({"urgency": good})["urgency"] == good


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


# ── per-task button sets ────────────────────────────────────────────────────

BLOCKED = {"id": "t", "managed_by": {"completion_blocked": True}}
ALL_VERBS = ["complete", "snooze", "skip", "open"]


def test_is_completion_blocked_reads_the_managed_by_marker():
    assert n.is_completion_blocked(BLOCKED)
    assert not n.is_completion_blocked({"id": "t"})
    assert not n.is_completion_blocked({"id": "t", "managed_by": None})
    assert not n.is_completion_blocked({"id": "t", "managed_by": {}})
    assert not n.is_completion_blocked({"id": "t", "managed_by": {"integration": "x"}})
    assert not n.is_completion_blocked(
        {"id": "t", "managed_by": {"completion_blocked": False}}
    )


def test_is_completion_blocked_ignores_a_non_mapping_managed_by():
    # Hand-written YAML/service payloads reach the store as anything at all.
    assert not n.is_completion_blocked({"id": "t", "managed_by": "completion_blocked"})
    assert not n.is_completion_blocked({"id": "t", "managed_by": ["blocked"]})


def test_actions_for_an_ordinary_task_is_the_configured_set_unchanged():
    task = {"id": "t"}
    assert n.actions_for(task, ALL_VERBS) == ALL_VERBS
    assert n.actions_for(task, ["open"]) == ["open"]
    assert n.actions_for(task, []) == []
    # A copy, so a caller can't mutate the stored notification through it.
    configured = ["complete", "snooze"]
    assert n.actions_for(task, configured) is not configured


def test_actions_for_a_blocked_task_drops_the_verbs_the_store_refuses():
    # Mark done and Skip both assert the problem is dealt with; the store rejects
    # both, and notifier swallows the rejection, so they'd read as dead buttons.
    assert n.actions_for(BLOCKED, ALL_VERBS) == ["snooze", "open"]
    assert n.actions_for(BLOCKED, ["complete", "skip"]) == ["snooze"]


def test_actions_for_a_blocked_task_keeps_the_configured_order():
    assert n.actions_for(BLOCKED, ["open", "snooze"]) == ["open", "snooze"]


def test_actions_for_a_blocked_task_offers_snooze_even_when_unconfigured():
    # A walk advances only on a successful action. Without Snooze, one of these at the
    # head of the queue would re-send forever and never reach the tasks behind it.
    assert n.actions_for(BLOCKED, ["complete", "open"]) == ["snooze", "open"]
    assert n.actions_for(BLOCKED, []) == ["snooze"]


def test_build_notification_offers_only_snooze_and_open_on_a_blocked_task():
    now = dt(2026, 6, 13, 12)
    task = {
        "id": "t1",
        "name": "Sump pump problem",
        "next_due": dt(2026, 6, 12, 12).isoformat(),
        "managed_by": {"completion_blocked": True},
    }
    notif = n.normalize_notification({"id": "n1", "actions": ALL_VERBS})
    payload = n.build_notification(task, notification=notif, now=now, lang="en")
    verbs = [n.decode_action(a["action"])[0] for a in payload["data"]["actions"]]
    assert verbs == ["snooze", "open"]


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
    assert actions[0]["action"] == (
        "home_keeper::complete::t1::n1::2026-06-10T00:00:00-04:00"
    )
    assert actions[2]["uri"] == "/home-keeper/tasks/t1"
    # Every button carries the task's next_due, so a tap on any of them can be checked
    # for freshness — not just "Mark done".
    assert all(a["action"].endswith(f"::{n.due_token(t)}") for a in actions)
    # The companion app stacks a channel's notifications by `group`, so the exact
    # string is a payload contract, not decoration.
    assert payload["data"]["group"] == "home_keeper"


def test_build_notification_falls_back_to_the_product_name_for_a_nameless_task():
    # A task can reach here with a blank name (a contributed task, a bad service
    # call). The phone shows the title verbatim, so an empty one reads as a bug.
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "n1", "actions": ["open"]})
    for name in (None, ""):
        t = {"id": "t1", "name": name, "next_due": dt(2026, 6, 10).isoformat()}
        payload = n.build_notification(t, notification=notif, now=now)
        assert payload["title"] == "Home Keeper"


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


def test_due_soon_holds_to_the_window_boundary():
    # The exact edge, because it is the one that decides which of two phrasings a
    # phone shows. "Due soon" must mean the same span here as it does to the filter
    # that queued the task (`profiles.matches_filter` / `recurrence.is_due_soon`):
    # inclusive at the window, and not one second past it.
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "p", "actions": ["complete"]})

    def phrase(next_due):
        t = task("t", "X", next_due)
        return n.build_notification(t, notification=notif, now=now)["message"]

    assert phrase(now + n.DUE_SOON_WINDOW) == "Due soon."
    assert phrase(now + n.DUE_SOON_WINDOW - timedelta(hours=1)) == "Due soon."
    assert phrase(now + n.DUE_SOON_WINDOW + timedelta(seconds=1)) == "Due in 3 days."


def test_a_task_past_the_window_says_how_far_off_it_is():
    # Before `status: all` existed a notification only ever carried something due, so
    # everything not overdue read "Due soon." — including a task months away. The count
    # is floored, matching the overdue branch: 10.5 days reads as 10, the same way 10.5
    # days late reads as "overdue by 10 days".
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "p", "actions": ["complete"]})

    def phrase(days, hours=0):
        t = task("t", "X", now + timedelta(days=days, hours=hours))
        return n.build_notification(t, notification=notif, now=now)["message"]

    assert phrase(10) == "Due in 10 days."
    assert phrase(10, 12) == "Due in 10 days."
    assert phrase(180) == "Due in 180 days."


def test_due_in_translates_and_pluralizes():
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "p", "actions": ["complete"]})
    t = task("t", "X", now + timedelta(days=10))
    assert (
        n.build_notification(t, notification=notif, now=now, lang="es")["message"]
        != n.build_notification(t, notification=notif, now=now, lang="en")["message"]
    )
    # Polish splits 2-4 from 5+, which is the reason the CLDR categories exist. A
    # `.other`-only table would answer both with the same string.
    few = n.build_notification(
        task("t", "X", now + timedelta(days=4)), notification=notif, now=now, lang="pl"
    )["message"]
    many = n.build_notification(
        task("t", "X", now + timedelta(days=9)), notification=notif, now=now, lang="pl"
    )["message"]
    assert few != many


def test_every_due_phrase_is_localized():
    """All four phrasings honour *lang*, not only the two that count days.

    ``_t`` falls back to English for an unknown language, so a phrase that quietly
    stopped passing *lang* through would still return a real sentence and read as
    working. Only a locale comparison catches it, and "due now" and "due soon" take
    no placeholder, so nothing else in this file was pinning them.
    """
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "p", "actions": ["complete"]})

    def phrase(next_due, lang):
        t = task("t", "X", next_due)
        return n.build_notification(t, notification=notif, now=now, lang=lang)[
            "message"
        ]

    assert phrase(now, "es") == "Vence ahora."
    assert phrase(now + timedelta(days=1), "es") == "Vence pronto."
    assert phrase(now, "de") == "Jetzt fällig."
    assert phrase(now + timedelta(days=1), "de") == "Bald fällig."


def test_build_notification_threads_the_due_soon_window_through():
    """The window reaches the phrase, rather than the phrase reading its own default.

    Both are ``DUE_SOON_WINDOW`` in every real call, so a dropped argument changes
    nothing until someone passes a different one — which is exactly when it would
    matter, and exactly when nobody would be looking.
    """
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification({"id": "p", "actions": ["complete"]})
    t = task("t", "X", now + timedelta(days=5))

    assert (
        n.build_notification(t, notification=notif, now=now)["message"]
        == "Due in 5 days."
    )
    # A window wide enough to swallow the same task calls it due soon instead.
    wide = n.build_notification(
        t, notification=notif, now=now, window=timedelta(days=30)
    )
    assert wide["message"] == "Due soon."


def test_sends_when_empty_only_for_the_all_clear_value():
    # The one branch that decides whether an empty queue still delivers.
    assert n.sends_when_empty(n.WHEN_EMPTY_ALL_CLEAR) is True
    assert n.sends_when_empty(n.WHEN_EMPTY_SKIP) is False
    assert n.sends_when_empty(None) is False
    assert n.sends_when_empty("") is False
    assert n.sends_when_empty("ALL_CLEAR") is False


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


# ── channel & urgency (#255) ────────────────────────────────────────────────
#
# One stored (channel, urgency) pair, two payload vocabularies. Every assertion here
# compares the *whole* data dict rather than checking a key is present: a payload key
# with the wrong value is a notification that lands silently, or one that overrides Do
# Not Disturb when it should not, and "has an importance" cannot tell those apart.


def test_payload_data_unconfigured_is_what_it_always_was():
    # The regression that matters most. Every notification saved before these fields
    # existed normalizes to no channel at `normal` urgency, and must keep sending the
    # exact payload it sent then — nothing extra for the phone to interpret.
    notif = n.normalize_notification({"id": "n1"})
    assert n.payload_data(notif) == {"tag": "home_keeper_n1", "group": "home_keeper"}
    assert n.payload_data(notif, actions=[]) == {
        "tag": "home_keeper_n1",
        "group": "home_keeper",
        "actions": [],
    }


def test_payload_data_quiet_asks_both_platforms_to_stay_quiet():
    notif = n.normalize_notification({"id": "n1", "urgency": "quiet"})
    assert n.payload_data(notif) == {
        "tag": "home_keeper_n1",
        "group": "home_keeper",
        "importance": "low",
        "push": {"interruption-level": "passive"},
    }


def test_payload_data_high_wakes_the_phone():
    # `ttl: 0` + `priority: high` is the companion app's documented way past Android's
    # Doze batching. Without them a "high" reminder can arrive an hour late, which is
    # indistinguishable to the user from the feature not working.
    notif = n.normalize_notification({"id": "n1", "urgency": "high"})
    assert n.payload_data(notif) == {
        "tag": "home_keeper_n1",
        "group": "home_keeper",
        "importance": "high",
        "ttl": 0,
        "priority": "high",
        "push": {"interruption-level": "time-sensitive"},
    }


def test_payload_data_critical_carries_the_ios_critical_sound():
    notif = n.normalize_notification({"id": "n1", "urgency": "critical"})
    assert n.payload_data(notif) == {
        "tag": "home_keeper_n1",
        "group": "home_keeper",
        "importance": "max",
        "ttl": 0,
        "priority": "high",
        "push": {
            "interruption-level": "critical",
            "sound": {"name": "default", "critical": 1, "volume": 1.0},
        },
    }


def test_payload_data_critical_sound_is_a_copy_per_payload():
    # The sound table is module state. Handing the same dict to two payloads would let
    # anything downstream that edits one silently edit every future critical alert.
    notif = n.normalize_notification({"id": "n1", "urgency": "critical"})
    first = n.payload_data(notif)["push"]["sound"]
    first["volume"] = 0.1
    assert n.payload_data(notif)["push"]["sound"]["volume"] == 1.0


def test_payload_data_channel_reaches_both_platforms():
    # Android names a notification channel; iOS has none, so the same string threads
    # the reminders instead. One field in the panel, two keys on the wire.
    notif = n.normalize_notification({"id": "n1", "channel": "Medication"})
    assert n.payload_data(notif) == {
        "tag": "home_keeper_n1",
        "group": "home_keeper",
        "channel": "Medication",
        "push": {"thread-id": "Medication"},
    }


def test_payload_data_combines_channel_and_urgency():
    notif = n.normalize_notification(
        {"id": "n1", "channel": "Medication", "urgency": "critical"}
    )
    assert n.payload_data(notif) == {
        "tag": "home_keeper_n1",
        "group": "home_keeper",
        "channel": "Medication",
        "importance": "max",
        "ttl": 0,
        "priority": "high",
        "push": {
            "thread-id": "Medication",
            "interruption-level": "critical",
            "sound": {"name": "default", "critical": 1, "volume": 1.0},
        },
    }


def test_payload_data_keeps_one_group_across_channels():
    # The channel decides how a reminder behaves; the group decides where it sits in
    # the shade. Home Keeper's notifications stack together either way, so `group` is
    # a fixed contract that a channel must not quietly redefine.
    for channel in ("", "Medication", "Chores"):
        notif = n.normalize_notification({"id": "n1", "channel": channel})
        assert n.payload_data(notif)["group"] == "home_keeper"


def test_every_urgency_is_reachable_and_distinct():
    # A typo in either mapping table that collapsed two urgencies onto one payload
    # would leave the panel offering a choice that does nothing.
    notif = {"id": "n1", "channel": "C"}
    seen = [
        n.payload_data(n.normalize_notification({**notif, "urgency": u}))
        for u in n.URGENCIES
    ]
    assert len(seen) == 4
    for i, a in enumerate(seen):
        for b in seen[i + 1 :]:
            assert a != b


def test_all_three_builders_carry_channel_and_urgency():
    # `payload_data` is shared, but a builder that stopped calling it would still pass
    # its own tag/group assertions above. Pin every send path to the real thing.
    now = dt(2026, 6, 13, 12)
    notif = n.normalize_notification(
        {"id": "n1", "channel": "Chores", "urgency": "high", "actions": ["open"]}
    )
    t = task("t1", "Furnace filter", dt(2026, 6, 10))
    payloads = [
        n.build_notification(t, notification=notif, now=now),
        n.build_digest([t], notification=notif, now=now),
        n.build_all_clear(notif),
    ]
    for payload in payloads:
        assert payload["data"]["channel"] == "Chores"
        assert payload["data"]["importance"] == "high"
        assert payload["data"]["push"]["thread-id"] == "Chores"
        assert payload["data"]["push"]["interruption-level"] == "time-sensitive"


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
    actions = payload["data"]["actions"]
    titles = [a["title"] for a in actions]
    assert titles == ["Marcar como hecho", "Posponer 6 h", "Omitir", "Abrir"]
    # The full button set, so this is where every verb's routing key is pinned: the
    # companion app echoes back whatever sits under "action", so a mistyped key on any
    # one of them ships a button that does nothing.
    assert [a["action"] for a in actions] == [
        n.encode_action(verb, "t1", "n1", n.due_token(t))
        for verb in ("complete", "snooze", "skip", "open")
    ]


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
