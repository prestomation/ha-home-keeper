import { afterEach, describe, expect, it } from 'vitest';
import {
  mergePartForm,
  partDependentSchema,
  partFormData,
  partPreview,
  partSchema,
} from '../src/forms.ts';
import { setLanguage } from '../src/i18n.ts';

afterEach(() => setLanguage('en'));

const TAGS = [
  { value: 'anode-tag', label: 'Anode rod' },
  { value: 'jacket-tag', label: 'Rain jacket' },
];

/** A wear part, as `partFormData`/`mergePartForm` leave one. */
function wear(overrides = {}) {
  return {
    id: 'p1',
    name: 'Anode rod',
    type: 'wear',
    replace_interval: 12,
    replace_unit: 'months',
    action: 'replace',
    ...overrides,
  };
}

/** Its counted cousin. */
function counted(overrides = {}) {
  return wear({ name: 'DWR coating', replace_interval: 25, replace_unit: 'uses', ...overrides });
}

const names = (fields) => fields.map((f) => f.name);
const field = (fields, name) => fields.find((f) => f.name === name);
const texts = (part, asset = 'Heater') => partPreview(part, asset).lines.map((l) => l.text);

describe('the part editor offers the NFC/RFID binding', () => {
  it('adds the tag picker and the scan toggle, in that order, at the foot of a wear item', () => {
    const got = names(partDependentSchema(wear(), TAGS));
    expect(got.slice(-3)).toEqual(['last_replaced', 'part_tag_id', 'part_require_tag_scan']);
  });

  it('offers them to a wear item that has no interval yet', () => {
    // The unit is chosen before the target is typed; the binding is the same field
    // either way, so hiding it until the interval exists would only make it jump in.
    const got = names(partDependentSchema(wear({ replace_interval: null }), TAGS));
    expect(got).toContain('part_tag_id');
    expect(got).toContain('part_require_tag_scan');
  });

  it('offers them to a counted wear item too', () => {
    const got = names(partDependentSchema(counted(), TAGS));
    expect(got.slice(-2)).toEqual(['part_tag_id', 'part_require_tag_scan']);
  });

  it('never offers them to a consumable', () => {
    const got = names(partDependentSchema({ id: 'p2', name: 'Bulb', type: 'consumable' }, TAGS));
    expect(got).not.toContain('part_tag_id');
    expect(got).not.toContain('part_require_tag_scan');
  });

  it('lists the registry tags and lets an id be typed', () => {
    const picker = field(partDependentSchema(wear(), TAGS), 'part_tag_id');
    expect(picker.selector).toEqual({
      select: { mode: 'dropdown', options: TAGS, custom_value: true },
    });
  });

  it('still offers the picker with an empty registry', () => {
    // The sticker's id can be typed straight off it before HA has ever seen it.
    const picker = field(partDependentSchema(wear()), 'part_tag_id');
    expect(picker.selector.select.options).toEqual([]);
    expect(picker.selector.select.custom_value).toBe(true);
  });

  it('draws the scan requirement as a switch', () => {
    const toggle = field(partDependentSchema(wear(), TAGS), 'part_require_tag_scan');
    expect(toggle.selector).toEqual({ boolean: {} });
  });

  it('is part of the flat schema as well', () => {
    const flat = partSchema(wear(), TAGS);
    expect(field(flat, 'part_tag_id').selector.select.options).toEqual(TAGS);
    expect(names(flat).slice(-2)).toEqual(['part_tag_id', 'part_require_tag_scan']);
  });
});

describe('the binding round-trips through the form data', () => {
  it('seeds an unbound part as an empty picker and an off switch', () => {
    const data = partFormData(wear());
    expect(data.part_tag_id).toBeUndefined();
    expect(data.part_require_tag_scan).toBe(false);
  });

  it('seeds a stored null tag the same way', () => {
    expect(partFormData(wear({ tag_id: null })).part_tag_id).toBeUndefined();
  });

  it('seeds a bound part with its tag and its flag', () => {
    const data = partFormData(wear({ tag_id: 'anode-tag', require_tag_scan: true }));
    expect(data.part_tag_id).toBe('anode-tag');
    expect(data.part_require_tag_scan).toBe(true);
  });

  it('writes a picked tag onto the part', () => {
    expect(mergePartForm(wear(), { part_tag_id: 'anode-tag' }).tag_id).toBe('anode-tag');
  });

  it('trims a typed id', () => {
    expect(mergePartForm(wear(), { part_tag_id: '  anode-tag ' }).tag_id).toBe('anode-tag');
  });

  it('stores an emptied picker as null, not as an empty string', () => {
    const next = mergePartForm(wear({ tag_id: 'anode-tag' }), { part_tag_id: '' });
    expect(next.tag_id).toBeNull();
  });

  it('writes the switch onto the part beside a tag', () => {
    const next = mergePartForm(wear({ tag_id: 'anode-tag' }), { part_require_tag_scan: true });
    expect(next.require_tag_scan).toBe(true);
  });

  it('turns the switch back off', () => {
    const next = mergePartForm(wear({ tag_id: 'anode-tag', require_tag_scan: true }), {
      part_require_tag_scan: false,
    });
    expect(next.require_tag_scan).toBe(false);
  });

  it('clears the flag when the tag is cleared', () => {
    // The backend refuses the pair, and would fail the whole appliance save over it.
    const next = mergePartForm(wear({ tag_id: 'anode-tag', require_tag_scan: true }), {
      part_tag_id: '',
    });
    expect(next.tag_id).toBeNull();
    expect(next.require_tag_scan).toBe(false);
  });

  it('never keeps the flag on a part with no tag', () => {
    const next = mergePartForm(wear(), { part_require_tag_scan: true });
    expect(next.require_tag_scan).toBe(false);
  });

  it('leaves the binding alone when the other form emits', () => {
    // Each of a part's 2 forms emits only its own fields; an absent key is not a clear.
    const prev = wear({ tag_id: 'anode-tag', require_tag_scan: true });
    const next = mergePartForm(prev, { vendor: 'Rheem' });
    expect(next.tag_id).toBe('anode-tag');
    expect(next.require_tag_scan).toBe(true);
  });

  it('clears the binding when the part becomes a consumable', () => {
    // A consumable's form hides the tag fields, so a kept tag could not be seen or cleared.
    const prev = wear({ tag_id: 'anode-tag', require_tag_scan: true });
    const next = mergePartForm(prev, { type: 'consumable' });
    expect(next.tag_id).toBeNull();
    expect(next.require_tag_scan).toBe(false);
  });
});

describe('the preview says what a scan does', () => {
  it('says nothing about tags for an unbound part', () => {
    const lines = texts(wear());
    expect(lines.join(' ')).not.toMatch(/tag/i);
  });

  it('says a scan completes a time-measured task, after its schedule', () => {
    expect(texts(wear({ tag_id: 'anode-tag' }))).toEqual([
      'Replace Anode rod (Heater)',
      'Due every 12 months.',
      'A tag scan completes it.',
    ]);
  });

  it('adds that Done waits for the scan when the part demands one', () => {
    const lines = texts(wear({ tag_id: 'anode-tag', require_tag_scan: true }));
    expect(lines.slice(-2)).toEqual([
      'A tag scan completes it.',
      'Done is blocked until the tag is scanned.',
    ]);
  });

  it('does not mention a blocked Done when the part only carries a tag', () => {
    expect(texts(wear({ tag_id: 'anode-tag' }))).not.toContain(
      'Done is blocked until the tag is scanned.',
    );
  });

  it('puts a counted part’s scan line under the use task, not the maintenance one', () => {
    expect(texts(counted({ tag_id: 'jacket-tag', require_tag_scan: true }), 'Rain jacket')).toEqual([
      'Use Rain jacket',
      'Each completion adds 1 to the count.',
      'A tag scan counts 1 use.',
      'Done is blocked until the tag is scanned.',
      'Replace DWR coating (Rain jacket)',
      'Due after 25 uses.',
    ]);
  });

  it('marks the tag lines as facts, not task names', () => {
    const kinds = partPreview(wear({ tag_id: 'anode-tag', require_tag_scan: true }), 'Heater').lines.map(
      (l) => l.kind,
    );
    expect(kinds).toEqual(['task', 'fact', 'fact', 'fact']);
  });

  it('says nothing for a consumable, tag or not', () => {
    const preview = partPreview({ id: 'p2', name: 'Bulb', type: 'consumable', tag_id: 'x' }, 'Lamp');
    expect(preview.lines).toEqual([]);
  });

  it('translates the scan lines', () => {
    setLanguage('de');
    expect(texts(wear({ tag_id: 'anode-tag' }))).toContain('Ein Scan des Tags schließt sie ab.');
  });
});
