"""Pure totals of what a household spent: maintenance and appliance purchases.

Maintenance spend is the sum of the ``cost`` on each completion, by the completion
time ``ts``. It reads the completions on each live task and the completions an
appliance keeps in ``task_history`` for its deleted tasks. A deleted standalone task
keeps no history, so its cost leaves the totals. A skip has no cost.

The purchase total is the sum of the ``cost`` on each appliance. It uses the same
arithmetic as the appliance report, so the 2 numbers always agree.

Imports nothing from Home Assistant. The caller gives the time ``now``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .appliance_report import _num

#: The windows a new install shows, in days.
DEFAULT_WINDOWS: tuple[int, ...] = (30, 60)
#: How many windows a user can set, and the longest one (10 years).
MAX_WINDOWS = 4
MAX_WINDOW_DAYS = 3650


def normalize_windows(value: Any) -> list[int]:
    """Coerce a stored or submitted window list to unique, sorted days.

    Each item is a whole number of days in ``1..MAX_WINDOW_DAYS``. Bad items are
    dropped. The list keeps at most ``MAX_WINDOWS`` items. A value that is not a list,
    or a list with no good item, gives the defaults, so the panel and the sensors
    always have a window to show.
    """
    if not isinstance(value, (list, tuple)):
        return list(DEFAULT_WINDOWS)
    days: set[int] = set()
    for item in value:
        if isinstance(item, bool):
            continue
        try:
            number = int(float(item))
        except (TypeError, ValueError, OverflowError):
            continue
        if 1 <= number <= MAX_WINDOW_DAYS:
            days.add(number)
    return sorted(days)[:MAX_WINDOWS] or list(DEFAULT_WINDOWS)


def _parse_ts(value: Any, tz: Any) -> datetime | None:
    """Parse a stored completion time. A time with no zone gets *tz*.

    A bad value gives ``None``: the log is user-editable and comes in through
    import, so 1 bad entry must not stop the totals.
    """
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def _record(
    entry: dict[str, Any],
    *,
    task_id: Any,
    task_name: Any,
    asset_id: Any,
    archived: bool,
    tz: Any,
) -> dict[str, Any] | None:
    """1 spend record for a completion that has a cost, else ``None``."""
    if entry.get("cost") is None:
        return None
    when = _parse_ts(entry.get("ts"), tz)
    if when is None:
        return None
    return {
        "ts": when.isoformat(),
        "cost": _num(entry.get("cost")),
        "who": entry.get("who"),
        "task_id": task_id,
        "task_name": task_name or "",
        "asset_id": asset_id,
        "archived": archived,
    }


def spend_records(
    tasks: list[dict[str, Any]], assets: list[dict[str, Any]], *, tz: Any
) -> list[dict[str, Any]]:
    """Every completion with a cost, newest first.

    A live task gives ``archived: False``. A deleted task that an appliance keeps
    gives ``archived: True`` and the appliance id. *tz* is the zone for a stored
    time that has none.
    """
    records: list[dict[str, Any]] = []
    for task in tasks:
        for entry in task.get("completions") or []:
            rec = _record(
                entry,
                task_id=task.get("id"),
                task_name=task.get("name"),
                asset_id=None,
                archived=False,
                tz=tz,
            )
            if rec is not None:
                records.append(rec)
    for asset in assets:
        for item in asset.get("task_history") or []:
            for entry in item.get("completions") or []:
                rec = _record(
                    entry,
                    task_id=item.get("task_id"),
                    task_name=item.get("task_name"),
                    asset_id=asset.get("id"),
                    archived=True,
                    tz=tz,
                )
                if rec is not None:
                    records.append(rec)
    records.sort(key=lambda r: datetime.fromisoformat(r["ts"]), reverse=True)
    return records


def _total(records: list[dict[str, Any]]) -> float:
    # Sum the raw costs and round once, so the total cannot drift a cent.
    return round(sum(r["cost"] for r in records), 2)


def spend_summary(
    records: list[dict[str, Any]], *, now: datetime, windows: list[int]
) -> dict[str, Any]:
    """The total and count for each window, and for all time.

    *records* come from :func:`spend_records`, newest first.
    A window of N days holds each record at or after ``now - N days``. A record
    after ``now`` (a clock that moved back) counts in every window. ``since`` is the
    start of the window. ``first`` is the time of the oldest record, or ``None``.
    """
    result: list[dict[str, Any]] = []
    for days in windows:
        start = now - timedelta(days=days)
        inside = [r for r in records if datetime.fromisoformat(r["ts"]) >= start]
        result.append(
            {
                "days": days,
                "total": _total(inside),
                "count": len(inside),
                "since": start.isoformat(),
            }
        )
    # The records are newest first, so the last one is the oldest.
    first = records[-1]["ts"] if records else None
    return {
        "windows": result,
        "all_time": {"total": _total(records), "count": len(records), "first": first},
    }


def purchase_total(assets: list[dict[str, Any]]) -> dict[str, Any]:
    """The sum of the appliance purchase costs, and how many appliances have one."""
    priced = [a for a in assets if a.get("cost") is not None]
    return {
        "total": round(sum(_num(a.get("cost")) for a in priced), 2),
        "count": len(priced),
    }
