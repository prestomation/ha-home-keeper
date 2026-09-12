"""Pure logic for the wear-part → maintenance-task reconciliation.

A wear part with a ``replace_interval`` yields a floating maintenance task attached
to the asset's device (so it reuses the existing to-do/calendar/per-task entities).
The task is keyed by ``source = {"part": {asset_id, part_id}}`` so the reconciler
exclusively owns it.

This module imports nothing from Home Assistant: it is a pure transformation over
plain dicts (assets, tasks) that :class:`store.HomeKeeperStore` wraps with
persistence. Keeping it pure lets the create/anchor/heal/orphan branches be
unit-tested directly (see ``tests/unit/test_reconcile.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import Any

from . import models, recurrence
from .assets import (
    part_action,
    part_carried_uses,
    part_counts_uses,
    part_is_low,
    part_replace_backstop,
    part_use_target,
    part_wants_buy_task,
    use_retention_cap,
)
from .const import (
    APPLIANCE_FALLBACK_NAMES,
    BUY_TASK_NAME_TEMPLATES,
    DEFAULT_LANGUAGE,
    PART_ACTION_REPLACE,
    PART_ROLE_REPLACE,
    PART_ROLE_USE,
    PART_WEAR,
    REC_FLOATING,
    REC_ONE_OFF,
    REC_TRIGGERED,
    REC_USE,
    TASK_SOURCE_BUY,
    TASK_SOURCE_PART,
    USE_TASK_NAME_TEMPLATES,
    WEAR_TASK_NAME_TEMPLATES,
    resolve_action_task_naming,
)

# English defaults so the pure reconciler is usable (and unit-testable) without a
# caller resolving the locale; ``store.reconcile_part_tasks`` passes the strings
# resolved from ``hass.config.language`` (see const.resolve_wear_task_naming).
_DEFAULT_NAME_TEMPLATE = WEAR_TASK_NAME_TEMPLATES[DEFAULT_LANGUAGE]
_DEFAULT_BUY_NAME_TEMPLATE = BUY_TASK_NAME_TEMPLATES[DEFAULT_LANGUAGE]
_DEFAULT_APPLIANCE_FALLBACK = APPLIANCE_FALLBACK_NAMES[DEFAULT_LANGUAGE]
_DEFAULT_USE_NAME_TEMPLATE = USE_TASK_NAME_TEMPLATES[DEFAULT_LANGUAGE]


def part_source(task: dict[str, Any]) -> dict[str, Any] | None:
    """Return a task's ``{asset_id, part_id}`` part provenance, or None.

    Covers both reconciler-derived tasks (auto-generated from a wear part's
    ``replace_interval``) and tasks a user *manually linked* to a consumable — both
    carry ``source = {"part": {"asset_id", "part_id", ...}}`` so completion consumes
    one spare from the part's stock. A manual link additionally carries
    ``"manual": True`` inside the part dict; use :func:`is_manual_part_link` to tell
    them apart where ownership matters (the reconciler must not own manual links).
    """
    source = task.get("source")
    if isinstance(source, dict) and isinstance(source.get(TASK_SOURCE_PART), dict):
        part = source[TASK_SOURCE_PART]
        # Require the identifying keys before treating this as a part source. A
        # malformed reserved shape (e.g. a caller passing ``source={"part": {...}}``
        # without asset_id/part_id) must not reach the bracket accesses in the
        # reconciler — otherwise it raises KeyError inside async_setup_entry and the
        # entry fails to set up on every restart until storage is hand-edited.
        if "asset_id" in part and "part_id" in part:
            return part
    return None


def is_manual_part_link(task: dict[str, Any]) -> bool:
    """True when a task's part link was set by the user, not the reconciler.

    The reconciler exclusively owns the wear-part tasks it generates (it creates,
    updates, and *deletes* them as parts change). A manual link reuses the same
    ``source.part`` shape so it consumes stock on completion, but must be invisible
    to the reconciler — otherwise the next reconcile pass would delete it as an
    "orphan" (its part has no ``replace_interval``). The ``manual`` flag is the
    discriminator that keeps the two apart with no storage migration: existing
    derived tasks lack it and stay reconciler-owned.
    """
    src = part_source(task)
    return bool(src and src.get("manual"))


def buy_source(task: dict[str, Any]) -> dict[str, Any] | None:
    """Return a buy task's ``{asset_id, part_id}`` provenance, or None.

    A buy task carries ``source = {"buy": {"asset_id", "part_id"}}`` and is owned
    exclusively by :func:`reconcile_buy_tasks`. Both identifying keys are required
    before treating the reserved shape as a real buy source (mirrors
    :func:`part_source`'s crash-safety guard).
    """
    source = task.get("source")
    if isinstance(source, dict) and isinstance(source.get(TASK_SOURCE_BUY), dict):
        buy = source[TASK_SOURCE_BUY]
        if "asset_id" in buy and "part_id" in buy:
            return buy
    return None


def part_role(task: dict[str, Any]) -> str:
    """Which half of a wear part a derived task is: ``use`` or ``replace``.

    An **absent** role reads as ``replace``. That is the whole migration story for
    counted wear items: every derived task written before they existed lacks the key
    and keeps its identity, so the reconciler recognizes it, updates it, and never
    orphans it as a stranger.
    """
    src = part_source(task)
    if src is None:
        return PART_ROLE_REPLACE
    role = src.get("role")
    return PART_ROLE_USE if role == PART_ROLE_USE else PART_ROLE_REPLACE


def is_use_task(task: dict[str, Any]) -> bool:
    """True when *task* is the use half of a counted wear item.

    Read at the store's completion chokepoint, where it is what keeps a use from
    consuming a spare and stamping ``last_replaced``. Checks the recurrence type as
    well as the role, so a malformed source cannot turn an ordinary replacement task
    into a silent no-op on stock.
    """
    return task.get("recurrence_type") == REC_USE and part_role(task) == PART_ROLE_USE


def _parse_ts(value: Any) -> datetime | None:
    """Parse a stored ISO timestamp, tolerating the malformed (returns ``None``).

    Same forgiving contract as :func:`qualify_iso`: a completion log is user-editable
    through the history dialog and travels through import, so one bad entry must not
    take the whole count down with it.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed


def _sortable(value: Any) -> tuple[int, float]:
    """A total order over completion timestamps, unparseable ones sorting oldest.

    A history that has seen a timezone change holds mixed offsets, so entries are
    compared as instants rather than as strings. The leading flag keeps a malformed
    entry at the bottom instead of raising, which is what makes the trim below drop it
    first — the right outcome for a row nothing can read.
    """
    parsed = _parse_ts(value)
    if parsed is None:
        return (0, 0.0)
    if parsed.tzinfo is None:
        return (1, parsed.replace(tzinfo=UTC).timestamp())
    return (1, parsed.timestamp())


def cycle_start(replace_task: dict[str, Any]) -> str | None:
    """When the current count cycle started, or ``None`` before it has ever started.

    The later of 2 instants: the replacement task's ``last_completed``, and its most
    recent skip. A completion is the obvious one — the part was replaced, so the next
    count starts from zero.

    A skip has to count for the same reason. ``recurrence.skip_occurrence`` leaves
    ``last_completed`` alone by contract and sets ``next_due`` to None, which is the
    exact state :func:`settle_use_tasks` arms from — so without the skip here the
    task re-arms on the next coordinator tick and fires a fresh
    ``home_keeper_task_triggered``. Skip on a counted wear item was a no-op that
    bounced straight back. It is the same failure ``store.skip_task`` resets a usage
    meter for (#268), and the same answer: a skip means "not this cycle", so it
    starts the next one.

    An entry that cannot be parsed is ignored rather than treated as the epoch, so
    one bad row in a user-edited history does not restart the count.
    """
    best: str | None = None
    best_key = (0, 0.0)
    candidates = [replace_task.get("last_completed")]
    candidates += [entry.get("ts") for entry in replace_task.get("skips") or []]
    for value in candidates:
        if not value:
            continue
        key = _sortable(value)
        if key[0] and key > best_key:
            best, best_key = str(value), key
    return best


def uses_since_replacement(
    use_task: dict[str, Any], replace_task: dict[str, Any]
) -> int:
    """How many uses have been recorded since the current cycle started.

    The count *is* the use task's completion log, filtered to the entries later than
    :func:`cycle_start`. There is no stored counter, and so nothing to keep in sync:
    completing or skipping the replacement task moves the marker forward and the next
    count starts from zero by construction.

    A replacement task that has never been completed or skipped counts every entry,
    which is right for a part in its first cycle.
    """
    completions = use_task.get("completions") or []
    since = cycle_start(replace_task)
    if since is None:
        return len(completions)
    marker = _sortable(since)
    return sum(1 for entry in completions if _sortable(entry.get("ts")) > marker)


def counted_uses(
    use_task: dict[str, Any],
    replace_task: dict[str, Any],
    part: dict[str, Any],
) -> int:
    """The figure every surface shows: the log since the cycle started, plus any carry.

    :func:`uses_since_replacement` answers for the log alone and stays that way, because
    :func:`trim_use_completions` protects the live *window* and the carry is not in it —
    routing the carry through the trim would inflate what it keeps for entries that do
    not exist.

    The carry applies only while :func:`cycle_start` is ``None``, which is exactly the
    state a replacement task minted by :func:`reconcile_part_tasks` is in. So an import
    restores the count, and the first completion or skip of the replacement half retires
    the carry by itself. There is deliberately no reset: a reset is a write path, and a
    write path is a thing that can go out of step with the log it is meant to track.
    """
    counted = uses_since_replacement(use_task, replace_task)
    if cycle_start(replace_task) is not None:
        return counted
    return counted + part_carried_uses(part)


def replacement_backstop_due(
    part: dict[str, Any],
    replace_task: dict[str, Any],
    *,
    tz: tzinfo | None,
) -> datetime | None:
    """When a counted wear item's time backstop comes due, or ``None`` if it has none.

    "Every 25 wears, **or** every 12 months, whichever comes first." The backstop
    measures from the same instant the count does — :func:`cycle_start` — so one
    completion or skip resets both halves and they can never disagree about which
    cycle they are in. While the cycle has never started it falls back to the part's
    recorded ``last_replaced`` and then to the task's ``created``, which is the ladder
    ``sensor_tasks.backstop_due`` already walks for a usage task.
    """
    backstop = part_replace_backstop(part)
    if backstop is None:
        return None
    raw = (
        cycle_start(replace_task)
        or qualify_iso(part.get("last_replaced"), tz)
        or replace_task.get("created")
    )
    anchor = _parse_ts(raw)
    if anchor is None:
        return None
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=tz) if tz is not None else anchor.astimezone()
    return recurrence.add_interval(
        anchor, int(backstop["interval"]), str(backstop["unit"])
    )


def replacement_is_due(
    part: dict[str, Any],
    use_task: dict[str, Any],
    replace_task: dict[str, Any],
    *,
    now: datetime,
) -> bool:
    """True when a counted wear item has earned its replacement task.

    Whichever comes first: the count reaching the target, or the optional time
    backstop elapsing. There is deliberately no "both must be met" combinator — a
    usage task offers one because a service interval has a real "no earlier than"
    floor, and a wear item does not.
    """
    target = part_use_target(part)
    if target and counted_uses(use_task, replace_task, part) >= target:
        return True
    due = replacement_backstop_due(part, replace_task, tz=now.tzinfo)
    return due is not None and due <= now


def trim_use_completions(
    use_task: dict[str, Any], replace_task: dict[str, Any], *, cap: int
) -> bool:
    """Trim *use_task*'s completion log to *cap*, protecting the live count.

    Returns ``True`` when entries were dropped. The window the reminder depends on is
    "uses since the last replacement", so an entry inside it is **never** trimmed even
    when it puts the log over the cap: losing one silently lowers the count and the
    replacement task then never comes due, with nothing on any surface to say why.
    Every other entry is history, kept newest-first for the cadence report.
    """
    completions = list(use_task.get("completions") or [])
    protected = uses_since_replacement(use_task, replace_task)
    keep = max(cap, protected)
    if len(completions) <= keep:
        return False
    completions.sort(key=lambda entry: _sortable(entry.get("ts")))
    use_task["completions"] = completions[-keep:]
    return True


def counted_part_pairs(
    assets: dict[str, dict[str, Any]], tasks: dict[str, dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """Every ``(asset, part, use_task, replace_task)`` a counted wear item owns.

    The settle step's one lookup. A part whose pair is incomplete — mid-reconcile, or
    a storage document edited by hand — is skipped rather than half-processed, because
    the count is meaningless without both halves.
    """
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for task in tasks.values():
        src = part_source(task)
        if src and not src.get("manual"):
            by_key[(src["asset_id"], src["part_id"], part_role(task))] = task

    pairs = []
    for asset in assets.values():
        for part in asset.get("parts", []):
            if not part_counts_uses(part):
                continue
            asset_id = asset.get("id")
            part_id = part.get("id")
            if not asset_id or not part_id:
                # A record with no id cannot be the target of a task's source, so
                # there is no pair to find. Skipped rather than looked up as
                # ``(None, ...)``, which can only ever miss.
                continue
            use_task = by_key.get((asset_id, part_id, PART_ROLE_USE))
            replace_task = by_key.get((asset_id, part_id, PART_ROLE_REPLACE))
            if use_task is not None and replace_task is not None:
                pairs.append((asset, part, use_task, replace_task))
    return pairs


def settle_use_tasks(
    assets: dict[str, dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    *,
    now: datetime,
) -> tuple[list[str], bool]:
    """Decide which replacement tasks to arm, and trim the use logs.

    Returns ``(task_ids_to_arm, trimmed)``. Pure: it arms nothing itself, because
    arming fires ``home_keeper_task_triggered`` and that belongs at the store's
    chokepoint. The trim *is* applied here, in place, since it is ordinary data
    hygiene with no event of its own — the caller persists when ``trimmed`` is true.

    A replacement task that is already armed is left alone, so a household that lets
    the count run past the target does not get a fresh event on every tick. A
    **disabled** one is left alone too, matching ``sensor_watcher``, its twin for
    usage tasks: arming it would fire ``home_keeper_task_triggered`` at a device
    trigger nobody asked for, and leave it overdue the moment it is re-enabled.
    """
    to_arm: list[str] = []
    trimmed = False
    for _asset, part, use_task, replace_task in counted_part_pairs(assets, tasks):
        if (
            replace_task.get("next_due") is None
            and replace_task.get("enabled", True)
            and replacement_is_due(part, use_task, replace_task, now=now)
        ):
            to_arm.append(replace_task["id"])
        if trim_use_completions(use_task, replace_task, cap=use_retention_cap(part)):
            trimmed = True
    return to_arm, trimmed


def qualify_iso(value: str | None, tz: tzinfo | None) -> str | None:
    """Parse an ISO date/datetime and return an aware ISO string (or None).

    A part's ``last_replaced`` is a date-only string; the recurrence engine
    compares the derived ``next_due`` against an aware ``now``, so a naive value
    must be qualified to Home Assistant's timezone first.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz) if tz is not None else parsed.astimezone()
    return parsed.isoformat()


def _replace_name_template(
    part: dict[str, Any], name_template: str, language: str | None
) -> str:
    """The ``"<Action> {part} ({asset})"`` template for *part*.

    ``replace`` returns *name_template* verbatim rather than re-resolving it. That is
    what keeps the caller's contract ("pass me the strings") true for the default
    action, and it is why every wear part written before actions existed generates the
    byte-identical name it already had.
    """
    action = part_action(part)
    if action == PART_ACTION_REPLACE:
        return name_template
    return resolve_action_task_naming(action, language)


def reconcile_part_tasks(
    assets: dict[str, dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    *,
    name_template: str = _DEFAULT_NAME_TEMPLATE,
    appliance_fallback: str = _DEFAULT_APPLIANCE_FALLBACK,
    use_name_template: str = _DEFAULT_USE_NAME_TEMPLATE,
    language: str | None = None,
    now: datetime,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Compute the task map derived from wear parts.

    Returns ``(new_tasks, changed)``. ``new_tasks`` is a fresh dict (the input is
    not mutated); ``changed`` is ``True`` when it differs from ``tasks``. Tasks
    without a part source are carried through untouched.

    ``name_template`` (with ``{part}``/``{asset}`` placeholders) and
    ``appliance_fallback`` (substituted for an unnamed appliance) are the localized
    strings for the generated task name; the caller resolves them from
    ``hass.config.language`` (see ``const.resolve_wear_task_naming``). Defaulting to
    English keeps this function pure and independently testable. Because the name is
    recomputed here on every pass, a language change is picked up as ordinary name
    drift — the existing ``before.get("name") != name`` branch rewrites it.

    ``name_template`` covers the ``replace`` action only, which is what every wear part
    used before actions existed. The other 6 actions resolve from *language* through
    ``const.resolve_action_task_naming``, and ``use_name_template`` names the use task
    a counted wear item generates. Both stay parameters rather than a language lookup
    inside, so this function keeps its "pass me the strings" contract.

    **A counted wear item owns 2 tasks**, so the index below is keyed by
    ``(asset_id, part_id, role)`` rather than by the part alone. Keyed by the part, the
    2 tasks collide, the second overwrites the first, and the orphan sweep deletes
    whichever one lost.
    """
    result = dict(tasks)

    desired: dict[tuple[str, str, str], tuple[dict, dict]] = {}
    for asset in assets.values():
        for part in asset.get("parts", []):
            if part.get("type") == PART_WEAR and part.get("replace_interval"):
                desired[(asset["id"], part["id"], PART_ROLE_REPLACE)] = (asset, part)
                if part_counts_uses(part):
                    desired[(asset["id"], part["id"], PART_ROLE_USE)] = (asset, part)

    existing_by_key: dict[tuple[str, str, str], str] = {}
    for tid, task in result.items():
        src = part_source(task)
        # Skip manually-linked tasks: they reuse the part-source shape (to consume
        # stock on completion) but are user-owned, so the reconciler must never
        # update or orphan-delete them.
        if src and not src.get("manual"):
            existing_by_key[(src["asset_id"], src["part_id"], part_role(task))] = tid

    changed = False

    # Remove orphaned part-tasks (the part or its wear cadence went away).
    for key, tid in list(existing_by_key.items()):
        if key not in desired:
            del result[tid]
            existing_by_key.pop(key, None)
            changed = True

    # Create or update the rest.
    for key, (asset, part) in desired.items():
        role = key[2]
        asset_name = asset.get("name") or appliance_fallback
        counted = part_counts_uses(part)
        if role == PART_ROLE_USE:
            # A part may name its use task outright ("Wear rain jacket"); otherwise it
            # gets the localized "Use {asset}". The part is not named either way — the
            # household taps this to record using the *thing*, not the component that
            # wears out.
            name = part.get("use_task_name") or use_name_template.format(
                asset=asset_name
            )
        else:
            name = _replace_name_template(part, name_template, language).format(
                part=part["name"], asset=asset_name
            )
        # The replacement half of a counted wear item is ``triggered``: dormant until
        # the settle step arms it, which is the existing shape for "something else
        # decides when this is due". A time-measured part keeps its floating cadence.
        rec_type = (
            REC_USE
            if role == PART_ROLE_USE
            else (REC_TRIGGERED if counted else REC_FLOATING)
        )
        # A part's last_replaced is a date-only string; qualify it to HA's tz so the
        # derived next_due is timezone-aware. A naive next_due otherwise crashes the
        # next-due sensor, overdue binary_sensor, and the calendar (which compare it
        # against an aware "now").
        anchored = qualify_iso(part.get("last_replaced"), now.tzinfo)
        existing_tid = existing_by_key.get(key)
        if existing_tid is None:
            # ``role`` is written only for a use task. An absent role already reads
            # as ``replace`` (see part_role), so stamping it on the replacement half
            # would put a second shape in storage for a value that never changes
            # meaning — and would rewrite the source of every wear part in the wild
            # for no gain.
            part_link: dict[str, Any] = {
                "asset_id": asset["id"],
                "part_id": part["id"],
            }
            if role == PART_ROLE_USE:
                part_link["role"] = PART_ROLE_USE
            payload: dict[str, Any] = {
                "name": name,
                "recurrence_type": rec_type,
                "device_id": asset.get("device_id"),
                "area_id": asset.get("area_id"),
                "source": {"part": part_link},
            }
            if rec_type == REC_FLOATING:
                payload["interval"] = part["replace_interval"]
                payload["unit"] = part["replace_unit"]
            task = models.build_task(payload, now=now)
            if rec_type == REC_TRIGGERED:
                # ``build_task`` creates a triggered task **armed**: compute_next_due
                # returns ``now`` for it (the re-arm contract). A counted wear item
                # has earned nothing yet, so left alone every one of them would ship
                # overdue the moment the part is saved. Start it dormant, exactly as
                # build_task itself does for a sensor task.
                task["next_due"] = None
            elif rec_type == REC_FLOATING and anchored:
                # Anchor the floating clock to the recorded replacement. With no
                # recorded replacement we leave last_completed unset (build_task's
                # default), so the part reads as due now rather than "assumed fresh" a
                # full interval out: an unknown replacement history is better surfaced
                # now — the user can backdate the replacement or mark it done — than
                # silently hidden for a cycle.
                task["last_completed"] = anchored
                task["next_due"] = recurrence.compute_next_due(
                    task, now=now
                ).isoformat()
            result[task["id"]] = task
            changed = True
        else:
            # Only pass fields that actually changed. Passing interval/unit
            # unconditionally would re-trigger a next_due recompute on every
            # reconcile (setup, any asset edit), needlessly churning the schedule.
            before = result[existing_tid]
            updates: dict[str, Any] = {}
            if before.get("name") != name:
                updates["name"] = name
            if before.get("recurrence_type") != rec_type:
                # The unit was switched between time and uses (or the storage document
                # predates counted wear items). This is a real conversion, not drift:
                # a floating task becomes triggered and vice versa.
                updates["recurrence_type"] = rec_type
            if rec_type == REC_FLOATING:
                if before.get("interval") != part["replace_interval"]:
                    updates["interval"] = part["replace_interval"]
                if before.get("unit") != part["replace_unit"]:
                    updates["unit"] = part["replace_unit"]
            if before.get("device_id") != asset.get("device_id"):
                updates["device_id"] = asset.get("device_id")
            if before.get("area_id") != asset.get("area_id"):
                updates["area_id"] = asset.get("area_id")
            merged = (
                models.merge_update(before, updates, now=now) if updates else before
            )
            if (
                rec_type == REC_TRIGGERED
                and before.get("recurrence_type") != REC_TRIGGERED
            ):
                # Same trap as creation, reached the other way: ``merge_update`` arms a
                # task converted *into* triggered, because a stale schedule date would
                # otherwise read as armed at an arbitrary instant. Switching a part
                # from "every 6 months" to "every 25 wears" has earned nothing, so the
                # replacement task starts the new cycle dormant and the settle step
                # arms it on the first target it actually reaches.
                merged = {**merged, "next_due": None}
            # Heal a legacy timezone-naive last_completed (older builds stored a
            # date-only last_replaced verbatim, yielding a naive next_due that crashed
            # the sensors/calendar). Only re-qualify a naive value — never overwrite a
            # real (already-aware) completion timestamp.
            lc = merged.get("last_completed")
            healed = qualify_iso(lc, now.tzinfo) if lc else None
            if healed and healed != lc:
                merged = dict(merged)
                merged["last_completed"] = healed
                if rec_type == REC_FLOATING:
                    # Only a floating task derives a due date from its last completion.
                    # The other 2 roles are dormant by definition, and recomputing
                    # would raise for a use task and arm a replacement task that has
                    # earned nothing.
                    merged["next_due"] = recurrence.compute_next_due(
                        merged, now=now
                    ).isoformat()
            if merged is not before:
                result[existing_tid] = merged
                changed = True

    # Clear a manual consumable link whose target part no longer exists (the part was
    # removed while the appliance remains). Left dangling, the link silently no-ops on
    # completion — the user would think they're drawing down stock but aren't. The task
    # itself survives as a plain standalone task; only its source is cleared.
    existing_parts = {
        (asset.get("id"), part.get("id"))
        for asset in assets.values()
        for part in asset.get("parts", [])
        if part.get("id")
    }
    for tid, task in list(result.items()):
        src = part_source(task)
        if src is None or not src.get("manual"):
            continue
        if (src["asset_id"], src["part_id"]) not in existing_parts:
            result[tid] = {**task, "source": None}
            changed = True

    return result, changed


def reconcile_buy_tasks(
    assets: dict[str, dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    *,
    name_template: str = _DEFAULT_BUY_NAME_TEMPLATE,
    now: datetime,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Compute the task map with auto-created "buy" tasks synced to low parts.

    Returns ``(new_tasks, changed)``. A buy task is **desired** for every ``(asset,
    part)`` where the part opts in (``part_wants_buy_task``) *and* is currently low
    (``part_is_low``). The task is a one-off ``"Buy {part}"`` reminder attached to the
    asset's device, keyed by ``source = {"buy": {asset_id, part_id}}`` so the
    reconciler exclusively owns it.

    Idempotency is **per low episode**: the existing index counts a buy task for a
    part whether it is open *or already completed*, so completing the reminder does
    not respawn it while the part stays low. The buy task is orphan-removed the moment
    its key leaves the desired set — the part restocked above the threshold, opted
    out, or was deleted — which also ends the episode and re-arms the next one.

    Pure: the input maps are not mutated, and the name is localized by the caller
    (``store.reconcile_buy_tasks`` resolves ``hass.config.language``). Buy tasks are
    never *updated* here (a one-off has no cadence to re-derive); only created and
    removed, so a rename after a language change is picked up as a delete + recreate
    on the next reconcile — acceptable for a transient reminder.
    """
    result = dict(tasks)

    desired: dict[tuple[str, str], tuple[dict, dict]] = {}
    for asset in assets.values():
        for part in asset.get("parts", []):
            if part_wants_buy_task(part) and part_is_low(part):
                desired[(asset["id"], part["id"])] = (asset, part)

    # Index existing buy tasks by their part key — open OR completed — so a completed
    # reminder still "occupies" the episode and blocks a duplicate.
    existing_by_key: dict[tuple[str, str], str] = {}
    for tid, task in result.items():
        src = buy_source(task)
        if src:
            existing_by_key[(src["asset_id"], src["part_id"])] = tid

    changed = False

    # Remove orphaned buy tasks (part restocked / opted out / part or asset gone).
    for key, tid in list(existing_by_key.items()):
        if key not in desired:
            del result[tid]
            existing_by_key.pop(key, None)
            changed = True

    # Create a buy task for each desired key that doesn't already have one.
    for key, (asset, part) in desired.items():
        if key in existing_by_key:
            continue
        task = models.build_task(
            {
                "name": name_template.format(part=part["name"]),
                "recurrence_type": REC_ONE_OFF,
                "device_id": asset.get("device_id"),
                "area_id": asset.get("area_id"),
                "source": {"buy": {"asset_id": asset["id"], "part_id": part["id"]}},
            },
            now=now,
        )
        result[task["id"]] = task
        changed = True

    return result, changed
