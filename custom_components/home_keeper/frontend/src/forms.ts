import { t } from './i18n';
import type { Hass, SensorBinding, SensorComparison, SensorMode, Task } from './types';

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
      ...(!locked.has('labels')
        ? [{ name: 'labels', selector: selLabel(true) } as FormField]
        : []),
    ];
  }

  const isFixed = task.recurrence_type === 'fixed';
  // A one-off (do-once) task has no cadence at all — just a single due date.
  const isOneOff = task.recurrence_type === 'one-off';
  // A sensor-based task has no clock cadence — its due-state comes from a bound
  // numeric sensor. Show the binding fields instead of interval/unit/freq.
  const isSensor = task.recurrence_type === 'sensor';

  const cadenceSubFields: FormField[] = isOneOff || isSensor
    ? []
    : isFixed
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

  // Sensor-based task: an entity picker, a mode toggle, and the mode's fields. The
  // current mode comes from the live edit state (flat `sensor_mode`) or the loaded
  // task's binding, defaulting to usage. Comparison labels are language-neutral
  // symbols, so they need no translation.
  const sd = task as Record<string, unknown>;
  const sensorMode =
    (sd.sensor_mode as string | undefined) ?? task.sensor?.mode ?? 'usage';
  const sensorFields: FormField[] = isSensor
    ? [
        { name: 'sensor_entity_id', required: true, selector: selEntity({}) },
        {
          name: 'sensor_mode',
          selector: selSelect([
            { value: 'usage', label: t('opt.sensor_mode.usage') },
            { value: 'threshold', label: t('opt.sensor_mode.threshold') },
          ]),
        },
        ...(sensorMode === 'threshold'
          ? [
              {
                name: 'sensor_comparison',
                selector: selSelect([
                  { value: '>=', label: '≥' },
                  { value: '<=', label: '≤' },
                  { value: '>', label: '>' },
                  { value: '<', label: '<' },
                  { value: '==', label: '=' },
                  { value: '!=', label: '≠' },
                ]),
              } as FormField,
              { name: 'sensor_value', required: true, selector: { number: { mode: 'box' } } },
              { name: 'sensor_for', selector: selNumber(0) },
            ]
          : [{ name: 'sensor_target', required: true, selector: selNumber(0) } as FormField]),
        { name: 'sensor_attribute', selector: selText() },
      ]
    : [];

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
              { value: 'one-off', label: t('opt.recurrence.one-off') },
              { value: 'sensor', label: t('opt.recurrence.sensor') },
            ]),
          } as FormField,
        ]
      : []),
    ...(cadence ? [cadence] : []),
    ...sensorFields,
    ...(isFixed && !locked.has('anchor')
      ? [{ name: 'anchor', selector: selDateTime() } as FormField]
      : []),
    ...(isOneOff && !locked.has('due')
      ? [{ name: 'due', selector: selDateTime() } as FormField]
      : []),
    ...(!task.id && !isOneOff && !locked.has('last_completed')
      ? [{ name: 'last_completed', selector: selDateTime() } as FormField]
      : []),
    ...(!locked.has('device_id') ? [{ name: 'device_id', selector: selDevice() } as FormField] : []),
    ...(!locked.has('labels') ? [{ name: 'labels', selector: selLabel(true) } as FormField] : []),
    ...(!locked.has('completion_detail')
      ? [
          {
            name: 'completion_detail',
            selector: selSelect([
              { value: 'none', label: t('opt.completion_detail.none') },
              { value: 'optional', label: t('opt.completion_detail.optional') },
              { value: 'required', label: t('opt.completion_detail.required') },
            ]),
          } as FormField,
        ]
      : []),
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
    // A new one-off defaults its due date to now; an existing one shows its stored due.
    due: isoToHaDateTime(task.due) ?? (task.id ? '' : isoToHaDateTime(new Date().toISOString())),
    last_completed: isoToHaDateTime(task.last_completed) ?? '',
    // Sensor binding flattened to form fields; assembled back in buildTaskPayload.
    sensor_entity_id: task.sensor?.entity_id ?? '',
    sensor_mode: task.sensor?.mode ?? 'usage',
    sensor_target: task.sensor?.target ?? undefined,
    sensor_value: task.sensor?.value ?? undefined,
    sensor_comparison: task.sensor?.comparison ?? '>=',
    sensor_for: task.sensor?.for_seconds ?? 0,
    sensor_attribute: task.sensor?.attribute ?? '',
    device_id: task.device_id ?? undefined,
    labels: task.labels ?? [],
    completion_detail: task.completion_detail ?? 'none',
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
  } else if (task.recurrence_type === 'sensor') {
    // A sensor task carries a `sensor` binding instead of a clock cadence; the form
    // holds its parts as flat `sensor_*` fields, assembled here.
    const sd = task as Record<string, unknown>;
    const mode = ((sd.sensor_mode as SensorMode) || task.sensor?.mode || 'usage') as SensorMode;
    const sensor: SensorBinding = {
      entity_id: String(sd.sensor_entity_id ?? task.sensor?.entity_id ?? ''),
      mode,
    };
    const attribute = String(sd.sensor_attribute ?? task.sensor?.attribute ?? '').trim();
    if (attribute) sensor.attribute = attribute;
    if (mode === 'usage') {
      sensor.target = Number(sd.sensor_target ?? task.sensor?.target) || 0;
    } else {
      sensor.comparison = (sd.sensor_comparison as SensorComparison) ||
        task.sensor?.comparison ||
        '>=';
      sensor.value = Number(sd.sensor_value ?? task.sensor?.value) || 0;
      const forSeconds = Number(sd.sensor_for ?? task.sensor?.for_seconds) || 0;
      if (forSeconds > 0) sensor.for_seconds = forSeconds;
    }
    payload = {
      name: task.name,
      notes: task.notes || '',
      recurrence_type: 'sensor',
      device_id: task.device_id || null,
      sensor,
      completion_detail: task.completion_detail || 'none',
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
    } else if (task.recurrence_type === 'one-off') {
      // A one-off has no cadence — just a due date. Always send a due (falling back
      // to now if the picker is blank, e.g. when converting an existing task to a
      // one-off) so the backend never rejects the update for a missing due.
      payload.due = haDateTimeToIso(task.due) || new Date().toISOString();
    } else {
      payload.freq = task.freq || 'DAILY';
      payload.anchor = haDateTimeToIso(task.anchor) ?? task.anchor;
    }
    // Capture mode applies to scheduled tasks; the backend derives which fields a
    // `required` task makes mandatory (v1: the note).
    payload.completion_detail = task.completion_detail || 'none';
  }
  // Labels apply to every task kind (including triggered) and always round-trip,
  // so an empty array correctly clears a task's labels on update.
  payload.labels = Array.isArray(task.labels) ? task.labels : [];
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
    // Auto-delete completed one-off tasks after N days; 0 keeps them forever.
    { name: 'one_off_retention_days', selector: selNumber(0) },
  ];
}
