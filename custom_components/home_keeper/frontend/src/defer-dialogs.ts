/**
 * The DOM half of snooze and skip: the menu controller and the two dialogs.
 *
 * Split from `defer.ts` on purpose. That module holds the decisions — which verbs a
 * task may be offered, what a preset resolves to — and is on the mutation surface,
 * where a score means something. This one assembles elements, so its mutants are
 * `className = ""` and `t("")`: killing them would mean asserting on every class name
 * and translation key, which pins the implementation rather than the behaviour. The
 * e2e specs cover this half, the same way they cover panel.ts.
 */

import * as api from './api';
import type { DeferVerbs, SkipState, SnoozeState } from './defer';
import {
  LATER_DATES,
  laterRows,
  moveHintText,
  moveTarget,
  occurrenceOrigin,
  offersLaterDates,
  pickOccurrence,
  snoozeHintText,
  snoozeTarget,
} from './defer';
import { makeDialog } from './dialogs';
import type { FormField, HaFormElement } from './forms';
import { selDate, selDateTime, selSelect, selText } from './forms';
import { t } from './i18n';
import type { Hass, Task } from './types';
import type { SnoozePresetId } from './utils';
import {
  SNOOZE_PRESETS,
  escapeHTML,
  formatOccurrenceTime,
  guardWrite,
  setBtnWeight,
  taskRecordsReading,
} from './utils';

/**
 * Styles for the date list of a fixed task's snooze dialog, shared by the panel and
 * the card:
 * the dialog is built in whichever shadow root opens it, so both stylesheets need
 * them. Written in Home Assistant's own theme variables, because the card has none of
 * the panel's `--hk-*` tokens.
 */
export const LATER_DATES_STYLES = `
  .hk-later-list { display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }
  .hk-later-row {
    appearance: none; font: inherit; text-align: left; cursor: pointer;
    display: flex; flex-wrap: wrap; align-items: center; gap: 2px 8px;
    min-height: 44px; padding: 6px 12px; border-radius: 8px;
    border: 1px solid var(--divider-color); background: transparent;
    color: var(--primary-text-color);
  }
  .hk-later-row:hover { background: var(--secondary-background-color); }
  .hk-later-row.picked {
    border-color: var(--primary-color);
    background: color-mix(in srgb, var(--primary-color) 12%, transparent);
  }
  .hk-later-row:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  .hk-later-date { font-weight: 500; }
  .hk-later-tag { font-size: 0.85em; color: var(--secondary-text-color); }
  .hk-later-head { font-size: 0.85em; color: var(--secondary-text-color); margin: 8px 0 0; }
  .hk-later-from { flex-basis: 100%; font-size: 0.85em; color: var(--secondary-text-color); }
  .hk-moved-badge {
    font-size: 0.75rem; font-weight: 600; padding: 1px 8px; border-radius: 999px;
    background: color-mix(in srgb, var(--warning-color, #ffa600) 18%, transparent);
    color: var(--primary-text-color);
  }
  .hk-move-lead { font-size: 0.85em; color: var(--secondary-text-color); margin-top: 6px; }
`;

/** What a host must supply for the menu to do anything. */
export interface DeferMenuHost {
  /** The task a split button stands for, by the id in its dataset. */
  taskById(id: string): Task | undefined;
  onSnooze(task: Task): void;
  onSkip(task: Task): void;
  onDueToday(task: Task): void;
  /** Open the completion dialog. Only the panel offers it (#399). */
  onDetails?(task: Task): void;
}

/**
 * Opens and dismisses deferral menus for one host.
 *
 * One controller per host holds the single open menu, so opening a second closes the
 * first without either caret having to know about the other.
 */
export class DeferMenus {
  private _open: { caret: HTMLElement; menu: HTMLElement } | null = null;
  private _onKey: ((e: KeyboardEvent) => void) | null = null;
  private _onClick: ((e: Event) => void) | null = null;
  /** A scroll or resize moves the button, but not the menu in the top layer. */
  private readonly _onMove = (): void => {
    if (this._split && this._open) placeMenu(this._split, this._open.menu);
  };
  private _split: HTMLElement | null = null;

  constructor(private readonly host: DeferMenuHost) {}

  /** Wire every split button under *root*. Safe to call on each render. */
  wire(root: ParentNode, caretSelector = '.hk-split-caret'): void {
    root.querySelectorAll<HTMLElement>('.hk-split').forEach((split) => {
      const task = split.dataset.id ? this.host.taskById(split.dataset.id) : undefined;
      if (task) this._wireOne(split, task, caretSelector);
    });
  }

  /** Whether a menu is open now. A background re-render would close it. */
  get isOpen(): boolean {
    return this._open !== null;
  }

  /** Close whatever is open. Hosts call this before replacing their markup. */
  close(): void {
    if (this._onKey) {
      document.removeEventListener('keydown', this._onKey);
      this._onKey = null;
    }
    if (this._onClick) {
      document.removeEventListener('click', this._onClick);
      this._onClick = null;
    }
    window.removeEventListener('scroll', this._onMove, true);
    window.removeEventListener('resize', this._onMove);
    if (!this._open) return;
    this._split = null;
    this._open.menu.hidden = true;
    if (typeof this._open.menu.hidePopover === 'function') {
      try {
        this._open.menu.hidePopover();
      } catch {
        /* not shown: the menu opened without the top layer */
      }
    }
    this._open.caret.setAttribute('aria-expanded', 'false');
    this._open = null;
  }

  private _wireOne(split: HTMLElement, task: Task, caretSelector: string): void {
    const caret = split.querySelector<HTMLElement>(caretSelector);
    const menu = split.querySelector<HTMLElement>('.hk-defer-menu');
    if (!caret || !menu) return;
    caret.addEventListener('click', (e) => {
      // A row opens the task's detail page and the caret sits inside it — without
      // this the menu would open and immediately navigate away from itself.
      e.stopPropagation();
      if (menu.hidden) this._openMenu(split, caret, menu);
      else this.close();
    });
    menu.addEventListener('click', (e) => e.stopPropagation());
    // A list keeps a row across a reload when the row's markup did not change, so the
    // task is read again at click time. The one found at wire time can be an older copy.
    const current = (): Task => this.host.taskById(task.id) ?? task;
    menu.querySelector('.hk-defer-snooze')?.addEventListener('click', () => {
      this.close();
      this.host.onSnooze(current());
    });
    menu.querySelector('.hk-defer-skip')?.addEventListener('click', () => {
      this.close();
      this.host.onSkip(current());
    });
    menu.querySelector('.hk-defer-due-today')?.addEventListener('click', () => {
      this.close();
      this.host.onDueToday(current());
    });
    menu.querySelector('.hk-defer-details')?.addEventListener('click', () => {
      this.close();
      this.host.onDetails?.(current());
    });
  }

  /**
   * Open one menu, closing any other, and arm its dismiss handlers.
   *
   * The handlers go on `document` rather than the host's own root, and are added on
   * open and removed on close rather than once per render. Both details matter.
   * Escape is delivered to whatever holds focus, and after a background refresh
   * replaces the caret that is the document body — so a listener confined to the
   * shadow root would simply never see the key. And a listener bound during render
   * would be re-added on every subsequent render, since the root outlives them all.
   */
  private _openMenu(split: HTMLElement, caret: HTMLElement, menu: HTMLElement): void {
    this.close();
    menu.hidden = false;
    // The top layer is outside every card, so no theme can clip or cover the menu.
    // A browser without the Popover API keeps the menu in the card, where CSS places it.
    if (typeof menu.showPopover === 'function') {
      menu.setAttribute('popover', 'manual');
      menu.showPopover();
      placeMenu(split, menu);
    }
    caret.setAttribute('aria-expanded', 'true');
    // The menu pattern (X11-5): focus goes to the first item on open, the arrow
    // keys, Home and End move it, and Escape puts it back on the caret. Without
    // this, focus stayed on the caret, and Escape from an item hid the focused
    // node, so focus fell to the page body.
    const items = Array.from(menu.querySelectorAll<HTMLElement>('[role="menuitem"]'));
    items[0]?.focus();
    this._onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        this.close();
        caret.focus();
        return;
      }
      const at = items.findIndex((item) => e.composedPath().includes(item));
      const next = menuKeyTarget(e.key, at, items.length);
      if (next == null) return;
      e.preventDefault();
      items[next].focus();
    };
    this._onClick = (e: Event) => {
      // A click inside a shadow root retargets to the host at document level, so
      // `contains` would see the component rather than the menu; the composed path
      // is what still names the real target.
      if (!e.composedPath().includes(split)) this.close();
    };
    document.addEventListener('keydown', this._onKey);
    document.addEventListener('click', this._onClick);
    window.addEventListener('scroll', this._onMove, true);
    window.addEventListener('resize', this._onMove);
    this._split = split;
    this._open = { caret, menu };
  }
}

/** The gap, in px, between the split button and its menu, and to the viewport edge. */
const MENU_GAP = 6;
const MENU_MARGIN = 12;

/**
 * Put an open top-layer menu under its split button.
 *
 * A top-layer element is placed against the viewport, so the position comes from the
 * button's box. A list row keeps its actions at the right margin, so its menu lines
 * up with the right edge of the button. The task page lines up with the left edge. The
 * menu stays inside the viewport, and opens above the button when there is no room
 * below.
 */
export function placeMenu(split: HTMLElement, menu: HTMLElement): void {
  const at = split.getBoundingClientRect();
  const { width, height } = menu.getBoundingClientRect();
  const rightEdge = split.closest('.hk-card-actions') !== null;
  const wanted = rightEdge ? at.right - width : at.left;
  const left = Math.max(MENU_MARGIN, Math.min(wanted, window.innerWidth - width - MENU_MARGIN));
  const below = at.bottom + MENU_GAP;
  const above = at.top - MENU_GAP - height;
  const top = below + height > window.innerHeight - MENU_GAP && above >= MENU_GAP ? above : below;
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
}

/**
 * The index of the menu item that *key* moves focus to, from the item at *at*
 * (-1 when focus is not on an item), in a menu of *count* items. `null` when the
 * key does not move focus. The arrow keys wrap around.
 */
export function menuKeyTarget(key: string, at: number, count: number): number | null {
  if (!count) return null;
  switch (key) {
    case 'ArrowDown':
      return at < 0 ? 0 : (at + 1) % count;
    case 'ArrowUp':
      return at < 0 ? count - 1 : (at - 1 + count) % count;
    case 'Home':
      return 0;
    case 'End':
      return count - 1;
    default:
      return null;
  }
}

/* ── The Snooze and Skip dialogs ──────────────────────────────────────────────
   Both hosts open the same two dialogs, so they are built here against a small
   host interface rather than against either component. The host supplies what
   genuinely differs — its `hass`, its language, how it builds a form, and how it
   re-renders and reloads — and nothing else. */

/** What a host must supply for the dialogs to build and submit. */
export interface DeferDialogHost {
  /** A function, not a field: the host's `hass` is replaced on every update. */
  hass(): Hass | undefined;
  lang(): string | undefined;
  makeForm(
    schema: FormField[],
    data: Record<string, unknown>,
    onChange: (value: Record<string, unknown>) => void,
  ): HaFormElement;
  /** Re-render the host, which is how a dialog picks up new state. */
  rerender(): void;
  /** Reload tasks after a successful write. */
  refresh(): Promise<void>;
  /** Show a short message. For an error of a dialog that is no longer open. */
  notify?(message: string): void;
}

/**
 * *close* made safe for a request that ends late (F10-3). A dialog closes its own
 * state only: after the user dismissed it, the host can show a different dialog of
 * the same kind, and a late reply must not close that one. Dismissal sets
 * `open = false` on the state object, so a later call does nothing.
 */
function closeOnce(s: { open: boolean }, close: () => void): () => void {
  return () => {
    if (!s.open) return;
    s.open = false;
    close();
  };
}

/**
 * Show the error of a failed write: in the dialog when it is still open, else as a
 * message from the host, because the dialog state is gone from the screen (F10-3).
 */
function reportError(
  host: DeferDialogHost,
  s: { open: boolean; error?: string },
  err: unknown,
): void {
  const message = String((err as { message?: string })?.message || err);
  if (s.open) {
    s.error = message;
    host.rerender();
  } else {
    host.notify?.(message);
  }
}

function footerButtons(
  footer: HTMLElement,
  primaryLabel: string,
  onPrimary: (button: Element) => void,
  onCancel: () => void,
): void {
  const primary = document.createElement('ha-button');
  primary.setAttribute('slot', 'primaryAction');
  setBtnWeight(primary, 'primary');
  primary.textContent = primaryLabel;
  primary.addEventListener('click', () => onPrimary(primary));
  footer.appendChild(primary);

  const cancel = document.createElement('ha-button');
  cancel.setAttribute('slot', 'secondaryAction');
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = t('btn.cancel');
  cancel.addEventListener('click', onCancel);
  footer.appendChild(cancel);
}

function errorAlert(body: HTMLElement, message?: string): void {
  if (!message) return;
  const err = document.createElement('ha-alert');
  err.setAttribute('alert-type', 'error');
  err.textContent = message;
  body.appendChild(err);
}

/** Build the snooze dialog into *mountTo*, closing through *close*. */
export function renderSnoozeDialog(
  host: DeferDialogHost,
  s: SnoozeState,
  mountTo: HTMLElement,
  close: () => void,
): void {
  if (!s.task) return;
  close = closeOnce(s, close);
  const { dialog, body, footer, mount } = makeDialog(t('defer.snoozeTitle'), close);

  if (offersLaterDates(s.task)) {
    renderDateList(host, s, body);
    if (s.picked) {
      renderMoveTo(host, s, body, mountTo);
      errorAlert(body, s.error);
      footerButtons(footer, t('btn.move'), () => void submitMove(host, s, close), close);
      mount();
      mountTo.appendChild(dialog);
      return;
    }
  }

  const options = SNOOZE_PRESETS.map((p) => ({ value: p.id, label: t('defer.preset.' + p.id) }));
  const schema: FormField[] = [
    { name: 'snoozePreset', required: true, selector: selSelect(options) },
  ];
  // With a set due time the task is due at that time, so the custom choice is a
  // date only (#438).
  if (s.preset === 'custom') {
    schema.push({
      name: 'snoozeAt',
      required: true,
      selector: s.dueTime ? selDate() : selDateTime(),
    });
  }
  const data: Record<string, unknown> = { snoozePreset: s.preset };
  if (s.preset === 'custom') data.snoozeAt = s.customAt ?? '';

  const form = host.makeForm(schema, data, (value) => {
    const preset = String(value.snoozePreset ?? s.preset) as SnoozePresetId;
    const wasCustom = s.preset === 'custom';
    s.preset = preset;
    s.customAt = value.snoozeAt == null ? s.customAt : String(value.snoozeAt);
    s.error = undefined;
    // Only a change in *which fields exist* justifies a re-render; anything else
    // would steal focus mid-keystroke, so the hint is updated in place instead.
    if (wasCustom !== (preset === 'custom')) host.rerender();
    else updateSnoozeHint(mountTo, s, host.lang());
  });
  body.appendChild(form);

  const hint = document.createElement('div');
  hint.className = 'hk-snooze-hint';
  hint.textContent = snoozeHintText(s, host.lang());
  body.appendChild(hint);

  errorAlert(body, s.error);
  footerButtons(footer, t('btn.snooze'), (b) => void submitSnooze(host, s, close, b), close);
  mount();
  mountTo.appendChild(dialog);
}

/**
 * The dates of a fixed task's snooze dialog. The first row is the due date, and a
 * snooze moves it. Each later row is a date of the schedule, and picking one moves
 * only that date (for "the city moved next week's pickup"). The later dates are asked
 * for when the dialog opens, from the engine the calendar reads, so a date that
 * already moved shows where it is now.
 */
function renderDateList(host: DeferDialogHost, s: SnoozeState, body: HTMLElement): void {
  const lang = host.lang();
  const list = document.createElement('div');
  list.className = 'hk-later-list';
  list.setAttribute('role', 'group');
  list.setAttribute('aria-label', t('defer.snoozeTitle'));
  body.appendChild(list);
  const row = (html: string, picked: boolean, onPick: () => void, start?: string) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'hk-later-row';
    btn.classList.toggle('picked', picked);
    btn.setAttribute('aria-pressed', String(picked));
    if (start) btn.dataset.start = start;
    btn.innerHTML = html;
    btn.addEventListener('click', () => {
      onPick();
      host.rerender();
    });
    list.appendChild(btn);
  };
  const due = s.task?.next_due;
  if (due) {
    row(
      `<span class="hk-later-date">${escapeHTML(formatOccurrenceTime(due, lang))}</span>` +
        `<span class="hk-later-tag">${escapeHTML(t('defer.nextDate'))}</span>`,
      !s.picked,
      () => pickOccurrence(s),
      due,
    );
  }
  if (s.occurrences === undefined) {
    const loading = document.createElement('div');
    loading.className = 'hk-later-head';
    loading.textContent = t('defer.loadingDates');
    list.appendChild(loading);
    void loadLaterDates(host, s);
    return;
  }
  const later = laterRows(s);
  if (!later.length) return;
  const head = document.createElement('div');
  head.className = 'hk-later-head';
  head.textContent = t('defer.laterDate');
  list.appendChild(head);
  for (const occ of later) {
    const picked = s.picked != null && occurrenceOrigin(s.picked) === occurrenceOrigin(occ);
    const moved = occ.moved_from
      ? `<span class="hk-moved-badge">${escapeHTML(t('upcoming.moved'))}</span>` +
        `<span class="hk-later-from">${escapeHTML(
          t('upcoming.movedFrom', { date: formatOccurrenceTime(occ.moved_from, lang) }),
        )}</span>`
      : '';
    row(
      `<span class="hk-later-date">${escapeHTML(formatOccurrenceTime(occ.start, lang))}</span>${moved}`,
      picked,
      () => pickOccurrence(s, occ),
      occ.start,
    );
  }
}

/** Where the picked later date goes, and what that does. */
function renderMoveTo(
  host: DeferDialogHost,
  s: SnoozeState,
  body: HTMLElement,
  mountTo: HTMLElement,
): void {
  const form = host.makeForm(
    [{ name: 'moveTo', required: true, selector: selDateTime() }],
    { moveTo: s.moveTo ?? '' },
    (value) => {
      s.moveTo = value.moveTo == null ? s.moveTo : String(value.moveTo);
      s.error = undefined;
      updateMoveHint(mountTo, s, host.lang());
    },
  );
  form.classList.add('hk-later-to');
  body.appendChild(form);
  const hint = document.createElement('div');
  hint.className = 'hk-snooze-hint hk-move-hint';
  hint.textContent = moveHintText(s, host.lang());
  body.appendChild(hint);
  const lead = document.createElement('div');
  lead.className = 'hk-move-lead';
  lead.textContent = t('move.lead');
  body.appendChild(lead);
}

async function loadLaterDates(host: DeferDialogHost, s: SnoozeState): Promise<void> {
  const hass = host.hass();
  if (!hass || !s.task) return;
  try {
    s.occurrences = await api.upcomingOccurrences(hass, { taskId: s.task.id }, LATER_DATES);
  } catch (err) {
    s.occurrences = [];
    s.error = String((err as { message?: string })?.message || err);
  }
  if (s.open) host.rerender();
}

/** Refresh the move line without re-rendering (which would steal focus). */
export function updateMoveHint(root: ParentNode, s: SnoozeState, lang?: string): void {
  const hint = root.querySelector<HTMLElement>('.hk-move-hint');
  if (hint) hint.textContent = moveHintText(s, lang);
}

export async function submitMove(
  host: DeferDialogHost,
  s: SnoozeState,
  close: () => void,
): Promise<void> {
  const to = moveTarget(s);
  const hass = host.hass();
  if (!hass || !s.task) return;
  if (!s.picked || !to) {
    // Say what is missing rather than doing nothing on Move.
    s.error = t(s.picked ? 'defer.snoozePickDate' : 'defer.movePick');
    host.rerender();
    return;
  }
  try {
    await api.moveOccurrence(hass, s.task.id, occurrenceOrigin(s.picked), to.toISOString());
    close();
    await host.refresh();
  } catch (err) {
    s.error = String((err as { message?: string })?.message || err);
    host.rerender();
  }
}

/** Refresh the resolved-date line without re-rendering (which would steal focus). */
export function updateSnoozeHint(root: ParentNode, s: SnoozeState, lang?: string): void {
  const hint = root.querySelector<HTMLElement>('.hk-snooze-hint');
  if (hint) hint.textContent = snoozeHintText(s, lang);
}

export async function submitSnooze(
  host: DeferDialogHost,
  s: SnoozeState,
  close: () => void,
  button?: Element | null,
): Promise<void> {
  const until = snoozeTarget(s);
  const hass = host.hass();
  const task = s.task;
  if (!hass || !task || !until) return;
  // A second press while the first call runs is ignored (X12-3).
  await guardWrite(
    s,
    async () => {
      try {
        await api.snoozeTask(hass, task.id, until.toISOString());
        close();
        await host.refresh();
      } catch (err) {
        reportError(host, s, err);
      }
    },
    button,
  );
}

/**
 * Build the skip dialog into *mountTo* — the note, who, and (for a usage task) the
 * meter reading.
 *
 * No duration: a skip advances to the next occurrence and that is the whole of it.
 * The same dialog amends an already-logged skip, which is why the title and the
 * primary button read differently when `ts` is set.
 */
export function renderSkipDialog(
  host: DeferDialogHost,
  s: SkipState,
  mountTo: HTMLElement,
  close: () => void,
): void {
  if (!s.task) return;
  close = closeOnce(s, close);
  const editing = s.ts != null;
  const { dialog, body, footer, mount } = makeDialog(
    editing ? t('defer.skipEditTitle') : t('defer.skipTitle'),
    close,
  );

  if (!editing) {
    const lead = document.createElement('div');
    lead.className = 'hk-snooze-hint';
    lead.textContent = t('defer.skipLead');
    body.appendChild(lead);
  }

  const schema: FormField[] = [
    { name: 'skipNote', selector: selText(true) },
    { name: 'skipWho', selector: selText() },
  ];
  // Only a metered task has a reading to record; asking every task for one would be
  // a field with no meaning attached. Bare number selector like the completion
  // dialog's: a reading can be 0 or negative, so it takes no minimum.
  if (taskRecordsReading(s.task)) {
    schema.push({ name: 'skipReading', selector: { number: { mode: 'box', step: 'any' } } });
  }
  const form = host.makeForm(
    schema,
    { skipNote: s.data.note ?? '', skipWho: s.data.who ?? '', skipReading: s.data.reading ?? '' },
    (value) => {
      const reading = Number(value.skipReading);
      s.data = {
        note: String(value.skipNote ?? '') || undefined,
        who: String(value.skipWho ?? '') || undefined,
        reading:
          value.skipReading === '' || value.skipReading == null || Number.isNaN(reading)
            ? undefined
            : reading,
      };
      s.error = undefined;
    },
  );
  body.appendChild(form);

  errorAlert(body, s.error);
  footerButtons(
    footer,
    editing ? t('btn.save') : t('btn.skip'),
    (b) => void submitSkip(host, s, close, b),
    close,
  );
  mount();
  mountTo.appendChild(dialog);
}

export async function submitSkip(
  host: DeferDialogHost,
  s: SkipState,
  close: () => void,
  button?: Element | null,
): Promise<void> {
  const hass = host.hass();
  const task = s.task;
  if (!hass || !task) return;
  // A double click must not skip two occurrences (X12-3).
  await guardWrite(
    s,
    async () => {
      try {
        if (s.ts != null) await api.updateSkip(hass, task.id, s.ts, s.data);
        else await api.skipTask(hass, task.id, s.data);
        close();
        await host.refresh();
      } catch (err) {
        reportError(host, s, err);
      }
    },
    button,
  );
}
