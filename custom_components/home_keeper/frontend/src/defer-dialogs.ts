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
import { snoozeHintText, snoozeTarget } from './defer';
import { makeDialog } from './dialogs';
import type { FormField, HaFormElement } from './forms';
import { selDateTime, selSelect, selText } from './forms';
import { t } from './i18n';
import type { Hass, Task } from './types';
import type { SnoozePresetId } from './utils';
import { SNOOZE_PRESETS, setBtnWeight, taskRecordsReading } from './utils';

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
