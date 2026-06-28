import { t } from './i18n';
import type {
  Hass,
  Notification,
  NotifyAction,
  NotifyStatus,
  NotifyStyle,
  Profile,
  SensorBinding,
  SensorComparison,
  SensorMode,
  Task,
} from './types';

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
export function taskSchema(
  task: Partial<Task>,
  consumables: { value: string; label: string }[] = [],
  links: { value: string; label: string }[] = [],
): FormField[] {
  const locked = new Set<string>((task as Task).managed_by?.locked_fields ?? []);

  // The "show on card" picker (appliance document/metadata links) — offered for
  // every task kind, but only when the task's appliance actually has links to show.
  const cardLinksField: FormField[] =
    links.length && !locked.has('card_links')
      ? [{ name: 'card_links', selector: selSelect(links, true) } as FormField]
      : [];

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
      ...cardLinksField,
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
    ...(!task.id && !isOneOff && !isSensor && !locked.has('last_completed')
      ? [{ name: 'last_completed', selector: selDateTime() } as FormField]
      : []),
    ...(!locked.has('device_id') ? [{ name: 'device_id', selector: selDevice() } as FormField] : []),
    // Link the task to an appliance consumable so completing it draws down stock
    // (and fires the low-stock reorder event). Only offered when the user has at
    // least one consumable defined; the leading blank option clears the link.
    ...(consumables.length && !locked.has('consumable_link')
      ? [
          {
            name: 'consumable_link',
            selector: selSelect([
              { value: '', label: t('opt.consumable.none') },
              ...consumables,
            ]),
          } as FormField,
        ]
      : []),
    ...(!locked.has('labels') ? [{ name: 'labels', selector: selLabel(true) } as FormField] : []),
    ...cardLinksField,
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
  // The edit state spreads flat `sensor_*` fields onto the task as the user edits;
  // read them back here so the form reflects the live mode/values, not just a loaded
  // task's nested binding.
  const sd = task as Record<string, unknown>;
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
    // The live edit state already holds flat `sensor_*` values (the form mutates
    // them), so prefer those and fall back to a loaded task's nested binding.
    sensor_entity_id: sd.sensor_entity_id ?? task.sensor?.entity_id ?? '',
    sensor_mode: sd.sensor_mode ?? task.sensor?.mode ?? 'usage',
    sensor_target: sd.sensor_target ?? task.sensor?.target ?? undefined,
    sensor_value: sd.sensor_value ?? task.sensor?.value ?? undefined,
    sensor_comparison: sd.sensor_comparison ?? task.sensor?.comparison ?? '>=',
    sensor_for: sd.sensor_for ?? task.sensor?.for_seconds ?? 0,
    sensor_attribute: sd.sensor_attribute ?? task.sensor?.attribute ?? '',
    device_id: task.device_id ?? undefined,
    // Consumable link as an `asset_id:part_id` token (empty = unlinked). The live
    // edit state holds the flat value once the user changes it; fall back to the
    // task's current part source.
    consumable_link: sd.consumable_link ?? consumableLinkToken(task),
    labels: task.labels ?? [],
    // The card-link picker holds `asset_id:entry_id` tokens. `cardLinkTokens`
    // accepts either the stored `{asset_id, entry_id}` objects (a freshly loaded
    // task) or the flat token strings the form mutates onto the edit state.
    card_links: cardLinkTokens(task),
    completion_detail: task.completion_detail ?? 'none',
  };
}

/** The `asset_id:part_id` token for a task's current part link (empty if none). */
export function consumableLinkToken(task: Partial<Task>): string {
  const part = task.source?.part;
  return part ? `${part.asset_id}:${part.part_id}` : '';
}

/**
 * The `asset_id:entry_id` tokens for a task's chosen card links. Tolerates both
 * shapes the field passes through: the persisted `{asset_id, entry_id}` objects and
 * the flat token strings the `ha-form` select emits as the user edits.
 */
export function cardLinkTokens(task: Partial<Task>): string[] {
  const raw = (task as Record<string, unknown>).card_links;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((entry) => {
      if (typeof entry === 'string') return entry;
      const e = entry as { asset_id?: string; entry_id?: string };
      return e.asset_id && e.entry_id ? `${e.asset_id}:${e.entry_id}` : '';
    })
    .filter(Boolean);
}

/**
 * Parse `asset_id:entry_id` card-link tokens back into stored reference objects.
 * Splits on the first `:` — safe because asset/document/metadata ids are UUIDs
 * (server- or `crypto.randomUUID`-generated) and never contain a colon. The bounds
 * check drops a malformed token rather than emitting an empty id half.
 */
export function cardLinksFromTokens(tokens: string[]): { asset_id: string; entry_id: string }[] {
  const out: { asset_id: string; entry_id: string }[] = [];
  for (const tok of tokens) {
    const i = tok.indexOf(':');
    if (i <= 0 || i >= tok.length - 1) continue;
    out.push({ asset_id: tok.slice(0, i), entry_id: tok.slice(i + 1) });
  }
  return out;
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
  // Card links likewise apply to every kind and always round-trip — an empty array
  // clears the selection on update. Convert the form's tokens back to references.
  payload.card_links = cardLinksFromTokens(cardLinkTokens(task));
  if (!task.id) {
    const lastCompleted = haDateTimeToIso(task.last_completed as string | undefined);
    if (lastCompleted) payload.last_completed = lastCompleted;
  }
  return payload;
}

/**
 * The `ha-form` schema for the Settings tab's **Problem sensor sync** card — the
 * sync toggle plus entity / device / area / label exclusions (a subset of the
 * options flow). The entity picker is filtered to `device_class: problem` binary
 * sensors.
 */
export function problemSyncSchema(): FormField[] {
  return [
    { name: 'sync_problem_sensors', selector: selBool() },
    {
      name: 'problem_sensor_exclude_entities',
      selector: selEntity({ domain: 'binary_sensor', device_class: 'problem' }, true),
    },
    { name: 'problem_sensor_exclude_devices', selector: selDevice(true) },
    { name: 'problem_sensor_exclude_areas', selector: selArea(true) },
    { name: 'problem_sensor_exclude_labels', selector: selLabel(true) },
  ];
}

/**
 * The `ha-form` schema for the Settings tab's **General** card — settings that
 * apply across Home Keeper, independent of any single feature. Currently just the
 * completed one-off retention (auto-delete after N days; 0 keeps them forever).
 */
export function generalSchema(): FormField[] {
  return [{ name: 'one_off_retention_days', selector: selNumber(0) }];
}

// ── profiles (saved filters) & notifications (delivery) ─────────────────────

const NOTIFY_STATUSES: NotifyStatus[] = ['all', 'overdue', 'due_soon'];
const NOTIFY_ACTIONS: NotifyAction[] = ['complete', 'snooze', 'skip', 'open'];
const NOTIFY_STYLES: NotifyStyle[] = ['walk', 'digest'];

/** Localized `{value,label}` options for a notify enum (status/action/style). */
const notifyOptions = (values: string[]): { value: string; label: string }[] =>
  values.map((v) => ({ value: v, label: t('notify.opt.' + v) }));

const strList = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

/** The `ha-form` schema for one **profile** (a named, reusable task filter). */
export function profileSchema(): FormField[] {
  return [
    { name: 'name', required: true, selector: selText() },
    { name: 'status', selector: selSelect(notifyOptions(NOTIFY_STATUSES)) },
    { name: 'labels', selector: selLabel(true) },
    { name: 'areas', selector: selArea(true) },
    { name: 'devices', selector: selDevice(true) },
  ];
}

/** Flatten a profile to the (flat) `ha-form` data the schema expects. */
export function profileFormData(p: Profile): Record<string, unknown> {
  return {
    name: p.name,
    status: p.filter.status,
    labels: p.filter.labels,
    areas: p.filter.areas,
    devices: p.filter.devices,
  };
}

/** Rebuild a profile (nested filter) from the flat form data, keeping *id*. */
export function profileFormToProfile(id: string, data: Record<string, unknown>): Profile {
  return {
    id,
    name: String(data.name ?? '').trim() || 'Tasks',
    filter: {
      status: (data.status as NotifyStatus) ?? 'overdue',
      labels: strList(data.labels),
      areas: strList(data.areas),
      devices: strList(data.devices),
    },
  };
}

/**
 * The `ha-form` schema for one **notification** (delivery). *targets* is the live
 * `mobile_app_*` list; *profiles* populates the profile dropdown (what tasks to send).
 */
export function notificationSchema(targets: string[], profiles: Profile[]): FormField[] {
  return [
    { name: 'name', required: true, selector: selText() },
    {
      name: 'profile_id',
      required: true,
      selector: selSelect(profiles.map((p) => ({ value: p.id, label: p.name }))),
    },
    {
      name: 'targets',
      selector: selSelect(
        targets.map((tg) => ({ value: tg, label: tg })),
        true,
      ),
    },
    { name: 'actions', selector: selSelect(notifyOptions(NOTIFY_ACTIONS), true) },
    { name: 'style', selector: selSelect(notifyOptions(NOTIFY_STYLES)) },
    { name: 'snooze_hours', selector: selNumber(1) },
    { name: 'auto_overdue', selector: selBool() },
    { name: 'auto_due_soon', selector: selBool() },
  ];
}

/** Flatten a notification to the flat `ha-form` data the schema expects. */
export function notifyFormData(n: Notification): Record<string, unknown> {
  return {
    name: n.name,
    profile_id: n.profile_id ?? '',
    targets: n.targets,
    actions: n.actions,
    style: n.style,
    snooze_hours: n.snooze_hours,
    auto_overdue: n.auto.overdue,
    auto_due_soon: n.auto.due_soon,
  };
}

/** Rebuild a notification (nested auto) from the flat form data, keeping *id*. */
export function notifyFormToNotification(
  id: string,
  data: Record<string, unknown>,
): Notification {
  return {
    id,
    name: String(data.name ?? '').trim() || 'Notification',
    profile_id: data.profile_id ? String(data.profile_id) : null,
    targets: strList(data.targets),
    actions: strList(data.actions) as NotifyAction[],
    style: (data.style as NotifyStyle) ?? 'walk',
    snooze_hours: Number(data.snooze_hours ?? 24) || 24,
    auto: { overdue: !!data.auto_overdue, due_soon: !!data.auto_due_soon },
  };
}
