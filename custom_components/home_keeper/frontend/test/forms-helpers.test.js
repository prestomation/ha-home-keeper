import { beforeEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_BACKSTOP_INTERVAL,
  MAX_SEASON_WINDOWS,
  backstopEnabled,
  cardLinkTokens,
  cardLinksFromTokens,
  consumableLinkToken,
  daysInMonth,
  haDateTimeToIso,
  isoToHaDateTime,
  profileFormData,
  profileFormToProfile,
  profileSchema,
  seasonCount,
  seasonEnabled,
  seasonFieldLabelKey,
  selArea,
  selBool,
  selDate,
  selDateTime,
  selDevice,
  selEntity,
  selIcon,
  selLabel,
  selNumber,
  selSelect,
  selText,
  taskFormSchemaKey,
} from '../src/forms.ts';
import { setLanguage } from '../src/i18n.ts';

// `forms.ts` is the panel's whole edit surface: selector factories that decide
// what `ha-form` renders, the datetime bridge between HA's local-string format
// and the ISO we persist, and the token round-trips behind card links and
// profiles. `completion.test.js` and `sensor-form.test.js` cover the task schema
// and payload; these are the helpers underneath them, which nothing exercised.

beforeEach(() => setLanguage('en'));

describe('selector factories', () => {
  // A selector object is a contract with `ha-form`: the wrong shape silently
  // renders the wrong control (or none). Assert the exact object, not just that
  // the right key is present.
  it('builds single-line and multiline text selectors', () => {
    expect(selText()).toEqual({ text: {} });
    expect(selText(false)).toEqual({ text: {} });
    expect(selText(true)).toEqual({ text: { multiline: true } });
  });

  it('builds a boxed number selector with a floor', () => {
    expect(selNumber()).toEqual({ number: { min: 0, mode: 'box' } });
    expect(selNumber(1)).toEqual({ number: { min: 1, mode: 'box' } });
    expect(selNumber(-5)).toEqual({ number: { min: -5, mode: 'box' } });
  });

  // A step is opt-in: whole numbers stay the default (an interval is 3 weeks, never
  // 3.5), and a genuinely decimal quantity asks for `'any'` or the field refuses
  // the value the user typed.
  it('omits step unless the field is decimal', () => {
    expect(selNumber(0)).not.toHaveProperty('number.step');
    expect(selNumber(0, 'any')).toEqual({ number: { min: 0, mode: 'box', step: 'any' } });
    expect(selNumber(2, 0.5)).toEqual({ number: { min: 2, mode: 'box', step: 0.5 } });
  });

  it('builds the parameterless selectors', () => {
    expect(selBool()).toEqual({ boolean: {} });
    expect(selDate()).toEqual({ date: {} });
    expect(selDateTime()).toEqual({ datetime: {} });
    expect(selIcon()).toEqual({ icon: {} });
  });

  // Registry pickers default to single-select; `multiple` is opt-in, and an
  // empty object is *not* the same as `{multiple: false}` to ha-form.
  it.each([
    ['device', selDevice],
    ['area', selArea],
    ['label', selLabel],
  ])('builds a %s picker that is single-select by default', (key, factory) => {
    expect(factory()).toEqual({ [key]: {} });
    expect(factory(false)).toEqual({ [key]: {} });
    expect(factory(true)).toEqual({ [key]: { multiple: true } });
  });

  it('builds an entity selector carrying its filter through', () => {
    expect(selEntity({ domain: 'sensor' })).toEqual({
      entity: { filter: { domain: 'sensor' }, multiple: false },
    });
    expect(selEntity({ device_class: 'problem' }, true)).toEqual({
      entity: { filter: { device_class: 'problem' }, multiple: true },
    });
  });

  it('builds an unsorted dropdown so option order is ours', () => {
    // `sort: false` matters: the options are ordered deliberately (statuses run
    // worst-first), and letting ha-form sort them alphabetically reorders them.
    const options = [
      { value: 'overdue', label: 'Overdue' },
      { value: 'due', label: 'Due' },
    ];
    expect(selSelect(options)).toEqual({
      select: { mode: 'dropdown', options, sort: false, multiple: false },
    });
    expect(selSelect(options, true)).toEqual({
      select: { mode: 'dropdown', options, sort: false, multiple: true },
    });
  });
});

describe('isoToHaDateTime / haDateTimeToIso', () => {
  it('formats an ISO timestamp as HA local "YYYY-MM-DD HH:mm:ss"', () => {
    // Built from local parts so the assertion holds in any TZ the suite runs in.
    const d = new Date(2026, 5, 13, 9, 8, 7);
    expect(isoToHaDateTime(d.toISOString())).toBe('2026-06-13 09:08:07');
  });

  it('zero-pads every component to two digits', () => {
    // The single-digit month/day/hour/minute/second case is the whole reason
    // `padStart` is there; a bare template string would emit "2026-6-1 9:8:7".
    const d = new Date(2026, 0, 2, 3, 4, 5);
    expect(isoToHaDateTime(d.toISOString())).toBe('2026-01-02 03:04:05');
  });

  it('uses a 1-based month', () => {
    const d = new Date(2026, 11, 31, 23, 59, 59);
    expect(isoToHaDateTime(d.toISOString())).toBe('2026-12-31 23:59:59');
  });

  it('returns undefined for empty or unparseable input', () => {
    expect(isoToHaDateTime(undefined)).toBeUndefined();
    expect(isoToHaDateTime(null)).toBeUndefined();
    expect(isoToHaDateTime('')).toBeUndefined();
    expect(isoToHaDateTime('not-a-date')).toBeUndefined();
  });

  it('parses HA local format back to ISO', () => {
    const iso = haDateTimeToIso('2026-06-13 09:08:07');
    expect(iso).toBe(new Date(2026, 5, 13, 9, 8, 7).toISOString());
  });

  it('returns undefined for empty or unparseable input', () => {
    expect(haDateTimeToIso(undefined)).toBeUndefined();
    expect(haDateTimeToIso(null)).toBeUndefined();
    expect(haDateTimeToIso('')).toBeUndefined();
    expect(haDateTimeToIso('not-a-date')).toBeUndefined();
  });

  it('round-trips a value through both directions', () => {
    const original = new Date(2026, 5, 13, 9, 8, 7).toISOString();
    expect(haDateTimeToIso(isoToHaDateTime(original))).toBe(original);
  });
});

describe('backstopEnabled', () => {
  it('reads the flat form switch when present', () => {
    expect(backstopEnabled({ sensor_backstop_on: true })).toBe(true);
    expect(backstopEnabled({ sensor_backstop_on: false })).toBe(false);
  });

  it('prefers the flat switch over a stored also_every', () => {
    // Switching the backstop off in the form must win over the value still on
    // the task being edited, or a switched-off backstop keeps applying.
    expect(
      backstopEnabled({ sensor_backstop_on: false, sensor: { also_every: { interval: 6 } } }),
    ).toBe(false);
    expect(backstopEnabled({ sensor_backstop_on: true, sensor: {} })).toBe(true);
  });

  it('falls back to the stored also_every when the switch is absent', () => {
    expect(backstopEnabled({ sensor: { also_every: { interval: 6 } } })).toBe(true);
    expect(backstopEnabled({ sensor: {} })).toBe(false);
    expect(backstopEnabled({})).toBe(false);
  });

  it('treats an explicit null switch as absent, not as off', () => {
    // null means "the form never set this", so the stored task decides — unlike
    // `false`, which is the user actively switching the backstop off.
    expect(backstopEnabled({ sensor_backstop_on: null, sensor: {} })).toBe(false);
    expect(
      backstopEnabled({ sensor_backstop_on: null, sensor: { also_every: { interval: 6 } } }),
    ).toBe(true);
  });

  it('seeds a sensible interval when first switched on', () => {
    expect(DEFAULT_BACKSTOP_INTERVAL).toBe(6);
  });
});

describe('seasonEnabled', () => {
  it('reads the flat form switch when present', () => {
    expect(seasonEnabled({ season_on: true })).toBe(true);
    expect(seasonEnabled({ season_on: false })).toBe(false);
  });

  it('prefers the flat switch over stored windows', () => {
    // Switching the season off has to win over the windows still on the task being
    // edited, or a switched-off season keeps restricting the due date.
    expect(
      seasonEnabled({ season_on: false, active_season: [{ start: '04-01', end: '09-30' }] }),
    ).toBe(false);
    expect(seasonEnabled({ season_on: true, active_season: null })).toBe(true);
  });

  it('falls back to the stored windows when the switch is absent', () => {
    expect(seasonEnabled({ active_season: [{ start: '04-01', end: '09-30' }] })).toBe(true);
    expect(seasonEnabled({ active_season: { start: '04-01', end: '09-30' } })).toBe(true);
    expect(seasonEnabled({ active_season: [] })).toBe(false);
    expect(seasonEnabled({})).toBe(false);
  });

  it('treats an explicit null switch as absent, not as off', () => {
    expect(seasonEnabled({ season_on: null, active_season: null })).toBe(false);
    expect(
      seasonEnabled({ season_on: null, active_season: [{ start: '04-01', end: '09-30' }] }),
    ).toBe(true);
  });
});

describe('seasonCount', () => {
  it('counts the stored windows when the form has not said otherwise', () => {
    expect(seasonCount({ active_season: [{ start: '04-01', end: '09-30' }] })).toBe(1);
    expect(
      seasonCount({
        active_season: [
          { start: '04-01', end: '05-31' },
          { start: '09-01', end: '10-31' },
        ],
      }),
    ).toBe(2);
  });

  it('prefers the live count, so a removed window stays removed', () => {
    // The stored list still has two windows; the form says one. Reading the task
    // would put the removed window straight back on screen.
    expect(
      seasonCount({
        season_count: 1,
        active_season: [
          { start: '04-01', end: '05-31' },
          { start: '09-01', end: '10-31' },
        ],
      }),
    ).toBe(1);
  });

  it('is at least one window and never more than the panel cap', () => {
    expect(seasonCount({})).toBe(1);
    expect(seasonCount({ season_count: 0 })).toBe(1);
    expect(seasonCount({ season_count: MAX_SEASON_WINDOWS + 3 })).toBe(MAX_SEASON_WINDOWS);
  });
});

describe('seasonFieldLabelKey', () => {
  it('points every window at one set of translations', () => {
    // Windows that named themselves individually ("Active season" then "Second
    // window") is the labelling inconsistency reported on #242.
    expect(seasonFieldLabelKey('season_1_start_month')).toBe('season_start_month');
    expect(seasonFieldLabelKey('season_3_end_day')).toBe('season_end_day');
  });

  it('leaves every other field name alone', () => {
    for (const name of ['season_on', 'interval', 'sensor_also_every', 'name']) {
      expect(seasonFieldLabelKey(name)).toBe(name);
    }
  });
});

describe('daysInMonth', () => {
  it('knows the short months, and gives February its leap day', () => {
    expect(daysInMonth(1)).toBe(31);
    expect(daysInMonth(2)).toBe(29);
    expect(daysInMonth(4)).toBe(30);
    expect(daysInMonth(12)).toBe(31);
  });
});

describe('consumableLinkToken', () => {
  it('joins the asset and part ids', () => {
    expect(consumableLinkToken({ source: { part: { asset_id: 'a1', part_id: 'p2' } } })).toBe(
      'a1:p2',
    );
  });

  it('is empty when the task has no part source', () => {
    expect(consumableLinkToken({})).toBe('');
    expect(consumableLinkToken({ source: {} })).toBe('');
  });
});

describe('cardLinkTokens / cardLinksFromTokens', () => {
  it('renders stored reference objects as tokens', () => {
    expect(
      cardLinkTokens({
        card_links: [
          { asset_id: 'a1', entry_id: 'e1' },
          { asset_id: 'a2', entry_id: 'e2' },
        ],
      }),
    ).toEqual(['a1:e1', 'a2:e2']);
  });

  it('passes through the flat strings the select emits mid-edit', () => {
    expect(cardLinkTokens({ card_links: ['a1:e1', 'a2:e2'] })).toEqual(['a1:e1', 'a2:e2']);
  });

  it('drops half-filled objects rather than emitting a broken token', () => {
    expect(
      cardLinkTokens({
        card_links: [{ asset_id: 'a1' }, { entry_id: 'e2' }, {}, { asset_id: 'a3', entry_id: 'e3' }],
      }),
    ).toEqual(['a3:e3']);
  });

  it('is empty for a missing or non-array field', () => {
    expect(cardLinkTokens({})).toEqual([]);
    expect(cardLinkTokens({ card_links: null })).toEqual([]);
    expect(cardLinkTokens({ card_links: 'a1:e1' })).toEqual([]);
  });

  it('parses tokens back into reference objects', () => {
    expect(cardLinksFromTokens(['a1:e1', 'a2:e2'])).toEqual([
      { asset_id: 'a1', entry_id: 'e1' },
      { asset_id: 'a2', entry_id: 'e2' },
    ]);
  });

  it('splits on the first colon only', () => {
    // Ids are UUIDs and never contain a colon, but splitting on the last one
    // would corrupt any that ever did — the entry id keeps the remainder.
    expect(cardLinksFromTokens(['a1:e1:extra'])).toEqual([
      { asset_id: 'a1', entry_id: 'e1:extra' },
    ]);
  });

  it('drops malformed tokens instead of emitting an empty id half', () => {
    expect(cardLinksFromTokens([':e1', 'a1:', ':', '', 'noseparator'])).toEqual([]);
  });

  it('round-trips objects through tokens and back', () => {
    const links = [
      { asset_id: 'a1', entry_id: 'e1' },
      { asset_id: 'a2', entry_id: 'e2' },
    ];
    expect(cardLinksFromTokens(cardLinkTokens({ card_links: links }))).toEqual(links);
  });
});

describe('profile form round-trip', () => {
  const profile = {
    id: 'p1',
    name: 'Overdue in the garage',
    sync: { entity_id: 'todo.family', two_way: false, vanish_as_completed: true },
    filter: {
      status: 'overdue',
      labels: ['l1'],
      areas: ['a1'],
      devices: ['d1'],
      companions: ['battery_notes'],
      exclude_labels: ['l2'],
      exclude_areas: ['a2'],
      exclude_devices: ['d2'],
      exclude_companions: ['dog_glue'],
      exclude_shopping: true,
    },
  };

  it('flattens a profile for ha-form', () => {
    expect(profileFormData(profile)).toEqual({
      name: 'Overdue in the garage',
      status: 'overdue',
      labels: ['l1'],
      areas: ['a1'],
      devices: ['d1'],
      companions: ['battery_notes'],
      exclude_labels: ['l2'],
      exclude_areas: ['a2'],
      exclude_devices: ['d2'],
      exclude_companions: ['dog_glue'],
      exclude_shopping: true,
    });
  });

  it('shows the shopping switch off for a profile saved before it existed', () => {
    // The form is seeded from this, so a default of `true` here would turn the
    // exclusion on for every old profile the moment someone opened it to rename.
    const older = { ...profile, filter: { ...profile.filter } };
    delete older.filter.exclude_shopping;
    expect(profileFormData(older).exclude_shopping).toBe(false);
  });

  it('leaves the sync block out of the filter form', () => {
    // The sync fields live in their own group, so the filter form must not carry
    // them — an `entity_id` row here would be a second, competing picker.
    const keys = Object.keys(profileFormData(profile));
    expect(keys).not.toContain('sync');
    expect(keys).not.toContain('entity_id');
  });

  it('rebuilds the nested profile, keeping the id', () => {
    expect(profileFormToProfile('p1', profileFormData(profile), profile.sync)).toEqual(profile);
  });

  it("carries the profile's sync block through a filter-only edit", () => {
    // The filter form never renders the sync fields, so a rename that dropped them
    // would silently switch a configured to-do list sync off.
    const renamed = profileFormToProfile('p1', { name: 'Renamed' }, profile.sync);
    expect(renamed.sync).toEqual(profile.sync);
  });

  it('treats a profile with no sync block as sync-off, both switches on', () => {
    // A profile saved before the field existed: the backend normalizer fills these
    // in as on, and reading them as off would flip two-way sync behind the user.
    expect(profileFormToProfile('p1', { name: 'x' }).sync).toEqual({
      entity_id: '',
      two_way: true,
      vanish_as_completed: true,
    });
  });

  it('trims the name and falls back to a default when blank', () => {
    expect(profileFormToProfile('p1', { name: '  Trimmed  ' }).name).toBe('Trimmed');
    for (const blank of ['', '   ', undefined, null]) {
      expect(profileFormToProfile('p1', { name: blank }).name).toBeTruthy();
      expect(profileFormToProfile('p1', { name: blank }).name).not.toBe('undefined');
    }
  });

  it('defaults the status to overdue and coerces list fields to arrays', () => {
    const rebuilt = profileFormToProfile('p1', { name: 'x' });
    expect(rebuilt.filter).toEqual({
      status: 'overdue',
      labels: [],
      areas: [],
      devices: [],
      companions: [],
      exclude_labels: [],
      exclude_areas: [],
      exclude_devices: [],
      exclude_companions: [],
      exclude_shopping: false,
    });
  });

  it('reads exclude_shopping as off unless the switch is on', () => {
    // Off is the default a profile saved before the switch existed must read back
    // as: an inverted or truthy-coerced read here would quietly empty a digest of
    // its buy reminders for every household that never asked.
    for (const value of [undefined, null, false, '', 0]) {
      expect(
        profileFormToProfile('p1', { name: 'x', exclude_shopping: value }).filter
          .exclude_shopping,
      ).toBe(false);
    }
    expect(
      profileFormToProfile('p1', { name: 'x', exclude_shopping: true }).filter
        .exclude_shopping,
    ).toBe(true);
  });

  it('offers the shopping exclusion as a switch, after the id pickers', () => {
    // It excludes by kind, not by id, so it cannot be a picker like its siblings.
    const names = profileSchema().map((f) => f.name);
    expect(names.indexOf('exclude_shopping')).toBe(names.length - 1);
    expect(names.indexOf('exclude_shopping')).toBeGreaterThan(names.indexOf('exclude_devices'));
    const field = profileSchema().find((f) => f.name === 'exclude_shopping');
    expect(field.selector).toEqual({ boolean: {} });
  });

  it('stringifies list members that arrive as non-strings', () => {
    const rebuilt = profileFormToProfile('p1', {
      name: 'x',
      labels: [1, 2],
      areas: 'nope',
      exclude_labels: [3],
      exclude_devices: 'nope',
    });
    expect(rebuilt.filter.labels).toEqual(['1', '2']);
    expect(rebuilt.filter.areas).toEqual([]);
    expect(rebuilt.filter.exclude_labels).toEqual(['3']);
    expect(rebuilt.filter.exclude_devices).toEqual([]);
  });

  it('describes every profile field in the schema', () => {
    // The exclude_* rows follow the include rows, so the form reads as "these, minus
    // these" top to bottom.
    expect(profileSchema().map((f) => f.name)).toEqual([
      'name',
      'status',
      'labels',
      'areas',
      'devices',
      'exclude_labels',
      'exclude_areas',
      'exclude_devices',
      'exclude_shopping',
    ]);
    expect(profileSchema()[0].required).toBe(true);
  });

  it('offers the exclude rows the same multi-pickers as their include twins', () => {
    const by = Object.fromEntries(profileSchema().map((f) => [f.name, f.selector]));
    expect(by.exclude_labels).toEqual(by.labels);
    expect(by.exclude_areas).toEqual(by.areas);
    expect(by.exclude_devices).toEqual(by.devices);
  });
});

describe('taskFormSchemaKey', () => {
  // The panel re-renders the task form when this key moves, and a re-render replaces
  // the field being typed in — focus falls back to `<body>` and Home Assistant's
  // global one-letter shortcuts start swallowing the keystrokes (`d` device search,
  // `a` Assist, `e`/`c` quick bar). So the key must move for exactly the four things
  // that change which fields are on screen, and for nothing else.

  it('is unchanged by an edit to a field that is always on screen', () => {
    const before = taskFormSchemaKey({ recurrence_type: 'floating', interval: 3 });
    for (const edit of [
      { name: 'D' },
      { name: 'Dishwasher descale' },
      { notes: 'under the sink' },
      { interval: 4 },
      { unit: 'weeks' },
      { labels: ['kitchen'] },
      { area_id: 'kitchen' },
      { completion_detail: 'required' },
    ]) {
      expect(
        taskFormSchemaKey({ recurrence_type: 'floating', interval: 3, ...edit }),
        `editing ${Object.keys(edit)[0]} must not move the key`,
      ).toBe(before);
    }
  });

  it('reads a bare new task the same as the values its form seeds', () => {
    // The bug: the form defaults `recurrence_type` to floating and `sensor_mode` to
    // usage, so comparing a *task* that carries neither against the *form values* that
    // carry both made the first keystroke look like a schema change.
    expect(taskFormSchemaKey({})).toBe(
      taskFormSchemaKey({ recurrence_type: 'floating', sensor_mode: 'usage', name: 'D' }),
    );
  });

  it('moves when the recurrence type changes', () => {
    expect(taskFormSchemaKey({ recurrence_type: 'sensor' })).not.toBe(
      taskFormSchemaKey({ recurrence_type: 'floating' }),
    );
    expect(taskFormSchemaKey({ recurrence_type: 'fixed' })).not.toBe(
      taskFormSchemaKey({ recurrence_type: 'floating' }),
    );
  });

  it('moves when the sensor mode changes', () => {
    expect(taskFormSchemaKey({ recurrence_type: 'sensor', sensor_mode: 'threshold' })).not.toBe(
      taskFormSchemaKey({ recurrence_type: 'sensor', sensor_mode: 'usage' }),
    );
  });

  it('moves when the time backstop is switched on', () => {
    const off = taskFormSchemaKey({ recurrence_type: 'sensor', sensor_backstop_on: false });
    expect(taskFormSchemaKey({ recurrence_type: 'sensor', sensor_backstop_on: true })).not.toBe(off);
    // A loaded task carries the backstop as a nested `also_every` rather than the flat
    // switch; both representations have to read the same way.
    expect(
      taskFormSchemaKey({
        recurrence_type: 'sensor',
        sensor: { entity_id: 'sensor.hours', mode: 'usage', also_every: { interval: 6, unit: 'months' } },
      }),
    ).not.toBe(off);
  });

  it('moves when the season is switched on, so its windows appear', () => {
    const off = taskFormSchemaKey({ recurrence_type: 'floating', season_on: false });
    expect(taskFormSchemaKey({ recurrence_type: 'floating', season_on: true })).not.toBe(off);
    // A loaded task carries the season as stored windows rather than the flat switch;
    // both representations have to read the same way.
    expect(
      taskFormSchemaKey({
        recurrence_type: 'floating',
        active_season: [{ start: '04-01', end: '09-30' }],
      }),
    ).not.toBe(off);
  });

  it('moves when a season window is added or removed', () => {
    const one = taskFormSchemaKey({
      recurrence_type: 'floating',
      active_season: [{ start: '04-01', end: '09-30' }],
    });
    expect(
      taskFormSchemaKey({
        recurrence_type: 'floating',
        active_season: [
          { start: '04-01', end: '09-30' },
          { start: '11-01', end: '12-31' },
        ],
      }),
    ).not.toBe(one);
  });

  it("moves when a season month changes, because the day picker's ceiling follows it", () => {
    // February offers 29 days and April 30, so the row has to be rebuilt — otherwise
    // the picker keeps offering a day the month it now names does not have.
    const january = taskFormSchemaKey({
      recurrence_type: 'floating',
      season_on: true,
      season_1_start_month: '1',
    });
    expect(
      taskFormSchemaKey({
        recurrence_type: 'floating',
        season_on: true,
        season_1_start_month: '2',
      }),
    ).not.toBe(january);
    // The day itself doesn't change which fields are on screen, so it must not move it.
    expect(
      taskFormSchemaKey({
        recurrence_type: 'floating',
        season_on: true,
        season_1_start_month: '1',
        season_1_start_day: 17,
      }),
    ).toBe(january);
  });

  it('moves when a state binding swaps between a binary sensor and anything else', () => {
    // State mode offers an on/off picker for a binary sensor and free text for every
    // other entity, so the bound entity decides which control is on screen.
    const base = { recurrence_type: 'sensor', sensor_mode: 'state' };
    const binary = taskFormSchemaKey({ ...base, sensor_entity_id: 'binary_sensor.leak' });
    expect(taskFormSchemaKey({ ...base, sensor_entity_id: 'vacuum.rosie' })).not.toBe(binary);
    // Reading an attribute compares the attribute's value, which is open-ended even on
    // a binary sensor — so that swaps the control back to free text.
    expect(
      taskFormSchemaKey({
        ...base,
        sensor_entity_id: 'binary_sensor.leak',
        sensor_attribute: 'moisture',
      }),
    ).not.toBe(binary);
    // Typing the state itself leaves the control alone.
    expect(
      taskFormSchemaKey({ ...base, sensor_entity_id: 'binary_sensor.leak', sensor_state: 'on' }),
    ).toBe(binary);
  });

  it('moves when the attached device changes, treating cleared and unset alike', () => {
    const none = taskFormSchemaKey({ recurrence_type: 'floating' });
    expect(taskFormSchemaKey({ recurrence_type: 'floating', device_id: null })).toBe(none);
    expect(taskFormSchemaKey({ recurrence_type: 'floating', device_id: undefined })).toBe(none);
    expect(taskFormSchemaKey({ recurrence_type: 'floating', device_id: '' })).toBe(none);
    expect(taskFormSchemaKey({ recurrence_type: 'floating', device_id: 'dev1' })).not.toBe(none);
    expect(taskFormSchemaKey({ recurrence_type: 'floating', device_id: 'dev2' })).not.toBe(
      taskFormSchemaKey({ recurrence_type: 'floating', device_id: 'dev1' }),
    );
  });
});
