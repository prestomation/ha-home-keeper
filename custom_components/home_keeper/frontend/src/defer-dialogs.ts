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
import { selDateTime, selSelect, selText } from './forms';
import { t } from './i18n';
import type { Hass, Task } from './types';
import type { SnoozePresetId } from './utils';
import {
  SNOOZE_PRESETS,
  escapeHTML,
  formatOccurrenceTime,
  setBtnWeight,
  taskRecordsReading,
} from './utils';

/**
 * Styles for "A later date" and the Upcoming block, shared by the panel and the card:
 * the dialog is built in whichever shadow root opens it, so both stylesheets need
 * them. Written in Home Assistant's own theme variables, because the card has none of
 * the panel's `--hk-*` tokens.
 */
export const LATER_DATES_STYLES = `
  .hk-snooze-mode {
    display: inline-flex; align-self: flex-start; border: 1px solid var(--divider-color);
    border-radius: 999px; overflow: hidden; margin-bottom: 12px;
  }
  .hk-snooze-mode .hk-mode-btn {
    appearance: none; border: 0; background: transparent; cursor: pointer;
    font: inherit; font-size: 0.9rem; padding: 0 16px; min-height: 40px;
    color: var(--primary-text-color);
  }
  .hk-snooze-mode .hk-mode-btn + .hk-mode-btn { border-left: 1px solid var(--divider-color); }
  .hk-snooze-mode .hk-mode-btn:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  .hk-snooze-mode .hk-mode-btn.active {
    background: var(--primary-color); color: var(--text-primary-color, #fff);
  }
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

  constructor(private readonly host: DeferMenuHost) {}

  /** Wire every split button under *root*. Safe to call on each render. */
  wire(root: ParentNode, caretSelector = '.hk-split-caret'): void {
    root.querySelectorAll<HTMLElement>('.hk-split').forEach((split) => {
      const task = split.dataset.id ? this.host.taskById(split.dataset.id) : undefined;
      if (task) this._wireOne(split, task, caretSelector);
    });
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
    if (!this._open) return;
    this._open.menu.hidden = true;
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
    menu.querySelector('.hk-defer-snooze')?.addEventListener('click', () => {
      this.close();
      this.host.onSnooze(task);
    });
    menu.querySelector('.hk-defer-skip')?.addEventListener('click', () => {
      this.close();
      this.host.onSkip(task);
    });
    menu.querySelector('.hk-defer-due-today')?.addEventListener('click', () => {
      this.close();
      this.host.onDueToday(task);
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
    caret.setAttribute('aria-expanded', 'true');
    this._onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') this.close();
    };
    this._onClick = (e: Event) => {
      // A click inside a shadow root retargets to the host at document level, so
      // `contains` would see the component rather than the menu; the composed path
      // is what still names the real target.
      if (!e.composedPath().includes(split)) this.close();
    };
    document.addEventListener('keydown', this._onKey);
    document.addEventListener('click', this._onClick);
    this._open = { caret, menu };
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
}

function footerButtons(
  footer: HTMLElement,
  primaryLabel: string,
  onPrimary: () => void,
  onCancel: () => void,
): void {
  const primary = document.createElement('ha-button');
  primary.setAttribute('slot', 'primaryAction');
  setBtnWeight(primary, 'primary');
  primary.textContent = primaryLabel;
  primary.addEventListener('click', onPrimary);
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
  const { dialog, body, footer, mount } = makeDialog(t('defer.snoozeTitle'), () => {
    if (s.open) close();
  });

  const later = offersLaterDates(s.task) && s.mode === 'later';
  if (offersLaterDates(s.task)) body.appendChild(snoozeModeSwitch(host, s));
  if (later) {
    renderLaterDates(host, s, body, mountTo);
    errorAlert(body, s.error);
    footerButtons(footer, t('btn.move'), () => void submitMove(host, s, close), close);
    mount();
    mountTo.appendChild(dialog);
    return;
  }

  const options = SNOOZE_PRESETS.map((p) => ({ value: p.id, label: t('defer.preset.' + p.id) }));
  const schema: FormField[] = [
    { name: 'snoozePreset', required: true, selector: selSelect(options) },
  ];
  if (s.preset === 'custom') schema.push({ name: 'snoozeAt', required: true, selector: selDateTime() });
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
  footerButtons(footer, t('btn.snooze'), () => void submitSnooze(host, s, close), close);
  mount();
  mountTo.appendChild(dialog);
}

/**
 * The switch at the top of a fixed task's snooze dialog: **Next date** is the snooze
 * everyone knows, **A later date** moves one future date of the schedule.
 */
function snoozeModeSwitch(host: DeferDialogHost, s: SnoozeState): HTMLElement {
  const seg = document.createElement('div');
  seg.className = 'hk-snooze-mode';
  seg.setAttribute('role', 'group');
  seg.setAttribute('aria-label', t('defer.snoozeTitle'));
  for (const mode of ['next', 'later'] as const) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'hk-mode-btn';
    btn.id = `hk-snooze-mode-${mode}`;
    const active = (s.mode ?? 'next') === mode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', String(active));
    btn.textContent = t(mode === 'next' ? 'defer.nextDate' : 'defer.laterDate');
    btn.addEventListener('click', () => {
      if ((s.mode ?? 'next') === mode) return;
      s.mode = mode;
      s.error = undefined;
      host.rerender();
    });
    seg.appendChild(btn);
  }
  return seg;
}

/**
 * "A later date": the next dates of the schedule, one of them picked, and where it
 * goes. The list is asked for the first time this mode opens, from the same engine
 * the calendar reads, so a date that already moved shows where it is now.
 */
function renderLaterDates(
  host: DeferDialogHost,
  s: SnoozeState,
  body: HTMLElement,
  mountTo: HTMLElement,
): void {
  const list = document.createElement('div');
  list.className = 'hk-later-list';
  list.setAttribute('role', 'group');
  list.setAttribute('aria-label', t('defer.laterDate'));
  body.appendChild(list);
  if (s.occurrences === undefined) {
    list.textContent = t('defer.loadingDates');
    void loadLaterDates(host, s);
    return;
  }
  if (!s.occurrences.length) {
    list.textContent = t('form.summary.noDates');
    return;
  }
  const lang = host.lang();
  for (const row of s.occurrences) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'hk-later-row';
    const picked = s.picked != null && occurrenceOrigin(s.picked) === occurrenceOrigin(row);
    btn.classList.toggle('picked', picked);
    btn.setAttribute('aria-pressed', String(picked));
    btn.dataset.start = row.start;
    const when = `<span class="hk-later-date">${escapeHTML(formatOccurrenceTime(row.start, lang))}</span>`;
    const moved = row.moved_from
      ? `<span class="hk-moved-badge">${escapeHTML(t('upcoming.moved'))}</span>` +
        `<span class="hk-later-from">${escapeHTML(
          t('upcoming.movedFrom', { date: formatOccurrenceTime(row.moved_from, lang) }),
        )}</span>`
      : '';
    btn.innerHTML = when + moved;
    btn.addEventListener('click', () => {
      pickOccurrence(s, row);
      host.rerender();
    });
    list.appendChild(btn);
  }
  if (s.picked) {
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
  }
  const hint = document.createElement('div');
  hint.className = 'hk-snooze-hint hk-move-hint';
  hint.textContent = moveHintText(s, lang);
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
): Promise<void> {
  const until = snoozeTarget(s);
  const hass = host.hass();
  if (!hass || !s.task || !until) return;
  try {
    await api.snoozeTask(hass, s.task.id, until.toISOString());
    close();
    await host.refresh();
  } catch (err) {
    s.error = String((err as { message?: string })?.message || err);
    host.rerender();
  }
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
  const editing = s.ts != null;
  const { dialog, body, footer, mount } = makeDialog(
    editing ? t('defer.skipEditTitle') : t('defer.skipTitle'),
    () => {
      if (s.open) close();
    },
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
    () => void submitSkip(host, s, close),
    close,
  );
  mount();
  mountTo.appendChild(dialog);
}

export async function submitSkip(
  host: DeferDialogHost,
  s: SkipState,
  close: () => void,
): Promise<void> {
  const hass = host.hass();
  if (!hass || !s.task) return;
  try {
    if (s.ts != null) await api.updateSkip(hass, s.task.id, s.ts, s.data);
    else await api.skipTask(hass, s.task.id, s.data);
    close();
    await host.refresh();
  } catch (err) {
    s.error = String((err as { message?: string })?.message || err);
    host.rerender();
  }
}
