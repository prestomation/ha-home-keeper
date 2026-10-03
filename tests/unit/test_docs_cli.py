"""Unit tests for ``ci/docs.py``, the docs CLI and the docs gate.

Each check runs against a small fake repository in ``tmp_path``. The fake has no git,
so ``ls_files`` falls back to a file walk. The last test runs the real gate on this
repository, as ``lint.yml`` does.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "ci" / "docs.py"


def _load():
    spec = importlib.util.spec_from_file_location("docs_cli", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses look the module up by name while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


docs = _load()

CONFIG = """
[tool.docs-audit]
line_width = 80
max_exceptions = 1
duplicate_min_words = 6
coverage = ["src/*.py"]
uncovered = []
link_scan = ["**/*.md"]
link_skip = []
code_dirs = ["src"]
code_ref_ignore = ["dist/**"]
doc_ref_suffixes = [".py", ".md"]
doc_ref_skip = []
budgets = [{ files = ["AGENTS.md"], max_lines = 30 }]
kinds = [
    { glob = "docs/design/*.md", kind = "design", strip = "docs/design/" },
    { glob = "docs/guide/**/*.md", kind = "guide", strip = "docs/" },
    { glob = "skills/**/*.md", kind = "skill", strip = "skills/" },
    { glob = "AGENTS.md", kind = "process" },
]

[tool.docs-audit.caps]
design = 40
process = 30
skill = 30

[tool.docs-audit.history]
all = ['(?i)\\bthis PR\\b', 'Status:']
design = ['(?<![\\w/&-])#\\d{2,}\\b']
"""

ENGINE_DOC = """\
---
title: Engine
summary: How the engine works.
implements:
  - src/engine.py
source_hash: {hash}
---

# Engine

The engine computes the next date.

## Goals

- **G1. Correct dates.** The next date is never in the past.

## Non-goals

- Calendars.

## Design

`engine.next_date` returns a date. See [the guide](../guide/use.md#how-to).

## Trade-offs

- Simple over fast.
"""

GUIDE = """\
# Use

## How to

Open the panel.
"""

AGENTS = """\
---
title: Agents
summary: Rules for agents.
---

# Agents

Run the tests before you push.
"""


def make_repo(tmp_path: Path) -> Path:
    files = {
        "pyproject.toml": CONFIG,
        "src/engine.py": "def next_date():\n    return 1\n",
        "docs/guide/use.md": GUIDE,
        "AGENTS.md": AGENTS,
        "skills/demo/SKILL.md": (
            "---\nname: demo\ndescription: A demo.\n---\n\n# Demo\n"
        ),
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    h = docs.source_hash(tmp_path, ["src/engine.py"])
    write(tmp_path, "docs/design/engine.md", ENGINE_DOC.format(hash=h))
    return tmp_path


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def problems(root: Path, base: str | None = None) -> list[str]:
    found, _ = docs.check(root, docs.load_config(root), base)
    return [str(p) for p in found]


def run(root: Path, *argv: str, capsys) -> str:
    assert docs.main(list(argv), root=root) in (0, 1)
    return capsys.readouterr().out


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


# ------------------------------------------------------------------- the clean case


def test_clean_repo_has_no_problems(repo: Path) -> None:
    assert problems(repo) == []


def test_check_command_exit_status(repo: Path, capsys) -> None:
    assert docs.main(["check"], root=repo) == 0
    assert "Docs are clean." in capsys.readouterr().out
    (repo / "src/engine.py").write_text("def next_date():\n    return 2\n")
    assert docs.main(["check"], root=repo) == 1


# ------------------------------------------------------------------------- helpers


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("docs/a.md", "docs/*.md", True),
        ("docs/design/a.md", "docs/*.md", False),
        ("docs/design/a.md", "docs/**/*.md", True),
        ("a.md", "**/*.md", True),
        ("src/x.py", "src/?.py", True),
        ("src/xy.py", "src/?.py", False),
        ("docs/a.mdx", "docs/*.md", False),
    ],
)
def test_glob_match(path: str, pattern: str, expected: bool) -> None:
    assert docs.glob_match(path, pattern) is expected


@pytest.mark.parametrize(
    ("path", "strip", "expected"),
    [
        ("docs/design/store.md", "docs/design/", "store"),
        (".claude/skills/open-work/SKILL.md", ".claude/skills/", "open-work"),
        (".claude/skills/ux/checklists.md", ".claude/skills/", "ux/checklists"),
        ("AGENTS.md", "", "AGENTS"),
    ],
)
def test_doc_id(path: str, strip: str, expected: str) -> None:
    assert docs.doc_id(path, strip) == expected


def test_source_hash_depends_on_path_and_content(tmp_path: Path) -> None:
    write(tmp_path, "a.py", "x")
    write(tmp_path, "b.py", "x")
    one = docs.source_hash(tmp_path, ["a.py"])
    assert len(one) == 12
    assert one != docs.source_hash(tmp_path, ["b.py"])
    assert docs.source_hash(tmp_path, ["a.py", "b.py"]) == docs.source_hash(
        tmp_path, ["b.py", "a.py", "a.py"]
    )
    write(tmp_path, "a.py", "y")
    assert docs.source_hash(tmp_path, ["a.py"]) != one


def test_heading_slugs() -> None:
    text = "# A B\n## A B\n## Snooze, skip & due {#custom}\n```\n# not a heading\n```\n"
    assert docs.heading_slugs(text) == {"a-b", "a-b-1", "custom"}


# ------------------------------------------------------------------- drift and stamp


def test_drift_names_the_doc_and_prints_its_goals(repo: Path) -> None:
    (repo / "src/engine.py").write_text("def next_date():\n    return 2\n")
    [problem] = problems(repo)
    assert problem.startswith("[drift] docs/design/engine.md")
    assert "G1. Correct dates." in problem
    assert "Non-goals" in problem and "Calendars." in problem
    assert "stop and ask the user" in problem
    assert "python ci/docs.py stamp engine" in problem


def test_stamp_fixes_drift_and_keeps_the_rest(repo: Path, capsys) -> None:
    (repo / "src/engine.py").write_text("def next_date():\n    return 2\n")
    before = (repo / "docs/design/engine.md").read_text()
    out = run(repo, "stamp", "engine", capsys=capsys)
    after = (repo / "docs/design/engine.md").read_text()
    new = docs.source_hash(repo, ["src/engine.py"])
    assert out.strip() == f"stamped engine: {new}"
    assert f"source_hash: {new}\n" in after
    assert after.split("---\n", 2)[2] == before.split("---\n", 2)[2]
    assert problems(repo) == []


def test_stamp_changed_touches_only_drifted_docs(repo: Path, capsys) -> None:
    assert run(repo, "stamp", "--changed", capsys=capsys) == ""
    (repo / "src/engine.py").write_text("x = 1\n")
    assert "stamped engine" in run(repo, "stamp", "--changed", capsys=capsys)


def test_stamp_adds_a_missing_hash_line(repo: Path, capsys) -> None:
    path = repo / "docs/design/engine.md"
    path.write_text(path.read_text().replace("source_hash:", "old_hash:"))
    run(repo, "stamp", "--all", capsys=capsys)
    meta, _ = docs.parse_meta(path.read_text())
    assert meta["source_hash"] == docs.source_hash(repo, ["src/engine.py"])


def test_stamp_needs_a_target(repo: Path) -> None:
    with pytest.raises(SystemExit):
        docs.main(["stamp"], root=repo)


# --------------------------------------------------------------------------- coverage


def test_uncovered_source_file_fails(repo: Path) -> None:
    write(repo, "src/new.py", "")
    assert problems(repo) == [
        "[coverage] src/new.py: no design doc lists this file in 'implements'"
    ]


def test_glob_that_matches_nothing_fails(repo: Path) -> None:
    path = repo / "docs/design/engine.md"
    path.write_text(
        path.read_text().replace(
            "  - src/engine.py\n", "  - src/engine.py\n  - src/gone.py\n"
        )
    )
    assert any("glob 'src/gone.py' matches no file" in p for p in problems(repo))


# ----------------------------------------------------------------------------- length


def _agents_lines(n: int) -> str:
    return AGENTS + "".join(f"Line {i}.\n\n" for i in range(n))[: n * 0] + "x\n" * n


def test_line_cap(repo: Path) -> None:
    write(repo, "AGENTS.md", _agents_lines(30))
    found = problems(repo)
    assert any(
        "[length] AGENTS.md:" in p and "cap 30 for kind 'process'" in p for p in found
    )


def test_exception_with_reason_raises_the_cap(repo: Path) -> None:
    text = _agents_lines(30).replace(
        "summary:", "max_lines: 45\nexception: big\nsummary:"
    )
    write(repo, "AGENTS.md", text)
    budget_free = [p for p in problems(repo) if "together" not in p]
    assert budget_free == []
    _, notices = docs.check(repo, docs.load_config(repo))
    assert notices == ["length exception: AGENTS.md: 45 lines (big)"]


def test_exception_needs_a_reason_and_a_bound(repo: Path) -> None:
    text = AGENTS.replace("summary:", "max_lines: 46\nsummary:")
    write(repo, "AGENTS.md", text)
    found = problems(repo)
    assert any("needs an 'exception' reason" in p for p in found)
    assert any("more than 1.5 x the cap of 30" in p for p in found)


def test_too_many_exceptions(repo: Path) -> None:
    write(
        repo,
        "AGENTS.md",
        AGENTS.replace("summary:", "max_lines: 31\nexception: a\nsummary:"),
    )
    write(
        repo,
        "skills/demo/extra.md",
        "---\ntitle: X\nsummary: Y\nmax_lines: 31\nexception: b\n---\n",
    )
    assert any("2 length exceptions, at most 1" in p for p in problems(repo))


def test_line_width_skips_tables_and_fences(repo: Path) -> None:
    long = "word " * 20
    write(repo, "AGENTS.md", AGENTS + f"| {long} |\n```\n{long}\n```\n{long}\n")
    found = [p for p in problems(repo) if "characters" in p]
    assert len(found) == 1 and found[0].startswith("[length] AGENTS.md:13:")


def test_budget_across_files(repo: Path) -> None:
    write(repo, "AGENTS.md", AGENTS + "x\n" * 20)
    assert problems(repo) == []
    write(repo, "AGENTS.md", AGENTS + "x\n" * 30)
    assert any("lines together, cap 30" in p for p in problems(repo))


# ---------------------------------------------------------------------------- history


def test_history_phrases_fail_outside_code(repo: Path) -> None:
    write(
        repo, "AGENTS.md", AGENTS + "This PR adds it.\n\n`this PR` in code is fine.\n"
    )
    found = [p for p in problems(repo) if p.startswith("[history]")]
    assert len(found) == 1
    assert "AGENTS.md:9" in found[0] and "Git keeps the history" in found[0]


def test_issue_numbers_fail_in_design_docs_only(repo: Path) -> None:
    write(repo, "AGENTS.md", AGENTS + "See #123.\n")
    assert problems(repo) == []
    path = repo / "docs/design/engine.md"
    path.write_text(
        path.read_text().replace("Simple over fast.", "Simple over fast (#123).")
    )
    assert any(p.startswith("[history] docs/design/engine.md") for p in problems(repo))


# ------------------------------------------------------------------- links and refs


def test_broken_link_and_anchor(repo: Path) -> None:
    write(
        repo,
        "AGENTS.md",
        AGENTS
        + "[a](docs/gone.md) [b](docs/guide/use.md#nope) [c](#agents) "
        + "[d](https://example.com/x.md) [e](docs/guide)\n\n```\n[f](gone.md)\n```\n",
    )
    found = [p for p in problems(repo) if p.startswith("[links]")]
    assert found == [
        "[links] AGENTS.md:9: broken link 'docs/gone.md'",
        "[links] AGENTS.md:9: no heading for 'docs/guide/use.md#nope'",
    ]


def test_code_refs(repo: Path) -> None:
    write(
        repo,
        "AGENTS.md",
        AGENTS
        + "`src/engine.py` `engine.py:12` `engine.next_date()` `engine.gone` "
        + "`src/missing.py` `report.md` `dist/x.js` `hass.data`\n",
    )
    found = [p for p in problems(repo) if p.startswith("[code-refs]")]
    assert found == [
        "[code-refs] AGENTS.md:9: src/engine.py defines no 'gone'",
        "[code-refs] AGENTS.md:9: no file 'src/missing.py'",
    ]


def test_doc_paths_in_code_must_exist(repo: Path) -> None:
    write(
        repo,
        "src/engine.py",
        "# See docs/design/engine.md and docs/OLD_PLAN.md.\n"
        "def next_date():\n    return 1\n",
    )
    docs.main(["stamp", "--all"], root=repo)
    assert problems(repo) == ["[doc-refs] src/engine.py:1: no doc 'docs/OLD_PLAN.md'"]


def test_duplicate_sentence_across_docs(repo: Path) -> None:
    sentence = "Always run every test before you push a branch."
    write(repo, "AGENTS.md", AGENTS + sentence + "\n")
    write(
        repo,
        "skills/demo/extra.md",
        f"---\ntitle: X\nsummary: Y\n---\n\n- {sentence}\n",
    )
    found = [p for p in problems(repo) if p.startswith("[duplicate]")]
    assert found == [
        "[duplicate] skills/demo/extra.md:6: same sentence as AGENTS.md:8. "
        "Keep one, link to it."
    ]


# ------------------------------------------------------------ front matter, sections


def test_front_matter_rules(repo: Path) -> None:
    write(repo, "AGENTS.md", "# Agents\n")
    write(repo, "skills/demo/SKILL.md", "---\nname: demo\n---\n")
    write(repo, "skills/demo/bad.md", "---\ntitle: [x\n---\n")
    write(
        repo, "skills/demo/rel.md", "---\ntitle: X\nsummary: Y\nrelated: [nope]\n---\n"
    )
    found = problems(repo)
    assert "[front-matter] AGENTS.md: no front matter (title, summary)" in found
    assert "[front-matter] skills/demo/SKILL.md: no 'description'" in found
    assert any(
        p.startswith("[front-matter] skills/demo/bad.md: front matter is not valid")
        for p in found
    )
    assert "[front-matter] skills/demo/rel.md: related 'nope' is not a doc" in found


def test_guide_pages_need_no_front_matter(repo: Path) -> None:
    write(repo, "docs/guide/other.md", "# Other\n" + "x\n" * 500)
    assert problems(repo) == []


def test_design_sections(repo: Path) -> None:
    path = repo / "docs/design/engine.md"
    text = (
        path.read_text()
        .replace("## Trade-offs", "## Choices")
        .replace("**G1.", "**One.")
    )
    path.write_text(text)
    found = problems(repo)
    assert "[sections] docs/design/engine.md: no '## Trade-offs' section" in found
    assert "[sections] docs/design/engine.md: number the goals G1, G2, ..." in found


def test_design_needs_implements(repo: Path) -> None:
    path = repo / "docs/design/engine.md"
    path.write_text(path.read_text().replace("implements:\n  - src/engine.py\n", ""))
    assert (
        "[front-matter] docs/design/engine.md: a design doc needs 'implements'"
        in problems(repo)
    )


# ------------------------------------------------------------------------- commands


def test_list(repo: Path, capsys) -> None:
    rows = json.loads(run(repo, "list", "--json", capsys=capsys))
    assert [(r["id"], r["kind"], r["cap"]) for r in rows] == [
        ("engine", "design", 40),
        ("guide/use", "guide", None),
        ("AGENTS", "process", 30),
        ("demo", "skill", 30),
    ]
    assert rows[0]["summary"] == "How the engine works."
    assert "engine" in run(repo, "list", "--kind", "design", capsys=capsys)
    assert "AGENTS" not in run(repo, "list", "--kind", "design", capsys=capsys)


def test_read_pages(repo: Path, capsys) -> None:
    text = (repo / "docs/design/engine.md").read_text().splitlines()
    body_start = text.index("---", 1) + 1
    body = text[body_start:]
    pages = -(-len(body) // 5)
    out = run(repo, "read", "engine", "--page-size", "5", capsys=capsys)
    assert out.splitlines()[:5] == body[:5]
    assert f"lines {body_start + 1}-{body_start + 5}, page 1 of {pages}" in out
    assert "--page 2" in out
    data = json.loads(
        run(
            repo,
            "read",
            "engine",
            "--page",
            str(pages),
            "--page-size",
            "5",
            "--json",
            capsys=capsys,
        )
    )
    assert data["page"] == pages and data["pages"] == pages
    assert data["lines"] == body[(pages - 1) * 5 :]
    assert data["lines"][-1] == "- Simple over fast."
    assert data["first_line"] == body_start + (pages - 1) * 5 + 1
    last = run(
        repo, "read", "engine", "--page", "99", "--page-size", "5", capsys=capsys
    )
    assert f"page {pages} of {pages}" in last and "Next:" not in last


def test_read_unknown_doc_exits(repo: Path) -> None:
    with pytest.raises(SystemExit):
        docs.main(["read", "nope"], root=repo)


def test_outline(repo: Path, capsys) -> None:
    heads = json.loads(run(repo, "outline", "engine", "--json", capsys=capsys))
    assert [(h["level"], h["title"]) for h in heads] == [
        (1, "Engine"),
        (2, "Goals"),
        (2, "Non-goals"),
        (2, "Design"),
        (2, "Trade-offs"),
    ]
    assert heads[0]["line"] == 9 and heads[0]["page"] == 1


def test_search(repo: Path, capsys) -> None:
    hits = json.loads(run(repo, "search", "PANEL", "--json", capsys=capsys))
    assert hits == [
        {"id": "guide/use", "line": 5, "heading": "How to", "text": "Open the panel."}
    ]
    assert run(repo, "search", "zzz", capsys=capsys).strip() == "no match"
    assert "engine" in run(repo, "search", "next.date", "--regex", capsys=capsys)


def test_for_prints_the_governing_goals(repo: Path, capsys) -> None:
    out = run(repo, "for", "src/engine.py", "src/other.py", capsys=capsys)
    assert "== engine (docs/design/engine.md) governs src/engine.py" in out
    assert "G1. Correct dates." in out
    assert "No design doc governs: src/other.py" in out


def test_hook(repo: Path, capsys, monkeypatch) -> None:
    payload = {"tool_input": {"file_path": str(repo / "src/engine.py")}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out = json.loads(run(repo, "hook", capsys=capsys))
    assert "design doc(s): engine" in out["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"tool_input": {"file_path": str(repo / "AGENTS.md")}})),
    )
    assert run(repo, "hook", capsys=capsys) == ""
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert run(repo, "hook", capsys=capsys) == ""


def test_missing_base_ref_fails(repo: Path) -> None:
    # tmp_path is not a git repository, so no ref exists there.
    assert problems(repo, base="origin/main") == [
        "[git] origin/main: no such git ref. Fetch it, or drop --base."
    ]


def test_ref_exists_on_this_repository() -> None:
    if not (_ROOT / ".git").exists():
        pytest.skip("needs the git checkout")
    assert docs.ref_exists(_ROOT, "HEAD") is True
    assert docs.ref_exists(_ROOT, "no-such-ref-for-docs-cli") is False


def test_goal_change_notice(repo: Path) -> None:
    path = repo / "docs/design/engine.md"
    doc = docs.load_docs(repo, docs.load_config(repo))[0]
    old = path.read_text()
    path.write_text(old.replace("Calendars.", "Calendars and clocks."))
    new_doc = docs.Doc(doc.id, doc.path, doc.kind, path.read_text(), doc.meta)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class R:
            stdout = old

        return R()

    real = docs.subprocess.run
    docs.subprocess.run = fake_run
    try:
        notices = docs.goal_changes(repo, "origin/main", [new_doc])
    finally:
        docs.subprocess.run = real
    assert calls == [["git", "show", "origin/main:docs/design/engine.md"]]
    assert notices == [
        "goal change: docs/design/engine.md '## Non-goals' changed against "
        "origin/main. "
        "The PR body needs a 'Goal changes' section that the user confirmed."
    ]


# ------------------------------------------------------------------ the real gate


@pytest.mark.skipif(
    not (_ROOT / ".git").exists(),
    reason="needs the whole checkout; mutmut runs from a partial copy in mutants/",
)
def test_repository_docs_are_clean() -> None:
    """The same gate as the lint.yml ``docs-audit`` job."""
    found, _ = docs.check(_ROOT, docs.load_config(_ROOT))
    assert [str(p) for p in found] == []


def test_text_helper_is_dedented() -> None:
    # The fixtures above are written flush left on purpose: front matter must start
    # at column 0. This guards against an editor re-indenting them.
    assert ENGINE_DOC.startswith("---\n") and textwrap.dedent(AGENTS) == AGENTS
