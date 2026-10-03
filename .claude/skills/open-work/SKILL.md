---
name: open-work
description: Report the open work on Home Keeper and sort it by who must act next, and show a draft of the CHANGELOG for the next stable release. Reads the open issues, the open PRs, the CHANGELOG and the to-do files in the repository. Use when asked what is open, what is actionable, what to work on next, what waits on a release or on a user, or what the next stable release will contain.
---

# Open work

This skill makes a report. It does not change anything. Many open issues need no work: the fix
is in a beta and waits for the stable release, or a preview build waits for a tester. The
report finds those, shows the items that need the maintainer or an agent now, and shows a draft
of the CHANGELOG for the next stable release. Use only the GitHub read tools (`list_*`,
`issue_read`, `pull_request_read`). Never comment, close, label, edit or merge (see
`AGENTS.md`, "Never comment on a GitHub issue"). A step that the report suggests, such as a
reminder, is for the maintainer. Do not do it. Write the report in ASD-STE100 English.

## 1. Collect the data

Use the GitHub MCP tools (owner `prestomation`, repo `ha-home-keeper`). Make independent calls
together.

1. `list_issues`, state `OPEN`, all pages. `list_pull_requests`, state `open`.
2. `list_releases`, the last 30: `tag_name`, `prerelease`, `published_at`. The newest
   release with `prerelease: false` is the **last stable**.
3. For each issue: `issue_read` with `get` (for `closed_by_pull_requests`, the linked PRs),
   and with `get_comments` when it has comments. For each open PR: `pull_request_read` for
   comments, reviews, check status and mergeable state.

The local clone has no tags, so use the release list to know if a version is out. List the
issues that each CHANGELOG section newer than the last stable fixes:

```bash
# Stops at the first stable heading. An empty section makes release-issues.py exit 1: skip it.
for v in $(grep -oP '^## \[\K[^\]]+' CHANGELOG.md \
           | awk '/^[0-9]+\.[0-9]+\.[0-9]+$/{exit} {print}'); do
  json=$(python3 ci/release-issues.py --version "$v" --json 2>/dev/null) || continue
  printf '%s' "$json" | python3 -c 'import json,sys; [print(sys.argv[1], i["number"]) for i in json.load(sys.stdin)]' "$v"
done
```

`ci/release-issues.py` is the parser that `release.yml` uses to close issues, so this list
agrees with the next release. Only `(Fixes #N)` counts.

## 2. Know who wrote each comment

- **Maintainer:** `author_association` is `OWNER`, `MEMBER` or `COLLABORATOR`.
- **Bot:** a login that ends in `[bot]`, or `github-actions`. Two bot comments carry a
  state: `<!-- home-keeper-release vX.Y.Z... -->` (that release has the fix) and, on a PR,
  `<!-- preview-release -->` (a preview build is available; use the newest one).
- **User:** any other author.

The **last human comment** is the newest comment that is not from a bot. Look at the linked
PR too: a user can give feedback there and not on the issue.

## 3. Sort each item into one group

Put each open issue and PR into the first group that matches, in the order A to G. When an
issue and its PR are in the same state, show them as one line.

### A. Actionable now

The maintainer or an agent must act. Show the items in this order of urgency:

1. An issue with the `ha-beta-regression` label: the nightly run against the Home
   Assistant beta failed.
2. An open PR from the maintainer or an agent with failed CI, a merge conflict, or review
   threads with no reply.
3. A user replied last, on the issue or its linked PR. This includes feedback on a preview
   build or a beta, also when the fix is in a beta (A comes before B). A "works" reply on a
   preview build means: merge the PR. A "works" reply on a beta needs no step: say so.
4. A PR from an outside contributor with no maintainer review after its last push.
5. A new issue with no maintainer comment and no linked PR.
6. A Dependabot PR. With green CI it is ready to merge; with red CI, say what failed.
7. A fix in the CHANGELOG under a version that is not in the release list. No build has
   it. Cut a beta.

### B to G. Items that wait

- **B. Waits on a stable release.** The issue is in a `(Fixes #N)` line of a section newer
  than the last stable, and that version is a published beta. `notify-issues` in
  `release.yml` closes it when the stable ships. Give the beta version, and say how many
  issues the next stable closes.
- **C. Waits on a tester.** A linked open PR has the `preview-release` label, and the last
  human comment on the issue and the PR is from the maintainer. Give the days since that
  comment. After 14 days, mark it **stale**: the maintainer can send a reminder, merge
  without feedback, or close it.
- **D. Waits on the reporter.** The last human comment is from the maintainer, it asks a
  question or for logs, and there is no preview build. Give the days. After 30 days, mark
  it **stale**.
- **E. Waits on the maintainer to decide.** A design question for the maintainer (for
  example a choice between mockup options) with no linked PR. Keep these apart from group
  A so that an agent does not start them.
- **F. Stale draft PR.** A draft PR, not in group C, with no push or comment for 14 days.
- **G. Other.** An item that matches no rule. Give the reason, and say that a rule is
  missing.

## 4. Read the to-do files in the repository

These are open work that is not in issues. Report them in a short **Backlog** section
after the groups, one line each, with the file and heading:

- `IDEAS.md`: each section whose text has **Blocked on:** and the blocker, and the
  "Not fixed" and "Fixed in part" lists under "Open items from the ... deep review". When
  one command can check a blocker (for example `npm view <package> versions`), check it.
  When the blocker is gone, mark the item **unblocked**. Do not list each idea: most of
  the file is a parking lot, not committed scope.
- The backlog docs: `python3 ci/docs.py list --kind backlog`. Give each one with its title.
- The docs gate: `python3 ci/docs.py check`. Report each problem as one Backlog line.
- `TODO` and `FIXME` comments (this search does not find names like `TODO_DOMAIN`):

  ```bash
  grep -rnE '(#|//|/\*|<!--)\s*(TODO|FIXME)\b' custom_components ci tests \
      --exclude-dir=node_modules --exclude-dir=dist
  ```

## 5. Draft the CHANGELOG for the next stable release

The draft is for the report only. Do not write it to `CHANGELOG.md`. The **next stable** is
the newest beta section without its suffix (`0.29.0b3` gives `0.29.0`). When no section is
newer than the last stable, say "No changes since vX.Y.Z" and stop. When `CHANGELOG.md` has
no `## [X.Y.Z]` heading for the last stable, the loops read every section: write no draft,
and say that the heading is missing.

Get the text of each section newer than the last stable:

```bash
for v in $(grep -oP '^## \[\K[^\]]+' CHANGELOG.md \
           | awk '/^[0-9]+\.[0-9]+\.[0-9]+$/{exit} {print}'); do
  printf '=== %s\n' "$v"
  python3 ci/release-issues.py --version "$v" --notes 2>/dev/null
done
```

Then get the bullets that open PRs add. For each open PR not from Dependabot, use
`pull_request_read` with `get_files`. When `CHANGELOG.md` is in the list, use `get_diff`. Keep
each added line that starts with `+- **` and the following lines that start with `+` and
spaces. Keep each bullet as written. When the diff changes an existing bullet, show the new
text in place of the old (the `-` lines of the hunk), and mark it with the PR number.

Write the draft as the stable section, by the `AGENTS.md` rule "A stable release's
`## [X.Y.Z]` notes describe what changed since the last _stable_ release":

- Write for a user who upgrades from the last stable. Do not show the betas.
- Put all beta bullets into one `### Added`, `### Changed` and `### Fixed`. A feature that
  a beta added is in **Added**, also when a later beta changed it.
- A `### Changed` bullet that changes only a feature that is new since the last stable:
  find the one Added bullet whose bold lead or link names the same feature or page. If
  the change is visible in the stable, add its text after the bold lead to that Added
  bullet; if the result has more than 3 sentences, keep it in `### Changed` and put it on
  **Check before release**. If it changes only something a beta did, remove it. If zero
  or more than one Added bullet match, keep it in `### Changed`.
- `### Fixed` gives each `(Fixes #N)` from the sections. Then check the commits since the
  last stable (replace `X.Y.Z`, for example `0.28.0`):

  ```bash
  git fetch -q --no-tags origin tag vX.Y.Z
  git log --format=%B vX.Y.Z..origin/main | python3 ci/release-issues.py --scan
  ```

  If the tag fetch fails, use the release commit:
  `git log --reverse --format=%H -S '## [X.Y.Z]' -- CHANGELOG.md | head -1`.
- Put each issue that `--scan` finds and the sections omit on **Check before release**:
  `notify-issues` does not close it.
- Put the open-PR bullets last, under **Pending, from open PRs**, with the PR number.
- After each merged bullet, give the beta that first shipped it, for example `(0.29.0b1)`.

## 6. Write the report

Write the report in chat. Start with one line of totals, for example: `11 open issues, 7 open
PRs: 4 actionable, 2 wait on stable, 3 wait on testers.` Then one section for each group that
is not empty (A to G), **Next stable (draft)**, and the Backlog. Start the draft with the
version and the last stable, for example `0.29.0, after v0.28.0. Tentative: this can change
before the release.` After the bullets, give **Pending, from open PRs**, then **Check before
release** when it is not empty. Each group line has the issue or PR number as a link and the
title, the linked PR or issue, why it is in this group (who spoke last, and when), and for
group A, the next step.

When the maintainer asks, or when the report is for other people, publish it as an
artifact. Do not post it on GitHub.
