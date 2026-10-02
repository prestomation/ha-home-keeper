---
name: open-work
description: Report the open work on Home Keeper and sort it by who must act next, and show a draft of the CHANGELOG for the next stable release. Reads the open issues, the open PRs, the CHANGELOG and the to-do files in the repository. Use when asked what is open, what is actionable, what to work on next, what waits on a release or on a user, or what the next stable release will contain.
---

# Open work

This skill makes a report. It does not change anything. Many open issues need no
work: the fix is in a beta and waits for the next stable release, or a preview build
waits for a user to test it. This skill finds those, so that the report shows the
items that need the maintainer or an agent now. The report also shows a draft of
the CHANGELOG for the next stable release, so the maintainer can see what that
release will contain before they cut it.

Use only the GitHub read tools (`list_*`, `issue_read`, `pull_request_read`). Never
comment on an issue or a PR, never close, label or edit anything, and never merge
(see `AGENTS.md`, "Never comment on a GitHub issue"). When the report suggests a
step such as a reminder, it is a suggestion for the maintainer. Do not do it. Write
the report in ASD-STE100 English.

## 1. Collect the data

Use the GitHub MCP tools (owner `prestomation`, repo `ha-home-keeper`). Make the
independent calls together.

1. `list_issues`, state `OPEN`, all pages. Fields: number, title, labels, user,
   comments, created_at, updated_at.
2. `list_pull_requests`, state `open`. Fields: number, title, draft, labels, user,
   head, updated_at, body.
3. `list_releases`, the last 30. Keep `tag_name`, `prerelease` and `published_at`.
   The newest release with `prerelease: false` is the **last stable**.
4. For each open issue that has comments: `issue_read` with `get_comments`. For each
   issue: `issue_read` with `get`, to read `closed_by_pull_requests` (the linked PRs).
5. For each open PR: `pull_request_read` for its comments, reviews, check status and
   mergeable state.

Then read the repository (the local clone does not have the tags, so use the release
list from step 3 for "is this version out"):

```bash
# Each issue that a CHANGELOG section newer than the last stable fixes, by version.
# The loop stops at the first stable heading. A section with no text makes
# release-issues.py exit 1; that section has no fixes, so the loop skips it.
for v in $(grep -oP '^## \[\K[^\]]+' CHANGELOG.md \
           | awk '/^[0-9]+\.[0-9]+\.[0-9]+$/{exit} {print}'); do
  json=$(python3 ci/release-issues.py --version "$v" --json 2>/dev/null) || continue
  printf '%s' "$json" | python3 -c 'import json,sys; [print(sys.argv[1], i["number"]) for i in json.load(sys.stdin)]' "$v"
done
```

`ci/release-issues.py` is the same parser that `release.yml` uses to close issues, so
this list agrees with what the next release does. Only `(Fixes #N)` counts. The
CHANGELOG is newest first, so these are the sections above the last stable heading
in the file.

## 2. Know who wrote each comment

- **Maintainer:** `author_association` is `OWNER`, `MEMBER` or `COLLABORATOR`.
- **Bot:** a login that ends in `[bot]`, or `github-actions`. A bot comment is never
  the "last human comment". Two bot comments carry a state:
  - `<!-- home-keeper-release vX.Y.Z... -->`: release `vX.Y.Z...` has the fix.
  - `<!-- preview-release -->` on a PR: a preview build is available. The workflow
    edits one sticky comment, so use the newest comment with this marker.
- **User:** any other author.

The **last human comment** on an issue is the newest comment that is not from a bot.
Look at the linked PR too: a user can give feedback on the PR and not on the issue.

## 3. Sort each item into one group

Sort again on each run. Put each open issue and each open PR into the first group
that matches, in the order A to G. Use one group for each item. When an issue and its PR are in the same state, show them as
one line.

### A. Actionable now

The maintainer or an agent must act. The rules are in order of urgency. Show the
items in that order.

1. An issue with the `ha-beta-regression` label. The nightly run against the Home
   Assistant beta failed.
2. An open PR from the maintainer or an agent with failed CI, a merge conflict, or
   review threads that have no reply.
3. A user replied last, on the issue or on its linked PR. This includes feedback on
   a preview build or on a beta ("it does not work", "it works, thanks"). Because A
   comes before B, an issue with a fix in a beta is in this group when a user
   replied after the bot's beta comment. A "works" reply on a preview build means:
   merge the PR. A "works" reply on a beta needs no step: say so, and the item can
   wait for the stable.
4. A PR from an outside contributor that has no maintainer review after its last
   push.
5. A new issue with no maintainer comment and no linked PR.
6. A Dependabot PR with green CI. It is ready to merge. A Dependabot PR with red CI
   is actionable work too: say what failed.
7. A fix in the CHANGELOG under a version that is not in the release list. The fix
   is merged, but no build has it. Cut a beta.

### B. Waits on a stable release

The issue number is in a `(Fixes #N)` line of a CHANGELOG section above the last
stable heading (newer than the last stable), and that version is in the release
list as a published beta. A fix in a version that is not in the release list is
rule A7, not this group. Nobody needs to do work on the
issue. `notify-issues` in `release.yml` closes it when the next stable ships. Give
the beta version for each one. When this group is not empty, say how many issues the
next stable release closes.

### C. Waits on a tester

A linked open PR has the `preview-release` label, and the last human comment on the
issue and on the PR is from the maintainer (for example "I have a preview build,
0.26.0.dev351"). Give the number of days since that comment. After 14 days, mark the
item **stale**. The maintainer can then send a reminder, merge the PR without
feedback, or close it.

### D. Waits on the reporter

The last human comment is from the maintainer, it asks a question or asks for logs,
and there is no preview build. Give the number of days. After 30 days, mark it
**stale**.

### E. Waits on the maintainer to decide

A design question that the maintainer must answer, for example a choice between
options in a mockup, and no linked PR yet. These are actionable for the maintainer
but not for an agent. Keep them apart from group A so that an agent does not start
them.

### F. Draft PR with no recent activity

A draft PR from any author, not in group C, with no push or comment for 14 days or
more. The maintainer can finish it, or close it.

### G. Other

An item that matches no rule above. Give the reason in a few words. When an item is
in this group, a rule above is missing, so say that in the report.

## 4. Read the to-do files in the repository

These are not issues, but they are open work. Report them in a short **Backlog**
section after the groups, one line each, with the file and heading:

- `IDEAS.md`: each section or bullet with **Status: blocked**, and the "Not fixed"
  and "Fixed in part" lists under "Open items from the ... deep review". For a
  blocked item, check the blocker when one command can check it (for example
  `npm view <package> versions`). When the blocker is gone, keep the item in the
  Backlog and mark it **unblocked**.
- `docs/*_PLAN.md`: each plan whose **Status** line is `proposed`, `planned`, or
  says that a part is still to do (for example "frontend next"). Skip the plans that
  say `implemented` or `shipped`.
- `TODO` and `FIXME` comments. This search does not find names like
  `TODO_DOMAIN`:

  ```bash
  grep -rnE '(#|//|/\*|<!--)\s*(TODO|FIXME)\b' custom_components ci tests \
      --exclude-dir=node_modules --exclude-dir=dist
  ```

Do not list each idea in `IDEAS.md`. Most of that file is a parking lot, and it is
not committed scope.

## 5. Draft the CHANGELOG for the next stable release

This draft is for the report only. Do not write it to `CHANGELOG.md`. The
maintainer writes the real section when they cut the stable release.

The **next stable** version is the newest beta section with its suffix removed. For
example, `0.29.0b3` gives `0.29.0`. When no section is newer than the last stable,
there is no draft: say "No changes since vX.Y.Z" and stop this step.

First make sure that `CHANGELOG.md` has a `## [X.Y.Z]` heading for the last stable
from the release list. If it does not, the loops in step 1 and below read every
section in the file. Do not write a draft. Say in the report that the heading is
missing.

Get the text of each section newer than the last stable, newest first. These are
the same versions as the loop in step 1. That loop reads `--json` for the issue
list, and this one reads `--notes` for the bullets:

```bash
for v in $(grep -oP '^## \[\K[^\]]+' CHANGELOG.md \
           | awk '/^[0-9]+\.[0-9]+\.[0-9]+$/{exit} {print}'); do
  printf '=== %s\n' "$v"
  python3 ci/release-issues.py --version "$v" --notes 2>/dev/null
done
```

Then get the CHANGELOG bullets that the open PRs add. These are not merged, so they
are not certain:

- For each open PR that is not from Dependabot, use `pull_request_read` with
  `get_files`. When `CHANGELOG.md` is in the list, use `get_diff`. Keep each added
  line that starts with `+- **`, and the added lines after it that start with `+`
  and one or more spaces. The bullet stops at the first line that does not start
  that way.
- When the diff changes a bullet that is already in a section, and does not add
  one, the old text is in the removed (`-`) lines of the same hunk. Show the new
  text in place of the old text, and mark it with the PR number.

Write the draft as the stable section, with the rules in `AGENTS.md` ("A stable
release's `## [X.Y.Z]` notes describe what changed since the last _stable_
release"):

- Write it for a user who upgrades from the last stable. Do not show the betas.
- Put all the beta bullets into one `### Added`, one `### Changed` and one
  `### Fixed`. A feature that a beta added is in **Added**, also when a later beta
  changed it.
- A `### Changed` bullet that changes only a feature that is new since the last
  stable does not go in `### Changed`. The bold lead or the link of the bullet
  names the feature. Find the Added bullet whose bold lead or link names the same
  feature or the same documentation page. When the Changed bullet changes what a
  user sees in the stable release, add the text after its bold lead to that Added
  bullet. When the result has more than 3 sentences, do not merge: keep the bullet
  in `### Changed`, and put it on the **Check before release** list. When it
  changes only
  something that a beta did, remove it. When no Added bullet matches, or more than
  one matches, keep the bullet in `### Changed`.
- Keep each bullet as the CHANGELOG has it. Do not write the bullets again.
- `### Fixed` must give each `(Fixes #N)` from the sections above. Then do a check
  of the commits since the last stable. In the commands below, replace `X.Y.Z` with
  the last stable version, for example `0.28.0`. The local clone has no tags, so get
  the tag of the last stable first:

  ```bash
  git fetch -q --no-tags origin tag vX.Y.Z
  git log --format=%B vX.Y.Z..origin/main | python3 ci/release-issues.py --scan
  ```

  If the tag fetch fails, use the oldest commit that added the stable heading:
  `git log --reverse --format=%H -S '## [X.Y.Z]' -- CHANGELOG.md | head -1`. That
  is the release commit. A later commit that changes the heading again comes after
  it, so `--reverse` and `head -1` do not take it.
- When `--scan` finds an issue that the sections do not give, or a Changed bullet
  stays in `### Changed` for one of the reasons above, write it in a
  **Check before release** list at the end of the draft. The `notify-issues` job does not close an issue that the
  section does not give.
- Put the bullets from open PRs at the end, under the heading
  **Pending, from open PRs**, with the PR number on each bullet. Do not mix them
  into the merged bullets.
- Give the beta that first shipped each bullet in brackets after it, for example
  `(0.29.0b1)`. The report uses this to show what beta testers can use now. The
  real stable section does not have it.

## 6. Write the report

Write the report in chat. Start with one line of totals, for example:
`11 open issues, 7 open PRs: 4 actionable, 2 wait on stable, 3 wait on testers.`

Then one section for each group that is not empty, in the order A to G, then a
**Next stable (draft)** section with the draft from step 5, then the Backlog. Start
the draft section with the version and the last stable it follows, for example
`0.29.0, after v0.28.0. Tentative: this can change before the release.` After the
bullets, give **Pending, from open PRs**, then **Check before release** when it is
not empty. Each group
line has:

- the issue or PR number as a link, and the title,
- the linked PR or issue, if there is one,
- why it is in this group, in a few words (who spoke last, and when),
- for group A, the next step.

When the maintainer asks for it, or when the report is for other people, publish it
as an artifact. Do not post it on GitHub.
