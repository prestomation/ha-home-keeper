/**
 * The task edit drawer: the form itself, the option lists its pickers are scoped to
 * (an appliance's consumables, the documents a card may link), and the live hint strip
 * that answers "what did I just build?" without a re-render.
 *
 * `drawerHead` — the fixed top bar with Close, the title, Cancel and the commit — is
 * exported because the appliance drawer wears the same one; the two forms differ
 * below it, not above it.
 *
 * The form's *lifecycle* (open, close, submit) stays on the panel: it is entangled
 * with navigation, the pending-edit dance across a route change, and the drawer's
 * modality. This module renders and reads; `p._submitForm` / `p._closeForm` decide.
 *
 * Free functions over a `PanelHost` (see `panel-host.ts`), except `drawerHead`, which
 * is a pure builder of its arguments.
 */

import {
  DEFAULT_BACKSTOP_INTERVAL,
  cardLinkTokens,
  formRecurrenceSummary,
  pickFormData,
  sensorHintText,
  sensorLive,
  taskFormData,
  taskFormSchemaKey,
  taskSchemaSections,
} from './forms';
import { t } from './i18n';
import { openConfirmDialog } from './panel-dialogs';
import { setIcon } from './panel-history';
import type { PanelHost } from './panel-host';
import { MDI_CLOSE, SENSOR_DOCS_URL } from './panel-icons';
import { isDisplayableDocument, documentLabel } from './documents';
import type { Asset, Task } from './types';
import { escapeHTML, formatQuantity, safeHref, setBtnWeight } from './utils';

/** Appliances associated with a task's attached device (its own or related). */
function assetsForDevice(p: PanelHost, deviceId?: string | null): Asset[] {
  if (!deviceId) return [];
  return p._assets.filter(
    (a) =>
      a.device_id === deviceId || (a.related_device_ids ?? []).includes(deviceId),
  );
}

/**
 * `asset_id:part_id` options for the task form's "Linked consumable" picker,
 * scoped to the consumables of the appliance the task is **attached to** (its
 * device). You link a task to its own appliance's consumable, not some unrelated
 * appliance's — so the list stays short and unambiguous. Empty when the task has no
 * device, or its appliance has no consumables (the picker then hides).
 */
function consumableOptions(p: PanelHost, task: Partial<Task>): { value: string; label: string }[] {
  const assets = assetsForDevice(p, task.device_id);
  const multi = assets.length > 1; // disambiguate by appliance only when needed
  const options: { value: string; label: string }[] = [];
  for (const asset of assets) {
    for (const part of asset.parts ?? []) {
      if (part.type !== 'consumable' || !part.id) continue;
      options.push({
        value: `${asset.id}:${part.id}`,
        label: multi ? `${asset.name} · ${part.name}` : part.name,
      });
    }
  }
  return options.sort((a, b) => a.label.localeCompare(b.label));
}

/** Appliances reachable from a task: the one(s) it's attached to via its device,
 *  plus the appliance behind a manual consumable link (its part's asset). */
function assetsForTask(p: PanelHost, task: Partial<Task>): Asset[] {
  const byDevice = assetsForDevice(p, task.device_id);
  const partAssetId = task.source?.part?.asset_id;
  if (partAssetId && !byDevice.some((a) => a.id === partAssetId)) {
    const a = p._assets.find((x) => x.id === partAssetId);
    if (a) return [...byDevice, a];
  }
  return byDevice;
}

/**
 * `asset_id:entry_id` options for the task form's "Links to show on card" picker:
 * every appliance document — an external **link** (kind `link`) or an **uploaded
 * file** (kind `file`, e.g. a PDF manual) — plus every metadata link (type `link`)
 * on the appliance(s) the task is associated with. The card resolves the chosen
 * pairs live (a file opens via a signed URL minted on click). Empty (the picker
 * then hides) when the task touches no appliance or none of them carry a document.
 */
function documentOptions(p: PanelHost, task: Partial<Task>): { value: string; label: string }[] {
  const assets = assetsForTask(p, task);
  const multi = assets.length > 1; // disambiguate by appliance only when needed
  const options: { value: string; label: string }[] = [];
  for (const asset of assets) {
    for (const doc of asset.documents ?? []) {
      if (!doc.id || !isDisplayableDocument(doc)) continue;
      const label = documentLabel(doc);
      options.push({
        value: `${asset.id}:${doc.id}`,
        label: multi ? `${asset.name} · ${label}` : label,
      });
    }
    for (const meta of asset.metadata ?? []) {
      if (meta.type !== 'link' || !meta.value || !meta.id) continue;
      options.push({
        value: `${asset.id}:${meta.id}`,
        label: multi ? `${asset.name} · ${meta.label}` : meta.label,
      });
    }
  }
  return options.sort((a, b) => a.label.localeCompare(b.label));
}

/** Resolve a task's part link to a "Appliance · Part · In stock: N" detail line
 *  (HTML — the part name is a clickable link to its product page when it has a
 *  `url`, same anchor pattern as the appliance's parts-list read view). */
export function consumableLinkLabel(p: PanelHost, task: Task): string {
  const part = task.source?.part;
  if (!part) return '';
  const asset = p._assets.find((a) => a.id === part.asset_id);
  const linked = asset?.parts?.find((x) => x.id === part.part_id);
  if (!asset || !linked) return '';
  const stock =
    linked.stock != null
      ? ` · ${escapeHTML(
          t(
            linked.reorder_at != null && linked.stock <= linked.reorder_at
              ? 'part.lowStock'
              : 'part.inStock',
            { n: formatQuantity(linked.stock, linked.stock_unit) },
          ),
        )}`
      : '';
  const name = linked.url
    ? `<a href="${safeHref(linked.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(linked.name)}</a>`
    : escapeHTML(linked.name);
  return `${escapeHTML(asset.name)} · ${name}${stock}`;
}

/**
 * Refresh the task form's live copy in place (no re-render → keeps input focus).
 *
 * Two pieces: the sensor primer (only on sensor tasks, explains the baseline model)
 * and the rule summary above the submit button (every task kind). Both are pure
 * text derived from the current edit state, so this runs on any field change.
 */
function updateFormHints(p: PanelHost, box?: HTMLElement): void {
  // `box` is passed while the form is still being assembled (before it's in the
  // shadow root); afterwards we look it up. Same code either way, so the first
  // paint and every keystroke can't disagree about what the strip says.
  const root: ParentNode | null | undefined =
    box ?? p.shadowRoot?.querySelector('.hk-form-summary');
  if (!root) return;
  const task = p._edit.task || {};

  const value = root.querySelector('#hk-form-summary-value') as HTMLElement | null;
  const ruleText = formRecurrenceSummary(task);
  if (value) value.textContent = ruleText;

  const detail = root.querySelector('#hk-sensor-hint') as HTMLElement | null;
  const detailText =
    task.recurrence_type === 'sensor' ? sensorHintText(task, sensorLive(p._hass, task)) : '';
  if (detail) {
    detail.textContent = detailText;
    detail.style.display = detailText ? '' : 'none';
  }

  // Hide the whole strip only when it has nothing at all to say — a form with a
  // recurrence type but no sensor detail still shows its rule.
  (root as HTMLElement).style.display = ruleText || detailText ? '' : 'none';
}

/**
 * The drawer's fixed top bar: close, the form's title and what it is editing, then
 * Cancel and the primary commit. Both forms use it, so Save sits in the same place
 * whichever one is open, and neither has to scroll to reach it.
 *
 * The commit and dismiss buttons keep the ids they have always carried
 * (`f-save`/`f-cancel` for a task, `a-save`/`a-cancel` for an appliance) — they
 * moved from the bottom of the form to the top of the drawer, but they are the
 * same controls.
 */
export function drawerHead(
  title: string,
  subtitle: string,
  saveLabel: string,
  onSave: () => void,
  onCancel: () => void,
  ids: { save: string; cancel: string },
  helpUrl?: string,
): HTMLElement {
  const head = document.createElement('div');
  head.className = 'hk-drawer-head';
  const close = document.createElement('ha-icon-button');
  close.className = 'hk-drawer-close';
  close.id = 'hk-drawer-close';
  close.setAttribute('label', t('btn.close'));
  close.addEventListener('click', onCancel);
  setIcon(close, MDI_CLOSE);
  const titles = document.createElement('div');
  titles.className = 'hk-drawer-titles';
  const help = helpUrl
    ? `<a class="hk-form-help" href="${helpUrl}" target="_blank" rel="noopener noreferrer" title="${escapeHTML(
        t('help.docsLink'),
      )}" aria-label="${escapeHTML(t('help.docsLink'))}"><ha-icon icon="mdi:help-circle-outline"></ha-icon></a>`
    : '';
  titles.innerHTML =
    `<div class="hk-drawer-title">${escapeHTML(title)}${help}</div>` +
    (subtitle ? `<div class="hk-drawer-sub">${escapeHTML(subtitle)}</div>` : '');
  const cancel = document.createElement('ha-button');
  cancel.id = ids.cancel;
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = t('btn.cancel');
  cancel.addEventListener('click', onCancel);
  const save = document.createElement('ha-button');
  setBtnWeight(save, 'primary');
  save.id = ids.save;
  save.textContent = saveLabel;
  save.addEventListener('click', onSave);
  head.append(close, titles, cancel, save);
  return head;
}

export function renderTaskForm(p: PanelHost, host: HTMLElement): void {
  const task = p._edit.task || {};
  const card = document.createElement('ha-card');
  card.className = 'hk-form-card';
  card.id = 'hk-form';
  card.appendChild(
    drawerHead(
      task.id ? t('form.task.edit') : t('form.task.new'),
      String(task.name ?? ''),
      task.id ? t('btn.save') : t('btn.create'),
      () => void p._submitForm(),
      () => p._closeForm(),
      { save: 'f-save', cancel: 'f-cancel' },
      SENSOR_DOCS_URL,
    ),
  );
  const inner = document.createElement('div');
  inner.className = 'hk-form-inner';

  // Sensor-based tasks have no clock cadence — a short primer (with a docs link)
  // explains the baseline/reset model the fields below can't convey on their own.
  if (task.recurrence_type === 'sensor') {
    const intro = document.createElement('div');
    intro.className = 'hk-settings-intro';
    intro.innerHTML = t('help.sensor.section', { url: SENSOR_DOCS_URL });
    inner.appendChild(intro);
  }

  const onChange = (value: Record<string, unknown>): void => {
      // Which fields the form shows, before this edit — normalized through
      // `taskFormData` so a default the form seeded can't read as a change (see
      // `taskFormSchemaKey`). Anything else, a typed character included, leaves it
      // untouched and must never reach `_render()`.
      const prevSchemaKey = taskFormSchemaKey(p._edit.task ?? {});
      const prevDevice = p._edit.task?.device_id ?? '';
      // The form is rendered as one `ha-form` per section, so an event carries only
      // the section that changed. Every rule below therefore has to ask whether the
      // field it cares about is even in this snapshot: an unconditional read would
      // see `undefined` for a field in another section and "correct" it. Typing in
      // the name box would have reset the cadence interval to 1 that way.
      const has = (key: string): boolean => key in value;
      p._edit.task = {
        ...p._edit.task,
        ...value,
        ...(has('interval') ? { interval: Number(value.interval) || 1 } : {}),
      } as Partial<Task>;
      p._edit.error = undefined;
      // Refresh the notes preview in place — a re-render here would drop focus from
      // the textarea mid-word.
      if (has('notes')) p._taskNotePreview?.update(String(value.notes ?? ''));
      // Changing the attached device re-scopes the consumable picker; drop a link
      // that no longer belongs to the newly-attached appliance. Both sides are
      // normalized to '' so a cleared picker (null vs. undefined vs. absent) doesn't
      // look like a change on an unrelated edit.
      if (has('device_id') && (value.device_id ?? '') !== prevDevice) {
        const opts = consumableOptions(p, p._edit.task);
        const cur = (p._edit.task as Record<string, unknown>).consumable_link;
        if (cur && !opts.some((o) => o.value === cur)) {
          (p._edit.task as Record<string, unknown>).consumable_link = '';
        }
        // The card-link picker is likewise device-scoped — drop chosen links that
        // no longer resolve to the newly-attached appliance.
        const docOpts = documentOptions(p, p._edit.task);
        (p._edit.task as Record<string, unknown>).card_links = cardLinkTokens(
          p._edit.task,
        ).filter((tok) => docOpts.some((o) => o.value === tok));
      }
      // Picking a meter entity prefills the unit label from the entity itself, so
      // "300" reads as "300 h" without anyone typing it. Only when still blank —
      // a label the user (or a managing integration) chose is never overwritten.
      if (
        has('sensor_unit') &&
        p._edit.task?.recurrence_type === 'sensor' &&
        !String(value.sensor_unit ?? '').trim()
      ) {
        const live = sensorLive(p._hass, p._edit.task);
        if (live.unit) {
          (p._edit.task as Record<string, unknown>).sensor_unit = live.unit;
        }
      }
      // Switching the time backstop on with a blank or zeroed interval seeds a
      // working default, so the three fields it reveals describe a real rule
      // immediately instead of sitting at "every 0" and being silently dropped.
      if (
        has('sensor_backstop_on') &&
        Boolean(value.sensor_backstop_on) &&
        !(Number((p._edit.task as Record<string, unknown>).sensor_also_every) > 0)
      ) {
        (p._edit.task as Record<string, unknown>).sensor_also_every =
          DEFAULT_BACKSTOP_INTERVAL;
      }
      // The recurrence type (cadence/sensor fields), the sensor mode (usage vs.
      // threshold vs. state), the time-backstop switch (which reveals or hides its
      // three fields), the bound entity's binary-ness (which swaps the state
      // control), and the attached device (which scopes the consumable picker) each
      // toggle the visible schema -> re-render. Read off the merged state, so it and
      // the "before" key above are the same shape through the same normalizer.
      if (taskFormSchemaKey(p._edit.task ?? {}) !== prevSchemaKey) {
        p._render();
      } else {
        // The edit didn't change the visible schema, so refresh the live copy in
        // place — a full re-render would drop focus from the box being typed in, and
        // Home Assistant's global one-letter shortcuts would then swallow the rest of
        // the word (`d` device search, `a` Assist, `e`/`c` quick bar, `m` my-link).
        // Every task kind, not just sensor: the rule summary above the submit
        // button has to track an interval or a unit change too.
        updateFormHints(p);
      }
  };

  // One `ha-form` per section, under its own heading. `ha-form` renders its rows
  // into its own shadow root and offers no slot between them, so a heading between
  // two fields is only reachable by splitting the schema — which is why
  // `taskSchemaSections` exists. `hk-task-form` stays on a wrapper around them all,
  // so every `#hk-task-form <selector>` that looked inside the form still resolves.
  const formData = taskFormData(task);
  const sections = taskSchemaSections(
    task,
    consumableOptions(p, task),
    documentOptions(p, task),
    p._tags,
  );
  // The form seeds defaults the edit state does not carry — a fresh sensor task
  // shows "on" as the state it waits for, without that ever having been typed.
  // While the form was a single `ha-form` those seeds reached the edit state on the
  // next change of any field, because the event carried the whole form. Now that
  // each section emits only its own fields, a seed would arrive only if the user
  // happened to touch the section holding it — so the rule summary described a
  // sensor task "changing to " nothing, and a save would have written that.
  // Adopting them here keeps the promise that what the form shows is what saving
  // writes. Keys already in the edit state win, so a value cleared on purpose is
  // not seeded back.
  const offered = pickFormData(
    formData,
    sections.flatMap((s) => s.fields),
  );
  p._edit.task = { ...offered, ...(p._edit.task ?? {}) } as Partial<Task>;

  const formWrap = document.createElement('div');
  formWrap.id = 'hk-task-form';
  for (const section of sections) {
    if (!section.fields.length) continue;
    // Each section is seeded with *only* its own fields. `ha-form` emits its whole
    // `data` object on every change, so seeding each section with the full form
    // would have every section re-asserting a snapshot of the others taken when it
    // was built — typing a name and then changing the recurrence would put the name
    // back to what it was before the first keystroke.
    const form = p._makeForm(section.fields, pickFormData(formData, section.fields), onChange);
    form.id = `hk-task-form-${section.key}`;
    // Muted per-field helper text under each field (keyed `help.<field>`); returns
    // '' where no string is authored, so helpers appear only where we wrote them.
    form.computeHelper = (s: { name: string }): string => {
      if (!s.name) return '';
      const h = t('help.' + s.name);
      return h === 'help.' + s.name ? '' : h;
    };
    if (section.dependent) {
      // A run that only exists because of the answer above it, indented behind a
      // rule and captioned with what revealed it.
      const indent = document.createElement('div');
      indent.className = 'hk-indent';
      const body = document.createElement('div');
      body.className = 'hk-indent-body';
      const head = document.createElement('div');
      head.className = 'hk-eyebrow accent hk-indent-head';
      head.textContent = t('form.section.dependent');
      body.append(head, form);
      indent.appendChild(body);
      formWrap.appendChild(indent);
    } else {
      const heading = document.createElement('div');
      heading.className = 'hk-eyebrow hk-form-section';
      heading.textContent = t(`form.section.${section.key}`);
      formWrap.append(heading, form);
    }
  }
  inner.appendChild(formWrap);

  // Live Markdown preview of the notes field. It sits after the whole form rather
  // than directly under the field: the task schema is one `ha-form` (name, notes,
  // recurrence, sensor…), and splitting it just to interleave a preview would fork a
  // pure, well-tested schema builder. The preview only shows once there's something
  // to preview, so it stays out of the way for the common no-notes task.
  p._taskNotePreview = p._attachNotePreview(inner, String(task.notes ?? ''));

  // One box, directly above the submit button, answering "what did I just build?"
  // in two registers: the rule as a headline, and — for a sensor task — the live
  // arithmetic underneath ("reads 660 h, so first due at 760 h"). These used to be
  // two separate panels stacked on each other, which meant two places to look for
  // one answer; the headline is the same sentence the saved task's card will show,
  // because it comes from the same formatter.
  const summary = document.createElement('div');
  summary.className = 'hk-form-summary';
  summary.innerHTML =
    `<span class="hk-form-summary-label">${escapeHTML(t('form.summary.label'))}</span>` +
    `<span class="hk-form-summary-value" id="hk-form-summary-value"></span>` +
    `<span class="hk-form-summary-detail" id="hk-sensor-hint"></span>`;
  inner.appendChild(summary);
  updateFormHints(p, summary);

  if (p._edit.error) {
    const err = document.createElement('ha-alert');
    err.setAttribute('alert-type', 'error');
    err.textContent = p._edit.error;
    inner.appendChild(err);
  }

  card.appendChild(inner);

  // The destructive and the "go somewhere else" actions live in a footer bar,
  // deliberately far from Save at the other end of the drawer. Both existed
  // already — Delete on the task's detail page, History as that page itself —
  // and are surfaced here so an edit session does not have to be abandoned to
  // reach them. Only for a saved task: neither means anything for a draft.
  if (task.id) {
    const foot = document.createElement('div');
    foot.className = 'hk-drawer-foot';
    const del = document.createElement('ha-button');
    del.className = 'hk-drawer-delete';
    setBtnWeight(del, 'danger');
    del.textContent = t('btn.delete');
    const onThisTasksPage = p._detail?.kind === 'task' && p._detail.id === task.id;
    del.addEventListener('click', () =>
      openConfirmDialog(p, t('confirm.deleteTask', { name: String(task.name ?? '') }), () => {
        p._closeForm();
        // Deleting from the task's own page empties that page: replace it with the
        // list first, the same way the page's own Delete does, so neither the render
        // that follows nor Forward lands on a task that is gone.
        if (onThisTasksPage) p._navigate({ view: 'tasks', detail: null }, true);
        void p._delete(task as Task);
      }),
    );
    const spacer = document.createElement('span');
    spacer.className = 'hk-drawer-foot-spacer';
    foot.append(del, spacer);
    // History is a way to the task's own page, so it is only offered from somewhere
    // else. Editing on that page already has the history under the form.
    if (!onThisTasksPage) {
      const history = document.createElement('ha-button');
      history.className = 'hk-drawer-history';
      setBtnWeight(history, 'tertiary');
      history.textContent = t('btn.history');
      history.addEventListener('click', () => {
        p._closeForm();
        p._openDetail('task', String(task.id));
      });
      foot.append(history);
    }
    card.appendChild(foot);
  }
  host.appendChild(card);
}
