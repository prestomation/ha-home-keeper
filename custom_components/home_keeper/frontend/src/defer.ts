/**
 * Snooze and Skip — the two answers to a due task that are not "done".
 *
 * Both the panel and the dashboard card offer them behind a caret on Done, so
 * everything they share lives here: which verbs a task may be offered, the markup of
 * the split button and its menu, and the controller that opens and dismisses one.
 *
 * The controller takes its host's callbacks rather than a component, because the two
 * hosts differ in what a click means — a card row and a panel list row both navigate,
 * but to different places — and in nothing else.
 */

import * as api from './api';
import { makeDialog } from './dialogs';
import type { FormField, HaFormElement } from './forms';
import { haDateTimeToIso, selDateTime, selSelect, selText, skipSnoozeFlags } from './forms';
import { t } from './i18n';
import type { Hass, Task } from './types';
import type { SnoozePresetId } from './utils';
import {
  DEFAULT_SNOOZE_PRESET,
  SNOOZE_PRESETS,
  escapeHTML,
  formatDateTime,
  resolveSnoozePreset,
  setBtnWeight,
  taskRecordsReading,
} from './utils';

/** Which deferral verbs a task may be offered right now. */
export interface DeferVerbs {
  snooze: boolean;
  skip: boolean;
}

/**
 * The verbs *task* may be offered, given the integration's options.
 *
 * Both switches default on, so a missing key means "not configured", not "off" —
 * `skipSnoozeFlags` is what encodes that. On top of the global switch two per-task
 * conditions apply: skip is refused on a completion-blocked task, because the store
 * rejects it and a button that always errors is worse than no button; and snooze is
 * refused on a dormant task, which has no due date to defer.
 *
 * Hiding rather than disabling: a control that explains why it is dead earns its
 * place when the action is the page's whole point, but these are already tucked
 * behind a caret, and a menu of dead entries is just noise.
 */
export function deferVerbs(
  task: Task,
  options: { allow_snooze?: unknown; allow_skip?: unknown },
): DeferVerbs {
  const { allowSnooze, allowSkip } = skipSnoozeFlags(options);
  const blocked = !!task.managed_by?.completion_blocked;
  const dormant = !task.next_due;
  return { snooze: allowSnooze && !dormant, skip: allowSkip && !blocked && !dormant };
}

/** The menu's entries, as markup. Exported for the card, which sizes its own caret. */
export function deferMenuItems(verbs: DeferVerbs): string {
  const item = (cls: string, icon: string, label: string, sub: string): string =>
    `<button type="button" role="menuitem" class="${cls}">` +
    `<ha-icon icon="${icon}"></ha-icon>` +
    `<span class="hk-defer-text">${escapeHTML(label)}` +
    `<span class="hk-defer-sub">${escapeHTML(sub)}</span></span></button>`;
  return (
    (verbs.snooze
      ? item('hk-defer-snooze', 'mdi:clock-outline', t('btn.snooze'), t('defer.snoozeHint'))
      : '') +
    (verbs.skip
      ? item('hk-defer-skip', 'mdi:skip-next-outline', t('btn.skip'), t('defer.skipHint'))
      : '')
  );
}

/**
 * Wrap *doneBtn* in a split button whose caret opens the deferral menu.
 *
 * Returns *doneBtn* untouched when there is no verb to offer, so a task with both
 * switches off — or a dormant one — looks exactly as it did before this existed.
 * *caretClass* lets the card ask for its own, denser caret.
 */
export function deferSplit(
  task: Task,
  doneBtn: string,
  verbs: DeferVerbs,
  caretClass = 'hk-split-caret',
): string {
  if (!doneBtn || (!verbs.snooze && !verbs.skip)) return doneBtn;
  return (
    `<span class="hk-split" data-id="${escapeHTML(task.id)}">${doneBtn}` +
    `<ha-icon-button class="${caretClass}" aria-haspopup="menu" aria-expanded="false" ` +
    `label="${escapeHTML(t('defer.more'))}" title="${escapeHTML(t('defer.more'))}">` +
    `<ha-icon icon="mdi:chevron-down"></ha-icon></ha-icon-button>` +
    `<div class="hk-defer-menu" role="menu" hidden>${deferMenuItems(verbs)}</div></span>`
  );
}

/** What a host must supply for the menu to do anything. */
export interface DeferMenuHost {
  /** The task a split button stands for, by the id in its dataset. */
  taskById(id: string): Task | undefined;
  onSnooze(task: Task): void;
  onSkip(task: Task): void;
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

export interface SnoozeState {
  open: boolean;
  task: Task | null;
  preset: SnoozePresetId;
  customAt?: string;
  error?: string;
}

export interface SkipState {
  open: boolean;
  task: Task | null;
  ts?: string;
  data: { note?: string; who?: string; reading?: number };
  error?: string;
}

export const emptySnoozeState = (): SnoozeState => ({
  open: false,
  task: null,
  preset: DEFAULT_SNOOZE_PRESET,
});

export const emptySkipState = (): SkipState => ({ open: false, task: null, data: {} });

/** The instant the current snooze selection resolves to, or `null` if unusable. */
export function snoozeTarget(s: SnoozeState, now: Date = new Date()): Date | null {
  if (s.preset !== 'custom') return resolveSnoozePreset(s.preset, now);
  if (!s.customAt) return null;
  const iso = haDateTimeToIso(s.customAt);
  if (!iso) return null;
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** The line stating where the current choice lands, or a prompt if unset. */
export function snoozeHintText(s: SnoozeState, lang?: string): string {
  const until = snoozeTarget(s);
  if (!until) return t('defer.snoozePickDate');
  return t('defer.snoozeResolves', { date: formatDateTime(until.toISOString(), lang) });
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
