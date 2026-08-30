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

import { skipSnoozeFlags } from './forms';
import { t } from './i18n';
import { escapeHTML } from './utils';
import type { Task } from './types';

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
