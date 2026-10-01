---
name: open-work
description: Report the open work on Home Keeper and sort it by who must act next. Reads the open issues, the open PRs, the CHANGELOG and the to-do files in the repository. Use when asked what is open, what is actionable, what to work on next, or what waits on a release or on a user.
---

# Open work

This skill makes a report. It does not change anything. Many open issues need no
work: the fix is in a beta and waits for the next stable release, or a preview build
waits for a user to test it. This skill finds those, so that the report shows the
items that need the maintainer or an agent now.

Never comment on an issue or a PR, never close or label anything, and never merge
(see `AGENTS.md`, "Never comment on a GitHub issue"). Write the report in ASD-STE100
English.

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
# Each issue that a CHANGELOG section since the last stable fixes, by version.
for v in $(grep -oP '^## \[\K[^\]]+' CHANGELOG.md \
           | awk '/^[0-9]+\.[0-9]+\.[0-9]+$/{exit} {print}'); do
  python3 ci/release-issues.py --version "$v" --json \
    | python3 -c 'import json,sys; [print(sys.argv[1], i["number"]) for i in json.load(sys.stdin)]' "$v"
done
```

`ci/release-issues.py` is the same parser that `release.yml` uses to close issues, so
this list agrees with what the next release does. Only `(Fixes #N)` counts.

## 2. Know who wrote each comment

- **Maintainer:** `author_association` is `OWNER`, `MEMBER` or `COLLABORATOR`.
- **Bot:** a login that ends in `[bot]`, or `github-actions`. A bot comment is never
  the "last human comment". Two bot comments carry a state:
  - `<!-- home-keeper-release vX.Y.Z... -->`: release `vX.Y.Z...` has the fix.
  - `<!-- preview-release -->` on a PR: a preview build is available.
- **User:** any other author.

The **last human comment** on an issue is the newest comment that is not from a bot.
Look at the linked PR too: a user can give feedback on the PR and not on the issue.

## 3. Sort each item into one group

Put each open issue and each open PR into the first group that matches. Use one
group for each item. When an issue and its PR are in the same state, show them as
one line.

### A. Actionable now

The maintainer or an agent must act. Put these first, the most urgent at the top.

1. An issue with the `ha-beta-regression` label. The nightly run against the Home
   Assistant beta failed.
2. An open PR from the maintainer or an agent with failed CI, a merge conflict, or
   review threads that have no reply.
3. A user replied last, on the issue or on its linked PR. This includes feedback on
   a preview build or on a beta ("it does not work", "it works, thanks"). A "works"
   reply means: merge the PR, or move the issue to group B.
4. A PR from an outside contributor that has no maintainer review after its last
   push.
5. A new issue with no maintainer comment and no linked PR.
6. A Dependabot PR with green CI. It is ready to merge. A Dependabot PR with red CI
   is actionable work too: say what failed.
7. A fix in the CHANGELOG under a version that is not in the release list. The fix
   is merged, but no build has it. Cut a beta.

### B. Waits on a stable release

The issue number is in a `(Fixes #N)` line of a CHANGELOG section above the last
stable heading, and that version is a published beta. Nobody needs to do work on the
issue. `notify-issues` in `release.yml` closes it when the next stable ships. Give
the beta version for each one. When this group is not empty, say how many issues the
next stable release closes.

An issue in this group goes to group A when a user says after the beta comment that
the fix does not work.

### C. Waits on a tester

A linked open PR has the `preview-release` label, and the last human comment on the
issue and on the PR is from the maintainer (for example "I have a preview build,
0.26.0.dev351"). Give the number of days since that comment. After 14 days, mark the
item **stale** and suggest a choice: send a reminder, merge the PR without feedback,
or close it.

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

A draft PR from the maintainer, not in group C, with no push or comment for 14 days
or more. Suggest: finish it, or close it.

## 4. Read the to-do files in the repository

These are not issues, but they are open work. Report them in a short **Backlog**
section after the groups, one line each, with the file and heading:

- `IDEAS.md`: each section or bullet with **Status: blocked**, and the "Not fixed"
  and "Fixed in part" lists under "Open items from the ... deep review". For a
  blocked item, check the blocker when it is quick to check (for example
  `npm view <package> versions`), and move it to group A when it is not blocked now.
- `docs/*_PLAN.md`: each plan whose **Status** line is `proposed`, `planned`, or
  says that a part is still to do (for example "frontend next"). Skip the plans that
  say `implemented` or `shipped`.
- `TODO` and `FIXME` comments in `custom_components/`, `ci/` and `tests/`. Do not
  count names like `TODO_DOMAIN`. Search for `# TODO`, `// TODO` and `FIXME`.

Do not list each idea in `IDEAS.md`. Most of that file is a parking lot, and it is
not committed scope.

## 5. Write the report

Write the report in chat. Start with one line of totals, for example:
`11 open issues, 7 open PRs: 4 actionable, 2 wait on stable, 3 wait on testers.`

Then one section for each group that is not empty, in the order A to F, then the
Backlog. Each line has:

- the issue or PR number as a link, and the title,
- the linked PR or issue, if there is one,
- why it is in this group, in a few words (who spoke last, and when),
- for group A, the next step.

When the maintainer asks for it, or when the report is for other people, publish it
as an artifact. Do not post it on GitHub.
