/**
 * The task list's layout choice, and the answers the two compact layouts need.
 *
 * A task list is drawn as rows, as tiles or as a board. The layout itself is
 * markup and belongs in `panel-lists.ts`; what is here is what has an answer
 * worth testing: which layout a stored value means, the short due text a tile or
 * a board card has room for, the urgency a card colours itself with, and which
 * actions the card's action sheet offers.
 *
 * Pure. It imports the shared decision modules only, so it carries no `PanelHost`
 * and no Home Assistant types, and it sits on the Stryker mutate list.
 */

import { DAY_MS, statusBucket } from './card-filter';
import type { DeferVerbs } from './defer';
import { t } from './i18n';
import type { Task } from './types';
import { isBuyTask, isMonitoredDormant, isOverdue, scanRequired } from './utils';

/** The layouts the Tasks tab offers, in the order the Layout menu lists them. */
export const TASK_LAYOUTS = ['rows', 'tiles', 'board'] as const;

/** One of `TASK_LAYOUTS`. Stored per user as a string (see `api.getTaskLayout`). */
export type TaskLayout = (typeof TASK_LAYOUTS)[number];

/**
 * The status-section options the panel groups by.
 *
 * A copy of `PANEL_BUCKETS` in `panel-types.ts`, because this module stays free of
 * the panel's own modules. Keep the two the same: the board's columns come from
 * `groupTasks`, which reads that one, and a tile's rail reads this one.
 */
const PANEL_STATUS_BUCKETS = { today: false, completed: true } as const;

/**
 * The layout *value* names, or `rows` for anything else.
 *
 * The stored value comes back from Home Assistant's per-user data store, which
 * holds whatever was last written to that key — an older panel's value, or a hand
 * edit. Rows is the layout every task list had before the picker, so it is the
 * safe answer to a value this panel does not know.
 */
export function parseTaskLayout(value: unknown): TaskLayout {
  return TASK_LAYOUTS.includes(value as TaskLayout) ? (value as TaskLayout) : 'rows';
}

/** Local midnight before *ms*, so a due date is counted in calendar days. */
function startOfDay(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/**
 * A task's due state in the few characters a board card has for it, or `''`.
 *
 * The list row spells this out ("3 days overdue", "in 2 weeks"). A board card is
 * 220px wide and already carries the name, so the due text is cut to a figure and
 * a unit: `129d` late, `in 30d` ahead, `Today` on the day.
 *
 * Only a live task with a due date has a short form. Every other state (disabled,
 * a finished one-off, a dormant monitored task, a buy reminder) answers `''`, and
 * the card shows the status pill's own words in its place. The board and the list
 * then never give one state 2 names.
 *
 * Late days are whole elapsed days, the count the status pill uses, so a card never
 * says one day more than its row. Days ahead are calendar days, which is how
 * `dueLabel` counts them: a task due at 09:00 reads `Today` all day.
 */
export function shortDueLabel(task: Task, now: Date = new Date()): string {
  if (task.enabled === false || isMonitoredDormant(task)) return '';
  // Stryker disable next-line ConditionalExpression: the NaN guard below answers a
  // dateless task the same way. This one is what keeps `new Date` off an empty value.
  if (!task.next_due) return '';
  const due = new Date(task.next_due).getTime();
  if (Number.isNaN(due)) return '';
  // `<=`, as `isOverdue` has it: a task due this very moment is late, not Today.
  if (due <= now.getTime()) {
    const late = Math.floor((now.getTime() - due) / DAY_MS);
    // Under a day late, the pill says Overdue with no count. So does the card.
    return late >= 1 ? t('layout.short.overdue', { n: late }) : '';
  }
  const days = Math.round((startOfDay(due) - startOfDay(now.getTime())) / DAY_MS);
  // Stryker disable next-line EqualityOperator: a future date is never before
  // today's midnight, so `days` is never below zero here and `=== 0` is the same.
  if (days <= 0) return t('layout.short.today');
  return t('layout.short.in', { n: days });
}

/**
 * How urgent *task* is, as the class a tile's rail or a board card's dot takes.
 *
 * A buy reminder is deliberately colourless. It is minted with no due date, so it
 * is overdue to every filter from the moment a part goes low — the same reason
 * `statusChipHtml` says "Low stock" instead of "Overdue" and the list row drops
 * its red rail.
 */
export function urgencyClass(task: Task, now: Date = new Date()): '' | 'overdue' | 'soon' {
  // A disabled task is not late and not due soon, whatever its frozen date says.
  // The list row drops its red rail for the same reason.
  if (task.enabled === false) return '';
  if (isBuyTask(task)) return '';
  if (isOverdue(task, now)) return 'overdue';
  if (statusBucket(task, now.getTime(), PANEL_STATUS_BUCKETS) === 'soon') return 'soon';
  return '';
}

/** What a task can be asked to do, read once for the sheet and its rows. */
export interface SheetFlags {
  /** Armed by a sensor or an integration, with nothing to mark done yet. */
  dormant: boolean;
  /** A do-once task that is already done. */
  completedOneOff: boolean;
  /** Completable, but not from here — the sheet explains instead of completing. */
  blocked: boolean;
}

/**
 * The three facts the action sheet's Done row turns on.
 *
 * The same guards the list row's Done applies (see `taskCard` in
 * `panel-lists.ts`), read in one place so a tile and a row can never offer
 * different actions for the same task.
 */
export function sheetFlags(task: Task): SheetFlags {
  return {
    dormant: isMonitoredDormant(task),
    completedOneOff:
      task.recurrence_type === 'one-off' && !task.next_due && !!task.last_completed,
    blocked: Boolean(task.managed_by?.completion_blocked) || scanRequired(task),
  };
}

/** Which action a sheet row performs. */
export type SheetActionId = 'done' | 'snooze' | 'skip' | 'dueToday' | 'open';

/** One row of the action sheet. */
export interface SheetAction {
  id: SheetActionId;
  /** True on a Done row that must explain why it cannot complete the task. */
  blocked: boolean;
}

/**
 * The sheet's rows, in order: Done, Snooze, Skip, Due today, Open task.
 *
 * Done leads because it is what most taps are for, and Open task is always last
 * because it is the way out of the sheet rather than an action on the task. A
 * verb the integration's options switched off, or one this task cannot take, is
 * dropped rather than shown dead — the sheet is a menu, and a menu of dead
 * entries is noise (see `deferVerbs`).
 */
export function sheetActions(verbs: DeferVerbs, flags: SheetFlags): SheetAction[] {
  const actions: SheetAction[] = [];
  if (!flags.dormant && !flags.completedOneOff) {
    actions.push({ id: 'done', blocked: flags.blocked });
  }
  if (verbs.snooze) actions.push({ id: 'snooze', blocked: false });
  if (verbs.skip) actions.push({ id: 'skip', blocked: false });
  if (verbs.dueToday) actions.push({ id: 'dueToday', blocked: false });
  actions.push({ id: 'open', blocked: false });
  return actions;
}

/**
 * A board column's heading.
 *
 * Group by none makes one unlabelled group holding every task. A column needs a
 * head to be a column, so that one is headed "All" — the same word the scope
 * pill for the whole list carries.
 */
export function boardColumnLabel(label: string): string {
  return label || t('filter.all');
}
