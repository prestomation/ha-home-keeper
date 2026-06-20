"""Recognition tests for the shipped Assist sentences (NLU layer).

These load ``custom_sentences/en/home_keeper.yaml`` and run it through ``hassil`` —
the very engine Home Assistant's default conversation agent uses — to assert that
representative utterances route to the right intent and capture the task name slot.
This is the only tier that exercises sentence -> intent matching, so it guards
against a typo or syntax error in the sentence file silently breaking voice control.

``hassil`` ships with Home Assistant (installed in CI via
pytest-homeassistant-custom-component); a bare ``pip install pytest`` run skips this.
"""

from __future__ import annotations

from pathlib import Path

import pytest

hassil = pytest.importorskip("hassil")
yaml = pytest.importorskip("yaml")

from hassil import Intents, recognize  # noqa: E402

_SENTENCES = (
    Path(__file__).resolve().parents[2] / "custom_sentences" / "en" / "home_keeper.yaml"
)


@pytest.fixture(scope="module")
def intents() -> Intents:
    data = yaml.safe_load(_SENTENCES.read_text())
    return Intents.from_dict(data)


@pytest.mark.parametrize(
    ("text", "expected_name"),
    [
        ("mark furnace filter as done", "furnace filter"),
        ("mark the furnace filter done", "furnace filter"),
        ("complete take medicine", "take medicine"),
        ("complete the task take medicine", "take medicine"),
        ("clear the fridge filter", "fridge filter"),
        ("check off the water filter", "water filter"),
        ("I just replaced the furnace filter", "furnace filter"),
        ("I changed the fridge filter", "fridge filter"),
    ],
)
def test_complete_sentences_route_and_capture_name(intents, text, expected_name):
    result = recognize(text, intents)
    assert result is not None, f"no intent matched: {text!r}"
    assert result.intent.name == "HomeKeeperCompleteTask"
    captured = result.entities["name"].value
    assert expected_name in captured.lower()


@pytest.mark.parametrize(
    "text",
    [
        "what tasks are due",
        "what chores are due today",
        "what tasks need to be done",
        "what's due right now",
        "do I have any chores due",
    ],
)
def test_query_sentences_route_to_list_due(intents, text):
    result = recognize(text, intents)
    assert result is not None, f"no intent matched: {text!r}"
    assert result.intent.name == "HomeKeeperListDueTasks"


def test_unrelated_sentence_does_not_match(intents):
    assert recognize("turn on the kitchen lights", intents) is None
