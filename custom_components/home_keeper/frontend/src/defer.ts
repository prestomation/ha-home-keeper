/**
 * Snooze and Skip — the decisions, shared by the panel and the dashboard card.
 *
 * What lives here is what has an answer worth testing: which verbs a task may be
 * offered, what the split button and its menu are made of, and what a snooze
 * selection resolves to. The elements those answers get assembled into — the menu
 * controller and the two dialogs — are in `defer-dialogs.ts`, because their mutants
 * are class names and translation keys rather than behaviour. This half is on the
 * mutation surface; that half is covered by the e2e specs.
 */

import { haDateTimeToIso, skipSnoozeFlags } from './forms';
import { t } from './i18n';
import type { Task } from './types';
import type { BtnWeight, SnoozePresetId } from './utils';
import {
  DEFAULT_SNOOZE_PRESET,
  btnAttrs,
  escapeHTML,
  formatDateTime,
  resolveSnoozePreset,
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
 * *weight* must be the weight *doneBtn* itself carries; see below.
 */
export function deferSplit(
  task: Task,
  doneBtn: string,
  verbs: DeferVerbs,
  weight: BtnWeight = 'primary',
): string {
  if (!doneBtn || (!verbs.snooze && !verbs.skip)) return doneBtn;
  // The caret is an ha-button carrying *Done's own weight*, which is the only way the
  // two halves are guaranteed to paint the same. Home Assistant fills a button from
  // its appearance, and the weights differ by surface — the task page's Done is solid
  // accent, a list row's is a pale tonal — so anything that names a colour here is
  // wrong on one of them, and wrong again under someone else's theme.
  //
  // Both halves square off (ha-button takes a single-value radius override, and
  // rejects a four-value one), and `.hk-split-pill` rounds the pair by clipping. The
  // menu is deliberately outside that clip: it hangs below the button, and the
  // overflow that rounds the corners would otherwise cut it off.
  return (
    `<span class="hk-split" data-id="${escapeHTML(task.id)}">` +
    `<span class="hk-split-pill">${doneBtn}` +
    `<ha-button ${btnAttrs(weight)} class="hk-split-caret" aria-haspopup="menu" ` +
    `aria-expanded="false" aria-label="${escapeHTML(t('defer.more'))}" ` +
    `title="${escapeHTML(t('defer.more'))}">` +
    `<ha-icon icon="mdi:chevron-down"></ha-icon></ha-button></span>` +
    `<div class="hk-defer-menu" role="menu" hidden>${deferMenuItems(verbs)}</div></span>`
  );
}

/**
 * The row's deferral actions, as their own buttons rather than behind a caret.
 *
 * The card takes this shape and the task page takes `deferSplit`, because the two
 * surfaces are answering different questions. A task page is *about* one task, so
 * the one action it is really for stays primary and the exceptions tuck behind a
 * caret. A card row is a list you scan, and a chevron with no container to lean on
 * read as decoration — so here the verbs are simply present, muted, ahead of Done.
 *
 * Returns '' when neither verb is on offer, which leaves the row exactly as it was
 * before this existed.
 */
export function deferRowActions(task: Task, verbs: DeferVerbs): string {
  const id = escapeHTML(task.id);
  const btn = (cls: string, label: string): string =>
    `<ha-icon-button class="hk-row-action ${cls}" data-id="${id}" ` +
    `label="${escapeHTML(label)}" title="${escapeHTML(label)}"></ha-icon-button>`;
  return (
    (verbs.snooze ? btn('hk-defer-snooze', t('btn.snooze')) : '') +
    (verbs.skip ? btn('hk-defer-skip', t('btn.skip')) : '')
  );
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
