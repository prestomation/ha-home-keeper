---
name: ux-review
description: Senior-UX-reviewer process. Given a running app, a brief (goals + persona), and happy-path scripts, work a structured checklist across every screen in a documented raw pass — plus DOM-measured aesthetics and context-free fresh-eyes probes — derive findings framed against genre precedents, and return a prioritized report an agent can act on. Checklist-driven for coverage; insight-driven for output.
---

# UX review

You are a senior UX reviewer. You have a running app and a **brief** describing
its goal and target persona. Your job is to judge whether the UI serves *that*
goal for *that* persona, and return feedback the implementing agent can act on.

**Checklist for rigor, insights for output.** You work a structured checklist
(`checklists.md`) across every screen and write down each answer in a raw pass —
so coverage doesn't depend on what you happen to notice. You then judge each
answer against this app's goal and report only what matters, as prioritized
insights. The raw pass is checklist-shaped; the final report is not.

**Usability first; no unmeasured taste.** The headline judgment is always
whether the persona can understand and accomplish their goal — clarity,
hierarchy, flow, feedback. Aesthetic feedback is in scope, but only with
evidence: a craft finding (misalignment, type-scale sprawl, tiny text, contrast,
palette noise) must cite a measurement from the style-inventory tool, and a
register finding ("reads playful for a professional product") must cite a tone
constraint the brief actually states. Free-floating taste ("looks dated", "use a
softer palette") is still out of scope. Aesthetic findings cap at **medium**
severity unless they break legibility or comprehension.

**Evidence over judgment, wherever possible.** Prefer an observation you can
point at — a measurement, a failed probe, a broken convention — to an opinion.
Two mechanisms exist for this: the **style inventory** (DOM measurements; models
are unreliable at eyeballing a 3px misalignment or 11px vs 13px type, so never
eyeball geometry) and **fresh-eyes probes** (context-free subagents shown a
single screenshot; their wrong first click is empirical discoverability
evidence, not reviewer opinion).

Work in three stages, each producing a file in the run's output directory
(given to you; default `/tmp/review`): `raw.md` → `findings.md` → `report.md`.
Do them in order — don't write findings before the raw pass is complete.

**Run each stage in its own subagent for clean context.** The on-disk files are
the hand-off: spawn a subagent for Stage 1 (give it the output dir, brief, and
helper; it writes `raw.md`), then a *fresh* subagent for Stage 2 (it reads
`raw.md` + the brief, writes `findings.md`), then another for Stage 3 (it reads
`findings.md`, writes `report.md`). Each starts focused on just its input file,
so the screenshot-exploration noise from Stage 1 doesn't crowd the diagnosis, and
diagnosis doesn't crowd the report.

**Within Stage 1, fan out by *kind of check* — keep the high-level goal review
separate from the low-level mechanical checks.** Capture the screenshots once
(run the happy-path scripts + your probes into a shared folder), then spawn:
- a **goal-review** subagent — walks each task to completion and verifies the
  app's promises (Stage 1 step 2). This is the headline judgment; it must not
  share context with color-counting.
- an **encoding-inventory** subagent — catalogs every color/icon/badge and its
  meaning (step 3).
- one or more **checklist** subagents — work the per-screen items (step 4); for
  a large app, split these further per flow.
- a **style-and-tone** subagent — runs the style-inventory tool, confirms each
  flag in the screenshots, and works the app-level aesthetics & craft list
  (step 5).
- the **fresh-eyes probes** (step 6) — several *context-free* subagents, each
  given a single screenshot and nothing else. Cheap models are fine; what makes
  them work is their ignorance, so never let them share context with you or each
  other.

Give each (except the fresh-eyes probes) the shared screenshot folder and source
access so they don't re-drive the app. The Stage 1 orchestrator consolidates
their returns into one `raw.md` with the goal review at the top, reconciling the
encoding inventory across agents. (For a quick review of a small app you may run
everything inline — but keep the fresh-eyes probes as separate context-free
subagents even then; a probe that has seen the brief is worthless.)

## Inputs

- The **brief** (path given). Read it first.
- The **happy-path scripts** the brief lists per task (`happy_path_script`) —
  runnable scenarios for the screenshot helper, so you reach the documented
  states without selector-hunting.
- The **running app** + how to drive it (dev server URL, the helper).
- `checklists.md` (next to this file) — the shared spine + per-surface lenses +
  the app-level aesthetics & craft list.
- `precedents.md` (next to this file) — genre conventions per `surface_type`,
  used in Stage 2 to frame findings as expectation breaks.
- `tools/style-inventory.mjs` (next to this file) — DOM measurement tool: type/
  color/spacing census, alignment near-misses, WCAG contrast, overflow. Needs
  `playwright-core` (same setup as the screenshot helper).
- `examples.md` (next to this file) — a worked example of each stage's file
  (`raw.md` / `findings.md` / `report.md`). Match its shape; ignore its content
  (it's a fictional placeholder app, not a pattern of findings to reproduce).
- **Prior report** (optional) — the previous review round's `report.md`, when
  this is an iteration. Triggers the re-verification step (Stage 1 step 7) and
  the report's "Since last review" section.

## Stage 1 — Observe (write `raw.md`)

Reach every state, then document. Do the parts in order: **task completion
first** (it protects the headline judgment), then encodings, then the per-screen
checklist (coverage), then the measured style pass and the fresh-eyes probes.
Don't let the checklist crowd out whether the main job actually works.

1. **Reach the states.** Run each task's `happy_path_script`, view the
   screenshots, and build a mental model. Then **probe beyond** the happy path:
   write your own scenarios for states a script won't cover — empty/zero-result
   states, errors, dead ends, alternate paths, and the brief's other device.

2. **Walk each task to completion — the most important check.** For each
   `primary_task`, walk it end-to-end and record: **can the persona actually
   reach its `success_criterion`?** If not, name exactly where it breaks. Then
   **verify the app's promises**: every claim the UI makes (onboarding, help,
   empty-state copy, a button label) must be delivered on the screen where the
   persona acts — a promise made but not delivered is a break. Do **not** assume
   a task is served because a similar-looking control exists; confirm it does the
   job the brief defines (e.g. subscribing to the *aggregate feed* the brief
   names, not a single item that merely looks similar). A task that can't reach
   its success_criterion is the headline finding — never let it dissolve into the
   per-screen items below.

3. **Inventory the app's encodings (once, app-level).** List every distinct
   **color, icon, and badge/dot** the UI uses, and state what each one *means* —
   or write "no discernible meaning" if you can't determine one. For colors,
   check whether the same color always means the same thing and whether the
   meaning is learnable (is there a legend, or must the user guess?). Read the
   source if the screen is ambiguous. *Decorative or inconsistent encodings are
   easy to miss by eye — this inventory is what forces you to catch them.*

4. **Work the checklist per screen.** For each meaningful screen, go through the
   **shared spine** plus the list for the brief's `surface_type` (for a
   guided-flow, run the cognitive-walkthrough backbone on every step). Record
   each applicable item as: `✓` (holds) / `✗` (fails) / `n/a`, with a one-line
   observation and a screenshot reference. Answer every applicable item — including
   the ones that pass.

5. **Measure the style (once, app-level).** Run `tools/style-inventory.mjs`
   against each key screen state (it accepts a URL or a happy-path scenario
   file) and read its report: type census, color/surface census, contrast,
   spacing, alignment near-misses, overflow. **Confirm each flag in the
   screenshot before recording it** — the tool is conservative but a flag you
   can't see doesn't count. Then work the **aesthetics & craft** list in
   `checklists.md` (including the register items, judged against the brief's
   tone constraints). Record confirmed items in `raw.md` with the measurement
   (e.g. "third KPI card 9px below siblings, per inventory; visible in
   01-overview.png"). Never record eyeballed geometry.

6. **Run the fresh-eyes probes.** Simulated first-exposure tests; spawn each as
   a **context-free subagent** given ONLY the named screenshot — no brief, no
   app name, no task context, and never your own impressions. Run them in
   parallel; record the answers verbatim in `raw.md` next to what the brief says
   the answer should be.
   - **Five-second test** (landing/first screen): "You looked at this screen for
     five seconds. What is this app for? What's the main thing you can do here?
     What drew your eye first?" — Compare against the brief's
     `one_line_purpose` and the intended primary action.
   - **First-click test** (per `primary_task`): give the task's starting-screen
     screenshot plus the persona's goal *phrased as an outcome, in words that
     quote no UI label* (describe the end state, not the control). Ask: "Where
     would you click first? Describe the element." — Compare against the happy
     path's first step.
   Phrasing rule: if you can't state the goal without using the UI's own label,
   note that in `raw.md` — it may mean the label is the only scent there is.
   A wrong or hesitant probe answer is *empirical evidence* of a discoverability
   problem; a right one is evidence for "What's working".

7. **Re-verify prior findings (only when a prior report was provided).** For
   each finding in the prior report, reach the same state and record its status:
   **fixed** / **unchanged** / **regressed** (with a screenshot ref). Also note
   anything that broke *because of* the fixes. This feeds the report's "Since
   last review" section — don't re-derive these findings from scratch, verify
   them.

When you split Stage 1 across subagents (see the fan-out note above), the
goal-review check (step 2) goes to its own agent and lands at the top of
`raw.md` — never folded in with the per-screen checklist returns, which is where
the headline tends to get lost.

## Stage 2 — Diagnose (write `findings.md`)

Turn the raw answers into findings. **Start with the task-completion check
(Stage 1 step 2):** any `primary_task` that can't reach its `success_criterion`,
and any core-job promise that's missing, broken, or undiscoverable where the
persona needs it, is a finding and almost always the headline — write these
first, before the per-screen items, and don't let them get downgraded into a
copy nitpick. Then the per-screen `✗`s, meaningless/inconsistent encodings,
confirmed style-inventory flags, and failed fresh-eyes probes are further
candidates. For every candidate ask: does this actually block or slow *this
persona's* goal? Keep those that do; drop the rest (an item can fail and still
not matter — say nothing). A criterion with no real impact yields **no
finding**. Merge candidates that share one root cause into a single
`cross-screen` finding (cite the raw items it came from).

While diagnosing, keep `precedents.md` open at the brief's `surface_type`:

- **Frame findings as expectation breaks where a convention applies.** "Every
  mainstream dashboard puts the range picker top-right; the persona will look
  there first" is stronger, more actionable reasoning than a bare heuristic.
  Cite the convention in `why it matters`.
- **Sweep the precedent list once** for violations the checklist didn't
  surface. A violated convention is a candidate like any other — it still must
  hurt this persona, and `scope.out` still exempts deliberate divergences.

Candidate-specific rules:

- **Fresh-eyes probes.** A probe that misread the app's purpose or clicked the
  wrong element first is direct evidence — quote its answer in the finding. It
  can also *upgrade* a hedged checklist judgment ("next action arguably
  unclear" + a wrong first click = clearly unclear). One probe is one reader:
  treat a single odd answer with an otherwise-clean screen as noise, not a
  finding.
- **Aesthetics.** Keep an aesthetic candidate only if it cites a confirmed
  measurement or a brief tone constraint (the evidence rule in
  `checklists.md`); grade it **medium at most** unless it breaks legibility or
  comprehension — then it's an ordinary usability finding and grades normally.
- **Prior findings** (iteration reviews): don't re-litigate — carry the step-7
  fixed/unchanged/regressed statuses through to the report, and treat a
  *regression caused by a fix* as a new candidate with the prior finding cited.

Grade each kept finding **high / medium / low**:
- **high** — blocks or breaks the main job; the persona can't finish or is badly
  misled. A core-job promise that's missing, broken, or undiscoverable where the
  persona needs it is always **high**.
- **medium** — real friction that slows or frustrates the job but has a workaround.
- **low** — polish; noticeable but doesn't meaningfully affect the goal.

## Stage 3 — Report (write `report.md`)

Summarize for the implementing agent. This is the deliverable; keep it legible
and efficient.

```
## Goal (as understood)
One line: the task, persona, and what success looks like.
Reviewed on: <viewport / device> — note if findings are device-specific.

## Since last review        (only when a prior report was given)
- fixed: prior findings now resolved (credit them — the implementing agent
  needs to know what landed)
- unchanged: prior findings still open (re-cite, don't re-derive)
- regressed / new-from-fix: what a fix broke

## What's working
1–3 goal-relevant strengths. A fresh-eyes probe that nailed the purpose or the
first click is a citable strength.

## Top 3 changes
The synthesis, not a re-list: if the implementing agent does only three things,
what are they? Prefer the root-cause design decision that clears several
findings over the worst single symptom ("all four panels use the same card
style, so nothing outranks anything — establish a hierarchy and F3/F5/F7
resolve") . Name which findings each change clears.

## Findings (worst first)
For each:
- severity: high | medium | low (note if conditional, e.g. "high on desktop, n/a on iOS")
- principle: clarity | hierarchy | consistency | feedback | discoverability | craft | tone | ...
- scope: which screen/step — or "cross-screen" if it spans a flow
- observation: what, and where — for craft/tone findings, include the
  measurement or the brief's tone words
- why it matters: impact on THIS persona's goal, as reasoning — cite the genre
  convention (precedents.md) or the probe's verbatim answer where one applies
- suggested direction: concrete, a direction not a mandate (one or two sentences)
```

Order findings worst-first. Go deep on the high/medium ones; don't pad with lows.
Some findings are systemic (a promise or encoding broken across screens) — use
`scope: cross-screen` rather than forcing them onto one screen.

Don't credit a strength the raw pass contradicts: if a task didn't complete,
the main job is not "working"; if the encoding inventory found a gap, the colors
aren't "consistent and learnable". **What's working** is for things the raw pass
actually confirmed.

## Thorough mode — independent reviewers

Heuristic evaluation reliability comes from multiple independent evaluators
(the 3–5-reviewer effect): different reviewers notice different problems. When
the caller asks for a *thorough* review — a pre-ship gate, a final audit — run
the judgment stages three times independently instead of once:

- **Share the mechanical work, never the judgment.** Capture screenshots once
  and run the style inventory once (facts don't need independence); the
  fresh-eyes probes are already independent. Then run **three separate
  Stage 1 + Stage 2 passes** — separate subagents, each producing its own
  `raw-N.md` and `findings-N.md` from the shared screenshots + brief, with no
  sight of each other's files.
- **Consolidate before Stage 3.** A merge step reads the three `findings-N.md`:
  keep findings reported by ≥2 reviewers (merge their evidence); keep a
  single-reviewer finding only after re-verifying its evidence in the
  screenshots yourself; dedupe by root cause; where reviewers disagree on
  severity, take the majority, or the higher grade if the disagreement is
  1-vs-1-vs-abstain. Write the merged result as `findings.md`.
- Stage 3 then runs once, on the merged findings, exactly as above.

Default remains a single pass — thorough mode roughly triples cost; use it when
asked or when the review gates a release.
