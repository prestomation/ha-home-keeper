# Review item lists

The checklist worked across every screen. In **Stage 1** (raw pass) answer every
applicable item — including the ones that pass — with `✓ / ✗ / n/a`, a one-line
observation, and a screenshot ref. In **Stage 2** the `✗`s become candidate
findings, kept only where they affect the persona's goal. So: tick everything in
the raw pass; the *final report* carries only prioritized insights (see
`SKILL.md`).

Apply the **shared spine** to every screen, plus the list for the brief's
`surface_type`. The **aesthetics & craft** list is applied once, app-level (like
the encoding inventory), fed by the style-inventory tool's measurements. Items
are adapted from established UX sources (cited per group).

---

## Shared spine — every screen

**Visual hierarchy & grouping** *(NN/g visual design, Gestalt)*
- Does the eye land on the goal-relevant action/info first, matching its importance?
- Are related elements grouped (proximity, shared style, a container) and unrelated ones separated?

**Emphasis & placement of actions** *(Material emphasis tiers; Apple HIG; Von Restorff; Fitts & Hick; WCAG 2.2 §2.5.8)*
- Is exactly one element the clear visual primary on this screen, and is it the goal action — with competing actions visibly subordinate in weight/contrast/size (no prominence inversion, where a lesser or destructive action outweighs the main one)?
- Are actions where the persona expects them and ordered by convention — primary consistently placed, destructive separated from primary, dialog/form button order following the platform — rather than hunted for?
- Does each action sit next to the object or context it affects (proximity), and is it reachable and large enough on the target device (target size, thumb zone on mobile)?

**Consistent meaning of color & icons** *(semantic color; WCAG "not color alone")*
- Does every color encode one consistent, learnable meaning (e.g. red = error/destructive, never decorative)?
- Is anything signalled by color also carried by text/icon/shape (survives grayscale & colorblindness)?
- Do icons carry stable meanings, labelled where ambiguous?

**Feedback & system status** *(Nielsen #1, #9)*
- After every meaningful action, is there timely feedback on what happened and the new state?
- On error, is the message plain-language, attached to the right place, with a clear recovery path?

**Error prevention & recall** *(Nielsen #5, #6)*
- Are likely errors prevented up front (constraints, sensible defaults, confirm destructive/irreversible actions)?
- Are the options/info the user needs visible in context, not something they must remember from a prior screen?

**Consistency & language** *(Nielsen #2, #4; legibility)*
- Do the same words, controls, and patterns mean the same thing everywhere, following conventions?
- Are labels/messages in the user's language (no system jargon) and do they say what will actually happen?
- Is text legible — size, contrast, reading order?

---

## Aesthetics & craft — app-level, once

*Run after the style-inventory tool (`tools/style-inventory.mjs`) has produced
its measurement report for the key screens. **Evidence rule:** every `✗` here
must cite either a measurement from that report (confirmed in the screenshot) or
a tone constraint stated in the brief. Never flag from eyeballed geometry or
personal taste — if it isn't measured or brief-anchored, it isn't a finding.
Severity for this group caps at **medium** unless the issue breaks legibility or
comprehension (then it's an ordinary usability finding, not an aesthetic one).*

**Craft — measured** *(type-scale practice; 4/8-pt spacing systems; WCAG 1.4.3)*
1. Is the type scale coherent — roughly 4–7 distinct sizes, no near-duplicate
   sizes (13px next to 14px), no visible text under 12px?
2. Is the palette disciplined — no near-duplicate colors doing the same job, and
   no decorative colors diluting the meaningful ones from the encoding inventory?
3. Are corner radii and shadows consistent across equivalent surfaces (cards,
   panels, inputs), rather than mixed for no reason?
4. Does spacing come from a consistent scale (e.g. multiples of 4), with
   equivalent gaps actually equal?
5. Do elements that are meant to line up actually line up — no confirmed
   near-miss edges (2–10px off a shared gridline or off their siblings)?
6. Does all text meet WCAG contrast (4.5:1 normal, 3:1 large), per computed
   ratios — not judged by eye?
7. Is nothing unintentionally truncated, clipped, or overlapping at the brief's
   primary viewport?

**Register — judged against the brief** *(brand/tone review practice)*
8. Does the rendered UI read as the brief's tone words? Name the concrete
   signals — shape language (radii, pill vs square), color saturation,
   typography, copy voice, emoji/illustration — that support or contradict each
   stated adjective (e.g. rounded bubbly buttons + emoji + saturated pastels
   read "playful" against a brief that says "professional, trustworthy").
9. Does the copy's voice match the persona and tone — exclamation marks, slang,
   or cuteness where the brief asks for calm, or stiff jargon where it asks for
   friendly?
10. Does visual density match the context of use — a calm, breathing layout for
    a consumer/first-time surface; an information-dense one for a professional
    tool the persona lives in?

---

## guided-flow — onboarding, forms, checkout, wizards, setup

*Apply per step. Items 1–4 are the backbone (cognitive walkthrough); run them on every step first.*

**Next-action clarity** *(cognitive walkthrough)*
1. Will the user form the right goal for this step (clear what it's for and why)?
2. Is the single correct next action visible and noticeable, not hunted for?
3. Will they connect that control to the outcome they want (labels name the outcome, e.g. "Continue to payment")?
4. After acting, is it clear they made progress toward the goal?

**Input & effort** *(GOV.UK one-thing-per-page; NN/g cognitive load; Baymard)*
5. Is the step scoped to one thing, not overloaded with unrelated asks?
6. Is every field actually necessary here, or can it be deferred/dropped?
7. Right input control & keyboard for the data type; required vs. optional unambiguous; labels persistent (not vanishing placeholders)?

**Errors** *(Baymard inline validation)*
8. Is input validated at the right moment (on blur, with positive confirmation), and are messages specific, adjacent, and fix-oriented?

**Progress & control** *(NN/g wizards; flexibility heuristic)*
9. Does the user know where they are and how much remains?
10. Can they go back and change earlier answers without losing data?
11. Is there a review/confirm before an irreversible commit?

**Trust** *(Baymard checkout)*
12. At sensitive input or commitment, is it clear why the data is needed, what happens next, and that it's safe (cost transparency, no surprise steps)?

---

## browse-search — search, listing, faceted filtering, content discovery

**Finding (search & filter)** *(Baymard search & filters; NN/g faceted search)*
1. Is search available, sensibly scoped, and tolerant of typos/synonyms/partial terms?
2. Are filters/facets relevant, predictable, jargon-free, prioritized — applied filters visible & individually removable, with a live result count?

**Scanning & information scent** *(NN/g information scent, list entries, cards)*
3. Does each result give a strong "scent" of where it leads (label, snippet, context) before clicking?
4. Can the user tell results apart at a glance without opening each one?
5. Is the key decision info (title, price, status, date) in a consistent position so the eye scans one column?
6. Is list-vs-grid / image-vs-text suited to the content and to comparison?

**Evaluating & comparing** *(NN/g product photos, comparison; Baymard sort)*
7. Are at-a-glance quality cues present without forcing a drill-down, and can results be sorted by what matters with a clear default?

**Result quality & empty states** *(Baymard no-results; search scope)*
8. Is a zero-results state a recovery point (related queries, broader category, relaxed filters), not a dead end?
9. Is result scope/progress clear (total count, range, load-more without losing place)?

**Navigation & orientation** *(NN/g large information spaces; GOV.UK navigation)*
10. Can the user always tell where they are and get back or broaden (location, breadcrumbs, path to a wider set)?

---

## monitoring — dashboards, admin consoles, status pages, analytics

**At-a-glance comprehension** *(Stephen Few; NN/g dashboards)*
1. Can the user grasp overall status and the few most important numbers within seconds, without scrolling or interaction?
2. Does the primary view fit one screen, so attention isn't fragmented across paging?
3. Do charts use fast encodings (length, position — bars/lines) over angle/area (pie/gauge) and no 3D?

**Hierarchy & density** *(Stephen Few; NN/g complex apps)*
4. Are the most decision-critical metrics the most salient, with secondary data visibly subordinate?
5. Has non-data ink (decoration, heavy gridlines, redundancy) been stripped?
6. Are numbers shown with context (vs. target/prior/threshold) and sensible precision?

**Status & alerting** *(Stephen Few; semantic color + accessibility)*
7. Are abnormal/alert states visually distinct and immediately findable, not buried among normal values?
8. Is alert meaning carried by more than color alone (icon, label, shape, position)?

**Drill-down & actionability** *(NN/g data tables, complex apps)*
9. From a flagged metric, is there a clear path to the detail or the action it implies?
10. For tables, does the layout support find/compare/act, with header rows/columns frozen when it overflows?

**Legibility** *(NN/g charts; Stephen Few)*
11. Are axes, units, time range, and "data as of" freshness labelled so a number can't be misread?
12. Is the chart type matched to the question (trend → line, comparison → bar, part-to-whole sparingly)?

**Chart perception — read the rendered chart, not the data behind it** *(Stephen Few; Cleveland & McGill; truthful-scale)*
13. **Honest baseline & scale:** does each bar/line value axis start at zero (or clearly mark a deliberate break), so heights and slopes don't visually exaggerate or flatten the real change? A truncated axis that turns a small move into a dramatic swing is misleading.
14. **Series distinguishable in the pixels:** can you tell every overlaid series apart in the rendered chart (actual vs target, multiple lines/bars) by colour, dash, marker, or direct label — and does that match whatever the legend claims? Two series that look identical can't be read, however correct the data.
15. **No prominence inversion:** is the single largest / first-read element the most decision-critical metric — not a cost or vanity figure blown up larger (hero slot, biggest type, highlighted card) than the outcome it should serve?
