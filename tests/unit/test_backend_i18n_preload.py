"""``backend_i18n.preload`` must leave every string table warm (#247).

The point of ``preload`` is that no ``resolve_exception``/``resolve_string`` call
ever reads a file, because the reading was done once in an executor during
``async_setup_entry``. Miss a table and the module goes straight back to opening
JSON on Home Assistant's event loop the first time something asks for one of its
keys — the warning the reporter of #247 pasted.

``tests/integration/test_event_loop_blocking.py`` asserts the outcome against Home
Assistant's own blocking-call detector. This is the fast-lane guard on the piece
that has to stay in step by hand: a table added to this module has to be added to
``preload`` too, so the check below is written against *every* cached table the
module defines rather than the two that exist today.
"""

from __future__ import annotations

import sys
from pathlib import Path

backend_i18n = sys.modules["hk.backend_i18n"]


def _cached_tables() -> list:
    """Every ``functools.cache``d table in the module (what ``preload`` must fill)."""
    return [
        value
        for value in vars(backend_i18n).values()
        if callable(value)
        and hasattr(value, "cache_info")
        and hasattr(value, "cache_clear")
    ]


def test_preload_warms_every_cached_table_for_the_language_and_english():
    tables = _cached_tables()
    assert tables, "expected backend_i18n to memoize its string tables"
    for table in tables:
        table.cache_clear()

    backend_i18n.preload("de")

    for table in tables:
        entries = table.cache_info().currsize
        assert entries == 2, (
            f"{table.__name__} holds {entries} cached languages after "
            "preload('de') — it must be warm for both the requested language and "
            "the English fallback, or the first resolve does file I/O on the loop"
        )


def test_resolving_after_preload_reads_no_files(monkeypatch):
    for table in _cached_tables():
        table.cache_clear()
    backend_i18n.preload("en")

    reads: list[Path] = []
    real_read_text = Path.read_text

    def spy(self: Path, *args, **kwargs):
        reads.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy)

    # One key from each table, resolved (not falling through to the bare key) — a
    # miss would prove the table empty and make the "no reads" assertion vacuous.
    assert (
        backend_i18n.resolve_exception("en", "task_not_found", task_id="t1")
        == "Task not found: t1"
    )
    assert backend_i18n.resolve_string("en", "inventory.csv.name") == "Name"
    assert reads == [], f"resolving read files after preload: {reads}"


def test_preload_is_idempotent():
    """An entry reload calls it again; that must not re-read anything."""
    for table in _cached_tables():
        table.cache_clear()
    backend_i18n.preload("fr")
    before = [table.cache_info().misses for table in _cached_tables()]

    backend_i18n.preload("fr")

    assert [table.cache_info().misses for table in _cached_tables()] == before
