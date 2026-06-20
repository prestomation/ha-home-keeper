"""Pure task-resolution helpers for the Home Keeper voice/intent layer.

This module imports nothing from Home Assistant so it can be unit-tested in
isolation under the synthetic ``hk`` package (see ``tests/conftest.py``), mirroring
``recurrence.py`` and ``models.py``. The HA-facing intent handlers in
``intents.py`` do the registry lookups (area/device names -> ids) and then delegate
the actual fuzzy name resolution and due-task selection to the functions here.

The matcher deliberately prefers asking the user to disambiguate over guessing:
completing the wrong task advances its recurrence, which is a destructive surprise,
so when two tasks are plausible we return them as *candidates* rather than picking
one. See ``tests/unit/test_task_match.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

# Leading filler words an utterance commonly wraps a task name in. Stripped before
# matching so "mark the fridge filter as done" resolves to the task "Replace fridge
# filter" without the article skewing the similarity score.
_ARTICLES = ("the ", "a ", "an ", "my ", "our ", "your ")

# Minimum similarity (0..1) for a fuzzy name match to be considered at all. Below
# this we report "no match" rather than guess. Tuned to accept typos and partial
# names ("furnace filter" -> "Replace furnace filter") while rejecting unrelated
# names; see ``tests/unit/test_task_match.py``.
NAME_MATCH_THRESHOLD = 0.6

# How much better the top candidate must score than a runner-up for it to be treated
# as an unambiguous winner. Anything scoring within this band of the top (and at or
# above the threshold) is collected as a co-candidate and the caller is asked to
# disambiguate, rather than risk completing the wrong task.
DOMINANCE_MARGIN = 0.12


def _normalize(text: str) -> str:
    """Lowercase, trim, and strip leading articles for comparison."""
    text = (text or "").strip().casefold()
    changed = True
    while changed:
        changed = False
        for article in _ARTICLES:
            if text.startswith(article):
                text = text[len(article) :]
                changed = True
    return text.strip()


def _score(query: str, name: str) -> float:
    """Similarity in 0..1 between a spoken *query* and a task *name*."""
    q, n = _normalize(query), _normalize(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    ratio = SequenceMatcher(None, q, n).ratio()
    # SequenceMatcher underweights containment when the lengths differ a lot
    # ("filter" vs "Replace furnace filter"), yet that is exactly how people refer
    # to tasks by a keyword. Floor such matches so they clear the threshold.
    if q in n or n in q:
        ratio = max(ratio, 0.85)
    return ratio


@dataclass
class MatchResult:
    """Outcome of resolving a spoken task name to a stored task.

    Exactly one of three states holds: a single ``task`` (unambiguous match),
    two-or-more ``candidates`` (ambiguous — ask the user), or neither (not found).
    """

    task: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return self.task is not None

    @property
    def ambiguous(self) -> bool:
        return self.task is None and len(self.candidates) > 1

    @property
    def not_found(self) -> bool:
        return self.task is None and not self.candidates


def match_task(
    tasks: Iterable[dict[str, Any]],
    name: str,
    *,
    area_id: str | None = None,
    device_id: str | None = None,
) -> MatchResult:
    """Resolve *name* to one of *tasks*, optionally scoped by area/device.

    *area_id*/*device_id*, when given, are hard filters (the caller has already
    resolved them from spoken area/device names); they narrow the pool before the
    fuzzy name match runs, which is what lets "complete the filter in the kitchen"
    disambiguate two same-named tasks in different areas.
    """
    pool = list(tasks)
    if area_id is not None:
        pool = [t for t in pool if t.get("area_id") == area_id]
    if device_id is not None:
        pool = [t for t in pool if t.get("device_id") == device_id]
    if not pool:
        return MatchResult()

    scored = sorted(
        ((_score(name, t.get("name", "")), t) for t in pool),
        key=lambda st: st[0],
        reverse=True,
    )
    top_score = scored[0][0]
    if top_score < NAME_MATCH_THRESHOLD:
        return MatchResult()

    # An exact (normalized) name wins outright — unless several tasks share it, in
    # which case only the user can say which, so surface them as candidates.
    if top_score == 1.0:
        exact = [t for s, t in scored if s == 1.0]
        if len(exact) == 1:
            return MatchResult(task=exact[0])
        return MatchResult(candidates=exact)

    contenders = [
        t
        for s, t in scored
        if s >= NAME_MATCH_THRESHOLD and top_score - s <= DOMINANCE_MARGIN
    ]
    if len(contenders) == 1:
        return MatchResult(task=contenders[0])
    return MatchResult(candidates=contenders)


def _parse_due(value: Any) -> datetime | None:
    """Parse a stored ISO ``next_due`` string to an aware datetime, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def select_due_tasks(
    tasks: Iterable[dict[str, Any]],
    now: datetime,
    *,
    enabled_only: bool = True,
) -> list[dict[str, Any]]:
    """Return tasks that are currently due or overdue, soonest-due first.

    A task counts as due when its ``next_due`` is set and at or before *now*. A
    dormant triggered task (``next_due`` is None) is never due. Disabled tasks are
    excluded by default. *now* is passed in (not read from the clock) so callers and
    tests stay deterministic.
    """
    due: list[tuple[datetime, dict[str, Any]]] = []
    for task in tasks:
        if enabled_only and not task.get("enabled", True):
            continue
        when = _parse_due(task.get("next_due"))
        if when is None:
            continue
        if when <= now:
            due.append((when, task))
    due.sort(key=lambda wt: wt[0])
    return [task for _, task in due]
