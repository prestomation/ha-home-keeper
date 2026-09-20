"""The panel and the reconciler must name a part's tasks identically.

``reconcile.py`` writes the real task name from the tables in ``const.py``. The
panel's preview box says what that name will be *before* the part is saved, and it
cannot call the backend to find out: only the browser knows the viewer's language,
and the preview redraws on every keystroke. So the templates exist twice, once as
``ACTION_TASK_NAME_TEMPLATES`` / ``USE_TASK_NAME_TEMPLATES`` and once as the
``part.taskName.*`` keys in the frontend locale files.

Two copies of a user-visible string drift. This module is what stops that: every
action, in every language the panel ships, must read the same on both sides. A new
action fails here until the locale files carry it, and an edited template fails here
until its twin is edited too.

Pure: reads both files off disk, imports no Home Assistant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.home_keeper.const import (
    ACTION_TASK_NAME_TEMPLATES,
    PART_ACTIONS,
    USE_TASK_NAME_TEMPLATES,
)

_LOCALES = (
    Path(__file__).resolve().parent.parent.parent
    / "custom_components"
    / "home_keeper"
    / "frontend"
    / "src"
    / "locales"
)


def _locale(lang: str) -> dict[str, str]:
    return json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def _panel_languages() -> list[str]:
    """Every language the panel ships, by locale file."""
    return sorted(p.stem for p in _LOCALES.glob("*.json"))


def test_panel_ships_a_locale_for_every_backend_language() -> None:
    """The 2 language lists must match, or a user reads a mixed-language task name.

    A language the backend knows but the panel does not means the preview falls back
    to English while the saved task arrives translated.
    """
    backend = set(ACTION_TASK_NAME_TEMPLATES["replace"])
    panel = set(_panel_languages())
    assert backend == panel, (
        f"backend-only: {sorted(backend - panel)}; panel-only: {sorted(panel - backend)}"
    )


@pytest.mark.parametrize("lang", _panel_languages())
@pytest.mark.parametrize("action", PART_ACTIONS)
def test_action_template_matches_the_panel(action: str, lang: str) -> None:
    """Each action's task-name template reads the same on both sides."""
    key = f"part.taskName.{action}"
    panel = _locale(lang)
    assert key in panel, f"{lang}.json is missing {key}"
    assert panel[key] == ACTION_TASK_NAME_TEMPLATES[action][lang], (
        f"{lang} {action}: panel has {panel[key]!r}, "
        f"backend has {ACTION_TASK_NAME_TEMPLATES[action][lang]!r}"
    )


@pytest.mark.parametrize("lang", _panel_languages())
def test_use_task_template_matches_the_panel(lang: str) -> None:
    """The use task a counted wear item generates is named the same on both sides."""
    panel = _locale(lang)
    assert panel["part.taskName.use"] == USE_TASK_NAME_TEMPLATES[lang]


@pytest.mark.parametrize("lang", _panel_languages())
def test_templates_keep_their_placeholders(lang: str) -> None:
    """A template that loses ``{part}`` or ``{asset}`` renders the token literally.

    ``str.format`` on the backend raises for an unknown token, but the panel's own
    ``t()`` leaves an unmatched one in the output, so a typo ships as a task called
    "Replace {prt} (Fridge)".
    """
    panel = _locale(lang)
    for action in PART_ACTIONS:
        template = panel[f"part.taskName.{action}"]
        assert "{part}" in template, f"{lang} {action} dropped {{part}}"
        assert "{asset}" in template, f"{lang} {action} dropped {{asset}}"
    assert "{asset}" in panel["part.taskName.use"]
    assert "{part}" not in panel["part.taskName.use"], (
        "the use task names the appliance, never the part"
    )
