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
  sensorLive,
  type FormField,
} from './forms';
import { t } from './i18n';
import type { MarkdownPreview } from './markdown';
import type { PanelHost } from './panel-host';
import { dialogCoverEl } from './panel-photo-markup';
import type { Completion, Hass, Task } from './types';
import { guardWrite, setBtnWeight, taskRecordsReading, toast } from './utils';

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
  p._moveCompletion = { open: true, task, ts, newTs: ts, kind: 'completion' };
  p._render();
}

function closeMoveCompletion(p: PanelHost): void {
  p._moveCompletion = { open: false, task: null, ts: '' };
  p._render();
}

async function submitMoveCompletion(p: PanelHost, button?: Element | null): Promise<void> {
  const m = p._moveCompletion;
  const hass = p._hass;
  const task = m.task;
  const newTs = m.newTs;
  if (!hass || !task || !newTs) return;
  await guardWrite(
    m,
    async () => {
      try {
        // Same dialog, two logs: `kind` says which list the entry being re-dated is in.
        if (m.kind === 'skip') await api.moveSkip(hass, task.id, m.ts, newTs);
        else await api.moveCompletion(hass, task.id, m.ts, newTs);
        // Close only this dialog: the user can have opened another one while the
        // request ran (F10-3).
        if (p._moveCompletion === m) closeMoveCompletion(p);
        await p._refresh();
      } catch (err) {
        const message = String((err as { message?: string })?.message || err);
        if (p._moveCompletion === m) {
          m.error = message;
          p._render();
        } else {
          toast(p, message);
        }
      }
    },
    button,
  );
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
async function submitCompletion(p: PanelHost, button?: Element | null): Promise<void> {
  const c = p._completion;
  const hass = p._hass;
  const task = c.task;
  if (!hass || !task) return;
  if (c.ts == null && completionMissing(p).length) {
    c.error = t('completion.required');
    p._render();
    return;
  }
  // A double click on Mark done must not log two completions (X12-3).
  await guardWrite(
    c,
    async () => {
      try {
        if (c.ts != null) {
          await api.updateCompletion(hass, task.id, c.ts, c.data);
        } else {
          await api.completeTask(hass, task.id, c.data, c.data.completedAt);
        }
        // Close only this dialog: the user can have opened another one while the
        // request ran (F10-3).
        if (p._completion === c) closeCompletionDialog(p);
        await p._refresh();
      } catch (err) {
        const message = String((err as { message?: string })?.message || err);
        if (p._completion === c) {
          c.error = message;
          p._render();
        } else {
          toast(p, message);
        }
      }
    },
    button,
  );
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

export function openConfirmDialog(
  p: PanelHost,
  label: string,
  onConfirm: () => void,
  body: string = t('confirm.cannotUndo'),
): void {
  // Drop any prior scrim (and its keydown listener) before opening a new one, so a
  // second open — or a stale scrim — can't orphan the earlier overlay + handler.
  teardownOverlay(p);
  p._confirmDelete = { open: true, label, body, onConfirm };
  renderConfirmDeleteDialog(p);
}

/** The element that had the keyboard when a confirmation opened, per panel. */
const confirmOpeners = new WeakMap<PanelHost, HTMLElement>();

/** The focused element, looking through open shadow roots to the real control. */
function deepActiveElement(): Element | null {
  let active: Element | null = document.activeElement;
  while (active?.shadowRoot?.activeElement) active = active.shadowRoot.activeElement;
  return active;
}

/**
 * The same scrim, with the destructive button taken away: a heading, a reason, and
 * Close. For an action the backend will refuse, where offering Delete would be a
 * button whose only outcome is an error. `onConfirm` is null, which is what
 * `renderConfirmDeleteDialog` reads to drop the Delete button and to label the one
 * remaining button Close — there is nothing here to cancel.
 */
export function openBlockedDialog(p: PanelHost, label: string, body: string): void {
  teardownOverlay(p);
  p._confirmDelete = { open: true, label, body, onConfirm: null };
  renderConfirmDeleteDialog(p);
}

function closeConfirmDialog(p: PanelHost): void {
  p._confirmDelete = { open: false, label: '', body: '', onConfirm: null };
  teardownOverlay(p);
  // Opening the confirmation took the drawer's Escape handler away, so that one
  // Escape could not close both overlays at once. Give it back: without this, a
  // Delete the reader thought better of left the drawer standing with no way out
  // but the mouse, for the rest of that edit.
  p._syncDrawerModality();
  // Give the keyboard back to the control that opened the dialog (X11-1).
  const opener = confirmOpeners.get(p);
  confirmOpeners.delete(p);
  if (opener?.isConnected) opener.focus();
}

function renderConfirmDeleteDialog(p: PanelHost): void {
  const { label, body, onConfirm } = p._confirmDelete;

  // Appended to document.body so position:fixed works correctly outside the
  // shadow DOM stacking context.
  const scrim = document.createElement('div');
  scrim.className = 'hk-confirm-scrim';
  scrim.style.cssText =
    'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;' +
    'justify-content:center;background:rgba(0,0,0,.4)';

  // A real modal dialog to assistive technology (X11-1): it names itself from its
  // heading, reads its body as the description, and says the page behind is inert.
  // Border-box and the viewport cap keep it on a 320px screen.
  const modal = document.createElement('div');
  modal.className = 'hk-confirm-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-labelledby', 'hk-confirm-title');
  modal.setAttribute('aria-describedby', 'hk-confirm-body');
  modal.style.cssText =
    'background:var(--ha-card-background,var(--card-background-color,#fff));' +
    'border-radius:28px;padding:24px;min-width:280px;max-width:400px;' +
    'box-sizing:border-box;max-width:min(400px,calc(100vw - 32px));' +
    'box-shadow:0 8px 32px rgba(0,0,0,.24)';

  const h2 = document.createElement('h2');
  h2.id = 'hk-confirm-title';
  h2.style.cssText =
    'margin:0 0 16px;font-size:1.25rem;font-weight:500;' +
    'color:var(--primary-text-color,#000)';
  h2.textContent = label;

  const para = document.createElement('p');
  para.id = 'hk-confirm-body';
  para.style.cssText = 'margin:0 0 24px;color:var(--secondary-text-color,#666)';
  para.textContent = body;

  const row = document.createElement('div');
  row.style.cssText = 'display:flex;justify-content:flex-end;gap:8px';

  const close = (): void => {
    closeConfirmDialog(p);
  };

  // Cancel when there is a Delete beside it, Close when this dialog only reports
  // something. A blocked action has nothing to cancel: the save never started.
  const cancel = document.createElement('ha-button');
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = onConfirm ? t('btn.cancel') : t('btn.close');
  cancel.addEventListener('click', close);
  row.appendChild(cancel);

  if (onConfirm) {
    // The one surface in the panel whose whole reason to exist is the destruction, so
    // the one place Delete carries a solid fill. Its red comes from `variant`, which
    // resolves against Home Assistant's document-level theme — this scrim is appended
    // to document.body, where the panel's own `:host` tokens do not reach.
    const del = document.createElement('ha-button');
    setBtnWeight(del, 'danger-primary');
    del.textContent = t('btn.delete');
    del.addEventListener('click', () => {
      onConfirm();
      closeConfirmDialog(p);
      // Re-render after the mutation: the confirm callbacks (metadata/part row
      // deletion) only mutate state, and neither this handler nor
      // closeConfirmDialog rendered — so a deleted row stayed visible, and its
      // siblings' value-changed closures kept stale render-time indices that wrote
      // into the now-shifted array and corrupted the wrong entry. Rebuilding the form
      // with fresh indices fixes both.
      p._render();
    });
    row.appendChild(del);
  }
  modal.appendChild(h2);
  modal.appendChild(para);
  modal.appendChild(row);
  scrim.appendChild(modal);
  scrim.addEventListener('click', (e) => {
    if (e.target === scrim) close();
  });

  // Escape closes. Tab and Shift+Tab move between the dialog's own buttons and never
  // reach the page behind the scrim (X11-1). Held on an instance field so
  // disconnectedCallback can remove it if we unmount while the dialog is open;
  // closeConfirmDialog is the single teardown path.
  const buttons = [...row.children] as HTMLElement[];
  const onKey = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') {
      closeConfirmDialog(p);
      return;
    }
    if (e.key !== 'Tab') return;
    e.preventDefault();
    const at = buttons.indexOf(document.activeElement as HTMLElement);
    const step = e.shiftKey ? -1 : 1;
    const next = at < 0 ? (e.shiftKey ? buttons.length - 1 : 0) : at + step;
    buttons[(next + buttons.length) % buttons.length].focus();
  };
  p._confirmOnKey = onKey;
  document.addEventListener('keydown', onKey);

  const opener = deepActiveElement();
  if (opener instanceof HTMLElement && opener !== document.body) confirmOpeners.set(p, opener);
  p._confirmScrim = scrim;
  document.body.appendChild(scrim);
  // Cancel (or Close) takes the keyboard: the safe choice for a destructive dialog.
  // In a real browser `ha-button` renders its inner <button> asynchronously, and its
  // focus() throws until it has one — which aborted this function and left the
  // keyboard on the opener behind the scrim. So try now (a test double, or a button
  // already rendered), and again once it has rendered, if this dialog is still open.
  const focusCancel = (): void => {
    try {
      cancel.focus();
    } catch {
      // Not rendered yet: the deferred call below focuses it.
    }
  };
  focusCancel();
  void customElements
    .whenDefined('ha-button')
    .then(() => (cancel as HTMLElement & { updateComplete?: Promise<unknown> }).updateComplete)
    .then(() => {
      if (p._confirmScrim === scrim && cancel.isConnected) focusCancel();
    });
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
export function makeDialog(
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
  // `ha-dialog` fires `closed` when it is removed from the DOM, not only when the
  // user dismisses it — and `_render()` removes it, because the dialog host is
  // rebuilt with the rest of the panel. So a re-render *while a dialog is open*
  // reported itself as a dismissal: the handler cleared the dialog state that the
  // very same render was about to rebuild, and the dialog vanished mid-edit. A
  // disconnected dialog is never the one the user closed.
  dialog.addEventListener('closed', () => {
    if (!dialog.isConnected) return;
    onClosed();
  });

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
  const live = taskRecordsReading(c.task) ? sensorLive(p._hass, c.task) : null;
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
  // The task's cover first, when logging a new completion: the person doing the
  // work sees which gap or which filter it was about (#399).
  const cover = editing ? null : dialogCoverEl(p, c.task);
  if (cover) body.appendChild(cover);
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
  primary.addEventListener('click', () => void submitCompletion(p, primary));
  footer.appendChild(primary);

  if (!editing && c.task.completion_detail === 'optional') {
    const skip = document.createElement('ha-button');
    skip.setAttribute('slot', 'secondaryAction');
    setBtnWeight(skip, 'secondary');
    skip.textContent = t('completion.skip');
    skip.addEventListener('click', () => {
      if (p._completion.busy) return;
      p._completion.data = {};
      void submitCompletion(p, skip);
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
  primary.addEventListener('click', () => void submitMoveCompletion(p, primary));
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
