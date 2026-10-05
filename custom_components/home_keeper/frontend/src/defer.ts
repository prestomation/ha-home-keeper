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

import { haDateTimeToIso, isoToHaDateTime, skipSnoozeFlags } from './forms';
import { t } from './i18n';
import type { Task, UpcomingOccurrence } from './types';
import type { BtnWeight, SnoozePresetId } from './utils';
import {
  DEFAULT_SNOOZE_PRESET,
  btnAttrs,
  escapeHTML,
  formatDateTime,
  formatOccurrenceTime,
  isOverdue,
  scanRequired,
  resolveSnoozePreset,
  snoozePresetForHours,
  taskSnoozeHours,
} from './utils';

/** Which deferral verbs a task may be offered right now. */
export interface DeferVerbs {
  snooze: boolean;
  skip: boolean;
  dueToday: boolean;
  /** Open the completion dialog on a one-tap task, for a photo or a note (#399). */
  details: boolean;
}

/**
 * The verbs *task* may be offered, given the integration's options.
 *
 * All three switches default on, so a missing key means "not configured", not
 * "off" — `skipSnoozeFlags` is what encodes that. On top of the global switch
 * three per-task conditions apply:
 *
 * * skip is refused on a completion-blocked task, because the store rejects it
 *   and a button that always errors is worse than no button;
 * * snooze and due today are refused on a dormant task, which has no due date to
 *   defer or move to today;
 * * due today is refused on a task that is **already due or overdue**. Moving
 *   such a task's due date to now does not bring it forward, it pushes an overdue
 *   date later and drops the overdue state, which is the opposite of what the
 *   button says. #312 asked for this on a task that was explicitly not overdue,
 *   and `notifications.py` keeps the verb off notifications for the same reason.
 *
 * The details entry is not a deferral, but it rides the same caret (#399). It is
 * offered only on a one-tap task: a task that asks for details already opens the
 * dialog from Done, so the entry would repeat it. A blocked or tag-locked task
 * cannot be completed from the panel at all, and a dormant one has no Done.
 *
 * Hiding rather than disabling: a control that explains why it is dead earns its
 * place when the action is the page's whole point, but these are already tucked
 * behind a caret, and a menu of dead entries is just noise.
 *
 * *now* is injectable so a test pins the clock instead of racing the wall.
 */
export function deferVerbs(
  task: Task,
  options: { allow_snooze?: unknown; allow_skip?: unknown; allow_due_today?: unknown },
  now: Date = new Date(),
): DeferVerbs {
  const { allowSnooze, allowSkip, allowDueToday } = skipSnoozeFlags(options);
  const blocked = !!task.managed_by?.completion_blocked;
  const dormant = !task.next_due;
  return {
    snooze: allowSnooze && !dormant,
    skip: allowSkip && !blocked && !dormant,
    dueToday: allowDueToday && !dormant && !isOverdue(task, now),
    details:
      (task.completion_detail ?? 'none') === 'none' && !blocked && !dormant && !scanRequired(task),
  };
}

/** The menu's entries, as markup. Exported for the card, which sizes its own caret. */
export function deferMenuItems(verbs: DeferVerbs): string {
  const item = (cls: string, icon: string, label: string, sub: string): string =>
    `<button type="button" role="menuitem" class="${cls}">` +
    `<ha-icon icon="${icon}"></ha-icon>` +
    `<span class="hk-defer-text">${escapeHTML(label)}` +
    `<span class="hk-defer-sub">${escapeHTML(sub)}</span></span></button>`;
  return (
    (verbs.details
      ? item(
          'hk-defer-details',
          'mdi:camera-outline',
          t('defer.details'),
          t('defer.detailsHint'),
        )
      : '') +
    (verbs.snooze
      ? item('hk-defer-snooze', 'mdi:clock-outline', t('btn.snooze'), t('defer.snoozeHint'))
      : '') +
    (verbs.skip
      ? item('hk-defer-skip', 'mdi:skip-next-outline', t('btn.skip'), t('defer.skipHint'))
      : '') +
    (verbs.dueToday
      ? item(
          'hk-defer-due-today',
          'mdi:calendar-arrow-left',
          t('btn.dueToday'),
          t('defer.dueTodayHint'),
        )
      : '')
  );
}

/**
 * Wrap *doneBtn* in a split button whose caret opens the deferral menu.
 *
 * Returns *doneBtn* untouched when there is no verb to offer, so a task with every
 * switch off — or a dormant one — looks exactly as it did before this existed.
 * *weight* must be the weight *doneBtn* itself carries; see below.
 */
export function deferSplit(
  task: Task,
  doneBtn: string,
  verbs: DeferVerbs,
  weight: BtnWeight = 'primary',
): string {
  if (!doneBtn || (!verbs.snooze && !verbs.skip && !verbs.dueToday && !verbs.details)) {
    return doneBtn;
  }
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
 * Returns '' when no verb is on offer, which leaves the row exactly as it was
 * before this existed.
 */
export function deferRowActions(task: Task, verbs: DeferVerbs): string {
  const id = escapeHTML(task.id);
  const btn = (cls: string, label: string): string =>
    `<ha-icon-button class="hk-row-action ${cls}" data-id="${id}" ` +
    `label="${escapeHTML(label)}" title="${escapeHTML(label)}"></ha-icon-button>`;
  return (
    (verbs.snooze ? btn('hk-defer-snooze', t('btn.snooze')) : '') +
    (verbs.skip ? btn('hk-defer-skip', t('btn.skip')) : '') +
    (verbs.dueToday ? btn('hk-defer-due-today', t('btn.dueToday')) : '')
  );
}

/**
 * Which date a snooze acts on. `next` is the classic snooze: it moves the due date.
 * `later` moves one *future* date of a fixed schedule (`move_occurrence`), for "the
 * city moved next week's pickup" — the date on the board is not the one that moved.
 */
export type SnoozeMode = 'next' | 'later';

export interface SnoozeState {
  /** Set while the save runs, so a second press is ignored (X12-3). */
  busy?: boolean;
  open: boolean;
  task: Task | null;
  preset: SnoozePresetId;
  customAt?: string;
  error?: string;
  /** `next` when absent. */
  mode?: SnoozeMode;
  /** The dates "A later date" lists. `undefined` until they are asked for. */
  occurrences?: UpcomingOccurrence[];
  /** The row being moved, and where to (an `ha-form` date-time value). */
  picked?: UpcomingOccurrence;
  moveTo?: string;
}

export interface SkipState {
  /** Set while the save runs, so a second press is ignored (X12-3). */
  busy?: boolean;
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

/**
 * The snooze dialog's opening state for *task*.
 *
 * A task with its own snooze length opens on the preset of that length. A length no
 * preset has (a service can set any number of hours) opens on `custom`, with the
 * date that length gives from *now* already filled in. A task with no length of its
 * own opens on the usual preset.
 */
export function snoozeStateFor(task: Task, now: Date = new Date()): SnoozeState {
  const hours = taskSnoozeHours(task);
  if (hours == null) return { open: true, task, preset: DEFAULT_SNOOZE_PRESET };
  const preset = snoozePresetForHours(hours);
  if (preset) return { open: true, task, preset };
  const at = new Date(snoozeFrom(task, now).getTime() + hours * 3_600_000);
  return { open: true, task, preset: 'custom', customAt: isoToHaDateTime(at.toISOString()) };
}

/**
 * The instant a snooze length counts from: *now*, or the due date when that is
 * later (F10-2). Snooze moves the due date later, and a length counted from *now*
 * moved a task due in 30 days to 7 days from now. The backend's
 * `recurrence.snooze_from` gives the same instant for the service and a
 * notification.
 */
export function snoozeFrom(task: Task | null | undefined, now: Date = new Date()): Date {
  const due = task?.next_due ? new Date(task.next_due).getTime() : NaN;
  return Number.isNaN(due) ? now : new Date(Math.max(due, now.getTime()));
}

/** The typed custom date, or `null` when there is none or it will not parse. */
function customDate(s: SnoozeState): Date | null {
  if (!s.customAt) return null;
  const iso = haDateTimeToIso(s.customAt);
  if (!iso) return null;
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** How many dates "A later date" offers. */
export const LATER_DATES = 6;

/**
 * Whether the snooze dialog offers "A later date". Only a fixed schedule has later
 * dates to move: a floating task's next date does not exist until this one is done.
 */
export function offersLaterDates(task: Task | null | undefined): boolean {
  return task?.recurrence_type === 'fixed';
}

/** The date on the rule a row stands for: where a moved date came from. */
export function occurrenceOrigin(row: UpcomingOccurrence): string {
  return row.moved_from ?? row.start;
}

/**
 * A starting value for the new date: one day after the row, same time. The day is
 * added on the wall clock of Home Assistant's zone, so the time stays the same across
 * a clock change and in a browser in another zone.
 */
export function defaultMoveTo(start: string): string {
  const shown = isoToHaDateTime(start);
  if (!shown) return '';
  const [date, time] = shown.split(' ');
  const [y, mo, d] = date.split('-').map(Number);
  return `${new Date(Date.UTC(y, mo - 1, d + 1)).toISOString().slice(0, 10)} ${time}`;
}

/** Pick *row* to move, seeding its new date. */
export function pickOccurrence(s: SnoozeState, row: UpcomingOccurrence): void {
  s.picked = row;
  s.moveTo = defaultMoveTo(row.start);
  s.error = undefined;
}

/** The instant the picked date moves to, or `null` when nothing usable is set. */
export function moveTarget(s: SnoozeState): Date | null {
  if (!s.picked || !s.moveTo) return null;
  const iso = haDateTimeToIso(s.moveTo);
  if (!iso) return null;
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** The line under "A later date": what moves where, or what to do next. */
export function moveHintText(s: SnoozeState, lang?: string): string {
  if (!s.picked) return t('defer.movePick');
  const to = moveTarget(s);
  if (!to) return t('defer.snoozePickDate');
  return t('defer.moveResolves', {
    from: formatOccurrenceTime(s.picked.start, lang),
    to: formatOccurrenceTime(to, lang),
  });
}

/**
 * The instant the current snooze selection resolves to, or `null` if unusable. A
 * custom date that is not later than `snoozeFrom` is unusable: it would move the
 * task earlier, or make it due at once (F10-2).
 */
export function snoozeTarget(s: SnoozeState, now: Date = new Date()): Date | null {
  const from = snoozeFrom(s.task, now);
  if (s.preset !== 'custom') return resolveSnoozePreset(s.preset, from);
  const at = customDate(s);
  return at && at.getTime() > from.getTime() ? at : null;
}

/** The line stating where the current choice lands, or a prompt if unset. */
export function snoozeHintText(s: SnoozeState, lang?: string, now: Date = new Date()): string {
  const until = snoozeTarget(s, now);
  if (until) {
    return t('defer.snoozeResolves', { date: formatDateTime(until.toISOString(), lang) });
  }
  // A typed date that is too early gets its own line, so the user knows why the
  // Snooze button does nothing (F10-2).
  if (s.preset === 'custom' && customDate(s)) {
    const from = snoozeFrom(s.task, now);
    return t('defer.snoozeTooEarly', { date: formatDateTime(from.toISOString(), lang) });
  }
  return t('defer.snoozePickDate');
}
