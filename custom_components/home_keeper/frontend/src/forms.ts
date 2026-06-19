import { t } from './i18n';
import type { Hass, Task } from './types';

/**
 * Shared `ha-form` primitives and the task form's schema/data/payload helpers.
 *
 * Both the sidebar panel and the dashboard card build their task editor from
 * the same Home Assistant `ha-form` selectors, so the field set, the
 * ISO↔selector datetime mapping, and the add/update payload all live here as a
 * single source of truth. Keeping these pure (no DOM, no element refs) also
 * makes the task-form behavior unit-testable.
 */

// Minimal shape of an `ha-form` element (only what we set/read).
export interface HaFormElement extends HTMLElement {
  hass?: Hass;
  schema?: unknown[];
  data?: Record<string, unknown>;
  computeLabel?: (schema: { name: string }) => string;
}

export type Selector = Record<string, unknown>;
export interface FormField {
  name: string;
  required?: boolean;
  selector?: Selector;
  type?: string;
  schema?: FormField[];
}

export const selText = (multiline = false): Selector => ({
  text: multiline ? { multiline: true } : {},
});
export const selNumber = (min = 0): Selector => ({ number: { min, mode: 'box' } });
export const selBool = (): Selector => ({ boolean: {} });
export const selDate = (): Selector => ({ date: {} });
export const selDateTime = (): Selector => ({ datetime: {} });
export const selDevice = (multiple = false): Selector => ({
  device: multiple ? { multiple: true } : {},
});
export const selArea = (multiple = false): Selector => ({ area: multiple ? { multiple: true } : {} });
export const selLabel = (multiple = false): Selector => ({
  label: multiple ? { multiple: true } : {},
});
export const selEntity = (
  filter: { domain?: string; device_class?: string },
  multiple = false,
): Selector => ({ entity: { filter, multiple } });
export const selIcon = (): Selector => ({ icon: {} });
export const selSelect = (
  options: { value: string; label: string }[],
  multiple = false,
): Selector => ({
  select: { mode: 'dropdown', options, sort: false, multiple },
});

// ── datetime <-> HA selector string helpers ────────────────────────────────
// HA's datetime selector uses local "YYYY-MM-DD HH:mm:ss"; we persist ISO.
export function isoToHaDateTime(iso?: string | null): string | undefined {
  if (!iso) return undefined;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return undefined;
  const p = (n: number): string => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(
    d.getMinutes(),
  )}:${p(d.getSeconds())}`;
}
export function haDateTimeToIso(value?: string | null): string | undefined {
  if (!value) return undefined;
  const d = new Date(value.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString();
}

// ── task form schema / data / payload ───────────────────────────────────────

/**
 * The `ha-form` schema for a task. Fields a managing integration declared as
 * locked are omitted so users can't overwrite integration-owned values, and a
 * triggered (condition-driven) task offers only its descriptive fields (it has
 * no schedule to edit).
 */
export function taskSchema(task: Partial<Task>): FormField[] {
  const locked = new Set<string>((task as Task).managed_by?.locked_fields ?? []);

  // A triggered (condition-driven) task has no schedule to edit — its state is
  // owned by the integration that monitors the condition. Offer only the
  // unlocked descriptive fields (notes), never a recurrence/cadence editor.
  if (task.recurrence_type === 'triggered') {
    return [
      ...(!locked.has('name')
        ? [{ name: 'name', required: true, selector: selText() } as FormField]
        : []),
      ...(!locked.has('notes') ? [{ name: 'notes', selector: selText(true) } as FormField] : []),
      ...(!locked.has('device_id')
        ? [{ name: 'device_id', selector: selDevice() } as FormField]
        : []),
    ];
  }

  const isFixed = task.recurrence_type === 'fixed';

  const cadenceSubFields: FormField[] = isFixed
    ? [
        ...(!locked.has('interval') ? [{ name: 'interval', selector: selNumber(1) }] : []),
        ...(!locked.has('freq')
          ? [
              {
                name: 'freq',
                selector: selSelect([
                  { value: 'DAILY', label: t('opt.freq.daily') },
                  { value: 'WEEKLY', label: t('opt.freq.weekly') },
                  { value: 'MONTHLY', label: t('opt.freq.monthly') },
                ]),
              },
            ]
          : []),
      ]
    : [
        ...(!locked.has('interval') ? [{ name: 'interval', selector: selNumber(1) }] : []),
        ...(!locked.has('unit')
          ? [
              {
                name: 'unit',
                selector: selSelect([
                  { value: 'days', label: t('opt.unit.days') },
                  { value: 'weeks', label: t('opt.unit.weeks') },
                  { value: 'months', label: t('opt.unit.months') },
                ]),
              },
            ]
          : []),
      ];
  const cadence: FormField | null =
    cadenceSubFields.length > 0 ? { name: '', type: 'grid', schema: cadenceSubFields } : null;

  const fields: FormField[] = [
    ...(!locked.has('name')
      ? [{ name: 'name', required: true, selector: selText() } as FormField]
      : []),
    ...(!locked.has('notes') ? [{ name: 'notes', selector: selText(true) } as FormField] : []),
    ...(!locked.has('recurrence_type')
      ? [
          {
            name: 'recurrence_type',
            selector: selSelect([
              { value: 'floating', label: t('opt.recurrence.floating') },
              { value: 'fixed', label: t('opt.recurrence.fixed') },
            ]),
          } as FormField,
        ]
      : []),
    ...(cadence ? [cadence] : []),
    ...(isFixed && !locked.has('anchor')
      ? [{ name: 'anchor', selector: selDateTime() } as FormField]
      : []),
    ...(!task.id && !locked.has('last_completed')
      ? [{ name: 'last_completed', selector: selDateTime() } as FormField]
      : []),
    ...(!locked.has('device_id') ? [{ name: 'device_id', selector: selDevice() } as FormField] : []),
  ];
  return fields;
}

/** Map a task onto the `ha-form` data object (selector-shaped values). */
export function taskFormData(task: Partial<Task>): Record<string, unknown> {
  return {
    name: task.name ?? '',
    notes: task.notes ?? '',
    recurrence_type: task.recurrence_type ?? 'floating',
    interval: task.interval ?? 1,
    unit: task.unit ?? 'months',
    freq: task.freq ?? 'DAILY',
    anchor: isoToHaDateTime(task.anchor) ?? '',
    last_completed: isoToHaDateTime(task.last_completed) ?? '',
    device_id: task.device_id ?? undefined,
  };
}

/**
 * Build the add/update payload from the edit state. A triggered task sends only
 * descriptive fields (sending recurrence/interval would make the backend
 * recompute next_due and re-arm a dormant task); `last_completed` seeds the
 * first due date only on creation.
 */
export function buildTaskPayload(task: Partial<Task>): Partial<Task> {
  let payload: Partial<Task>;
  if (task.recurrence_type === 'triggered') {
    payload = {
      name: task.name,
      notes: task.notes || '',
      device_id: task.device_id || null,
    };
  } else {
    payload = {
      name: task.name,
      notes: task.notes || '',
      recurrence_type: task.recurrence_type,
      interval: Math.max(1, Number(task.interval) || 1),
      device_id: task.device_id || null,
    };
    if (task.recurrence_type === 'floating') {
      payload.unit = task.unit || 'months';
    } else {
      payload.freq = task.freq || 'DAILY';
      payload.anchor = haDateTimeToIso(task.anchor) ?? task.anchor;
    }
  }
  if (!task.id) {
    const lastCompleted = haDateTimeToIso(task.last_completed as string | undefined);
    if (lastCompleted) payload.last_completed = lastCompleted;
  }
  return payload;
}

/**
 * The `ha-form` schema for the panel's Settings tab — a 1:1 mirror of the options
 * flow: the problem-sensor sync toggle plus entity / area / label exclusions. The
 * entity picker is filtered to `device_class: problem` binary sensors.
 */
export function settingsSchema(): FormField[] {
  return [
    { name: 'sync_problem_sensors', selector: selBool() },
    {
      name: 'problem_sensor_exclude_entities',
      selector: selEntity({ domain: 'binary_sensor', device_class: 'problem' }, true),
    },
    { name: 'problem_sensor_exclude_areas', selector: selArea(true) },
    { name: 'problem_sensor_exclude_labels', selector: selLabel(true) },
  ];
}
