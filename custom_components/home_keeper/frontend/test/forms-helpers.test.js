import { beforeEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_BACKSTOP_INTERVAL,
  backstopEnabled,
  cardLinkTokens,
  cardLinksFromTokens,
  consumableLinkToken,
  haDateTimeToIso,
  isoToHaDateTime,
  profileFormData,
  profileFormToProfile,
  profileSchema,
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
    filter: { status: 'overdue', labels: ['l1'], areas: ['a1'], devices: ['d1'] },
  };

  it('flattens a profile for ha-form', () => {
    expect(profileFormData(profile)).toEqual({
      name: 'Overdue in the garage',
      status: 'overdue',
      labels: ['l1'],
      areas: ['a1'],
      devices: ['d1'],
    });
  });

  it('rebuilds the nested profile, keeping the id', () => {
    expect(profileFormToProfile('p1', profileFormData(profile))).toEqual(profile);
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
    });
  });

  it('stringifies list members that arrive as non-strings', () => {
    const rebuilt = profileFormToProfile('p1', { name: 'x', labels: [1, 2], areas: 'nope' });
    expect(rebuilt.filter.labels).toEqual(['1', '2']);
    expect(rebuilt.filter.areas).toEqual([]);
  });

  it('describes every profile field in the schema', () => {
    expect(profileSchema().map((f) => f.name)).toEqual([
      'name',
      'status',
      'labels',
      'areas',
      'devices',
    ]);
    expect(profileSchema()[0].required).toBe(true);
  });
});
