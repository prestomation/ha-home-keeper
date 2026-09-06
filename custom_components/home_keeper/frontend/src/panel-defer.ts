/**
 * The panel's half of Snooze and Skip: opening and closing the two dialogs, the
 * split button that reaches them, and re-dating or removing a logged skip.
 *
 * The decisions and the markup live in `defer.ts`, and the dialogs themselves in
 * `defer-dialogs.ts` — both shared with the dashboard card, so the card opens the
 * panel's dialogs rather than an imitation of them. This module is only the binding
 * between those and a `PanelHost`, in the same shape as `panel-dialogs.ts`.
 */

import * as api from './api';
import {
  deferSplit,
  deferVerbs,
  emptySkipState,
  emptySnoozeState,
  type DeferVerbs,
} from './defer';
import { renderSkipDialog, renderSnoozeDialog, type DeferDialogHost } from './defer-dialogs';
import { t } from './i18n';
import type { PanelHost } from './panel-host';
import { MDI_DELETE, MDI_EDIT, MDI_MOVE_DATE } from './panel-icons';
import { setIcon } from './panel-history';
import type { Task } from './types';
import { DEFAULT_SNOOZE_PRESET, toast, type BtnWeight } from './utils';

/**
 * Which deferral verbs *task* can actually take, given the global switches.
 *
 * Two gates, and both have to pass — see `deferVerbs`, which holds the reasoning.
 */
export function verbsFor(p: PanelHost, task: Task): DeferVerbs {
  return deferVerbs(task, p._options ?? {});
}

/** Wrap *doneBtn* in the split button whose caret opens the deferral menu. */
export function deferMenu(
  p: PanelHost,
  task: Task,
  doneBtn: string,
  weight: BtnWeight = 'primary',
): string {
  return deferSplit(task, doneBtn, verbsFor(p, task), weight);
}

export function openSnooze(p: PanelHost, task: Task): void {
  p._snooze = { open: true, task, preset: DEFAULT_SNOOZE_PRESET };
  p._render();
}

export function closeSnooze(p: PanelHost): void {
  p._snooze = emptySnoozeState();
  p._render();
}

/** Open the skip dialog — for a new skip, or to amend a logged one when *ts* is
 *  given. Both collect the same fields, so they share a dialog. */
export function openSkip(p: PanelHost, task: Task, ts?: string): void {
  const entry = ts ? (task.skips ?? []).find((x) => x.ts === ts) : undefined;
  p._skip = {
    open: true,
    task,
    ts,
    data: entry ? { note: entry.note, who: entry.who, reading: entry.reading } : {},
  };
  p._render();
}

export function closeSkip(p: PanelHost): void {
  p._skip = emptySkipState();
  p._render();
}

/** Re-date a logged skip. Same dialog as a completion's — see the state's `kind`. */
export function openMoveSkip(p: PanelHost, task: Task, ts: string): void {
  p._moveCompletion = { open: true, task, ts, newTs: ts, kind: 'skip' };
  p._render();
}

export async function deleteSkip(p: PanelHost, taskId: string, ts: string): Promise<void> {
  if (!p._hass) return;
  try {
    await api.deleteSkip(p._hass, taskId, ts);
    await p._refresh();
  } catch (err) {
    console.error('home-keeper: delete skip failed', err);
    toast(p, t('error.actionFailed'));
  }
}

/**
 * Build the snooze dialog — a preset dropdown plus, for `custom`, a date-time field.
 *
 * The helper line under the field states the date the choice resolves to, so the
 * user reads the answer rather than doing the arithmetic.
 */
export function renderSnooze(p: PanelHost, host: HTMLElement): void {
  renderSnoozeDialog(dialogHost(p), p._snooze, host, () => closeSnooze(p));
}

/**
 * Build the skip dialog — the note, who, and (for a usage task) the meter reading.
 *
 * No duration: a skip advances to the next occurrence and that is the whole of it.
 * The same dialog amends an already-logged skip, which is why the title and the
 * primary button read differently when `ts` is set.
 */
export function renderSkip(p: PanelHost, host: HTMLElement): void {
  renderSkipDialog(dialogHost(p), p._skip, host, () => closeSkip(p));
}

/** Adapt a `PanelHost` to what the shared dialogs ask for. */
function dialogHost(p: PanelHost): DeferDialogHost {
  return {
    hass: () => p._hass,
    lang: () => p._lang(),
    makeForm: (schema, data, onChange) => p._makeForm(schema, data, onChange),
    rerender: () => p._render(),
    refresh: () => p._refresh(),
  };
}

/**
 * Wire the skip rows' three buttons in a history list.
 *
 * Same icons and shape as the completion ones beside them — a skip is editable
 * exactly as a completion is — but routed to the skip services, since the two logs
 * are separate lists keyed on their own timestamps.
 */
export function wireSkipHistoryRows(p: PanelHost, root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('.hk-hist-skip-del').forEach((b) => {
    setIcon(b, MDI_DELETE);
    b.addEventListener('click', () => {
      const ts = b.dataset.ts;
      const taskId = b.dataset.delSkip;
      if (ts && taskId) void deleteSkip(p, taskId, ts);
    });
  });
  root.querySelectorAll<HTMLElement>('.hk-hist-skip-edit').forEach((b) => {
    setIcon(b, MDI_EDIT);
    b.addEventListener('click', () => {
      const ts = b.dataset.ts;
      const taskId = b.dataset.editTask;
      if (!ts || !taskId) return;
      const task = p._tasks.find((x) => x.id === taskId);
      if (task) openSkip(p, task, ts);
    });
  });
  root.querySelectorAll<HTMLElement>('.hk-hist-skip-move').forEach((b) => {
    setIcon(b, MDI_MOVE_DATE);
    b.addEventListener('click', () => {
      const ts = b.dataset.ts;
      const taskId = b.dataset.moveTask;
      if (!ts || !taskId) return;
      const task = p._tasks.find((x) => x.id === taskId);
      if (task) openMoveSkip(p, task, ts);
    });
  });
}
