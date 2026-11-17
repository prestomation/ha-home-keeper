"""The repeat guard of the tag and notification listeners.

A double tap or a second read of 1 tag fires 2 events. The guard says the second
one is a repeat, so the listener acts once.
"""

from datetime import UTC, datetime, timedelta

import hk_repeats as repeats

T0 = datetime(2026, 6, 1, 9, tzinfo=UTC)


def test_the_first_input_is_not_a_repeat():
    assert repeats.RepeatGuard().is_repeat("tag-1", T0) is False


def test_the_same_input_inside_the_window_is_a_repeat():
    guard = repeats.RepeatGuard()
    guard.is_repeat("tag-1", T0)
    assert guard.is_repeat("tag-1", T0) is True
    assert guard.is_repeat("tag-1", T0 + timedelta(seconds=9.9)) is True


def test_the_same_input_at_the_end_of_the_window_is_new():
    guard = repeats.RepeatGuard()
    guard.is_repeat("tag-1", T0)
    assert guard.is_repeat("tag-1", T0 + timedelta(seconds=10)) is False
    # The window starts again at the input that went through.
    assert guard.is_repeat("tag-1", T0 + timedelta(seconds=19)) is True


def test_a_repeat_does_not_move_the_window():
    guard = repeats.RepeatGuard()
    guard.is_repeat("tag-1", T0)
    guard.is_repeat("tag-1", T0 + timedelta(seconds=8))
    assert guard.is_repeat("tag-1", T0 + timedelta(seconds=11)) is False


def test_another_input_is_not_a_repeat():
    guard = repeats.RepeatGuard()
    guard.is_repeat("tag-1", T0)
    assert guard.is_repeat("tag-2", T0) is False
    assert guard.is_repeat("tag-2", T0) is True


def test_the_window_is_10_seconds_and_can_be_set():
    assert timedelta(seconds=10) == repeats.REPEAT_WINDOW
    guard = repeats.RepeatGuard(timedelta(seconds=2))
    guard.is_repeat("a", T0)
    assert guard.is_repeat("a", T0 + timedelta(seconds=1)) is True
    assert guard.is_repeat("a", T0 + timedelta(seconds=2)) is False


def test_old_keys_are_dropped():
    guard = repeats.RepeatGuard()
    for index in range(50):
        guard.is_repeat(f"tag-{index}", T0)
    guard.is_repeat("late", T0 + timedelta(seconds=10))
    assert list(guard._seen) == ["late"]
    guard.is_repeat("later", T0 + timedelta(seconds=19))
    assert list(guard._seen) == ["late", "later"]
