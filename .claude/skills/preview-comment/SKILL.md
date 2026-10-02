---
name: preview-comment
description: Draft the maintainer's short comment that tells an issue reporter a preview build of the fix is ready to try, and post it on the issue only after the maintainer approves the exact text. Use only when the maintainer asks to post the preview comment, or to tell a reporter that a preview build is ready.
---

# Preview comment

This skill writes one comment on one issue: the note that a preview build of the fix
is ready, the version to install, how to install it, and that the PR may wait for
feedback. It is the only exception to `AGENTS.md`, "Never comment on a GitHub issue".
The exception holds only when the maintainer asks for this comment, and only after
the maintainer approves the exact text.

## The rules

- Post only when the maintainer asks for this comment in this conversation. Never
  post it because a PR, a check or another comment suggests it.
- Show the maintainer the exact text first, and post only after they approve that
  text. If they change it, show it again and post the approved version unchanged.
- Post one comment, on the issue the maintainer named. Do not edit, close or label
  anything, and do not comment on any other issue.

## 1. Find the version

1. Find the open PR that fixes the issue: its body has `Fixes #N`. If there is more
   than one, or none, ask the maintainer which PR.
2. Read the PR's comments (`pull_request_read`, method `get_comments`). Find the
   newest comment from `github-actions[bot]` with the marker `<!-- preview-release -->`.
   Its first code span is the version, for example `0.29.0.dev422`.
3. If the PR has no such comment, the preview has not been published. Say so: the PR
   needs the `preview-release` label and a finished `publish` job. Do not guess a
   version.

## 2. Write the text

Write it as the maintainer does: casual, 2 or 3 short sentences, no headings, no
greeting, no sign-off. Use this template and change only the version:

> This is available in preview build **{version}** if you'd like to try it out. In HACS, open Home Keeper → ⋮ → **Redownload**, turn on **Show beta versions**, and pick `{version}`. I'd like some feedback before I merge, so I may hold off until I hear from you.

The maintainer's earlier comments of this kind, for the voice:

- #306: "0.23.0.dev321 is available if you'd like to test"
- #346: "I've made an Attempt at this in v0.25.0.dev361. could you test and provide
  feedback before I merge?"
- #367: "This is available in preview build 0.28.0.dev397. If you'd like to try it
  out and provide feedback"

This is the maintainer's voice, so the ASD-STE100 rules for project text do not apply
to it. Do not add the Claude Code footer: the comment is posted for the maintainer, in
their words.

## 3. Confirm, then post

1. Show the maintainer the issue number, the PR, and the exact text in a quote block.
   Ask: "Post this on #N?"
2. Only after a clear yes, post it with `add_issue_comment` on the issue (not the
   PR), with the approved text and nothing else.
3. Reply with the link to the new comment.
