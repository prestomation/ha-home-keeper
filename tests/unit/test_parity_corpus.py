"""The generated parity corpus: Hypothesis inputs with the Python answers.

The shared case files hold cases that a person wrote. This corpus adds inputs that
Hypothesis draws, for the rules that ``tests/fixtures/parity.json`` marks ``corpus``.
The Python side writes each input with its own answer to
``tests/fixtures/parity_corpus.json``, and ``frontend/test/parity-corpus.test.js``
replays the file against the TypeScript side.

``test_corpus_holds_the_python_answers`` runs on every PR. It computes the Python
answer for each committed input again and compares it with the committed answer, so a
change to a Python rule fails here until the corpus is written again:
``bash ci/parity-corpus.sh`` (``HK_PARITY_WRITE=1``). The check does not draw the
inputs again, because a new Hypothesis version can draw different inputs from the
same seed; only the answers must stay current.

The strategies stay in the domain that each rule can receive: a filter that
``profiles.normalize_filter`` accepts, an aware ``next_due``, a quantity from 0 to
``MAX_INTERVAL``. Everything the 2 sides read is drawn, including the shapes that only
hand-edited storage can hold.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st
from parity_adapters import ADAPTERS, REGISTRY, ROOT

CORPUS = ROOT / "tests/fixtures/parity_corpus.json"
# At most this many entries for each rule, so the file stays small to review.
LIMIT = 150

_WRITE = settings(
    max_examples=LIMIT * 2,
    derandomize=True,
    database=None,
    phases=[Phase.explicit, Phase.generate],
    suppress_health_check=list(HealthCheck),
    deadline=None,
)

# ── profile_filter ─────────────────────────────────────────────────────────────

_NOWS = ("2026-06-16T12:00:00+00:00", "2026-01-31T23:30:00-05:00")
_OFFSETS = (
    UTC,
    timezone(timedelta(hours=-4)),
    timezone(timedelta(hours=5, minutes=30)),
)
# Seconds from now: the edges of the overdue and 3-day due-soon windows, and a spread.
_EDGES = (0, -1, 1, 3 * 86400, 3 * 86400 + 1, 3 * 86400 - 1, -86400, 7 * 86400)
_LABELS = ("dog", "pool", "garden")
_AREAS = ("kitchen", "garage")
_DEVICES = ("d1", "d2")
_COMPANIONS = (
    "battery_notes",
    "home_keeper",
    "home_keeper:declarative:filter",
    "home_keeper:problem_sensors",
)


def _due(now: str, seconds: int, offset: timezone, zulu: bool) -> str:
    when = (datetime.fromisoformat(now) + timedelta(seconds=seconds)).astimezone(offset)
    text = when.isoformat()
    return text.replace("+00:00", "Z") if zulu else text


_sources = st.sampled_from(
    [
        None,
        {"declarative_companion": {"spec_id": "filter"}},
        {"declarative_companion": {"spec_id": "other"}},
        {"problem_sensor": {"entity_id": "binary_sensor.leak"}},
        {"problem_sensor": []},
        {"buy": {"asset_id": "a", "part_id": "p"}},
        {"buy": {"asset_id": "a"}},
        {"buy": {"asset_id": "", "part_id": "p"}},
    ]
)
_managed = st.sampled_from(
    [
        None,
        {},
        {"integration": "battery_notes"},
        {"integration": "home_keeper"},
        {"integration": ""},
    ]
)


@st.composite
def _profile_case(draw: st.DrawFn) -> dict[str, Any]:
    now = draw(st.sampled_from(_NOWS))
    task: dict[str, Any] = {"id": "t"}
    enabled = draw(st.sampled_from([None, None, True, False]))
    if enabled is not None:
        task["enabled"] = enabled
    seconds = draw(
        st.one_of(st.sampled_from(_EDGES), st.integers(-10 * 86400, 10 * 86400))
    )
    due = _due(now, seconds, draw(st.sampled_from(_OFFSETS)), draw(st.booleans()))
    task["next_due"] = draw(st.sampled_from([due, due, due, None]))
    task["labels"] = draw(st.lists(st.sampled_from(_LABELS), max_size=2, unique=True))
    for key, pool in (("area_id", _AREAS), ("device_id", _DEVICES)):
        value = draw(st.sampled_from([None, *pool]))
        if value is not None or draw(st.booleans()):
            task[key] = value
    managed = draw(_managed)
    if managed is not None:
        task["managed_by"] = managed
    source = draw(_sources)
    if source is not None:
        task["source"] = source

    def ids(pool: tuple[str, ...]) -> list[str]:
        # Empty 2 times in 3, so that enough tasks clear every list.
        some = st.lists(st.sampled_from(pool), min_size=1, max_size=2, unique=True)
        return draw(st.one_of(st.just([]), st.just([]), some))

    filt: dict[str, Any] = {
        "status": draw(st.sampled_from(["all", "overdue", "due_soon"])),
        "labels": ids(_LABELS),
        "areas": ids(_AREAS),
        "devices": ids(_DEVICES),
    }
    for key, pool in (
        ("companions", _COMPANIONS),
        ("exclude_labels", _LABELS),
        ("exclude_areas", _AREAS),
        ("exclude_devices", _DEVICES),
        ("exclude_companions", _COMPANIONS),
    ):
        if draw(st.booleans()):
            filt[key] = ids(pool)
    if draw(st.booleans()):
        filt["exclude_shopping"] = draw(st.booleans())
    return {"task": task, "filter": filt, "now": now}


# ── icon ──────────────────────────────────────────────────────────────────────

# The spaces that Python strips and JavaScript trims are not the same set; draw both.
_SPACES = "".join(
    map(
        chr,
        (
            0x20,
            0x09,
            0x0A,
            0x0B,
            0x0C,
            0x0D,
            0x1C,
            0x1F,
            0x85,
            0xA0,
            0x2000,
            0x3000,
            0xFEFF,
            0x200B,
        ),
    )
)
# The Kelvin sign (U+212A) lowers to an ASCII k in both languages.
_NAME = "abcdhmoxyz0129-_:\"' K" + chr(0x212A) + chr(0xE4)


@st.composite
def _icon_case(draw: st.DrawFn) -> dict[str, Any]:
    pad = st.text(alphabet=_SPACES, max_size=2)
    name = draw(
        st.one_of(
            st.text(alphabet="abhmoz019-", min_size=1, max_size=8),
            st.text(alphabet=_NAME, max_size=8),
        )
    )
    prefix = draw(st.sampled_from(["mdi:", "MDI:", "Mdi:", "hass:", "mdi", ""]))
    text = draw(pad) + prefix + name + draw(pad)
    value = draw(
        st.one_of(
            st.just(text),
            st.just(text),
            st.just(text),
            st.none(),
            st.integers(-5, 5),
            st.booleans(),
            st.just([text]),
        )
    )
    return {"input": value}


# ── quantity_format ───────────────────────────────────────────────────────────

_MAX_QUANTITY = 1_000_000


@st.composite
def _quantity_case(draw: st.DrawFn) -> dict[str, Any]:
    value = draw(
        st.one_of(
            st.integers(0, _MAX_QUANTITY),
            # Halfway values at the 4th place, where Python's round and toFixed part.
            st.integers(0, 20_000).map(lambda n: (2 * n + 1) / 2000),
            st.integers(0, 10**7).map(lambda n: n / 1000),
            st.floats(0, _MAX_QUANTITY, allow_nan=False, allow_infinity=False),
        )
    )
    return {
        "value": value,
        "unit": draw(st.sampled_from(["", "ml", " kg ", "L"])),
        "lang": draw(st.sampled_from(["en", "de", "fr", "fa", "pt-BR", "de-CH"])),
    }


STRATEGIES: dict[str, st.SearchStrategy[dict[str, Any]]] = {
    "profile_filter": _profile_case(),
    "icon": _icon_case(),
    "quantity_format": _quantity_case(),
}


def _draw(rule_id: str) -> list[dict[str, Any]]:
    """Up to LIMIT distinct inputs for *rule_id*, in a fixed order, with the answers."""
    drawn: list[dict[str, Any]] = []
    seen: set[str] = set()

    @_WRITE
    @given(STRATEGIES[rule_id])
    def collect(case: dict[str, Any]) -> None:
        key = json.dumps(case, sort_keys=True)
        if key not in seen and len(drawn) < LIMIT:
            seen.add(key)
            drawn.append(case)

    collect()
    return [{**case, "expected": ADAPTERS[rule_id](case, {})} for case in drawn]


def _write() -> None:
    rules = {
        rule["id"]: _draw(rule["id"])
        for rule in REGISTRY["rules"]
        if rule.get("corpus")
    }
    data = {
        "_comment": (
            "Generated by tests/unit/test_parity_corpus.py: run "
            "bash ci/parity-corpus.sh. Do not edit. Each entry is an input that "
            "Hypothesis drew, with the Python answer in expected."
        ),
        "rules": rules,
    }
    CORPUS.write_text(json.dumps(data, indent=1, ensure_ascii=True) + "\n")


def test_every_corpus_rule_has_a_strategy() -> None:
    marked = {rule["id"] for rule in REGISTRY["rules"] if rule.get("corpus")}
    assert set(STRATEGIES) == marked


def test_corpus_holds_the_python_answers() -> None:
    if os.environ.get("HK_PARITY_WRITE") == "1":
        _write()
    corpus = json.loads(CORPUS.read_text())["rules"]
    stale = []
    for rule_id, entries in corpus.items():
        assert 0 < len(entries) <= LIMIT, rule_id
        for entry in entries:
            got = ADAPTERS[rule_id](entry, {})
            if got != entry["expected"] or type(got) is not type(entry["expected"]):
                stale.append((rule_id, entry, got))
    assert not stale, (
        f"{len(stale)} corpus answers differ from the Python side now; "
        "run bash ci/parity-corpus.sh and commit the file. First: "
        f"{stale[0]}"
    )


@pytest.mark.parametrize("rule_id", ["profile_filter", "icon"])
def test_corpus_reaches_both_answers(rule_id: str) -> None:
    """A corpus that gives 1 answer only checks nothing on the other side."""
    entries = json.loads(CORPUS.read_text())["rules"][rule_id]
    answers = {bool(entry["expected"]) for entry in entries}
    assert answers == {True, False}
