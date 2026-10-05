#!/usr/bin/env python3
"""Query and check the repository's docs.

An agent uses this to find docs, read them a page at a time, and learn which design
doc governs a file. CI runs ``check``, which fails when a doc drifts from the code it
describes, grows past its cap, tells history, or links to something that is gone.

Each doc's kind comes from its path (``[[tool.docs-audit.kinds]]`` in
``pyproject.toml``). Every capped doc starts with YAML front matter that gives
``title`` and ``summary``. A design doc also gives ``implements`` (globs of the files
that implement it) and ``source_hash`` (the hash of those files). ``stamp`` is the
only way to change a hash: run it after you read the code change against the doc's
goals and make the doc true again.

Run ``python ci/docs.py --help`` for the commands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]

FRONT_MATTER = re.compile(r"\A---\n(.*?\n)---\n", re.S)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
CODE_SPAN = re.compile(r"`([^`\n]+)`")
FILE_REF = re.compile(r"^[\w./-]+\.(?:py|ts|md|mjs|js|json|yaml|yml|toml|sh)$")
SYMBOL_REF = re.compile(r"^([a-z_][a-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)(?:\(\))?$")
DRIFT_FIX = (
    "Read the code change against these goals. If the change works against a goal, "
    "stop and ask the user. Change the doc so that it describes the code as it is "
    "now, then run: python ci/docs.py stamp {id}"
)
HISTORY_FIX = "Describe the current design. Git keeps the history."
REQUIRED_DESIGN_SECTIONS = ("Goals", "Non-goals", "Design", "Trade-offs")


# --------------------------------------------------------------------------- config


@dataclass
class Config:
    kinds: list[tuple[str, str, str]]  # (glob, kind, id prefix to strip)
    caps: dict[str, int]
    line_width: int
    max_exceptions: int
    budgets: list[dict[str, Any]]
    coverage: list[str]
    uncovered: list[str]
    history: dict[str, list[str]]
    link_scan: list[str]
    link_skip: list[str]
    code_dirs: list[str]
    code_ref_ignore: list[str]
    duplicate_min_words: int
    doc_ref_suffixes: tuple[str, ...]
    doc_ref_skip: list[str]


def load_config(root: Path) -> Config:
    data = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["docs-audit"]
    return Config(
        kinds=[(k["glob"], k["kind"], k.get("strip", "")) for k in data["kinds"]],
        caps=dict(data["caps"]),
        line_width=int(data["line_width"]),
        max_exceptions=int(data["max_exceptions"]),
        budgets=list(data.get("budgets", [])),
        coverage=list(data["coverage"]),
        uncovered=list(data.get("uncovered", [])),
        history={k: list(v) for k, v in data["history"].items()},
        link_scan=list(data["link_scan"]),
        link_skip=list(data.get("link_skip", [])),
        code_dirs=list(data["code_dirs"]),
        code_ref_ignore=list(data.get("code_ref_ignore", [])),
        duplicate_min_words=int(data["duplicate_min_words"]),
        doc_ref_suffixes=tuple(data["doc_ref_suffixes"]),
        doc_ref_skip=list(data.get("doc_ref_skip", [])),
    )


# ----------------------------------------------------------------------------- docs


@dataclass
class Doc:
    id: str
    path: str  # relative to the root, with forward slashes
    kind: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)
    meta_error: str | None = None

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    @property
    def body_start(self) -> int:
        """Index of the first line after the front matter."""
        m = FRONT_MATTER.match(self.text)
        return m.group(0).count("\n") if m else 0

    @property
    def title(self) -> str:
        if self.meta.get("title"):
            return str(self.meta["title"])
        if self.meta.get("name"):
            return str(self.meta["name"])
        for line in self.lines[self.body_start :]:
            h = HEADING.match(line)
            if h:
                return h.group(2)
        return self.id

    @property
    def summary(self) -> str:
        return str(self.meta.get("summary") or self.meta.get("description") or "")


def ls_files(root: Path) -> list[str]:
    """Every file git knows about plus untracked, not-ignored ones."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return sorted(p for p in out.splitlines() if (root / p).is_file())
    except (OSError, subprocess.CalledProcessError):
        return sorted(
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts
        )


def glob_match(path: str, pattern: str) -> bool:
    """Match like a gitignore-style glob: ``*`` stays in one directory, ``**`` not."""
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            regex += ".*"
            i += 2
        elif pattern[i] == "*":
            regex += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            regex += "[^/]"
            i += 1
        else:
            regex += re.escape(pattern[i])
            i += 1
    return re.fullmatch(regex, path) is not None


def kind_for(path: str, cfg: Config) -> tuple[str, str] | None:
    for pattern, kind, strip in cfg.kinds:
        if glob_match(path, pattern):
            return kind, strip
    return None


def doc_id(path: str, strip: str) -> str:
    ident = path[: -len(".md")] if path.endswith(".md") else path
    if strip and ident.startswith(strip):
        ident = ident[len(strip) :]
    return ident.removesuffix("/SKILL")


def parse_meta(text: str) -> tuple[dict[str, Any], str | None]:
    m = FRONT_MATTER.match(text)
    if not m:
        return {}, None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as err:
        return {}, f"front matter is not valid YAML: {err}"
    if not isinstance(meta, dict):
        return {}, "front matter is not a mapping"
    return meta, None


def load_docs(root: Path, cfg: Config, files: list[str] | None = None) -> list[Doc]:
    docs = []
    for path in files if files is not None else ls_files(root):
        if not path.endswith(".md"):
            continue
        found = kind_for(path, cfg)
        if found is None:
            continue
        kind, strip = found
        text = (root / path).read_text(encoding="utf-8")
        meta, err = parse_meta(text)
        docs.append(Doc(doc_id(path, strip), path, kind, text, meta, err))
    return sorted(docs, key=lambda d: (d.kind, d.id))


def sections(doc: Doc) -> dict[str, str]:
    """Map each ``##`` heading to its text, up to the next ``##`` heading."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    in_fence = False
    for line in doc.lines[doc.body_start :]:
        if FENCE.match(line):
            in_fence = not in_fence
        h = None if in_fence else HEADING.match(line)
        if h and len(h.group(1)) == 2:
            current = h.group(2)
            out[current] = []
        elif current is not None and not (h and len(h.group(1)) == 1):
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def prose_lines(doc: Doc) -> list[tuple[int, str]]:
    """(1-based line number, text) for lines outside front matter and code fences."""
    out = []
    in_fence = False
    for i, line in enumerate(doc.lines):
        if i < doc.body_start:
            continue
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((i + 1, line))
    return out


# ---------------------------------------------------------------------------- hashes


def expand(root: Path, globs: list[str], files: list[str]) -> dict[str, list[str]]:
    return {g: [f for f in files if glob_match(f, g)] for g in globs}


def source_hash(root: Path, paths: list[str]) -> str:
    h = hashlib.sha256()
    for path in sorted(set(paths)):
        h.update(path.encode() + b"\0")
        h.update((root / path).read_bytes() + b"\0")
    return h.hexdigest()[:12]


def doc_sources(root: Path, doc: Doc, files: list[str]) -> list[str]:
    globs = doc.meta.get("implements") or []
    return sorted(
        {f for matched in expand(root, globs, files).values() for f in matched}
    )


# ---------------------------------------------------------------------------- checks


@dataclass
class Problem:
    check: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.check}] {self.where}: {self.message}"


def heading_slugs(text: str) -> set[str]:
    slugs: set[str] = set()
    seen: dict[str, int] = {}
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        h = None if in_fence else HEADING.match(line)
        if not h:
            continue
        title = h.group(2)
        custom = re.search(r"\{#([\w-]+)\}\s*$", title)
        if custom:
            slugs.add(custom.group(1))
            continue
        slug = re.sub(r"<[^>]+>", "", title).lower()
        slug = re.sub(r"[^\w\- ]", "", slug).replace(" ", "-")
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        slugs.add(slug if n == 0 else f"{slug}-{n}")
    return slugs


def check_links(root: Path, cfg: Config, files: list[str]) -> list[Problem]:
    problems = []
    slug_cache: dict[str, set[str]] = {}

    def slugs(path: str) -> set[str]:
        if path not in slug_cache:
            slug_cache[path] = heading_slugs((root / path).read_text(encoding="utf-8"))
        return slug_cache[path]

    fileset = set(files)
    for path in files:
        if not path.endswith(".md"):
            continue
        if not any(glob_match(path, g) for g in cfg.link_scan):
            continue
        if any(glob_match(path, g) for g in cfg.link_skip):
            continue
        in_fence = False
        text = (root / path).read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            if FENCE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for target in LINK.findall(CODE_SPAN.sub("", line)):
                if re.match(r"^[a-z]+:", target) or target.startswith("/"):
                    continue
                target_path, _, anchor = target.partition("#")
                if target_path:
                    resolved = (Path(path).parent / target_path).as_posix()
                    resolved = _normalize(resolved)
                    is_dir = any(
                        f.startswith(resolved.rstrip("/") + "/") for f in fileset
                    )
                    if resolved not in fileset and not is_dir:
                        problems.append(
                            Problem("links", f"{path}:{n}", f"broken link {target!r}")
                        )
                        continue
                else:
                    resolved = path
                if (
                    anchor
                    and resolved.endswith(".md")
                    and anchor not in slugs(resolved)
                ):
                    problems.append(
                        Problem("links", f"{path}:{n}", f"no heading for {target!r}")
                    )
    return problems


DOC_PATH_REF = re.compile(r"(?<![\w/.-])docs/[\w./-]+\.md\b")


def check_doc_refs(root: Path, cfg: Config, files: list[str]) -> list[Problem]:
    """A ``docs/...md`` path named in code, config or a doc must exist.

    Code comments point at design docs. When a doc is renamed or deleted, the link
    check sees only Markdown links, so this catches the comments and backticks too.
    """
    fileset = set(files)
    problems = []
    for path in files:
        if not path.endswith(cfg.doc_ref_suffixes):
            continue
        if any(glob_match(path, g) for g in [*cfg.link_skip, *cfg.doc_ref_skip]):
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for ref in DOC_PATH_REF.findall(line):
                if "*" in ref or "..." in ref or ref in fileset:
                    continue
                problems.append(Problem("doc-refs", f"{path}:{n}", f"no doc {ref!r}"))
    return problems


def _normalize(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def _defines(source: str, name: str) -> bool:
    word = re.escape(name)
    pattern = rf"^\s*(?:async\s+def|def|class)\s+{word}\b|^{word}\s*[:=]"
    return re.search(pattern, source, re.M) is not None


def check_code_refs(
    root: Path, cfg: Config, doc: Doc, files: list[str]
) -> list[Problem]:
    problems = []
    basenames = {f.rsplit("/", 1)[-1] for f in files}
    fileset = set(files)
    for n, line in prose_lines(doc):
        for span in CODE_SPAN.findall(line):
            ref = re.sub(r":\d+(?:[-,]\d+)*$", "", span.strip())
            if any(glob_match(ref, g) for g in cfg.code_ref_ignore):
                continue
            if FILE_REF.match(ref):
                if ref.startswith("/"):
                    continue
                if "/" in ref:
                    bases = ["", str(Path(doc.path).parent), *cfg.code_dirs]
                    found = any(
                        _normalize(f"{b}/{ref}") in fileset
                        or any(
                            f.startswith(_normalize(f"{b}/{ref}") + "/")
                            for f in fileset
                        )
                        for b in bases
                    )
                elif ref.endswith((".py", ".ts")):
                    found = ref in basenames
                else:  # a bare name such as `report.md` can be a scratch file
                    found = True
                if not found:
                    problems.append(
                        Problem("code-refs", f"{doc.path}:{n}", f"no file {ref!r}")
                    )
                continue
            sym = SYMBOL_REF.match(ref)
            if not sym:
                continue
            module, name = sym.groups()
            for base in cfg.code_dirs:
                candidate = _normalize(f"{base}/{module}.py")
                if candidate in fileset:
                    source = (root / candidate).read_text(encoding="utf-8")
                    if not _defines(source, name):
                        problems.append(
                            Problem(
                                "code-refs",
                                f"{doc.path}:{n}",
                                f"{candidate} defines no {name!r}",
                            )
                        )
                    break
    return problems


def sentences(doc: Doc) -> list[tuple[int, str]]:
    """(line, normalized sentence) for the prose paragraphs of a doc."""
    out: list[tuple[int, str]] = []
    para: list[tuple[int, str]] = []

    def flush() -> None:
        if not para:
            return
        joined = " ".join(t for _, t in para)
        for s in re.split(r"(?<=[.!?])\s+", joined):
            norm = re.sub(r"[^\w\s]", "", s.lower())
            norm = re.sub(r"\s+", " ", norm).strip()
            out.append((para[0][0], norm))
        para.clear()

    for n, line in prose_lines(doc):
        stripped = line.strip()
        if not stripped or stripped.startswith(("|", "#", "<")):
            flush()
            continue
        if re.match(r"^([-*+]|\d+\.)\s", stripped):
            flush()
            stripped = re.sub(r"^([-*+]|\d+\.)\s+", "", stripped)
        para.append((n, stripped.lstrip("> ")))
    flush()
    return out


def check(
    root: Path, cfg: Config, base: str | None = None
) -> tuple[list[Problem], list[str]]:
    """Run every check. Return (problems, notices)."""
    files = ls_files(root)
    docs = load_docs(root, cfg, files)
    problems: list[Problem] = []
    notices: list[str] = []
    ids: dict[str, str] = {}
    exceptions = []

    for doc in docs:
        if doc.id in ids:
            problems.append(
                Problem(
                    "front-matter",
                    doc.path,
                    f"id {doc.id!r} also used by {ids[doc.id]}",
                )
            )
        ids[doc.id] = doc.path

    for doc in docs:
        cap = cfg.caps.get(doc.kind)
        if cap is None:  # uncapped kinds (the user guide) get only the link check
            continue
        if doc.meta_error:
            problems.append(Problem("front-matter", doc.path, doc.meta_error))
            continue
        if not FRONT_MATTER.match(doc.text):
            problems.append(
                Problem("front-matter", doc.path, "no front matter (title, summary)")
            )
            continue
        for key in (
            ("name", "description")
            if doc.path.endswith("/SKILL.md")
            else ("title", "summary")
        ):
            if not doc.meta.get(key):
                problems.append(Problem("front-matter", doc.path, f"no {key!r}"))
        for rel in doc.meta.get("related") or []:
            if rel not in ids:
                problems.append(
                    Problem("front-matter", doc.path, f"related {rel!r} is not a doc")
                )

        # Length.
        limit = cap
        if "max_lines" in doc.meta:
            reason = str(doc.meta.get("exception") or "").strip()
            if not reason:
                problems.append(
                    Problem("length", doc.path, "max_lines needs an 'exception' reason")
                )
            if int(doc.meta["max_lines"]) > cap * 1.5:
                problems.append(
                    Problem(
                        "length",
                        doc.path,
                        f"max_lines is more than 1.5 x the cap of {cap}",
                    )
                )
            limit = int(doc.meta["max_lines"])
            exceptions.append(f"{doc.path}: {limit} lines ({reason})")
        if len(doc.lines) > limit:
            problems.append(
                Problem(
                    "length",
                    doc.path,
                    f"{len(doc.lines)} lines, cap {limit} for kind {doc.kind!r}. "
                    "Make it shorter.",
                )
            )
        for n, line in prose_lines(doc):
            if (
                len(line) <= cfg.line_width
                or line.lstrip().startswith("|")
                or "http" in line
            ):
                continue
            problems.append(
                Problem(
                    "length",
                    f"{doc.path}:{n}",
                    f"line has {len(line)} characters, cap {cfg.line_width}",
                )
            )

        # History.
        patterns = cfg.history.get("all", []) + cfg.history.get(doc.kind, [])
        for n, line in prose_lines(doc):
            plain = CODE_SPAN.sub("", line)
            for pattern in patterns:
                m = re.search(pattern, plain)
                if m:
                    problems.append(
                        Problem(
                            "history",
                            f"{doc.path}:{n}",
                            f"{m.group(0)!r}. {HISTORY_FIX}",
                        )
                    )

        problems += check_code_refs(root, cfg, doc, files)

        if doc.kind == "design":
            problems += check_design(root, doc, files)

    if len(exceptions) > cfg.max_exceptions:
        problems.append(
            Problem(
                "length",
                "pyproject.toml",
                f"{len(exceptions)} length exceptions, "
                f"at most {cfg.max_exceptions} are allowed",
            )
        )
    notices += [f"length exception: {e}" for e in exceptions]

    for budget in cfg.budgets:
        total = sum(len((root / p).read_text().splitlines()) for p in budget["files"])
        if total > budget["max_lines"]:
            problems.append(
                Problem(
                    "length",
                    " + ".join(budget["files"]),
                    f"{total} lines together, cap {budget['max_lines']}",
                )
            )

    problems += check_coverage(root, cfg, docs, files)
    problems += check_links(root, cfg, files)
    problems += check_doc_refs(root, cfg, files)
    problems += check_duplicates(cfg, [d for d in docs if d.kind in cfg.caps])
    if base:
        if ref_exists(root, base):
            design = [d for d in docs if d.kind == "design"]
            notices += goal_changes(root, base, design)
        else:
            # A missing base would make the goal-change report silently empty.
            problems.append(
                Problem("git", base, "no such git ref. Fetch it, or drop --base.")
            )
    return problems, notices


def check_design(root: Path, doc: Doc, files: list[str]) -> list[Problem]:
    problems = []
    secs = sections(doc)
    for name in REQUIRED_DESIGN_SECTIONS:
        if name not in secs:
            problems.append(Problem("sections", doc.path, f"no '## {name}' section"))
    goals = secs.get("Goals", "")
    if goals and not re.search(r"\bG1\b", goals):
        problems.append(Problem("sections", doc.path, "number the goals G1, G2, ..."))
    globs = doc.meta.get("implements")
    if not globs:
        problems.append(
            Problem("front-matter", doc.path, "a design doc needs 'implements'")
        )
        return problems
    for g, matched in expand(root, globs, files).items():
        if not matched:
            problems.append(
                Problem("front-matter", doc.path, f"glob {g!r} matches no file")
            )
    want = source_hash(root, doc_sources(root, doc, files))
    have = str(doc.meta.get("source_hash") or "")
    if have != want:
        detail = drift_detail(root, doc, files)
        problems.append(
            Problem(
                "drift",
                doc.path,
                f"source_hash {have or '(none)'} != {want}.\n{detail}",
            )
        )
    return problems


def drift_detail(root: Path, doc: Doc, files: list[str]) -> str:
    secs = sections(doc)
    out = []
    try:
        last = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", doc.path],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if last:
            changed = subprocess.run(
                [
                    "git",
                    "log",
                    "--format=  %h %s",
                    f"{last}..HEAD",
                    "--",
                    *doc_sources(root, doc, files),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.rstrip()
            if changed:
                out.append(
                    "    Commits to its sources since the doc last changed:\n" + changed
                )
    except (OSError, subprocess.CalledProcessError):
        pass
    for name in ("Goals", "Non-goals"):
        if secs.get(name):
            out.append(
                f"    {name}:\n"
                + "\n".join("      " + s for s in secs[name].splitlines())
            )
    out.append("    " + DRIFT_FIX.format(id=doc.id))
    return "\n".join(out)


def check_coverage(
    root: Path, cfg: Config, docs: list[Doc], files: list[str]
) -> list[Problem]:
    covered: set[str] = set()
    for doc in docs:
        if doc.kind == "design":
            covered |= set(doc_sources(root, doc, files))
    problems = []
    for f in files:
        if not any(glob_match(f, g) for g in cfg.coverage):
            continue
        if f in covered or any(glob_match(f, g) for g in cfg.uncovered):
            continue
        problems.append(
            Problem("coverage", f, "no design doc lists this file in 'implements'")
        )
    return problems


def check_duplicates(cfg: Config, docs: list[Doc]) -> list[Problem]:
    seen: dict[str, tuple[str, int]] = {}
    problems: list[Problem] = []
    for doc in docs:
        for n, s in sentences(doc):
            if len(s.split()) < cfg.duplicate_min_words:
                continue
            other = seen.get(s)
            if other and other[0] != doc.path:
                found = Problem(
                    "duplicate",
                    f"{doc.path}:{n}",
                    f"same sentence as {other[0]}:{other[1]}. Keep one, link to it.",
                )
                if not any(
                    p.where == found.where and p.message == found.message
                    for p in problems
                ):
                    problems.append(found)
            elif not other:
                seen[s] = (doc.path, n)
    return problems


def ref_exists(root: Path, ref: str) -> bool:
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def goal_changes(root: Path, base: str, docs: list[Doc]) -> list[str]:
    notices = []
    for doc in docs:
        try:
            old = subprocess.run(
                ["git", "show", f"{base}:{doc.path}"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError):
            continue
        meta, _ = parse_meta(old)
        before = sections(Doc(doc.id, doc.path, doc.kind, old, meta))
        after = sections(doc)
        for name in ("Goals", "Non-goals"):
            if before.get(name, "") != after.get(name, ""):
                notices.append(
                    f"goal change: {doc.path} '## {name}' changed against {base}. "
                    "The PR body needs a 'Goal changes' section "
                    "that the user confirmed."
                )
    return notices


# -------------------------------------------------------------------------- commands


def find_doc(docs: list[Doc], ident: str) -> Doc:
    for doc in docs:
        if ident in (doc.id, doc.path):
            return doc
    sys.exit(f"[docs] no doc {ident!r}. Run: python ci/docs.py list")


def changed_files(root: Path, base: str) -> list[str]:
    out: set[str] = set()
    for cmd in (
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        ["git", "diff", "--name-only", "HEAD"],
    ):
        try:
            res = subprocess.run(
                cmd, cwd=root, capture_output=True, text=True, check=True
            )
            out |= set(res.stdout.split())
        except (OSError, subprocess.CalledProcessError):
            pass
    return sorted(out)


def governing(
    root: Path, docs: list[Doc], files: list[str], paths: list[str]
) -> dict[str, list[Doc]]:
    sources = {
        d.id: set(doc_sources(root, d, files)) for d in docs if d.kind == "design"
    }
    by_id = {d.id: d for d in docs}
    return {p: [by_id[i] for i, s in sources.items() if p in s] for p in paths}


def emit(args: argparse.Namespace, data: Any, text: str) -> None:
    print(json.dumps(data, indent=2) if args.json else text)


def cmd_list(args: argparse.Namespace, root: Path, cfg: Config) -> int:
    docs = [d for d in load_docs(root, cfg) if not args.kind or d.kind == args.kind]
    rows = [
        {
            "id": d.id,
            "kind": d.kind,
            "path": d.path,
            "lines": len(d.lines),
            "cap": d.meta.get("max_lines") or cfg.caps.get(d.kind),
            "title": d.title,
            "summary": d.summary,
        }
        for d in docs
    ]
    width = max((len(r["id"]) for r in rows), default=0)
    text = "\n".join(
        f"{r['id']:<{width}}  {r['kind']:<9} "
        f"{r['lines']:>4}/{r['cap'] or '-':<4} {r['title']}"
        + (f"\n{'':<{width}}  {r['summary']}" if r["summary"] and args.long else "")
        for r in rows
    )
    emit(args, rows, text)
    return 0


def cmd_read(args: argparse.Namespace, root: Path, cfg: Config) -> int:
    doc = find_doc(load_docs(root, cfg), args.id)
    body = doc.lines[doc.body_start :]
    pages = max(1, -(-len(body) // args.page_size))
    page = min(max(args.page, 1), pages)
    start = (page - 1) * args.page_size
    chunk = body[start : start + args.page_size]
    first = doc.body_start + start + 1
    footer = (
        f"-- {doc.path} lines {first}-{first + len(chunk) - 1}, page {page} of {pages}"
    )
    if page < pages:
        footer += f". Next: python ci/docs.py read {doc.id} --page {page + 1}"
    emit(
        args,
        {
            "id": doc.id,
            "path": doc.path,
            "meta": doc.meta,
            "page": page,
            "pages": pages,
            "first_line": first,
            "lines": chunk,
        },
        "\n".join(chunk) + "\n" + footer,
    )
    return 0


def cmd_outline(args: argparse.Namespace, root: Path, cfg: Config) -> int:
    doc = find_doc(load_docs(root, cfg), args.id)
    heads = []
    in_fence = False
    for i, line in enumerate(doc.lines, 1):
        if FENCE.match(line):
            in_fence = not in_fence
        h = None if in_fence else HEADING.match(line)
        if h and i > doc.body_start:
            body_line = i - doc.body_start
            heads.append(
                {
                    "line": i,
                    "level": len(h.group(1)),
                    "title": h.group(2),
                    "page": (body_line - 1) // args.page_size + 1,
                }
            )
    emit(
        args,
        heads,
        "\n".join(
            f"{h['line']:>5} p{h['page']:<3}{'  ' * (h['level'] - 1)}{h['title']}"
            for h in heads
        ),
    )
    return 0


def cmd_search(args: argparse.Namespace, root: Path, cfg: Config) -> int:
    pattern = re.compile(args.text if args.regex else re.escape(args.text), re.I)
    hits = []
    for doc in load_docs(root, cfg):
        if args.kind and doc.kind != args.kind:
            continue
        heading = ""
        for i, line in enumerate(doc.lines, 1):
            h = HEADING.match(line)
            if h:
                heading = h.group(2)
            if i > doc.body_start and pattern.search(line):
                hits.append(
                    {"id": doc.id, "line": i, "heading": heading, "text": line.strip()}
                )
    emit(
        args,
        hits,
        "\n".join(f"{h['id']}:{h['line']}  {h['heading']} > {h['text']}" for h in hits)
        or "no match",
    )
    return 0


def cmd_for(args: argparse.Namespace, root: Path, cfg: Config) -> int:
    files = ls_files(root)
    docs = load_docs(root, cfg, files)
    paths = args.paths or [p for p in changed_files(root, args.base) if p in files]
    paths = [
        Path(p).resolve().relative_to(root).as_posix() if Path(p).is_absolute() else p
        for p in paths
    ]
    gov = governing(root, docs, files, paths)
    by_doc: dict[str, dict[str, Any]] = {}
    for p, ds in gov.items():
        for d in ds:
            entry = by_doc.setdefault(d.id, {"doc": d, "files": []})
            entry["files"].append(p)
    ungoverned = [p for p, ds in gov.items() if not ds]
    data = {
        "docs": [
            {
                "id": i,
                "path": e["doc"].path,
                "files": e["files"],
                "goals": sections(e["doc"]).get("Goals", ""),
                "non_goals": sections(e["doc"]).get("Non-goals", ""),
            }
            for i, e in by_doc.items()
        ],
        "ungoverned": ungoverned,
    }
    out = []
    for d in data["docs"]:
        out.append(f"== {d['id']} ({d['path']}) governs {', '.join(d['files'])}")
        out.append("Goals:\n" + d["goals"])
        if d["non_goals"]:
            out.append("Non-goals:\n" + d["non_goals"])
        out.append(f"Full doc: python ci/docs.py read {d['id']}\n")
    if ungoverned:
        out.append("No design doc governs: " + ", ".join(ungoverned))
    emit(args, data, "\n".join(out) or "no files")
    return 0


def cmd_stamp(args: argparse.Namespace, root: Path, cfg: Config) -> int:
    files = ls_files(root)
    docs = [d for d in load_docs(root, cfg, files) if d.kind == "design"]
    if args.all:
        targets = docs
    elif args.changed:
        targets = [
            d
            for d in docs
            if str(d.meta.get("source_hash"))
            != source_hash(root, doc_sources(root, d, files))
        ]
    else:
        targets = [find_doc(docs, i) for i in args.ids]
    for doc in targets:
        new = source_hash(root, doc_sources(root, doc, files))
        fm = FRONT_MATTER.match(doc.text)
        if not fm:
            sys.exit(f"[docs] {doc.path} has no front matter")
        block = fm.group(1)
        if re.search(r"^source_hash:.*$", block, re.M):
            block = re.sub(
                r"^source_hash:.*$", f"source_hash: {new}", block, count=1, flags=re.M
            )
        else:
            block += f"source_hash: {new}\n"
        (root / doc.path).write_text(
            f"---\n{block}---\n" + doc.text[fm.end() :], encoding="utf-8"
        )
        print(f"stamped {doc.id}: {new}")
    return 0


def cmd_check(args: argparse.Namespace, root: Path, cfg: Config) -> int:
    problems, notices = check(root, cfg, args.base)
    if args.json:
        print(
            json.dumps(
                {"problems": [p.__dict__ for p in problems], "notices": notices},
                indent=2,
            )
        )
    else:
        for p in problems:
            print(p)
        for n in notices:
            print(f"notice: {n}")
        print(f"{len(problems)} problem(s)." if problems else "Docs are clean.")
    return 1 if problems else 0


def cmd_hook(args: argparse.Namespace, root: Path, cfg: Config) -> int:
    """PostToolUse hook: name the design docs that govern the edited file."""
    try:
        payload = json.load(sys.stdin)
        path = (
            Path(payload["tool_input"]["file_path"])
            .resolve()
            .relative_to(root)
            .as_posix()
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 0
    if not any(glob_match(path, g) for g in cfg.coverage):
        return 0
    files = ls_files(root)
    docs = governing(root, load_docs(root, cfg, files), files, [path])[path]
    ids = (
        ", ".join(d.id for d in docs)
        or "none (add the file to a design doc's 'implements')"
    )
    msg = (
        f"{path} is governed by design doc(s): {ids}. Read their goals with "
        f"`python ci/docs.py for {path}` and keep the doc true; CI fails on drift."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": msg,
                }
            }
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print JSON")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "list", parents=[common], help="list the docs with kind, length and title"
    )
    p.add_argument("--kind")
    p.add_argument("--long", action="store_true", help="also print each summary")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("read", parents=[common], help="print a doc one page at a time")
    p.add_argument("id")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--page-size", type=int, default=80)
    p.set_defaults(func=cmd_read)

    p = sub.add_parser(
        "outline", parents=[common], help="print a doc's headings with line and page"
    )
    p.add_argument("id")
    p.add_argument("--page-size", type=int, default=80)
    p.set_defaults(func=cmd_outline)

    p = sub.add_parser("search", parents=[common], help="find text in the docs")
    p.add_argument("text")
    p.add_argument("--kind")
    p.add_argument("--regex", action="store_true")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser(
        "for",
        parents=[common],
        help="print the design docs and goals that govern files",
    )
    p.add_argument("paths", nargs="*")
    p.add_argument("--base", default="origin/main")
    p.set_defaults(func=cmd_for)

    p = sub.add_parser(
        "stamp", parents=[common], help="write the current source hash into design docs"
    )
    p.add_argument("ids", nargs="*")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true")
    group.add_argument(
        "--changed", action="store_true", help="only the docs that drifted"
    )
    p.set_defaults(func=cmd_stamp)

    p = sub.add_parser(
        "check", parents=[common], help="run every docs gate; exit 1 on a problem"
    )
    p.add_argument("--base", help="also report goal changes against this git ref")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser(
        "hook",
        parents=[common],
        help="Claude Code PostToolUse hook (reads JSON on stdin)",
    )
    p.set_defaults(func=cmd_hook)
    return parser


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "stamp" and not (args.ids or args.all or args.changed):
        parser.error("stamp needs doc ids, --all or --changed")
    return int(args.func(args, root, load_config(root)))


if __name__ == "__main__":
    raise SystemExit(main())
