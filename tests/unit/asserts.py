"""Shared assertion helpers for the pure unit tier.

Kept out of ``conftest.py`` so it stays a plain importable module: the unit
tests import it as ``from asserts import raises_exactly`` (pytest puts each test
file's directory on ``sys.path``).
"""

from __future__ import annotations

import re
from typing import Any

import pytest


def raises_exactly(exception: type[BaseException], message: str) -> Any:
    """``pytest.raises`` that pins the **whole** error message.

    Home Keeper's validation messages are contract, not decoration: the service
    layer re-raises them to the user as ``ServiceValidationError`` and the panel
    shows them verbatim, so a test that asserts only "something was raised"
    lets the wrong message — or an empty one — ship unnoticed.

    Anchored and escaped on purpose. ``pytest.raises(match=...)`` is a
    *search* over a regex, so an unanchored pattern passes on a message with
    anything bolted onto either end, and a message containing ``(`` or ``.``
    would otherwise be read as a pattern rather than as text.
    """
    return pytest.raises(exception, match=f"^{re.escape(message)}$")
