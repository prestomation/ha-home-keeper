import { t } from './i18n';
import { recurrenceSummary, round1 } from './utils';
import type {
  Hass,
  Notification,
  NotifyAction,
  NotifyStatus,
  NotifyStyle,
  Profile,
  ProfileSync,
  SensorBinding,
  SensorCombinator,
  SensorComparison,
  SensorMode,
  Task,
  Unit,
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
  computeHelper?: (schema: { name: string }) => string;
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
/**
 * A number box. `step` is omitted by default, which leaves Home Assistant on its
 * whole-number step — a task interval is 3 weeks, never 3.5. Pass `'any'` for a
 * quantity that is genuinely decimal (spare stock measured in millilitres), or the
 * field silently refuses the value the user typed.
 */
export const selNumber = (min = 0, step?: number | 'any'): Selector => ({
  number: step === undefined ? { min, mode: 'box' } : { min, mode: 'box', step },
});
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
/**
 * An entity picker. `exclude` drops specific entity ids from the list offered —
 * used to keep Home Keeper's own to-do list out of the shopping-list picker,
 * where choosing it would mean mirroring a list onto itself. Omitted entirely
 * when there is nothing to exclude, so the emitted selector config stays as
 * small as it was.
 */
export const selEntity = (
  filter: { domain?: string; device_class?: string },
  multiple = false,
  exclude: string[] = [],
): Selector => ({
  entity: { filter, multiple, ...(exclude.length ? { exclude_entities: exclude } : {}) },
});
export const selIcon = (): Selector => ({ icon: {} });
export const selSelect = (
  options: { value: string; label: string }[],
  multiple = false,
): Selector => ({
  select: { mode: 'dropdown', options, sort: false, multiple },
});
/**
 * A dropdown that also accepts a value the user types. Used for the NFC/RFID tag
 * picker: HA's tag registry only lists tags it already knows about, and a tag id
 * printed on a sticker is a perfectly good binding before the tag has ever been
 * scanned — so the list is a convenience, not the limit.
 */
export const selSelectCustom = (options: { value: string; label: string }[]): Selector => ({
  select: { mode: 'dropdown', options, custom_value: true },
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
/** The interval seeded when the time backstop is first switched on. */
export const DEFAULT_BACKSTOP_INTERVAL = 6;

/**
 * Whether a usage task's **time backstop** is in play, from either representation.
 *
 * The form holds it as a flat `sensor_backstop_on` switch; a task loaded for editing
 * holds it as the presence of `sensor.also_every`. One predicate over both keeps the
 * schema, the payload and the hint from ever disagreeing about whether the backstop
 * fields count — the sort of split that shows a switched-off backstop still applying.
 */
export function backstopEnabled(task: Partial<Task>): boolean {
  const flag = (task as Record<string, unknown>).sensor_backstop_on;
  if (flag !== undefined && flag !== null) return Boolean(flag);
  return Boolean(task.sensor?.also_every);
}

/**
 * Whether a state-mode binding points at a `binary_sensor`, from either representation.
 *
 * Binary sensors are the reason this mode exists and they only ever report `on`/`off`,
 * so they get a two-option picker; every other entity keeps free text because its
 * states are open-ended (`docked`, `finished`, …). Reads the live edit state's flat
 * `sensor_entity_id` first so the control swaps as soon as the entity is picked, not
 * only after a save.
 *
 * A binding that reads an `attribute` is deliberately *not* treated as binary: the
 * attribute's value is what gets compared, and that's arbitrary even on a binary sensor.
 */
export function isBinarySensorBinding(task: Partial<Task>): boolean {
  const sd = task as Record<string, unknown>;
  const attribute = String(sd.sensor_attribute ?? task.sensor?.attribute ?? '').trim();
  if (attribute) return false;
  const entityId = String(sd.sensor_entity_id ?? task.sensor?.entity_id ?? '');
  return entityId.startsWith('binary_sensor.');
}

/**
 * One labelled run of the task form. The panel renders each as its own `ha-form`
 * under a section heading, which is the only way to get a heading *between* two
 * fields: `ha-form` owns its rows and exposes no slot to interleave one.
 *
 * `key` names the section for the panel (heading text, and whether the section is
 * the conditional one that gets indented behind a rule). `dependent` marks a run
 * that only exists because of a choice made in the section above it.
 */
export interface TaskSchemaSection {
  key: 'basics' | 'schedule' | 'cadence' | 'placement' | 'completion';
  fields: FormField[];
  dependent?: boolean;
}

/**
 * The task form's fields, grouped into sections.
 *
 * {@link taskSchema} is the flattened form of exactly this, and a unit test asserts
 * the two stay identical — so the grouping can never silently add, drop or reorder
 * a field relative to the schema the payload builder and the tests are written
 * against.
 */
export function taskSchemaSections(
  task: Partial<Task>,
  consumables: { value: string; label: string }[] = [],
  links: { value: string; label: string }[] = [],
  tags: { value: string; label: string }[] = [],
): TaskSchemaSection[] {
  const locked = new Set<string>((task as Task).managed_by?.locked_fields ?? []);

  // The NFC/RFID binding — offered for every task kind (a triggered task can carry a
  // tag too), and offered even when the registry is empty: `custom_value` lets the
  // user type an id straight off the sticker.
  const tagFields: FormField[] = [
    ...(!locked.has('tag_id')
      ? [{ name: 'tag_id', selector: selSelectCustom(tags) } as FormField]
      : []),
    ...(!locked.has('require_tag_scan')
      ? [{ name: 'require_tag_scan', selector: selBool() } as FormField]
      : []),
  ];

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
      {
        key: 'basics',
        fields: [
          ...(!locked.has('name')
            ? [{ name: 'name', required: true, selector: selText() } as FormField]
            : []),
          ...(!locked.has('notes')
            ? [{ name: 'notes', selector: selText(true) } as FormField]
            : []),
        ],
      },
      {
        key: 'placement',
        fields: [
          ...(!locked.has('device_id')
            ? [{ name: 'device_id', selector: selDevice() } as FormField]
            : []),
          ...(!locked.has('area_id')
            ? [{ name: 'area_id', selector: selArea() } as FormField]
            : []),
          ...tagFields,
          ...(!locked.has('labels')
            ? [{ name: 'labels', selector: selLabel(true) } as FormField]
            : []),
          ...cardLinksField,
        ],
      },
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
  // Whether the time backstop's fields are showing. The live switch wins; a task
  // loaded for editing infers it from whether it actually carries a backstop, so an
  // existing "every 300 h or 6 months" task opens with the switch already on.
  const backstopOn = backstopEnabled(task);
  const sensorFields: FormField[] = isSensor
    ? [
        { name: 'sensor_entity_id', required: true, selector: selEntity({}) },
        {
          name: 'sensor_mode',
          selector: selSelect([
            { value: 'usage', label: t('opt.sensor_mode.usage') },
            { value: 'threshold', label: t('opt.sensor_mode.threshold') },
            { value: 'state', label: t('opt.sensor_mode.state') },
          ]),
        },
        ...(sensorMode === 'state'
          ? [
              // A binary sensor only ever reports on/off, so offer those directly
              // rather than making the user type a magic word. Any other entity keeps
              // free text so `docked` / `finished` stay reachable.
              {
                name: 'sensor_state',
                required: true,
                selector: isBinarySensorBinding(task)
                  ? selSelect([
                      { value: 'on', label: t('opt.sensor_state.on') },
                      { value: 'off', label: t('opt.sensor_state.off') },
                    ])
                  : selText(),
              } as FormField,
              { name: 'sensor_for', selector: selNumber(0) } as FormField,
              { name: 'sensor_clear_on_recover', selector: selBool() } as FormField,
            ]
          : sensorMode === 'threshold'
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
              { name: 'sensor_clear_on_recover', selector: selBool() } as FormField,
            ]
          : [
              { name: 'sensor_target', required: true, selector: selNumber(0) } as FormField,
              { name: 'sensor_unit', selector: selText() } as FormField,
              // Where the meter counts from. Left blank, Home Keeper anchors at the
              // sensor's reading when you save — the original behaviour, and still the
              // common case. Filled in, it says "the last service happened at this
              // reading", so a task created for a car serviced 3,000 miles ago starts
              // 3,000 miles in instead of a whole interval late. Bare number selector
              // rather than `selNumber(0)`: that helper pins `min: 0`, and neither the
              // backend (`_finite_float`, no range gate) nor a real meter agrees — a
              // net-energy or temperature sensor reads below zero, and a stored float
              // like 660.5 must stay re-savable.
              {
                name: 'sensor_baseline',
                selector: { number: { mode: 'box', step: 'any' } },
              } as FormField,
              // The time backstop, behind its own switch. A real service interval is
              // usually "every N hours *or* every M months", and without the second
              // half a machine that sits idle never comes due — but a pure meter is
              // just as legitimate, so the three fields only appear once you ask for
              // them. (They used to be always-visible with the interval doubling as
              // its own off switch at 0, which read as three mandatory fields you had
              // to know to neutralise.)
              { name: 'sensor_backstop_on', selector: selBool() } as FormField,
              ...(backstopOn
                ? [
                    { name: 'sensor_also_every', selector: selNumber(1) } as FormField,
                    {
                      name: 'sensor_also_unit',
                      selector: selSelect([
                        { value: 'days', label: t('opt.unit.days') },
                        { value: 'weeks', label: t('opt.unit.weeks') },
                        { value: 'months', label: t('opt.unit.months') },
                      ]),
                    } as FormField,
                    {
                      name: 'sensor_combinator',
                      selector: selSelect([
                        { value: 'any', label: t('opt.sensor_combinator.any') },
                        { value: 'all', label: t('opt.sensor_combinator.all') },
                      ]),
                    } as FormField,
                  ]
                : []),
            ]),
        { name: 'sensor_attribute', selector: selText() },
      ]
    : [];

  const basics: FormField[] = [
    ...(!locked.has('name')
      ? [{ name: 'name', required: true, selector: selText() } as FormField]
      : []),
    ...(!locked.has('notes') ? [{ name: 'notes', selector: selText(true) } as FormField] : []),
  ];

  // "How does this repeat?" — the one choice every field below it depends on.
  const schedule: FormField[] = [
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
  ];

  // Everything the recurrence choice reveals. Rendered indented behind a rule, so
  // "these exist because of the answer above" is visible rather than inferred.
  const cadenceSection: FormField[] = [
    ...(cadence ? [cadence] : []),
    ...sensorFields,
    ...(isFixed && !locked.has('anchor')
      ? [{ name: 'anchor', selector: selDateTime() } as FormField]
      : []),
    ...(isOneOff && !locked.has('due')
      ? [{ name: 'due', selector: selDateTime() } as FormField]
      : []),
    // "Last completed" seeds the first history entry. For a scheduled task that
    // places the first due date; for a *sensor* task it anchors the time backstop
    // (`sensor.also_every`), so "every 10,000 mi or 12 months" starts its calendar
    // half where the meter half starts rather than restarting today. `build_task`
    // has always handled the sensor case (recording history without arming) — only
    // this predicate hid the field.
    ...(!task.id && !isOneOff && !locked.has('last_completed')
      ? [{ name: 'last_completed', selector: selDateTime() } as FormField]
      : []),
  ];

  // Where the task hangs off the house: a device, a room, a sticker, a consumable.
  const placement: FormField[] = [
    ...(!locked.has('device_id') ? [{ name: 'device_id', selector: selDevice() } as FormField] : []),
    // A task's *own* area, independent of any device. A task with an attached device
    // already inherits that device's area for grouping and filtering (see
    // `taskAreaId`), but a device-less task had no way to be placed in a room at all —
    // the panel grouped it under "Unassigned" with no control to fix it, even though
    // `area_id` has always been a first-class field on the service API. Setting it
    // here overrides the inherited value; clearing it falls back to the device's area.
    ...(!locked.has('area_id') ? [{ name: 'area_id', selector: selArea() } as FormField] : []),
    // Bind an NFC/RFID tag, and optionally make scanning it the *only* way to
    // complete the task. Sits with the other attachment fields — a tag is one more
    // physical thing the task hangs off, like a device or a room.
    ...tagFields,
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
  ];

  // What happens when someone taps Done.
  const completion: FormField[] = [
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

  return [
    { key: 'basics', fields: basics },
    { key: 'schedule', fields: schedule },
    { key: 'cadence', fields: cadenceSection, dependent: true },
    { key: 'placement', fields: placement },
    { key: 'completion', fields: completion },
  ];
}

/**
 * Every field name a schema offers, including those nested inside a `grid` group.
 */
export function schemaFieldNames(schema: FormField[]): string[] {
  return schema.flatMap((f) =>
    f.schema ? schemaFieldNames(f.schema) : f.name ? [f.name] : [],
  );
}

/**
 * The slice of *data* belonging to *schema* — the seed for one section's `ha-form`.
 *
 * `ha-form` emits its entire `data` object on every change, so a section seeded with
 * the whole form would re-assert a stale snapshot of every other section each time
 * it changed. Narrowing the seed makes each section's event carry only that
 * section's fields, which is also what lets the panel's change handler tell "this
 * field was set to nothing" apart from "this field is not in this section".
 */
export function pickFormData(
  data: Record<string, unknown>,
  schema: FormField[],
): Record<string, unknown> {
  const picked: Record<string, unknown> = {};
  for (const name of schemaFieldNames(schema)) {
    if (name in data) picked[name] = data[name];
  }
  return picked;
}

/**
 * The task form's fields as one flat schema — the order the payload builder, the
 * saved task and the tests are all written against. Kept as the flattening of
 * {@link taskSchemaSections} so the two can never disagree.
 */
export function taskSchema(
  task: Partial<Task>,
  consumables: { value: string; label: string }[] = [],
  links: { value: string; label: string }[] = [],
  tags: { value: string; label: string }[] = [],
): FormField[] {
  return taskSchemaSections(task, consumables, links, tags).flatMap((s) => s.fields);
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
    // Seeded to `on` because a binary sensor is what this mode is for, and `on` is the
    // state that means "something needs doing" for every device class that matters
    // here (water tank low, battery almost empty, leak detected).
    sensor_state: sd.sensor_state ?? task.sensor?.state ?? 'on',
    sensor_clear_on_recover: sd.sensor_clear_on_recover ?? task.sensor?.clear_on_recover ?? false,
    sensor_for: sd.sensor_for ?? task.sensor?.for_seconds ?? 0,
    sensor_attribute: sd.sensor_attribute ?? task.sensor?.attribute ?? '',
    sensor_unit: sd.sensor_unit ?? task.sensor?.unit ?? '',
    sensor_baseline: sd.sensor_baseline ?? task.sensor?.baseline ?? undefined,
    sensor_backstop_on: backstopEnabled(task),
    // Seeded rather than left at 0 so switching the backstop on gives a working rule
    // straight away instead of three fields that quietly do nothing until you notice
    // the interval is zero.
    sensor_also_every:
      sd.sensor_also_every ?? task.sensor?.also_every?.interval ?? DEFAULT_BACKSTOP_INTERVAL,
    sensor_also_unit: sd.sensor_also_unit ?? task.sensor?.also_every?.unit ?? 'months',
    sensor_combinator: sd.sensor_combinator ?? task.sensor?.combinator ?? 'any',
    device_id: task.device_id ?? undefined,
    area_id: task.area_id ?? undefined,
    // `undefined`, not '' — an unbound tag must leave the combo box empty rather
    // than pre-selecting a blank option.
    tag_id: task.tag_id ?? undefined,
    require_tag_scan: task.require_tag_scan ?? false,
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

/**
 * The values that decide **which fields the task form shows**: the recurrence kind, the
 * sensor mode, whether the time backstop is on, whether a state binding points at a
 * binary sensor (which swaps its value control), and the attached device (which scopes
 * the consumable and card-link pickers). Serialized into one comparable key.
 *
 * The form's `value-changed` handler re-renders only when this key moves, and it must
 * compare like with like: both sides run through `taskFormData`, so a default the
 * *form* seeded (an unset `sensor_mode` shows as 'usage') can never read as a change
 * against an edit state that simply doesn't carry the field. Comparing the raw edit
 * state against form values did exactly that, and re-rendered on the first unrelated
 * character typed into a task's name — which replaced the field mid-word, dropped
 * focus to `<body>`, and handed the rest of the keystrokes to Home Assistant's global
 * one-letter shortcuts (`d` device search, `a` Assist, `e`/`c`/`m`).
 *
 * Accepts either shape the two sides come in — a task (nested `sensor` binding) or the
 * flat `sensor_*` form values — because `taskFormData` reads both.
 */
export function taskFormSchemaKey(task: Partial<Task> | Record<string, unknown>): string {
  const d = taskFormData(task as Partial<Task>);
  return JSON.stringify([
    d.recurrence_type,
    d.sensor_mode,
    d.sensor_backstop_on,
    // State mode's value control follows the bound entity: an on/off picker for a
    // binary sensor, free text for anything else. This predicate reads the flat and the
    // nested binding itself, so it needs no normalizing pass of its own.
    isBinarySensorBinding(task as Partial<Task>),
    // No device, a cleared picker and a blank string all mean "unattached", so they all
    // have to land on the same value here.
    d.device_id || null,
  ]);
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
      const unit = String(sd.sensor_unit ?? task.sensor?.unit ?? '').trim();
      if (unit) sensor.unit = unit;
      // The meter's starting point. Only sent when the box actually holds a number:
      // blank on create means "anchor at the live reading" (the backend leaves
      // `baseline` unset for the watcher to stamp), and blank on edit is preserved
      // by `merge_update`. Note the deliberate absence of the `|| 0` fallback used
      // for `target` above — 0 is a *valid* baseline (a brand-new hour meter) and
      // that idiom would turn a cleared box into a real anchor at zero.
      const rawBaseline = sd.sensor_baseline ?? task.sensor?.baseline;
      if (rawBaseline != null && rawBaseline !== '' && Number.isFinite(Number(rawBaseline)))
        sensor.baseline = Number(rawBaseline);
      // The backstop applies only when its switch is on; a blank or zero interval
      // still drops it, so a half-filled form can't save a meaningless "every 0".
      const alsoEvery = Number(sd.sensor_also_every ?? task.sensor?.also_every?.interval) || 0;
      if (backstopEnabled(task) && alsoEvery > 0) {
        sensor.also_every = {
          interval: alsoEvery,
          unit: (String(sd.sensor_also_unit ?? task.sensor?.also_every?.unit ?? 'months') ||
            'months') as Unit,
        };
        sensor.combinator = (String(
          sd.sensor_combinator ?? task.sensor?.combinator ?? 'any',
        ) || 'any') as SensorCombinator;
      }
    } else {
      // The edge-driven modes (threshold / state) share the hold and the
      // clear-on-recover flag; only the condition itself differs.
      if (mode === 'state') {
        sensor.state = String(sd.sensor_state ?? task.sensor?.state ?? '').trim();
      } else {
        sensor.comparison = (sd.sensor_comparison as SensorComparison) ||
          task.sensor?.comparison ||
          '>=';
        sensor.value = Number(sd.sensor_value ?? task.sensor?.value) || 0;
      }
      const forSeconds = Number(sd.sensor_for ?? task.sensor?.for_seconds) || 0;
      if (forSeconds > 0) sensor.for_seconds = forSeconds;
      const clearOnRecover = sd.sensor_clear_on_recover ?? task.sensor?.clear_on_recover;
      if (clearOnRecover) sensor.clear_on_recover = true;
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
  // Area applies to every task kind (including triggered) and always round-trips, so
  // clearing the picker sends an explicit null and drops the task's own area rather
  // than silently keeping the previous one. `merge_update` strips it again when the
  // managing integration locks the field.
  payload.area_id = task.area_id || null;
  // The tag binding applies to every task kind and always round-trips, so clearing
  // the picker sends an explicit null and unbinds the tag. Clearing it also force-
  // clears `require_tag_scan`: a task that demands a scan but has no tag to scan
  // could never be completed at all, from any surface.
  payload.tag_id = task.tag_id || null;
  payload.require_tag_scan = task.tag_id ? !!task.require_tag_scan : false;
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
 * The rule the form currently describes, in the *same words the saved task will use*.
 *
 * The recurrence fields are individually clear and collectively opaque: a target, a
 * unit, a backstop interval and a combinator are four boxes that add up to "every 100 h
 * of use, or every month, whichever lands first", and nothing on screen said that
 * sentence until the task existed. So the form renders it live, right above the submit
 * button, and you read the rule before you commit to it.
 *
 * Deliberately built by running the edit state through `buildTaskPayload` and handing
 * the result to `recurrenceSummary` — the very functions that produce the payload and
 * the card's caption. A separate "preview formatter" would be free to drift from what
 * the task actually becomes, which is the one thing a preview must never do.
 *
 * Returns `''` when the type isn't chosen yet, so the caller can hide the strip.
 */
export function formRecurrenceSummary(task: Partial<Task>): string {
  if (!task.recurrence_type) return '';
  try {
    // `recurrence_type` is re-attached because the triggered branch of
    // buildTaskPayload deliberately omits it (the managing integration owns the
    // kind, so the update need not carry it). Without this a triggered task would
    // fall through to the clock branch and the preview would read "every day" —
    // the exact class of confident-but-wrong copy this strip exists to prevent.
    const payload = { ...buildTaskPayload(task), recurrence_type: task.recurrence_type };
    return recurrenceSummary(payload as Task);
  } catch {
    // A half-typed form is not an error state; say nothing until it parses.
    return '';
  }
}

/** Stored sensor comparisons rendered as their human symbol for help/hint copy. */
const COMPARISON_SYMBOLS: Record<string, string> = {
  '>=': '≥',
  '<=': '≤',
  '>': '>',
  '<': '<',
  '==': '=',
  '!=': '≠',
};

/**
 * The meter half of `sensorHintText`: where counting starts, and where that lands.
 *
 * Split out because a usage task now has two anchors rather than one. Without an
 * explicit starting reading the meter anchors at whatever the sensor says when you
 * save, which is the original behaviour and reads forward ("reads 660, due at 760").
 * With one, the anchor is a fact about the past ("the oil was changed at 45,000"),
 * so the sentence has to say how much of the interval that already spends — the
 * whole point of the field is that you're partway through before you begin.
 *
 * Two cases the arithmetic has to call out rather than leave the reader to spot:
 * a starting reading *above* the live one (a typo, or a meter about to be reset —
 * either way the watcher will re-anchor, so say so), and one far enough back that
 * the target is already met, which arms the task moments after you save.
 */
function usageHint(
  task: Partial<Task>,
  ctx: { reading?: number; unit?: string },
  target: number,
  targetStr: string,
  unit: string,
): string {
  const sd = task as Record<string, unknown>;
  const rawBaseline = sd.sensor_baseline ?? task.sensor?.baseline;
  const baseline = Number(rawBaseline);
  const hasBaseline =
    rawBaseline != null && rawBaseline !== '' && Number.isFinite(baseline);
  const hasReading = ctx.reading != null && !Number.isNaN(ctx.reading);

  if (!hasBaseline) {
    return hasReading
      ? t('hint.sensor.usage', {
          reading: `${ctx.reading}${unit}`,
          due: `${round1((ctx.reading as number) + target)}${unit}`,
          target: targetStr,
        })
      : t('hint.sensor.usageNoReading', { target: targetStr });
  }

  const due = `${round1(baseline + target)}${unit}`;
  if (!hasReading) {
    return t('hint.sensor.usageFromBaselineNoReading', {
      baseline: `${baseline}${unit}`,
      due,
      target: targetStr,
    });
  }
  const reading = ctx.reading as number;
  if (reading < baseline) {
    return t('hint.sensor.usageBaselineAhead', {
      baseline: `${baseline}${unit}`,
      reading: `${reading}${unit}`,
    });
  }
  const consumed = round1(reading - baseline);
  if (consumed >= target) {
    return t('hint.sensor.usageAlreadyDue', {
      baseline: `${baseline}${unit}`,
      consumed: `${consumed}${unit}`,
      target: targetStr,
    });
  }
  return t('hint.sensor.usageFromBaseline', {
    baseline: `${baseline}${unit}`,
    consumed: `${consumed}${unit}`,
    due,
    target: targetStr,
  });
}

/**
 * A plain-language sentence explaining when a sensor-based task will next become
 * due, given the sensor's live reading. Pure (no DOM) so the panel can render it
 * under the sensor fields and unit tests can assert the wording and arithmetic.
 *
 * Usage mode anchors a *baseline* at the sensor's reading when the task is created
 * (or last completed) and arms once the reading climbs `target` above it — so the
 * first due point is `reading + target`, and it repeats `target` after each
 * completion. Threshold mode arms on a comparison instead. Reads the live edit
 * state's flat `sensor_*` fields, falling back to a loaded task's nested binding.
 * Returns `''` when there isn't enough entered yet to say anything useful.
 */
export function sensorHintText(
  task: Partial<Task>,
  ctx: { reading?: number; unit?: string } = {},
): string {
  const sd = task as Record<string, unknown>;
  const mode = ((sd.sensor_mode as SensorMode) ?? task.sensor?.mode ?? 'usage') as SensorMode;
  const unit = ctx.unit ? ` ${ctx.unit}` : '';

  // The edge-driven modes share the hold wording and the clear-on-recover suffix.
  const forSeconds = Number(sd.sensor_for ?? task.sensor?.for_seconds ?? 0) || 0;
  const withRecovery = (base: string): string =>
    (sd.sensor_clear_on_recover ?? task.sensor?.clear_on_recover)
      ? `${base} ${t('hint.sensor.clearOnRecover')}`
      : base;

  if (mode === 'state') {
    const state = String(sd.sensor_state ?? task.sensor?.state ?? '').trim();
    if (!state) return '';
    return withRecovery(
      forSeconds > 0
        ? t('hint.sensor.stateFor', { state, seconds: forSeconds })
        : t('hint.sensor.state', { state }),
    );
  }

  if (mode === 'threshold') {
    const rawValue = sd.sensor_value ?? task.sensor?.value;
    if (rawValue == null || rawValue === '' || Number.isNaN(Number(rawValue))) return '';
    const comparison = String(sd.sensor_comparison ?? task.sensor?.comparison ?? '>=');
    const symbol = COMPARISON_SYMBOLS[comparison] ?? comparison;
    const value = `${Number(rawValue)}${unit}`;
    return withRecovery(
      forSeconds > 0
        ? t('hint.sensor.thresholdFor', { comparison: symbol, value, seconds: forSeconds })
        : t('hint.sensor.threshold', { comparison: symbol, value }),
    );
  }

  // usage / meter
  const rawTarget = sd.sensor_target ?? task.sensor?.target;
  const target = Number(rawTarget);
  if (rawTarget == null || rawTarget === '' || Number.isNaN(target) || target <= 0) return '';
  const targetStr = `${target}${unit}`;
  const base = usageHint(task, ctx, target, targetStr, unit);
  const alsoEvery = Number(sd.sensor_also_every ?? task.sensor?.also_every?.interval) || 0;
  if (!backstopEnabled(task) || alsoEvery <= 0) return base;
  const alsoUnit = String(sd.sensor_also_unit ?? task.sensor?.also_every?.unit ?? 'months');
  const every = `${alsoEvery} ${t(`opt.unit.${alsoUnit}`)}`;
  const combinator = String(sd.sensor_combinator ?? task.sensor?.combinator ?? 'any');
  return `${base} ${
    combinator === 'all'
      ? t('hint.sensor.backstopAll', { every })
      : t('hint.sensor.backstopAny', { every })
  }`;
}

/**
 * The `ha-form` schema for the Settings tab's **Problem sensor sync** card — the
 * sync toggle plus entity / device / area / label exclusions (a subset of the
 * options flow). The entity picker is filtered to `device_class: problem` binary
 * sensors.
 */
export function problemSyncSchema(): FormField[] {
  return [...problemSyncToggleSchema(), ...problemSyncExclusionsSchema()];
}

/** The switch that decides whether problem sensors are mirrored at all. */
export function problemSyncToggleSchema(): FormField[] {
  return [{ name: 'sync_problem_sensors', selector: selBool() }];
}

/**
 * The two switches deciding whether Home Keeper offers Snooze and Skip on a task.
 *
 * They govern what this panel shows and what a notification's button set may carry.
 * The `home_keeper.snooze_task` / `skip_task` services stay callable either way, so
 * turning one off never breaks an automation someone already wrote.
 */
export function skipSnoozeSchema(): FormField[] {
  return [
    { name: 'allow_snooze', selector: selBool() },
    { name: 'allow_skip', selector: selBool() },
  ];
}

/**
 * Read the two switches off an options object, defaulting **on**.
 *
 * `!!v` would read a missing key as off, which would withdraw both verbs from every
 * install whose stored options predate the switches — which is all of them.
 */
export function skipSnoozeFlags(options: {
  allow_snooze?: unknown;
  allow_skip?: unknown;
}): { allowSnooze: boolean; allowSkip: boolean } {
  return {
    allowSnooze: boolOr(options?.allow_snooze, true),
    allowSkip: boolOr(options?.allow_skip, true),
  };
}

/**
 * The four exclusion pickers, which only mean anything while the sync above them is
 * on. Split from the toggle so the panel can indent them behind a rule and caption
 * them — `ha-form` has no slot between two of its own rows. `problemSyncSchema` is
 * the concatenation of the two, and a test holds them to that.
 */
export function problemSyncExclusionsSchema(): FormField[] {
  return [
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

/**
 * The `ha-form` schema for the Settings tab's **Shopping list** card — the one
 * to-do list auto-buy reminders are mirrored onto (empty turns the mirror off).
 * Home Keeper's own to-do lists are excluded from the picker: mirroring a list
 * onto itself is a loop, and ours accepts no new items anyway.
 */
export function shoppingSchema(exclude: string[] = []): FormField[] {
  return [
    { name: 'shopping_list_entity', selector: selEntity({ domain: 'todo' }, false, exclude) },
  ];
}

// ── profiles (saved filters) & notifications (delivery) ─────────────────────

const NOTIFY_STATUSES: NotifyStatus[] = ['all', 'overdue', 'due_soon'];
const NOTIFY_ACTIONS: NotifyAction[] = ['complete', 'snooze', 'skip', 'open'];
const NOTIFY_STYLES: NotifyStyle[] = ['walk', 'digest'];

/** Localized `{value,label}` options for a notify enum (status/action/style). */
const notifyOptions = (values: string[]): { value: string; label: string }[] =>
  values.map((v) => ({ value: v, label: t('notify.opt.' + v) }));

const strList = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

/**
 * A switch whose stored default is **on**. `!!v` would read a missing key as off,
 * which silently turns two-way sync (or vanish-as-completed) off for any profile
 * snapshot that predates the field — the opposite of what the backend normalizer
 * fills in.
 */
const boolOr = (value: unknown, fallback: boolean): boolean =>
  value == null ? fallback : Boolean(value);

/** A stored, form-emitted or entirely absent sync block, before normalization. */
type SyncLike = { [K in keyof ProfileSync]?: unknown } | null | undefined;

/**
 * Normalize a sync block — read off a stored profile, or emitted by the sync form —
 * into a full `ProfileSync`.
 *
 * Clearing the entity picker emits `undefined`, and JSON drops an undefined on the
 * way to the backend, so the key would never reach the saved profile and "switch the
 * sync off" silently wouldn't stick; `''` is what the backend reads as off. Both
 * switches default **on**, matching the backend normalizer — a profile saved before
 * these fields existed must not come back with two-way sync quietly disabled.
 */
export function toProfileSync(raw: SyncLike): ProfileSync {
  return {
    entity_id: String(raw?.entity_id ?? ''),
    two_way: boolOr(raw?.two_way, true),
    vanish_as_completed: boolOr(raw?.vanish_as_completed, true),
  };
}

/**
 * The `ha-form` schema for a profile's **Sync to a to-do list** group: the list
 * itself, then the two switches that decide what a change on that list means here.
 *
 * There is no separate on/off control — an empty picker *is* off — so the picker is
 * single-valued (a `multiple` one saves an array the backend reads as unusable).
 * *exclude* drops Home Keeper's own to-do lists, exactly as `shoppingSchema` does:
 * mirroring a list onto itself is a loop, and ours accepts no new items anyway.
 */
export function profileSyncSchema(exclude: string[] = []): FormField[] {
  return [
    { name: 'entity_id', selector: selEntity({ domain: 'todo' }, false, exclude) },
    { name: 'two_way', selector: selBool() },
    { name: 'vanish_as_completed', selector: selBool() },
  ];
}

/**
 * The `ha-form` schema for one **profile** (a named, reusable task filter).
 *
 * The include lists come first, then the `exclude_*` lists that subtract from them —
 * so a profile can say "everything overdue except the jobs that need a tradesperson".
 */
export function profileSchema(): FormField[] {
  return [
    { name: 'name', required: true, selector: selText() },
    { name: 'status', selector: selSelect(notifyOptions(NOTIFY_STATUSES)) },
    { name: 'labels', selector: selLabel(true) },
    { name: 'areas', selector: selArea(true) },
    { name: 'devices', selector: selDevice(true) },
    { name: 'exclude_labels', selector: selLabel(true) },
    { name: 'exclude_areas', selector: selArea(true) },
    { name: 'exclude_devices', selector: selDevice(true) },
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
    exclude_labels: p.filter.exclude_labels,
    exclude_areas: p.filter.exclude_areas,
    exclude_devices: p.filter.exclude_devices,
  };
}

/**
 * Rebuild a profile (nested filter) from the flat form data, keeping *id*.
 *
 * The profile form doesn't render the sync fields — they live in their own group —
 * so *sync* carries the profile's existing block through. Omitting it would wipe a
 * configured to-do list the moment somebody renamed the profile.
 */
export function profileFormToProfile(
  id: string,
  data: Record<string, unknown>,
  sync?: SyncLike,
): Profile {
  return {
    id,
    name: String(data.name ?? '').trim() || t('profile.defaultName'),
    sync: toProfileSync(sync),
    filter: {
      status: (data.status as NotifyStatus) ?? 'overdue',
      labels: strList(data.labels),
      areas: strList(data.areas),
      devices: strList(data.devices),
      exclude_labels: strList(data.exclude_labels),
      exclude_areas: strList(data.exclude_areas),
      exclude_devices: strList(data.exclude_devices),
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
    name: String(data.name ?? '').trim() || t('notify.defaultName'),
    profile_id: data.profile_id ? String(data.profile_id) : null,
    targets: strList(data.targets),
    actions: strList(data.actions) as NotifyAction[],
    style: (data.style as NotifyStyle) ?? 'walk',
    snooze_hours: Number(data.snooze_hours ?? 24) || 24,
    auto: { overdue: !!data.auto_overdue, due_soon: !!data.auto_due_soon },
  };
}
