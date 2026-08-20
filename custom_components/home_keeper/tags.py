"""Pure routing and authorization for NFC/RFID tag completion.

A task can carry a ``tag_id`` (a Home Assistant tag) and, optionally,
``require_tag_scan``. This module answers the two questions that follow from that
pairing: which tasks a scanned tag completes, and whether a given completion is
allowed to go through at all. Both are plain dict-in/answer-out functions with no
Home Assistant imports, so the routing table and the authorization rule are
unit-testable without a bus; ``tag_listener.py`` is the thin Home Assistant boundary
that feeds them real scans and ``store.complete_task`` enforces the rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .const import (
    ORIGIN_PROBLEM_SENSOR_SYNC,
    ORIGIN_SENSOR_RECOVER,
    ORIGIN_TAG_SCAN,
)

# The ``origin`` markers that satisfy ``require_tag_scan``. A real scan
# (``ORIGIN_TAG_SCAN``) is the point of the feature; the other two are Home Keeper
# completing the task *itself* — the problem-sensor sync clearing its mirror and a
# ``clear_on_recover`` sensor task clearing when its entity returns to normal. Those
# are not a person clicking Done, so blocking them would strand the task armed
# forever with nobody able to scan it clear. Every human-facing surface (to-do,
# button, notification tap, panel, bare ``complete_task`` service) sends no origin or
# its own, and is rejected.
SCAN_ALLOWED_ORIGINS: frozenset[str] = frozenset(
    {ORIGIN_TAG_SCAN, ORIGIN_SENSOR_RECOVER, ORIGIN_PROBLEM_SENSOR_SYNC}
)


def tasks_for_tag(tasks: Iterable[dict[str, Any]], tag_id: str) -> list[dict[str, Any]]:
    """Return the enabled tasks bound to *tag_id*.

    A tag is many-to-one on purpose: sticking one tag on the coffee machine can
    complete "descale" and "refill beans" in a single scan. Disabled tasks are
    skipped — a disabled task is invisible on every other surface, so a scan must not
    be a back door that completes it.
    """
    return [
        task
        for task in tasks
        if task.get("enabled", True) and task.get("tag_id") == tag_id
    ]


def completion_allowed(task: dict[str, Any], origin: str | None) -> bool:
    """Whether a completion of *task* carrying *origin* may proceed.

    ``require_tag_scan`` turns completion into a physical presence check: the task is
    only completable by scanning its tag, so a completion is allowed only when it
    carries one of :data:`SCAN_ALLOWED_ORIGINS`. A task without the flag is
    completable from anywhere, whatever the origin.
    """
    if not task.get("require_tag_scan"):
        return True
    return origin in SCAN_ALLOWED_ORIGINS
