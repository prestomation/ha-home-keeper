# Wear item preview — implementation plan

> A plain-language box at the foot of a wear item, saying what the part will create.
> Written September 2026, against `main` at `6c9c7cc`. The agreed mock-up is
> [Wear Item Preview Box](https://claude.ai/artifact/PmYi7jUH6hdfiUwMtDQ33N).

---

## 1. The CHANGELOG entry this ships

```markdown
- **[Wear item preview](https://prestomation.github.io/ha-home-keeper/docs/guide/appliances#parts--wear-items).**
  A wear item now says what it will create before you save it. The box names each
  task, its schedule, and the count a use task feeds.
```

`v0.24.0b7` is a published tag and is the current `main`, so this work opens
**`0.24.0b8`**: bump `manifest.json` and `const.PANEL_VERSION`, and add a
`## [0.24.0b8]` section with an `### Added` heading. An edit to the `0.24.0b7` section
fails `changelog-release-gap`.

The PR gets the `preview-release` label.

---

## 2. The problem

A wear item has 3 fields whose result the form never states.

- **Action** picks the task name from a table of 7 (`ACTION_TASK_NAME_TEMPLATES` in
  `const.py`). The form says "What the maintenance task is called", and never says
  what that name is.
- **Count uses as** captions the count. Nothing shows the caption.
- **Use task name** names the second task. Nothing says a second task exists.

A counted wear item creates **2** tasks: the use task that records one use, and the
maintenance task that comes due after the target. `reconcile.py` builds both, and the
form shows neither. A user finds out on save.

The task form already answers the same question for a task, in the box labelled
**When due** (`panel-task-form.ts`, `.hk-form-summary`). This change gives a part the
same device.

---

## 3. What the box says

One label, then one line per fact. A task name is one line and its schedule is the
next. The lines come from the style rule added in
[#347](https://github.com/prestomation/ha-home-keeper/pull/347): cut the empty subject
and verb, and write the fact as a phrase.

| State | Lines |
| --- | --- |
| No interval | `Set an interval to create a task.` |
| Time, Replace | `Replace HEPA filter (Air purifier)` / `Due every 6 months.` |
| Time, other action | The action's own template, from `resolve_action_task_naming`. |
| Last replaced set | Adds `First one due 3 June 2026.` |
| Counted | `Wear rain jacket` / `Each completion adds 1 to the count.` / `Renew Waterproof coating (Rain jacket)` / `Due after 20 wears.` |
| Counted, no use task name | The use task reads `Use Rain jacket`. |
| Counted, no use noun | `uses` in place of the noun. |
| Backstop on | `Due after 20 wears, or after 12 months.` / `The earlier one wins.` |
| Stock and auto-buy | A second, quieter block: `Takes 1 from stock.` / `Buy reminder at 1.` |
| Part unnamed | The name as stored, which is empty. |
| Appliance unnamed | `Appliance`, the word `reconcile.py` substitutes. |

**Three rows of this table were wrong, and building it is what showed that.**

1. **No count line.** The draft said the box would read `Count reads 0 of 20 wears.`
   The capture of the seeded rain jacket put that line beside a part row reading
   **17 of 25 wears**. The box previews what a part creates, so a hardcoded 0 states a
   falsehood on every part that has been used, and threading the live count in would
   make a pure builder depend on the task list. The noun was all that line added, and
   the due line above it already carries the noun.
2. **No `New appliance`.** `reconcile.py` substitutes the localized `Appliance`
   (`const.APPLIANCE_FALLBACK_NAMES`), and the panel already ships that word as
   `appliance.fallbackName`. The preview reuses the existing key, so this needs no new
   string and cannot drift.
3. **No part-name fallback.** `reconcile.py` writes `part["name"]` verbatim, so an
   unnamed part really does generate `Replace  (Fridge)`. A placeholder here would
   preview a name the task will not have.

**One line was added that the plan did not have.** A time-measured part with a
last-replaced date says `First one due Sep 3, 2026.`, from `partFirstDue`. Month
arithmetic clamps the way `recurrence.add_months` does, which `resolveSnoozePreset` in
`utils.ts` already does for the same reason. A counted part gets no such line: its
replacement task is `triggered`, so the count arms it rather than the calendar.

The second block uses `.hk-form-summary-detail`, the same element the sensor task's
live arithmetic uses. It draws only when the part tracks stock.

---

## 4. Where it goes

`panel-asset-editors.ts`, in the part editor, after `wearHint` and before
`renderPartFile`. That puts it under the last field of the dependent form and above
the part's own Remove row. A collapsed part draws nothing, because the whole body is
inside the `details` element.

`wearHint` (`part.wearHint`) says a wear item with an interval creates a maintenance
task. The preview says the same thing with the real name in it, so the hint goes and
the preview takes its place. The hint's second sentence, about the last-replaced date,
moves to the `last_replaced` field's own help text.

The box redraws inside `merge()`, which already runs on every keystroke and already
calls `updateSummary(next)` for the collapsed row's line. The preview is a second call
beside it. Nothing here calls `_render()`, and the preview must not either: a rebuild
from a keystroke is the iOS jump the 2-form split exists to prevent.

---

## 5. The builder

A pure function in `forms.ts`, beside `partSummaryLine`:

```ts
export interface PartPreviewLine {
  text: string;
  kind: 'task' | 'fact';
}
export interface PartPreview {
  lines: PartPreviewLine[];
  detail: string[];
}
export function partPreview(part: Part, assetName: string): PartPreview;
```

`forms.ts` is already on the mutation-tested allowlist, so the builder is scored at
80% from its first commit. It takes `assetName` as an argument rather than reading the
panel's state, which keeps it pure and testable.

**The name has to agree with `reconcile.py`.** The backend owns the templates, and a
second copy of them in TypeScript drifts. `const.ACTION_TASK_NAME_TEMPLATES` and
`USE_TASK_NAME_TEMPLATES` are per-language tables, and the panel has its own locale
files. So the panel keeps the templates as locale strings and a **parity test** proves
the 2 sets agree for English:

- `tests/unit/test_part_preview_parity.py` reads `locales/en.json` and
  `const.ACTION_TASK_NAME_TEMPLATES["en"]`, and fails when an action's template
  differs or an action is missing. The repository already tests this way
  (`test_translations_parity.py`).

Without that test this change is a second source of truth for a user-visible name.

---

## 6. New locale keys

| Key | English |
| --- | --- |
| `part.preview.label` | `What this creates` |
| `part.preview.setInterval` | `Set an interval to create a task.` |
| `part.preview.dueEvery` | `Due every {n} {unit}.` |
| `part.preview.dueAfterUses` | `Due after {n} {noun}.` |
| `part.preview.dueAfterUsesOr` | `Due after {n} {noun}, or after {n2} {unit2}.` |
| `part.preview.earlierWins` | `The earlier one wins.` |
| `part.preview.firstDue` | `First one due {date}.` |
| `part.preview.countsOne` | `Each completion adds 1 to the count.` |
| `part.preview.stockDraw` | `Takes {n} from stock.` |
| `part.preview.buyAt` | `Buy reminder at {n}.` |
| `part.taskName.<7 actions>` + `part.taskName.use` | The task-name templates, for the parity test above. |

Two of these changed while building.

- **`dueAfterUsesOr` carries the backstop's own number and unit** rather than a
  separate `{every}` key holding `"{n} {unit}"`. That key would read identically in
  all 16 languages, and the untranslated-leak gate in `i18n-parity.test.js` rejects
  a value equal to its English one.
- **No `newAsset` key.** The existing `appliance.fallbackName` already holds the word,
  as noted in section 3.

`part.taskName.*` is copied verbatim from the backend's own tables rather than
translated by hand, which makes the parity test pass by construction. One value trips
the leak gate legitimately: Norwegian takes the English verb unchanged for *service*,
so `nb` gets an entry in that test's reviewed-cognate list, with its reason.

Every key lands in all 16 locale files, or `i18n-parity.test.js` fails. A value equal
to the English one fails the untranslated-leak gate as well, unless it is a genuine
cognate in that language.

`field.action`, `field.use_noun` and `field.use_task_name` keep their help text. The
help says what a field is for; the preview says what the fields add up to.

---

## 7. Styling

3 rules in `panel-styles.ts`, next to `.hk-form-summary`:

```css
.hk-form-summary-value { display: flex; flex-direction: column; gap: 1px; }
.hk-form-summary-task { font-weight: 700; overflow-wrap: anywhere; }
.hk-form-summary-task + .hk-form-summary-fact { margin-bottom: 5px; }
```

The task form's own box gains the column layout, which changes nothing there because
it holds one line.

`overflow-wrap: anywhere` matters: a task name is 2 names and 2 brackets, and the
phone width is 360px.

---

## 8. Tests

| Lane | What it proves |
| --- | --- |
| `frontend/test/part-preview.test.js` | The builder, state by state, from the table in §3. One case per row, plus a part that tracks stock without a reorder point. |
| `tests/unit/test_part_preview_parity.py` | The panel's action templates and `const.ACTION_TASK_NAME_TEMPLATES["en"]` agree. |
| `frontend/test/i18n-parity.test.js` | Runs as it is. The new keys reach all 16 locales. |
| `tests/e2e/tests/counted-wear.spec.ts` | The box is in the DOM with the right lines after the form is filled. A screenshot is documentation, not coverage. |
| `ci/test-mutation-frontend.sh` | 80% on the changed lines of `forms.ts`. |

---

## 9. Screenshots

Hard gate. Both widths, for the one changed surface.

- Desktop: extend the appliance-form walk in `screenshots.capture.ts` to open a
  counted wear item and photograph the box. Name it `21g-panel-wear-preview.png`.
- Phone: add a step to the `setViewportSize(PHONE)` block for the same part. Name it
  `21h-panel-mobile-wear-preview.png`.

Read both PNGs with the Read tool before the commit. A part card is inside a `details`
element inside a drawer, which is exactly the shape that photographs blank.

Embed both in the PR body with an HTML `<img>` tag, pinned to the commit SHA. Avoid a
character entity in the `alt` text.

---

## 10. Walkthrough

The tour steps through the appliance form already. A preview box is a new surface on
an existing page, so it needs a beat only if the tour does not already pause on a wear
item. Check `walkthrough.capture.ts` and, if a beat is added, re-measure the budget:
`npx playwright test --config=walkthrough.config.ts --timeout=600000 --reporter=list`,
then set the cap to the reported duration plus 40%. The cap is at 360s, and the note
in `walkthrough.config.ts` says the next raise is not free.

---

## 11. User guide

`docs/guide/appliances/appliances.md`, under **Parts & wear items**, gains a short
section after **Count uses instead of months**. It says what the box lists and shows
the desktop screenshot with a relative `../../images/…` path. No new page, so
`doc-map.mjs` is unchanged.

---

## 12. One-way doors

**None.** The box is panel text built from fields that already exist. No service,
event, entity attribute, storage field or websocket command changes.

The 2 surfaces this change does touch are reversible:

- The new locale keys are internal to the panel. A key can be renamed.
- `part.wearHint` is removed. Its text is replaced by the preview, and no automation
  reads a locale string.

---

## 13. Order of work

1. `partPreview` in `forms.ts`, plus its unit tests. No UI yet.
2. The parity test, then fix whichever side is wrong.
3. English locale keys, then the other 15.
4. Wire it into `panel-asset-editors.ts`. Remove `wearHint`.
5. The 3 CSS rules.
6. The e2e assertion in `counted-wear.spec.ts`.
7. Screenshots, both widths. Read each one.
8. Guide section, CHANGELOG bullet, version bump to `0.24.0b8`.
9. `bash ci/test-frontend.sh`, `pytest tests/unit -v`, `vale` on the changed prose,
   `bash ci/test-mutation-frontend.sh`.
10. Push, open the PR as a draft, apply `preview-release`, and post the `/q review`
    request.
