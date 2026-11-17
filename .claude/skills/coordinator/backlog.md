---
title: Coordinator backlog rules
summary: The item template, the allowed values, the events that update the backlog and the audit that the coordinator runs after each change.
---

# Backlog rules

The backlog must match the facts at all times. It drifted once because no rule said when to
update it. The rules below say when, what and how to check.

## Item template

Every item in collection `items` has these fields. Never leave one out.

| Field | Value |
|---|---|
| `repo` | One repository of the scope in `SKILL.md`. |
| `title` | One line. Start with the issue or PR number when there is one. |
| `type` | `bug`, `feature`, `design`, `dependency` or `input`. |
| `status` | `inbox`, `ready`, `in-progress`, `waiting-operator`, `blocked`, `done`, `dropped`. |
| `priority` | `P0` to `P3`. |
| `labels` | From `agent-ready`, `needs-design`, `needs-operator`, `agent-in-progress`, `agent-blocked`, `ui`. |
| `links` | Every issue, PR and Artifact page of the item, as full `https://` URLs. |
| `notes` | A list of `{t, by, text}`. Add to it. Never remove a note of the maintainer. |
| `updated` | The UTC time of the last change. |

- The page shows only `links` as links. An Artifact URL in another field, or only in a
  note, is invisible. Put it in `links`.
- Use no other value for `status`, `type` or `labels`. The page does not know them and
  shows them wrongly. Map a new idea to the nearest value. Example: an item that waits
  for a PR to merge is `blocked`. An item that waits for a reporter is `blocked`.
- Extra fields are fine (`cost_usd`, `worker`, `next`). They never replace a field above.

## Events and what to update

Update the item in the same turn as the event. Do not batch it for later.

| Event | Update |
|---|---|
| A worker starts | `in-progress`, label `agent-in-progress`, the session id in a note. |
| A worker stops | The cost and result in a note, the head SHA, the label removed. Do the steps in `SKILL.md` "When a worker is done". |
| A PR opens | The PR URL in `links`. A note with the CI state. |
| CI or review changes | A note. Change the status only if the work state changed. |
| An Artifact is published | The URL in `links`. `waiting-operator`, label `needs-operator`, and a note with the numbered questions and the suggested answers. |
| The maintainer answers | A note by `operator` with the decision. Set the next status. |
| A PR merges | `done`, the merge SHA in a note, the agent labels removed. Add the `automerged` document if the rubric applied. Unblock the follow-up items. |
| A new outside issue or comment | A new item, or a note on the item. Never comment on the issue. |
| The maintainer gives a new rule | Add it to `SKILL.md` in a PR, and say so in a note. |

## Audit

Run the audit at the end of each turn that changed a state, and in each tick. Read the
item list again first. Do not trust what you wrote earlier.

1. Every open PR of the scope is in the `links` of exactly 1 item.
2. Every running worker session is in 1 item with status `in-progress`.
3. Every Artifact page that you or a worker published is in the `links` of its item.
4. Every `status`, `type`, `label` and `priority` is an allowed value. Every item has `repo`,
   `type`, `priority` and `updated`.
5. No `done` item has an open PR. No `in-progress` item lacks a live worker or an open PR.
6. Every archived worker has its cost in the notes of its item.
7. The scan times in `coord/notes` are current.

Fix every finding. Then say it in the report: "Backlog audit: clean", or the list of fixes.

## After a context compaction

Read `coord/notes` and this file first. Then run the audit before you do anything else.
