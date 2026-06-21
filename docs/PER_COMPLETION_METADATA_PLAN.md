# Per-Completion Metadata (notes, cost, photo, who)

**Status: planned.** Today every completion records only a timestamp
(`task["completions"][] = {"ts": <iso>}`). This feature lets a completion carry
optional context — a **note**, a **cost**, a **photo**, and **who** did the work —
captured when a task is marked done and editable afterwards. It builds directly on the
completion-history surface already shipped (see `docs/COMPLETION_HISTORY_PLAN.md`): the
history list becomes a rich maintenance log instead of a bare list of dates.

This plan reflects four product decisions already made:

1. **Photo →** uploaded through Home Assistant's image-upload API; the completion record
   stores only an **image reference** (id / serve URL), never bytes. Keeps the single
   JSON store small.
2. **Who →** an HA **user/person picker**; the record stores a **stable id**, not free
   text.
3. **Capture mode is a per-task setting**, chosen when defining the task:
   **`none`** (one-click done, today's behaviour — the default), **`optional`** (a
   details dialog appears on done, all fields optional), or **`required`** (the dialog
   appears and at least the configured fields must be filled). This preserves the fast
   one-click flow for the many tasks that don't need detail while making rich capture
   first-class for the ones that do.
4. **Past completions are editable** — fix a note or add a forgotten receipt after the
   fact.

---

## 1. What already exists (and what doesn't)

Already present (the plumbing this feature extends):

- **Single completion chokepoint.** Every surface (to-do list, device mark-done button,
  `home_keeper.complete_task` service, `home_keeper/complete_task` websocket) funnels
  through `HomeKeeperStore.complete_task()` (`store.py`), which calls
  `recurrence.apply_completion()` to append `{"ts": <iso>}` and recompute `next_due`.
- **Per-completion delete** already exists end-to-end: `store.delete_completion()` +
  `recurrence.remove_completion()`, the `home_keeper/delete_completion` websocket
  command, and a trash button per row in the history list (`panel.ts`). This is the
  template for the new **edit** path.
- **History UI.** The task detail page already renders completions newest-first
  (`panel.ts` `_completionGroupsFor()` / history list); `Task.completions` is already in
  the TS type (`frontend/src/types.ts`) as `{ ts: string }[]`.
- **Archival retention.** Deleting a task archives its `completions` onto the related
  appliance (`assets.build_archived_history` / `remove_archived_completion`). Because it
  copies the whole completion dict, **metadata rides along for free** — no extra work to
  preserve it on archive.
- **Form conventions.** The task form is built from a schema via `_makeForm()`
  (`panel.ts`) with selector helpers in `frontend/src/forms.ts` (`selText`, `selNumber`,
  `selBool`, `selDevice`, `selArea`, …). The asset **metadata editor** (`panel.ts`) is a
  good precedent for a small structured sub-form.

Gaps to close:

1. The completion record has no metadata fields and `apply_completion()` accepts none.
2. There is **no image upload** anywhere in the panel or backend, and **no access to HA
   users/persons** in the frontend.
3. There is **no edit path** for an existing completion (only delete).
4. Tasks have no **capture-mode** field, and the form has no control for it.

---

## 2. Data model

### Completion record (additive, all optional)

```python
{
    "ts":    "2026-06-13T10:00:00-04:00",  # unchanged, the identity key
    "note":  "Replaced filter, hinge squeak fixed",  # str  | absent
    "cost":  12.50,                                   # number | absent (>= 0)
    "photo": "<image-upload-id>",                     # str  | absent (HA image id)
    "who":   "person.alice",                          # str  | absent (stable id)
}
```

- **Keys are omitted when empty** (we never write `null`); all readers use `.get()`.
  `ts` remains the identity used by delete/edit/archive — unchanged.
- **`cost`** is a bare number in the HA instance's configured currency
  (`hass.config.currency`); we store the number, the UI formats it. No per-completion
  currency (documented as out of scope).
- **`who`** stores a stable id. We use a **`person` entity id** (`person.*`) — persons
  are first-class HA entities, stable across renames, and pickable with a standard
  entity selector. (HA *users* have no entity and no first-class selector; persons are
  the right primitive and what "who lives here" maps to.)
- **`photo`** stores the **image-upload id** returned by HA's image API; the panel
  renders it via `/api/image/serve/<id>/<size>`. We do **not** store bytes.

### Task field (capture mode)

Add one key to the task dict (`models.py` seed):

```python
"completion_detail": "none",   # "none" | "optional" | "required"
```

Default `"none"` ⇒ existing tasks and one-click completion are unchanged with no
migration. `required` enforces a non-empty **note** by default (the most useful single
field); the set of required fields can stay fixed at "note" for v1 to avoid a
combinatorial settings UI — revisit if users ask for "require cost", etc.

### Migration

**No `STORAGE_VERSION` bump.** Every change is additive-optional and read with `.get()`,
matching the project's established "additive fields need no migration" pattern
(`store.load()` comment, the `assets`/`part_numbers` precedent). Old completions simply
lack the new keys; old tasks default `completion_detail` to `"none"`.

---

## 3. Photo upload — how it works

Home Assistant ships the **`image_upload`** integration (part of `default_config`),
which the frontend's `<ha-picture-upload>` element drives:

- Upload: `POST /api/image/upload` (multipart) → returns `{ "id": ... }`.
- Serve: `GET /api/image/serve/<id>/<size>` (e.g. `512x512`).
- Delete: `DELETE /api/image/upload/<id>`.

Plan:

- **Frontend** uses `<ha-picture-upload>` in the completion dialog; on success it holds
  the returned image **id** and submits it as `photo`. Display in the history list uses a
  small `<img>` pointing at the serve URL (thumbnail; click to open full size).
- **Backend** treats `photo` as an opaque string — it does **not** proxy bytes.
- **Cleanup (important):** when a completion is **deleted** or its photo **replaced**,
  the orphaned image should be removed via the image-upload delete API so the feature
  doesn't leak images. This happens at the HA boundary (`store`/service handler, which
  has `hass`), never in pure `recurrence.py`. Best-effort: log and continue on failure.
- **Degraded mode:** if `image_upload` is unavailable, the dialog hides the photo field
  rather than erroring; `note`/`cost`/`who` still work.

---

## 4. Backend changes

Per the project rule **"expose every data action as a service"** and **"fire an event
for every state change"**, metadata flows through services + events, and websocket
commands merely delegate.

### Pure core (`recurrence.py`, `models.py`) — no HA imports

- `apply_completion(task, completed_at, *, now, metadata=None)` — merge non-empty
  metadata keys into the appended completion dict. Pure; recurrence math untouched
  (still keys off `ts`).
- New `update_completion(task, ts, metadata)` — find the completion by `ts`, set/replace
  metadata keys (empty value ⇒ remove key); does **not** touch `ts`/`next_due`. Returns
  the prior `photo` id (if changed/cleared) so the HA layer can clean it up.
- `models.py` — add `completion_detail: "none"` to the task seed and to the
  create/update field whitelist.

### Store (`store.py`) — the chokepoint

- `complete_task(..., *, note=None, cost=None, photo=None, who=None)` — pass a metadata
  dict to `apply_completion`. Keep `origin` as-is.
- New `update_completion(task_id, ts, *, note, cost, photo, who)` — calls
  `recurrence.update_completion`, persists, fires event; deletes any orphaned prior photo.
- `delete_completion()` — additionally delete the completion's photo (best-effort).
- Validation that needs HA (e.g. `who` resolves to a real `person`, `cost >= 0`) lives in
  the service handlers and raises **localized** `ServiceValidationError`
  (`translation_key` under `strings.json` → `exceptions`).

### Services (`__init__.py` + `services.yaml` + `strings.json`)

- Extend **`complete_task`** with optional `note` (text, multiline), `cost`
  (number, min 0), `photo` (text — image id), `who` (entity selector, `domain: person`).
- Add **`update_completion`** service: `task_id`, `ts` (required) + the four optional
  metadata fields, with a flag/convention for "clear this field".
- Full **services.yaml ⇄ strings.json parity** (selectors + field names/descriptions),
  enforced by `test_translations_parity.py`.

### Websocket (`websocket_api.py`)

- Extend `home_keeper/complete_task` schema with the metadata fields → delegate to
  `store.complete_task`.
- Add `home_keeper/update_completion` → delegate to `store.update_completion`.
  (These are UI optimizations over the services, per the architecture rule.)

### Events (`events.py` + `docs/EVENTS.md`)

- `completion_event_data()` — include the metadata in the `home_keeper_task_completed`
  payload (alongside `completed_at`/`origin`).
- Add a `home_keeper_task_completion_updated` event fired from `store.update_completion`
  (state change ⇒ event). Document both in `docs/EVENTS.md`; add to `device_trigger.py`
  with translation-parity labels only if we decide it's device-facing (likely **not** —
  it's a metadata edit; default to docs-only, no device trigger).

### Entities (`sensor.py`)

- Surface the **latest** completion's metadata on the task sensor's
  `extra_state_attributes` (e.g. `last_completion_note`, `last_completion_cost`,
  `last_completion_who`, `last_completion_photo`) so automations/dashboards can read the
  most recent context without parsing the array. Keep `completions_count` as-is.

---

## 5. Frontend changes

### Types & API

- `types.ts` — extend the completion type to
  `{ ts: string; note?: string; cost?: number; photo?: string; who?: string }` and add
  `completion_detail?: 'none' | 'optional' | 'required'` to `Task`.
- `api.ts` — `completeTask(hass, taskId, metadata?)` gains an optional metadata arg;
  add `updateCompletion(hass, taskId, ts, metadata)`.
- `forms.ts` — add selectors as needed: `selEntity({domain:'person'})` for **who**;
  reuse `selText(true)` for **note**, `selNumber(0)` for **cost**.

### Capture-mode control on the task form

Add a select control (`none` / `optional` / `required`) to the task schema in the task
form, wired through the existing `_makeForm()` flow, with i18n labels.

### Completion dialog

`_complete(task)` branches on `task.completion_detail`:

- **`none`** → today's instant complete (no dialog).
- **`optional` / `required`** → open a **completion details dialog** (HA-native
  `ha-dialog`/`ha-card`, mirroring the edit form): note, cost, who (person picker),
  photo (`<ha-picture-upload>`). On submit call `api.completeTask(hass, id, metadata)`.
  `required` disables Save until the required field(s) are filled and shows an inline
  `ha-alert` otherwise. A "Skip details" affordance in `optional` mode completes with no
  metadata.

The dashboard **card** (`card.ts`) keeps its quick mark-done; if the task is
`required`, the card defers to the panel (deep-link to the task) rather than completing
without the mandated detail.

### History display + edit

In the task detail history list (`panel.ts`):

- Render metadata under each row: note text, formatted cost
  (`hass.config.currency`/locale), who's friendly name (resolved from the `person`
  entity), and a photo thumbnail (serve URL) that opens full-size.
- Add an **edit** (pencil) button per row beside the existing trash button, opening the
  same dialog pre-filled and calling `api.updateCompletion`. Mirror `_wireHistoryDeletes`
  with a `_wireHistoryEdits`.
- Resolving **who** → friendly name and rendering the **photo** both read from `hass`
  (entities for person names; the image serve URL for photos).

### i18n

Add all new keys (capture-mode labels, dialog labels, field names, the "skip"/"required"
strings) to **every** locale file; `test_translations_parity.py` enforces parity.

---

## 6. Files touched

**Backend (pure / HA-free):**
- `custom_components/home_keeper/recurrence.py` — metadata on `apply_completion`; new `update_completion`
- `custom_components/home_keeper/models.py` — `completion_detail` seed + whitelist

**Backend (HA layer):**
- `custom_components/home_keeper/store.py` — metadata pass-through, `update_completion`, photo cleanup on delete/replace
- `custom_components/home_keeper/__init__.py` — extend `complete_task` schema/handler; add `update_completion` service; localized validation
- `custom_components/home_keeper/services.yaml` + `strings.json` (+ locale strings) — fields & parity
- `custom_components/home_keeper/websocket_api.py` — extend `complete_task`; add `update_completion`
- `custom_components/home_keeper/events.py` + `docs/EVENTS.md` — payload metadata + `task_completion_updated` event
- `custom_components/home_keeper/sensor.py` — latest-completion metadata attributes

**Frontend:**
- `frontend/src/types.ts`, `api.ts`, `forms.ts`
- `frontend/src/panel.ts` — capture-mode control, completion dialog, history metadata + edit
- `frontend/src/card.ts` — respect `required` mode
- `frontend/src/i18n.ts` + locale JSON

**Docs / tests / CI:**
- `README.md` — new feature section + screenshot(s) (relative `docs/images/…` path)
- `CHANGELOG.md` — `## [Unreleased] → ### Added`
- `tests/e2e/screenshots.capture.ts` — capture the completion dialog + history-with-metadata
- `tests/unit/test_recurrence_*.py`, `tests/unit/test_models.py`, `tests/unit/test_events.py`
- `tests/integration/*` — websocket/service round-trips
- `frontend/test/*` — vitest for metadata formatting / dialog logic
- `.amazonq/rules/architecture-and-code.md` — record the completion-metadata model & person-id convention if it sets new precedent

---

## 7. Testing strategy

- **Unit (pytest, HA-free):** `apply_completion` merges/omits metadata and leaves
  recurrence math unchanged; `update_completion` edits by `ts` without touching
  `next_due` and reports the orphaned photo id; empty values clear keys; `completion_detail`
  defaulting.
- **Unit (events):** `completion_event_data` carries metadata; `task_completion_updated`
  builder shape.
- **Integration (Docker HA):** `complete_task` + `update_completion` services and
  websocket commands round-trip; `who` validation rejects a non-person; photo id stored
  and cleaned up on delete; sensor attributes reflect latest metadata.
- **Frontend (vitest):** cost/locale formatting, who→name resolution, capture-mode
  branching, required-field gating.
- **e2e (Playwright):** complete an `optional`/`required` task through the dialog; edit a
  past completion; screenshots captured for the PR (hard UI gate).

---

## 8. Phasing & recommended first step

Suggested order to keep each PR reviewable:

1. **Backend core + services/events/ws** (no UI): data model, `apply_completion`
   metadata, `update_completion`, services, events, sensor attributes, photo cleanup,
   docs/EVENTS.md, full unit/integration tests. Shippable and automate-able on its own.
2. **Frontend capture + display:** capture-mode control, completion dialog (incl.
   `ha-picture-upload` and person picker), history metadata + edit, card behaviour,
   i18n, vitest, **screenshots**, README, CHANGELOG.

**First step:** land Phase 1's pure-core changes (`recurrence.apply_completion` +
`update_completion`) with unit tests — it's HA-free, low-risk, and everything else
depends on the record shape it defines.
