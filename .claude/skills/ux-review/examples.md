# Worked examples

A short, fictional example of each stage's file — copy the **shape**, not the
content. The app below ("Expensr") is a placeholder to show format only; never
import its findings into a real review.

> Placeholder brief: **Expensr** — submit a work expense for reimbursement.
> Persona: a non-finance employee who wants to get paid back fast.
> `surface_type: guided-flow`. Core task: *submit one expense and know it's filed.*

---

## `raw.md` (Stage 1)

```
# Expensr UX Review — Raw Pass
Reviewed on: Desktop 1280×900

## Stage 1.2 — Task completion (headline check)

### Task: Submit one expense and know it's filed
Completion: ✗ BREAKS — at the Review step (04-review.png) the "Submit" button is
disabled with no explanation; the persona can't tell what's missing or finish.
Promise check: onboarding says "Submit in under a minute" — not delivered; the
persona stalls at Review with no path forward.

## Stage 1.3 — Encoding inventory (app-level)
| Encoding | Where | Meaning |
|---|---|---|
| green check | field rows | field validated ✓ consistent |
| amber dot | category pills | no discernible meaning — same amber on unrelated pills |
| red text | errors only | error ✓ consistent, also carries an icon |

## Stage 1.4 — Per-screen checklist

### Screen: Amount entry (02-amount.png)  [surface: guided-flow]
- next-action clear (item 2): ✓ single "Next" button, prominent
- right input/keyboard (item 7): ✗ amount field opens a text keyboard on mobile (03-mobile.png)
- inline validation (item 8): ✓ validates on blur, confirms with the green check
- spine — consistent color meaning: ✗ amber dot on pills has no meaning (see inventory)

### Screen: Review (04-review.png)
- next-action clear (item 2): ✗ "Submit" disabled, no reason shown
- progress/where-am-I (item 9): ✓ "Step 3 of 3" shown

## Stage 1.5 — Style inventory (app-level, measured)
Tool report: /tmp/review/style-01.md. Confirmed flags only:
- aesthetics item 1: ✗ 9 distinct font sizes incl. 13px AND 14px labels; field
  hints render at 11px (inventory §type; visible 02-amount.png)
- aesthetics item 5: ✗ "Receipt" card left edge 6px right of its siblings
  (inventory §alignment, delta 6px; visible 04-review.png)
- aesthetics item 6: ✓ no contrast failures (inventory §contrast)
- aesthetics item 8 (register vs brief "efficient, businesslike"): ✓ plain
  shapes, quiet palette, no novelty signals

## Stage 1.6 — Fresh-eyes probes (context-free, verbatim)
- 5-second (01-home.png): "An expense or receipt tracker; main thing is adding
  an expense; the big green button drew my eye." → matches brief ✓
- first-click, task "get money back for something you bought" (01-home.png):
  "I'd click the green '+ New expense' button, top right." → matches happy path ✓
- first-click, task "check whether an earlier claim was paid" (01-home.png):
  "Maybe the bell icon? Nothing obviously says past claims." → happy path
  expects the "History" tab — MISS, discoverability evidence
```

Note: answer passing items too (the `✓`s) — they're how coverage is proven.

---

## `findings.md` (Stage 2)

```
# Expensr — Findings

## F1 — Can't submit at Review (HIGH)
From raw: Stage 1.2 BREAK + Review item-2 ✗. The core task can't complete:
Submit is disabled with no stated reason. Headline; blocks the job.

## F2 — Amber pill dots are meaningless (LOW)
From raw: inventory + amount-screen spine ✗. A color with no meaning adds minor
noise; doesn't block the task. Kept as low.

## F3 — Past claims are undiscoverable from home (MEDIUM)
From raw: fresh-eyes first-click MISS ("maybe the bell icon?") on the
check-payment task. Empirical: a cold reader can't find History. Precedent:
transactional apps put past activity behind a top-level "History/Activity" tab
users expect to see labeled from home.

## F4 — Type scale sprawl, hints below legible size (MEDIUM, craft)
From raw: style inventory — 9 distinct sizes, 13px vs 14px duplicates, 11px
hints. Cites measurements; capped at medium (hints are still readable, barely).

## Dropped (failed an item, no real impact)
- Mobile amount keyboard (item 7 ✗): real, but the persona is desktop-primary
  per the brief → no finding.
- Receipt-card 6px misalignment: measured and confirmed, but isolated and below
  the noticeability bar for this persona → no finding (an example of a measured
  flag still failing the impact filter).
```

Each `✗` is a *candidate*; promote only what affects the goal, and say where you
dropped one and why.

---

## `report.md` (Stage 3)

Use the output format in `SKILL.md`. The Top-3 block and one finding, filled,
for shape:

```
## Top 3 changes
1. Unblock Submit at Review — show what's incomplete inline. (clears F1)
2. Add a labeled "History" tab to the home nav — a cold reader couldn't find
   past claims. (clears F3)
3. Collapse the type ramp to one scale (~5 sizes, nothing under 12px) — the
   sprawl is why the form reads busier than it is. (clears F4, shrinks F2's
   noise)

### 1. Can't submit at the Review step
- severity: high
- principle: feedback / next-action clarity
- scope: Review screen
- observation: "Submit" is disabled with no message saying what's incomplete (04-review.png).
- why it matters: This is the core task's final step — the persona reaches the
  end and cannot file the expense or tell what's wrong, so the job fails.
- suggested direction: Enable Submit, or show inline what's missing and link to it.
```

For an iteration review (prior report given), a "Since last review" block sits
above "What's working":

```
## Since last review
- fixed: F1 (Submit unblocked — completes end-to-end, 04-review.png), F4
- unchanged: F3 (History still unlabeled)
- regressed: the new inline error summary overlaps the footer at 1280×800
  (05-review-error.png) — new finding, see #2
```
