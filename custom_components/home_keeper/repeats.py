"""Pure guard that ignores the same physical input when it comes again soon.

A person taps a phone button 2 times, or an NFC reader reads 1 tap 2 times. Home
Assistant then fires 2 events, and each event would act. A recurring task then
records 2 completions, and a Skip drops 2 occurrences. ``tag_listener.py`` and
``notifier.py`` keep one :class:`RepeatGuard` each for the Home Assistant run, and
ask it about each event before they act.

The guard has no Home Assistant import. The caller gives the clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# How long the same input counts as a repeat. A double tap or a second read of
# 1 tag comes within 1 or 2 seconds. A person who scans a tag again to do the
# task again waits longer than this.
REPEAT_WINDOW = timedelta(seconds=10)


class RepeatGuard:
    """Says if an input is a repeat of the same input in the last window."""

    def __init__(self, window: timedelta = REPEAT_WINDOW) -> None:
        self._window = window
        # The time of the last accepted input, for each key. Only keys inside the
        # window stay, so the map cannot grow without a limit.
        self._seen: dict[str, datetime] = {}

    def is_repeat(self, key: str, now: datetime) -> bool:
        """True if *key* was accepted less than the window before *now*.

        An input that is not a repeat is recorded, and the window starts at it. A
        repeat does not move the window, so a steady stream of reads still lets 1
        input through for each window.
        """
        self._seen = {
            seen_key: when
            for seen_key, when in self._seen.items()
            if now - when < self._window
        }
        if key in self._seen:
            return True
        self._seen[key] = now
        return False
