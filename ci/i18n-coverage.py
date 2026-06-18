#!/usr/bin/env python3
"""Report per-locale translation coverage for Home Keeper.

Coverage is a *quality* signal, not a hard gate (the gates live in the unit
tests: ``tests/unit/test_translations_parity.py`` and
``custom_components/home_keeper/frontend/test/i18n.test.js``). A string counts as
"translated" when it is present and not byte-identical to its English source.

Usage:
    python3 ci/i18n-coverage.py            # human-readable table
    python3 ci/i18n-coverage.py --markdown # GitHub-comment table

Exit status is always 0 — this is a report, not a check.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "custom_components" / "home_keeper" / "translations"
_FRONTEND = _ROOT / "custom_components" / "home_keeper" / "frontend" / "src" / "locales"


def _flatten(obj, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, str):
                out[path] = value
            else:
                out.update(_flatten(value, path))
    return out


def _load(path: Path) -> dict[str, str]:
    return _flatten(json.loads(path.read_text(encoding="utf-8")))


def _coverage(directory: Path) -> list[tuple[str, int, int]]:
    """Return [(lang, translated, total)] for every non-English locale."""
    en = _load(directory / "en.json")
    total = len(en)
    rows: list[tuple[str, int, int]] = []
    for path in sorted(directory.glob("*.json")):
        lang = path.stem
        if lang == "en":
            continue
        loc = _load(path)
        translated = sum(
            1 for key, value in en.items() if loc.get(key) not in (None, value)
        )
        rows.append((lang, translated, total))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", action="store_true", help="emit a Markdown table")
    args = parser.parse_args()

    sections = (("Backend (strings.json)", _BACKEND), ("Panel (frontend)", _FRONTEND))

    if args.markdown:
        print("### Translation coverage\n")
        for title, directory in sections:
            print(f"**{title}**\n")
            print("| Locale | Translated | Coverage |")
            print("| --- | --- | --- |")
            for lang, done, total in _coverage(directory):
                pct = 100 * done / total if total else 0
                print(f"| `{lang}` | {done}/{total} | {pct:.0f}% |")
            print()
    else:
        for title, directory in sections:
            print(f"\n{title}")
            for lang, done, total in _coverage(directory):
                pct = 100 * done / total if total else 0
                bar = "█" * round(pct / 5) + "░" * (20 - round(pct / 5))
                print(f"  {lang:8} {bar} {done:3}/{total} ({pct:3.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
