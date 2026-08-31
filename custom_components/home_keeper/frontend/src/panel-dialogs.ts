/**
 * Every overlay the panel puts over its own content: the completion-details dialog
 * (logging a completion, or editing a recorded one), the "move completion date"
 * dialog, and the destructive-action confirmation.
 *
 * The first two share `makeDialog`, the one place an `ha-dialog` is constructed —
 * Home Assistant has broken hand-built dialogs twice, and each time the fix had to be
 * written once per dialog. The confirmation is deliberately *not* one of them: it is
 * built by hand onto `document.body`, for the reason its own comment gives.
 *
 * `teardownOverlay` is the single dismantling of the confirmation's body-level scrim
 * and its document keydown listeners. It ran in three places (open, close, and the
 * panel's `disconnectedCallback`) as three copies of the same twelve lines; the panel's
 * unmount path still owns the call, but no longer the code.
 *
 * Free functions over a `PanelHost` (see `panel-host.ts`), except `makeDialog`, which
 * touches no panel state at all.
 */

import * as api from './api';
import {
  haDateTimeToIso,
  isoToHaDateTime,
  selDateTime,
  selEntity,
  selNumber,
  selText,
  type FormField,
} from './forms';
import { t } from './i18n';
import type { MarkdownPreview } from './markdown';
import type { PanelHost } from './panel-host';
import type { Completion, Hass, Task } from './types';
import { setBtnWeight, taskRecordsReading } from './utils';

// ── completion dialog lifecycle ─────────────────────────────────────────────

/** Open the completion-details dialog to log a new completion for *task*. */
export function openCompletionDialog(p: PanelHost, task: Task): void {
  p._completion = {
    open: true,
    task,
    data: {},
    required:
      task.completion_detail === 'required' ? task.completion_required_fields || ['note'] : [],
  };
  p._render();
}

/** Open the dialog to edit an already-recorded completion's metadata. */
export function openCompletionEdit(p: PanelHost, task: Task, c: Completion): void {
  p._completion = {
    open: true,
    task,
    ts: c.ts,
    data: { note: c.note, cost: c.cost, photo: c.photo, who: c.who, reading: c.reading },
    required: [],
  };
  p._render();
}

function closeCompletionDialog(p: PanelHost): void {
  p._completion = { open: false, task: null, data: {}, required: [] };
  p._render();
}

/**
 * Open the "move date" dialog to re-timestamp an already-recorded completion.
 * Distinct from `openCompletionEdit` (metadata only) — this changes `ts` itself
 * via `api.moveCompletion`, never `api.updateCompletion`.
 */
export function openMoveCompletion(p: PanelHost, task: Task, ts: string): void {
  p._moveCompletion = { open: true, task, ts, newTs: ts };
  p._render();
}

function closeMoveCompletion(p: PanelHost): void {
  p._moveCompletion = { open: false, task: null, ts: '' };
  p._render();
}

async function submitMoveCompletion(p: PanelHost): Promise<void> {
  const m = p._moveCompletion;
  if (!p._hass || !m.task || !m.newTs) return;
  try {
    await api.moveCompletion(p._hass, m.task.id, m.ts, m.newTs);
    closeMoveCompletion(p);
    await p._refresh();
  } catch (err) {
    m.error = String((err as { message?: string })?.message || err);
    p._render();
  }
}

/** True when every required field of the in-progress completion is filled. */
function completionMissing(p: PanelHost): string[] {
  const d = p._completion.data;
  return p._completion.required.filter((f) => {
    const v = (d as Record<string, unknown>)[f];
    return v == null || v === '' || (typeof v === 'number' && Number.isNaN(v));
  });
}

/** Save the dialog: a new completion (with metadata) or an edit of a past one. */
async function submitCompletion(p: PanelHost): Promise<void> {
  const c = p._completion;
  if (!p._hass || !c.task) return;
  if (c.ts == null && completionMissing(p).length) {
    c.error = t('completion.required');
    p._render();
    return;
  }
  try {
    if (c.ts != null) {
      await api.updateCompletion(p._hass, c.task.id, c.ts, c.data);
    } else {
      await api.completeTask(p._hass, c.task.id, c.data, c.data.completedAt);
    }
    closeCompletionDialog(p);
    await p._refresh();
  } catch (err) {
    c.error = String((err as { message?: string })?.message || err);
    p._render();
  }
}

// ── destructive-action confirmation ─────────────────────────────────────────

/**
 * Dismantle the confirmation overlay: its body-level scrim and both document keydown
 * listeners (its own, and the drawer's — opening a confirmation takes the drawer's
 * Escape away so one press cannot close two overlays).
 *
 * Safe to call when nothing is open, which is what lets the three callers — opening a
 * confirmation, closing one, and the panel unmounting mid-dialog — share it.
 */
export function teardownOverlay(p: PanelHost): void {
  if (p._drawerOnKey) {
    document.removeEventListener('keydown', p._drawerOnKey);
    p._drawerOnKey = null;
  }
  if (p._confirmOnKey) {
    document.removeEventListener('keydown', p._confirmOnKey);
    p._confirmOnKey = null;
  }
  if (p._confirmScrim) {
    p._confirmScrim.remove();
    p._confirmScrim = null;
  }
}

export function openConfirmDialog(p: PanelHost, label: string, onConfirm: () => void): void {
  // Drop any prior scrim (and its keydown listener) before opening a new one, so a
  // second open — or a stale scrim — can't orphan the earlier overlay + handler.
  teardownOverlay(p);
  p._confirmDelete = { open: true, label, onConfirm };
  renderConfirmDeleteDialog(p);
}

function closeConfirmDialog(p: PanelHost): void {
  p._confirmDelete = { open: false, label: '', onConfirm: null };
  teardownOverlay(p);
  // Opening the confirmation took the drawer's Escape handler away, so that one
  // Escape could not close both overlays at once. Give it back: without this, a
  // Delete the reader thought better of left the drawer standing with no way out
  // but the mouse, for the rest of that edit.
  p._syncDrawerModality();
}

function renderConfirmDeleteDialog(p: PanelHost): void {
  const { label, onConfirm } = p._confirmDelete;

  // Appended to document.body so position:fixed works correctly outside the
  // shadow DOM stacking context.
  const scrim = document.createElement('div');
  scrim.className = 'hk-confirm-scrim';
  scrim.style.cssText =
    'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;' +
    'justify-content:center;background:rgba(0,0,0,.4)';

  const modal = document.createElement('div');
  modal.style.cssText =
    'background:var(--ha-card-background,var(--card-background-color,#fff));' +
    'border-radius:28px;padding:24px;min-width:280px;max-width:400px;' +
    'box-shadow:0 8px 32px rgba(0,0,0,.24)';

  const h2 = document.createElement('h2');
  h2.style.cssText =
    'margin:0 0 16px;font-size:1.25rem;font-weight:500;' +
    'color:var(--primary-text-color,#000)';
  h2.textContent = label;

  const para = document.createElement('p');
  para.style.cssText = 'margin:0 0 24px;color:var(--secondary-text-color,#666)';
  para.textContent = t('confirm.cannotUndo');

  const row = document.createElement('div');
  row.style.cssText = 'display:flex;justify-content:flex-end;gap:8px';

  // Held on an instance field so disconnectedCallback can remove it if we unmount
  // while the dialog is open; closeConfirmDialog is the single teardown path.
  const onKey = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') closeConfirmDialog(p);
  };
  p._confirmOnKey = onKey;
  document.addEventListener('keydown', onKey);

  const close = (): void => {
    closeConfirmDialog(p);
  };

  const cancel = document.createElement('ha-button');
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = t('btn.cancel');
  cancel.addEventListener('click', close);

  // The one surface in the panel whose whole reason to exist is the destruction, so
  // the one place Delete carries a solid fill. Its red comes from `variant`, which
  // resolves against Home Assistant's document-level theme — this scrim is appended
  // to document.body, where the panel's own `:host` tokens do not reach.
  const del = document.createElement('ha-button');
  setBtnWeight(del, 'danger-primary');
  del.textContent = t('btn.delete');
  del.addEventListener('click', () => {
    onConfirm?.();
    closeConfirmDialog(p);
    // Re-render after the mutation: the confirm callbacks (metadata/part row
    // deletion) only mutate state, and neither this handler nor
    // closeConfirmDialog rendered — so a deleted row stayed visible, and its
    // siblings' value-changed closures kept stale render-time indices that wrote
    // into the now-shifted array and corrupted the wrong entry. Rebuilding the form
    // with fresh indices fixes both.
    p._render();
  });

  row.appendChild(cancel);
  row.appendChild(del);
  modal.appendChild(h2);
  modal.appendChild(para);
  modal.appendChild(row);
  scrim.appendChild(modal);
  scrim.addEventListener('click', (e) => {
    if (e.target === scrim) close();
  });

  p._confirmScrim = scrim;
  document.body.appendChild(scrim);
}

// ── dialog shell and the two dialogs built on it ────────────────────────────

/**
 * The shell every panel dialog shares: an open `ha-dialog` carrying *title*, the
 * content div its form goes in, and the footer its action buttons slot into.
 *
 * The panel's two dialogs were hand-built side by side, and Home Assistant has now
 * broken both the same way twice by moving `ha-dialog` onto `wa-dialog`. #144 took
 * the action buttons — only a `footer` slot survived, and buttons slotted straight
 * onto `ha-dialog` stopped rendering. #262 took the titles — `heading` is no longer
 * read at all, and the title now comes from a `headerTitle` slot, so both dialogs
 * had been opening as a bare ✕ over their body with no way to tell which task you
 * were completing. Each time the same fix had to be written twice. It is written
 * once here.
 *
 * The title is set **both** ways rather than feature-detected. A current frontend
 * renders the slotted span and ignores the unread attribute; an older one renders
 * the attribute and drops the span, because a light-DOM child whose slot name
 * matches no slot is not rendered at all. Neither can show the title twice.
 */
function makeDialog(
  title: string,
  onClosed: () => void,
): { dialog: HTMLElement; body: HTMLElement; footer: HTMLElement; mount: () => void } {
  const dialog = document.createElement('ha-dialog');
  dialog.setAttribute('open', '');
  dialog.setAttribute('heading', title);
  const heading = document.createElement('span');
  heading.setAttribute('slot', 'headerTitle');
  heading.textContent = title;
  dialog.appendChild(heading);
  dialog.addEventListener('closed', onClosed);

  const body = document.createElement('div');
  body.className = 'hk-completion-body';

  // Action buttons must be wrapped in <ha-dialog-footer slot="footer"> — current
  // ha-dialog only exposes a "footer" slot; primaryAction/secondaryAction slotted
  // directly on <ha-dialog> silently don't render. Fall back to slotting straight
  // on <ha-dialog> (the pre-wa-dialog convention) if ha-dialog-footer isn't
  // registered, so older HA frontends keep working too.
  const hasFooter = Boolean(customElements.get('ha-dialog-footer'));
  const footer: HTMLElement = hasFooter ? document.createElement('ha-dialog-footer') : dialog;
  if (hasFooter) footer.setAttribute('slot', 'footer');

  // Deferred so the caller can fill body and footer in whatever order reads best,
  // while the dialog still reaches the DOM with its children already attached.
  const mount = (): void => {
    dialog.appendChild(body);
    if (hasFooter) dialog.appendChild(footer);
  };
  return { dialog, body, footer, mount };
}

/** Build the completion-details dialog (log a new completion, or edit a past one). */
export function renderCompletionDialog(p: PanelHost, host: HTMLElement): void {
  const c = p._completion;
  if (!c.task) return;
  const editing = c.ts != null;
  const { dialog, body, footer, mount } = makeDialog(
    editing ? t('completion.edit') : t('completion.title', { name: c.task.name }),
    () => {
      if (p._completion.open) closeCompletionDialog(p);
    },
  );

  // note / cost / who via ha-form; required fields get the asterisk cue. Logging a
  // *new* completion also offers an optional "Completed at" date/time (defaults to
  // now server-side when left blank) — never shown in edit-metadata mode, which
  // must never touch the timestamp (see MoveCompletionDialogState for that).
  const req = new Set(c.required);
  const schema: FormField[] = [];
  if (!editing) {
    schema.push({ name: 'completedAt', selector: selDateTime() });
  }
  schema.push(
    { name: 'note', required: req.has('note'), selector: selText(true) },
    { name: 'cost', required: req.has('cost'), selector: selNumber(0) },
    { name: 'who', required: req.has('who'), selector: selEntity({ domain: 'person' }) },
  );
  // A sensor task in a numeric mode also logs where its meter stood. Home Keeper
  // fills this in from the live sensor, so it is never *required* — but it is
  // editable, which matters twice: back-dating records today's reading (the meter
  // has moved since the work was done), and on a usage task correcting it on the
  // latest completion re-anchors the meter itself. Bare number selector, like the
  // form's starting-reading box: a reading can be 0 or negative.
  const live = taskRecordsReading(c.task) ? p._sensorLive(c.task) : null;
  if (live)
    schema.push({
      name: 'reading',
      selector: { number: { mode: 'box', step: 'any' } },
    });
  // A completion note renders as Markdown in the history list, so it gets the same
  // live preview as every other notes field.
  let notePreview: MarkdownPreview | null = null;
  const form = p._makeForm(
    schema,
    {
      completedAt: isoToHaDateTime(c.data.completedAt),
      note: c.data.note ?? '',
      cost: c.data.cost ?? undefined,
      who: c.data.who ?? undefined,
      // Logging a new completion pre-fills the live reading (that *is* where the
      // meter stands); editing shows what was recorded at the time.
      reading: c.data.reading ?? (editing ? undefined : live?.reading),
    },
    (value) => {
      p._completion.data = {
        ...p._completion.data,
        completedAt: editing ? c.data.completedAt : haDateTimeToIso(value.completedAt as string),
        note: (value.note as string) || undefined,
        cost: value.cost == null || value.cost === '' ? undefined : Number(value.cost),
        who: (value.who as string) || undefined,
        reading:
          value.reading == null || value.reading === '' ? undefined : Number(value.reading),
      };
      p._completion.error = undefined;
      notePreview?.update(String(value.note ?? ''));
    },
  );
  body.appendChild(form);
  notePreview = p._attachNotePreview(body, String(c.data.note ?? ''));

  // Photo upload via HA's native picture-upload, if the element is available in
  // this frontend build (degrade gracefully if not — the rest still works).
  if (customElements.get('ha-picture-upload')) {
    const label = document.createElement('div');
    label.className = 'hk-completion-photo-label';
    label.textContent = t('completion.photo');
    const upload = document.createElement('ha-picture-upload') as HTMLElement & {
      hass?: Hass;
      value?: string | null;
    };
    upload.hass = p._hass;
    upload.value = c.data.photo ?? null;
    p._liveHassEls.push(upload);
    const onPhoto = (): void => {
      p._completion.data = { ...p._completion.data, photo: upload.value || undefined };
    };
    upload.addEventListener('change', onPhoto);
    upload.addEventListener('value-changed', onPhoto);
    body.append(label, upload);
  }

  if (c.error) {
    const err = document.createElement('ha-alert');
    err.setAttribute('alert-type', 'error');
    err.textContent = c.error;
    body.appendChild(err);
  }
  // Primary action: log (or save edit). Optional-mode logging also offers "skip
  // details" to complete with nothing recorded — a real alternative way through, so
  // tonal; Cancel is the null action and stays tertiary beside them.
  const primary = document.createElement('ha-button');
  primary.setAttribute('slot', 'primaryAction');
  setBtnWeight(primary, 'primary');
  primary.textContent = editing ? t('btn.save') : t('completion.markDone');
  primary.addEventListener('click', () => void submitCompletion(p));
  footer.appendChild(primary);

  if (!editing && c.task.completion_detail === 'optional') {
    const skip = document.createElement('ha-button');
    skip.setAttribute('slot', 'secondaryAction');
    setBtnWeight(skip, 'secondary');
    skip.textContent = t('completion.skip');
    skip.addEventListener('click', () => {
      p._completion.data = {};
      void submitCompletion(p);
    });
    footer.appendChild(skip);
  }
  const cancel = document.createElement('ha-button');
  cancel.setAttribute('slot', 'secondaryAction');
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = t('btn.cancel');
  cancel.addEventListener('click', () => closeCompletionDialog(p));
  footer.appendChild(cancel);

  mount();
  host.appendChild(dialog);
}

/**
 * Build the "move completion date" dialog — re-timestamps one already-recorded
 * completion via `api.moveCompletion`. Deliberately minimal (one date/time field)
 * and separate from `renderCompletionDialog`'s edit-metadata mode.
 */
export function renderMoveCompletionDialog(p: PanelHost, host: HTMLElement): void {
  const m = p._moveCompletion;
  if (!m.task) return;
  const { dialog, body, footer, mount } = makeDialog(t('completion.moveDate'), () => {
    if (p._moveCompletion.open) closeMoveCompletion(p);
  });

  const schema: FormField[] = [{ name: 'completedAt', required: true, selector: selDateTime() }];
  const form = p._makeForm(
    schema,
    { completedAt: isoToHaDateTime(m.newTs) },
    (value) => {
      p._moveCompletion.newTs = haDateTimeToIso(value.completedAt as string);
      p._moveCompletion.error = undefined;
    },
  );
  body.appendChild(form);

  if (m.error) {
    const err = document.createElement('ha-alert');
    err.setAttribute('alert-type', 'error');
    err.textContent = m.error;
    body.appendChild(err);
  }

  const primary = document.createElement('ha-button');
  primary.setAttribute('slot', 'primaryAction');
  setBtnWeight(primary, 'primary');
  primary.textContent = t('btn.save');
  primary.addEventListener('click', () => void submitMoveCompletion(p));
  footer.appendChild(primary);

  const cancel = document.createElement('ha-button');
  cancel.setAttribute('slot', 'secondaryAction');
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = t('btn.cancel');
  cancel.addEventListener('click', () => closeMoveCompletion(p));
  footer.appendChild(cancel);

  mount();
  host.appendChild(dialog);
}
