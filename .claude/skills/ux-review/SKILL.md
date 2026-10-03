---
name: ux-review
description: Senior-UX-reviewer process. Given a running app, a brief (goals + persona), and happy-path scripts, work a structured checklist across every screen in a documented raw pass — plus DOM-measured aesthetics and context-free fresh-eyes probes — derive findings framed against genre precedents, and return a prioritized report an agent can act on. Checklist-driven for coverage; insight-driven for output.
---

# UX review

You are a senior UX reviewer. You have a running app and a **brief** that gives its goal and
target persona. Judge whether the UI serves *that* goal for *that* persona, and return
feedback that the implementing agent can act on.

**Checklist for rigor, insights for output.** Answer the checklist (`checklists.md`) on every
screen in a raw pass, so coverage does not depend on what you notice. Then report only what
matters for the goal, as prioritized insights.

**Usability first; no unmeasured taste.** The headline judgment is always whether the
persona can understand and do their job: clarity, hierarchy, flow, feedback. Aesthetic
feedback is in scope only with evidence. A craft finding (misalignment, type-scale sprawl,
tiny text, contrast, palette noise) must cite a style-inventory measurement. A register
finding ("reads playful for a professional product") must cite a tone constraint that the
brief states. Free-floating taste ("looks dated") is out of scope. Aesthetic findings are
**medium** at most, unless they break legibility or comprehension.

**Evidence over judgment.** Prefer an observation you can point at (a measurement, a failed
probe, a broken convention) to an opinion. Two mechanisms give it: the **style inventory**
(DOM measurements; never eyeball geometry, because models cannot see 3px or 11px vs 13px)
and **fresh-eyes probes** (context-free subagents shown one screenshot; a wrong first click
is empirical discoverability evidence).

## Stages and subagents

Work in three stages, in order. Each writes a file in the output directory (given; default
`/tmp/review`): `raw.md`, then `findings.md`, then `report.md`. **Run each stage in its own
subagent.** The files are the hand-off: Stage 1 gets the output
directory, brief and helper and writes `raw.md`. A *fresh* Stage 2 subagent reads `raw.md`
and the brief and writes `findings.md`. A Stage 3 subagent reads `findings.md` and writes
`report.md`. This keeps the screenshot noise of Stage 1 out of the diagnosis.

**In Stage 1, fan out by kind of check.** Capture the screenshots once (the happy-path
scripts and your probes, into a shared folder), then spawn:

- **goal review** (step 2): the headline judgment. It must not share context with color
  counting.
- **encoding inventory** (step 3), and one or more **checklist** subagents (step 4; split
  per flow for a large app).
- **style and tone** (step 5): runs the style-inventory tool and confirms each flag.
- the **fresh-eyes probes** (step 6): *context-free* subagents, each given one screenshot
  and nothing else. Cheap models are fine; their ignorance is what makes them work.

Give each one, except the probes, the screenshot folder and source access, so they do not
drive the app again. The Stage 1 orchestrator merges their returns into one `raw.md`, puts
the goal review at the top (never folded into the checklist returns, where the headline
gets lost), and reconciles the encoding inventory. For a quick review of a small app you
can run everything inline, but the probes must still be separate context-free subagents: a
probe that has seen the brief is worthless.

## Inputs

- The **brief** (path given). Read it first.
- The **happy-path scripts** that the brief lists per task (`happy_path_script`): runnable
  scenarios for the screenshot helper, so you reach the states without selector hunting.
- The **running app** and how to drive it (dev server URL, the helper). For this
  repository, read `SOURCE.md` first.
- `checklists.md`: the shared spine, the per-surface lenses, and the app-level aesthetics
  and craft list.
- `precedents.md`: genre conventions per `surface_type`, for Stage 2.
- `tools/style-inventory.mjs` (in this repository, `tools/style-inventory-ha.mjs`): the DOM
  measurement tool (type, color and spacing census, alignment, WCAG contrast, overflow).
- `examples.md`: a worked example of each stage file. Match its shape, not its content.
- A **prior report** (optional): the last round's `report.md`. It starts step 7 and the
  report's "Since last review" section.

## Stage 1: Observe (write `raw.md`)

Reach every state, then document. Do the steps in order: **task completion first**, then
encodings, the per-screen checklist, the style pass and the probes. Do not let the
checklist hide whether the main job works.

1. **Reach the states.** Run each `happy_path_script`, view the screenshots, and build a
   mental model. Then **probe beyond** the happy path: empty and zero-result states,
   errors, dead ends, alternate paths, and the other device in the brief.
2. **Walk each task to completion: the most important check.** For each `primary_task`,
   record whether the persona can reach its `success_criterion`. If not, name where it
   breaks. Then **verify the app's promises**: each claim the UI makes (onboarding, help,
   empty-state copy, a button label) must be delivered on the screen where the persona
   acts. Do **not** assume a task works because a similar control exists; confirm it does
   the job the brief defines (for example the *aggregate feed* the brief names, not one
   item). A task that cannot reach its success criterion is the headline finding.
3. **Inventory the encodings (once, app-level).** List each distinct **color, icon and
   badge or dot**, and what it *means*, or "no discernible meaning". For colors, check that
   one color always has one meaning and that the meaning is learnable (a legend, or a
   guess?). Read the source when a screen is ambiguous.
4. **Work the checklist per screen.** For each meaningful screen, use the **shared spine**
   plus the list for the `surface_type` (for a guided flow, run the cognitive-walkthrough
   backbone on each step). Record each applicable item as `✓`, `✗` or `n/a`, with a
   one-line observation and a screenshot reference. Answer the items that pass too.
5. **Measure the style (once, app-level).** Run the style-inventory tool on each key
   screen state (a URL or a happy-path scenario file). **Confirm each flag in the
   screenshot before you record it**: a flag you cannot see does not count. Then work the
   **aesthetics and craft** list in `checklists.md`, with the register items judged against
   the brief's tone constraints. Record each confirmed item with its measurement (for
   example "third KPI card 9px below siblings, per inventory; visible in 01-overview.png").
6. **Run the fresh-eyes probes.** Spawn each as a **context-free subagent** given ONLY the
   named screenshot: no brief, no app name, no task, none of your impressions. Run them in
   parallel. Record the answers verbatim, next to the answer the brief expects.
   - **Five-second test** (first screen): "You looked at this screen for five seconds.
     What is this app for? What is the main thing you can do here? What drew your eye
     first?" Compare with `one_line_purpose` and the intended primary action.
   - **First-click test** (per `primary_task`): the task's start screenshot plus the goal
     *as an outcome, in words that quote no UI label*. Ask: "Where would you click first?
     Describe the element." Compare with the first step of the happy path. If you cannot
     state the goal without the UI's own label, note it: the label can be the only scent.

   A wrong or hesitant answer is empirical evidence of a discoverability problem; a right
   one is evidence for "What's working".
7. **Re-verify prior findings (only with a prior report).** For each prior finding, reach
   the same state and record **fixed**, **unchanged** or **regressed**, with a screenshot
   reference. Note what broke *because of* a fix. Verify; do not derive again.

## Stage 2: Diagnose (write `findings.md`)

Turn the raw answers into findings. **Start with task completion (step 2):** a
`primary_task` that cannot reach its `success_criterion`, or a core-job promise that is
missing, broken or undiscoverable, is almost always the headline. Write these first, and
never downgrade them to a copy nitpick. Then take the other candidates: per-screen `✗`s,
meaningless or inconsistent encodings, confirmed style flags, failed probes. For each, ask:
does this block or slow *this persona's* goal? Keep it if so; else say nothing. Merge
candidates with one root cause into one `cross-screen` finding that cites its raw items.

Keep `precedents.md` open at the brief's `surface_type`:

- **Frame findings as expectation breaks where a convention applies** ("every mainstream
  dashboard puts the range picker top-right"). Cite the convention in `why it matters`.
- **Sweep the precedent list once** for violations the checklist missed. They must still
  hurt this persona, and `scope.out` exempts deliberate divergences.

Rules for some candidates:

- **Fresh-eyes probes.** A misread purpose or a wrong first click is direct evidence: quote
  it. It can *upgrade* a hedged checklist item. One probe is one reader: one odd answer on
  an otherwise clean screen is noise.
- **Aesthetics.** Keep one only with a confirmed measurement or a brief tone constraint.
  Grade it **medium at most**, unless it breaks legibility or comprehension; then grade it
  as a usability finding.
- **Prior findings.** Do not argue them again. Carry the step 7 statuses to the report, and
  treat a *regression caused by a fix* as a new candidate that cites the prior finding.

Grade each finding:

- **high**: blocks or breaks the main job; the persona cannot finish or is badly misled. A
  core-job promise that is missing, broken or undiscoverable is always **high**.
- **medium**: real friction that slows the job, with a workaround.
- **low**: polish; noticeable, but no real effect on the goal.

## Stage 3: Report (write `report.md`)

This is the deliverable for the implementing agent. Keep it legible and short. Use the
output format in `examples.md` ("Report format"), in this order: **Goal (as understood)**
with the viewport, **Since last review** (only with a prior report), **What's working**
(1 to 3 strengths), **Top 3 changes**, and **Findings (worst first)**.

**Top 3 changes** is the synthesis, not a list again: if the agent does only three things,
what are they? Prefer the root-cause decision that clears several findings, and name the
findings each change clears.

Go deep on high and medium findings; do not pad with lows. Use `scope: cross-screen` for a
systemic problem. Credit only strengths the raw pass confirmed: if a task did not complete,
the main job is not "working"; if the encoding inventory found a gap, the colors are not
"consistent".

## Thorough mode: independent reviewers

Different reviewers find different problems, so a *thorough* review (a pre-ship gate, a
final audit) runs the judgment stages three times. It costs about 3 times as much; use it
only when asked or when the review gates a release.

- **Share the mechanical work, never the judgment.** Capture screenshots and run the style
  inventory once; the probes are already independent. Then run **three separate Stage 1
  and Stage 2 passes** in separate subagents. Each writes its own `raw-N.md` and
  `findings-N.md` and does not see the others.
- **Merge before Stage 3.** Keep findings from 2 or more reviewers (merge their evidence).
  Keep a single-reviewer finding only after you verify its evidence in the screenshots.
  Dedupe by root cause. On severity, take the majority, or the higher grade when it is 1
  against 1. Write the result as `findings.md`, then run Stage 3 once.
