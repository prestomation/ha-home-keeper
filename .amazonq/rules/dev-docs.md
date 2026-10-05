---
title: Developer docs
summary: How the dev docs are typed, capped and checked, and how to keep a design doc true to the code.
---

# Developer docs

## Kinds and the tool

- Each dev doc starts with YAML front matter (`title`, `summary`). Its kind comes from its
  path (`[tool.docs-audit]` `kinds` in `pyproject.toml`): `docs/design/*.md` is design,
  `docs/*.md` is reference, `.amazonq/rules/*.md` is rules, `AGENTS.md`, `CLAUDE.md` and
  `RELEASE.md` are process, `IDEAS.md` is backlog, and `.claude/skills/**` is skill.
- `python3 ci/docs.py` finds and reads them:
  - `list [--kind K]` lists each doc with its kind, length and title.
  - `read <id>` prints a doc 1 page at a time. `outline <id>` prints its headings.
  - `search <text>` finds text in the docs.
  - `for <path>` prints the design docs and the goals that govern a file.
  - `check [--base origin/main]` runs every gate. `stamp <id>` writes a design doc's hash.
- **Before you change code, run `python3 ci/docs.py for <path>`** and read the goals and
  non-goals that it prints.

## Design docs

- The 15 docs in `docs/design/` say how each subsystem works and why. Each has Goals,
  Non-goals, Design, Trade-offs and One-way doors. The rules files say only what to do,
  and link to a design doc for the how.
- A design doc lists the files that implement it in `implements`, and the hash of those
  files in `source_hash`. When the code changes, `check` fails on drift. Then:
  1. Read the change against the doc's Goals and Non-goals.
  2. If the change works against a goal, stop and ask the user.
  3. Make the doc describe the code as it is now, as if it was always designed that way.
     Write no history. Git keeps it.
  4. Run `python3 ci/docs.py stamp <id>`.
- A PR that changes a design doc's Goals or Non-goals needs a **Goal changes** section in
  its body, and the maintainer must agree to it.
- Each new source file under `custom_components/home_keeper/` must be in the `implements`
  list of a design doc. `check` fails on a file that no doc covers.
- Work that is not built goes in `IDEAS.md`, never in a design doc. There are no plan
  files: a plan lives in the PR body.

## Caps and gates

| Kind | Line cap |
|---|---|
| design | 150 |
| reference | 300 |
| rules | 200 |
| process | 200 |
| backlog | 300 |
| skill | 200 |

- `CLAUDE.md` and `AGENTS.md` together are at most 250 lines, because every Claude
  session loads both.
- A prose line is at most 100 characters. Tables and code fences are exempt.
- A length exception (`max_lines` plus `exception: <reason>` in the front matter) is
  allowed for at most 2 docs in the repository. Shorten the doc before you ask for one.
- `check` also fails on history (`this PR`, `originally`, `Phase 2`), a broken link or
  anchor, a backticked file or `module.function` that does not exist, a doc path named in
  code that does not exist, and a sentence of 12 or more words that is in 2 docs. Keep
  a fact in 1 place and link to it.
- `lint.yml`'s `docs-audit` job runs `python3 ci/docs.py check --base origin/main`.

## Keep the rules current

- When a convention is set or changed, in a conversation, a review, or a PR, update the
  matching file in `.amazonq/rules/` in the same change. Update `AGENTS.md` too if it is a
  hard gate. A convention is not real until it is in the rules.
- A rule says what to do and, in 1 clause, why. Do not tell the story of the bug that
  made the rule. Do not explain a subsystem: link its design doc.
