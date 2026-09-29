/**
 * The fixed-schedule controls of the task form that `ha-form` cannot draw: the row of
 * day buttons, the "this rule says more" notice with **Reset to simple**, and the
 * live "Next dates" line.
 *
 * The rule text (`p._edit.task.rrule`) is the one stored value. Repeats, Every and the
 * day buttons are views of it, so each edit writes the rule and then repaints every
 * view **in place**: re-rendering the form would take focus away from the rule box on
 * each typed character (see `taskFormSchemaKey`). The pure translation between the
 * rule and the controls lives in `rrule.ts`.
 */

import * as api from './api';
import {
  haDateTimeToIso,
  pickFormData,
  taskFormData,
  taskRule,
  taskSchemaSections,
} from './forms';
import { getLanguage, t } from './i18n';
import type { PanelHost } from './panel-host';
import {
  WEEKDAYS,
  parseSimple,
  resetToSimple,
  shownDays,
  toggleDay,
  weekdayName,
  withSimpleChange,
} from './rrule';
import type { Task } from './types';
import { formatOccurrence } from './utils';

type HaForm = HTMLElement & { schema: unknown; data: Record<string, unknown> };

const previewTimers = new WeakMap<PanelHost, number>();
const previewSeq = new WeakMap<PanelHost, number>();
/** How long the preview waits after the last keystroke before it asks the backend. */
const PREVIEW_DELAY_MS = 350;

function anchorDate(task: Partial<Task>): Date | null {
  const iso = haDateTimeToIso(task.anchor) ?? task.anchor;
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** The empty container the day row paints into; see {@link paintRuleControls}. */
export function ruleControls(p: PanelHost): HTMLElement {
  const box = document.createElement('div');
  box.className = 'hk-rule-days';
  box.id = 'hk-rule-days';
  paintRuleControls(p, box);
  return box;
}

/**
 * Draw the day row for the current rule.
 *
 * - A simple weekly rule: 7 buttons, the rule's days pressed.
 * - Any other simple rule: nothing — daily, monthly and yearly need no days.
 * - A rule the controls cannot show: the buttons greyed out, a line that says so, and
 *   **Reset to simple**, which keeps the frequency and interval and drops the rest.
 */
export function paintRuleControls(p: PanelHost, box?: HTMLElement | null): void {
  const root = box ?? (p.shadowRoot?.getElementById('hk-rule-days') as HTMLElement | null);
  if (!root) return;
  const task = p._edit.task ?? {};
  root.replaceChildren();
  if (task.recurrence_type !== 'fixed') {
    root.hidden = true;
    return;
  }
  const rule = taskRule(task);
  const simple = parseSimple(rule);
  if (simple && simple.freq !== 'WEEKLY') {
    root.hidden = true;
    return;
  }
  root.hidden = false;
  const label = document.createElement('div');
  label.className = 'hk-rule-days-label';
  label.id = 'hk-rule-days-label';
  label.textContent = t('rule.days');
  const row = document.createElement('div');
  row.className = 'hk-rule-day-row';
  row.setAttribute('role', 'group');
  row.setAttribute('aria-labelledby', 'hk-rule-days-label');
  const lang = getLanguage();
  const on = new Set(shownDays(rule, anchorDate(task)));
  for (const day of WEEKDAYS) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'hk-day-btn';
    btn.dataset.day = day;
    btn.textContent = weekdayName(day, lang, 'short');
    btn.setAttribute('aria-label', weekdayName(day, lang, 'long'));
    btn.setAttribute('aria-pressed', String(on.has(day)));
    btn.disabled = !simple;
    btn.addEventListener('click', () => {
      const current = p._edit.task ?? {};
      setRule(p, toggleDay(taskRule(current), day, anchorDate(current)));
    });
    row.appendChild(btn);
  }
  root.append(label, row);
  if (!simple) {
    root.classList.add('hk-rule-custom');
    const note = document.createElement('div');
    note.className = 'hk-rule-note';
    note.id = 'hk-rule-note';
    const text = document.createElement('span');
    text.textContent = t('rule.notSimple');
    const reset = document.createElement('ha-button');
    reset.setAttribute('appearance', 'plain');
    reset.id = 'hk-rule-reset';
    reset.textContent = t('rule.reset');
    reset.addEventListener('click', () => setRule(p, resetToSimple(taskRule(p._edit.task ?? {}))));
    note.append(text, reset);
    root.appendChild(note);
  } else {
    root.classList.remove('hk-rule-custom');
  }
}

/**
 * *task* with *rule* stored, and `freq`/`interval` set to what the rule says. The
 * payload builder reads those two for a simple rule (see `formRule`), so they must
 * never lag behind a rule that was typed or reset.
 */
function withRule(task: Partial<Task>, rule: string): Partial<Task> {
  const simple = parseSimple(rule);
  return simple
    ? ({ ...task, rrule: rule, freq: simple.freq, interval: simple.interval } as Partial<Task>)
    : ({ ...task, rrule: rule } as Partial<Task>);
}

/** Write a new rule from a button, then repaint every view of it. */
function setRule(p: PanelHost, rule: string): void {
  p._edit.task = withRule(p._edit.task ?? {}, rule);
  syncRuleViews(p, { ruleText: true });
}

/**
 * Apply a change the `ha-form` sections just reported to the rule.
 *
 * Repeats or Every rewrite the rule; typing in the rule box *is* the rule. Returns
 * whether anything about the schedule changed, so the caller refreshes the views.
 */
export function applyRuleChange(p: PanelHost, value: Record<string, unknown>): boolean {
  const task = p._edit.task ?? {};
  if (task.recurrence_type !== 'fixed') return false;
  if ('rrule' in value) {
    p._edit.task = withRule(task, String(value.rrule ?? ''));
    syncRuleViews(p, { ruleText: false });
    return true;
  }
  if ('freq' in value || 'interval' in value) {
    // `task` already carries the new freq/interval (the caller merged them), so the
    // rule they change is the one stored before this edit.
    const rule = withSimpleChange(taskRule(task), {
      freq: 'freq' in value ? String(value.freq) : undefined,
      interval: 'interval' in value ? Number(value.interval) || 1 : undefined,
    });
    p._edit.task = withRule(task, rule);
    syncRuleViews(p, { ruleText: true });
    return true;
  }
  if ('anchor' in value) {
    // A weekly rule with no days follows the start date's weekday.
    syncRuleViews(p, { ruleText: false });
    return true;
  }
  return false;
}

/**
 * Repaint Repeats/Every, the day row, the rule box (when the change did not come from
 * it — rewriting a box someone is typing in moves their cursor) and the preview.
 */
function syncRuleViews(p: PanelHost, opts: { ruleText: boolean }): void {
  const task = p._edit.task ?? {};
  const root = p.shadowRoot;
  const data = taskFormData(task);
  const sections = taskSchemaSections(task);
  const find = (key: string): HaForm | null =>
    (root?.getElementById(`hk-task-form-${key}`) as HaForm | null) ?? null;
  const cadence = find('cadence');
  const cadenceSection = sections.find((s) => s.key === 'cadence');
  if (cadence && cadenceSection) {
    // The schema carries the greyed-out state, so it is replaced along with the data.
    cadence.schema = cadenceSection.fields;
    cadence.data = pickFormData(data, cadenceSection.fields);
  }
  const ruleForm = find('rule');
  const ruleSection = sections.find((s) => s.key === 'rule');
  if (opts.ruleText && ruleForm && ruleSection) {
    ruleForm.data = pickFormData(data, ruleSection.fields);
  }
  paintRuleControls(p);
  schedulePreview(p);
}

/** The preview container under the rule summary. */
export function previewLine(): HTMLElement {
  const line = document.createElement('span');
  line.className = 'hk-form-summary-next';
  line.id = 'hk-form-next';
  line.hidden = true;
  return line;
}

/** Ask for the next dates once the user stops typing. */
export function schedulePreview(p: PanelHost): void {
  const prior = previewTimers.get(p);
  if (prior) window.clearTimeout(prior);
  previewTimers.set(
    p,
    window.setTimeout(() => void refreshPreview(p), PREVIEW_DELAY_MS),
  );
}

/**
 * Fill the "Next dates" line from the backend. A reply to an older request is
 * dropped, so a slow answer cannot overwrite the one for the rule now in the box.
 */
export async function refreshPreview(p: PanelHost): Promise<void> {
  const line = p.shadowRoot?.getElementById('hk-form-next') as HTMLElement | null;
  const task = p._edit.task ?? {};
  if (!line) return;
  const anchor = haDateTimeToIso(task.anchor) ?? task.anchor;
  if (task.recurrence_type !== 'fixed' || !p._hass || !anchor) {
    line.hidden = true;
    return;
  }
  const seq = (previewSeq.get(p) ?? 0) + 1;
  previewSeq.set(p, seq);
  try {
    const rows = await api.upcomingOccurrences(p._hass, {
      rrule: taskRule(task),
      anchor,
    });
    if (previewSeq.get(p) !== seq) return;
    const lang = getLanguage();
    line.classList.remove('hk-form-summary-error');
    line.textContent = rows.length
      ? t('form.summary.next', {
          dates: rows.map((r) => formatOccurrence(r.start, lang)).join(', '),
        })
      : t('form.summary.noDates');
  } catch (err) {
    if (previewSeq.get(p) !== seq) return;
    line.classList.add('hk-form-summary-error');
    line.textContent = (err as { message?: string })?.message || String(err);
  }
  line.hidden = false;
}
