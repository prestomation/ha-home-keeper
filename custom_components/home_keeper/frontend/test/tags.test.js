import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../src/api.ts';
import { buildTaskPayload, selSelectCustom, taskFormData, taskSchema } from '../src/forms.ts';
import { setLanguage } from '../src/i18n.ts';
import { scanRequired, tagName } from '../src/utils.ts';

// NFC/RFID tag binding (issue #211). A task can name an HA tag, and can demand
// that scanning that tag is the *only* way it gets completed. The frontend's job
// is to offer the binding, show it, and never send a combination the backend
// would have to reject — a required scan with no tag to scan is a task nobody
// could ever finish.

beforeEach(() => setLanguage('en'));

// `ha-form` nests cadence fields in an unnamed grid, so flatten before naming.
const names = (fields) =>
  fields.flatMap((f) => (f.schema ? names(f.schema) : [f.name])).filter(Boolean);

const TAGS = [
  { value: 'tag_kitchen', label: 'Kitchen sticker' },
  { value: 'a1b2c3', label: 'a1b2c3' },
];

describe('selSelectCustom', () => {
  it('is a dropdown that also accepts a typed value', () => {
    // `custom_value` is the whole point: a tag id printed on a sticker is a valid
    // binding before HA's registry has ever seen that tag.
    expect(selSelectCustom(TAGS)).toEqual({
      select: { mode: 'dropdown', options: TAGS, custom_value: true },
    });
  });

  it('stays a usable typable box with no known tags', () => {
    expect(selSelectCustom([])).toEqual({
      select: { mode: 'dropdown', options: [], custom_value: true },
    });
  });
});

describe('taskSchema tag fields', () => {
  it('offers both tag controls on every task kind, including triggered', () => {
    for (const recurrence_type of ['floating', 'fixed', 'one-off', 'sensor', 'triggered']) {
      const got = names(taskSchema({ recurrence_type }, [], [], TAGS));
      expect(got, recurrence_type).toContain('tag_id');
      expect(got, recurrence_type).toContain('require_tag_scan');
    }
  });

  it('offers the tag picker even when no tags are registered', () => {
    // An empty registry is the *normal* first-time state; hiding the field there
    // would leave no way to bind a brand-new sticker at all.
    const fields = taskSchema({ recurrence_type: 'floating' });
    const got = names(fields);
    expect(got).toContain('tag_id');
    expect(got).toContain('require_tag_scan');
    // And the dropdown is genuinely empty rather than seeded with anything — the
    // typed value is the only binding available until HA sees the tag.
    expect(fields.find((f) => f.name === 'tag_id').selector.select.options).toEqual([]);
  });

  it('threads the live tag list into the picker options', () => {
    const field = taskSchema({ recurrence_type: 'floating' }, [], [], TAGS).find(
      (f) => f.name === 'tag_id',
    );
    expect(field.selector.select.options).toEqual(TAGS);
    expect(field.selector.select.custom_value).toBe(true);
  });

  it('gives the require-scan switch a boolean selector', () => {
    const field = taskSchema({ recurrence_type: 'floating' }, [], [], TAGS).find(
      (f) => f.name === 'require_tag_scan',
    );
    expect(field.selector).toEqual({ boolean: {} });
  });

  it('sits with the other attachment fields, right after the area picker', () => {
    const got = names(taskSchema({ recurrence_type: 'floating' }, [], [], TAGS));
    expect(got.indexOf('tag_id')).toBe(got.indexOf('area_id') + 1);
    expect(got.indexOf('require_tag_scan')).toBe(got.indexOf('tag_id') + 1);
  });

  it('omits tag_id alone when the managing integration locks it', () => {
    const locked = {
      recurrence_type: 'floating',
      managed_by: { integration: 'x', display_name: 'X', locked_fields: ['tag_id'] },
    };
    const got = names(taskSchema(locked, [], [], TAGS));
    expect(got).not.toContain('tag_id');
    // Locking one must not take the other with it.
    expect(got).toContain('require_tag_scan');
    expect(taskSchema(locked, [], [], TAGS).length).toBe(
      taskSchema({ recurrence_type: 'floating' }, [], [], TAGS).length - 1,
    );
  });

  it('omits require_tag_scan alone when it is locked', () => {
    const fields = taskSchema(
      {
        recurrence_type: 'floating',
        managed_by: { integration: 'x', locked_fields: ['require_tag_scan'] },
      },
      [],
      [],
      TAGS,
    );
    const got = names(fields);
    expect(got).not.toContain('require_tag_scan');
    expect(got).toContain('tag_id');
    // Count the raw entries, not the names: a nameless entry would be dropped by
    // `names()`, so only this catches the locked branch contributing anything at
    // all to the schema instead of nothing.
    expect(fields.length).toBe(
      taskSchema({ recurrence_type: 'floating' }, [], [], TAGS).length - 1,
    );
  });

  it('applies the same locking on a triggered task', () => {
    // The triggered branch builds its own short list, so it needs its own proof.
    const fields = taskSchema(
      {
        recurrence_type: 'triggered',
        managed_by: { integration: 'x', locked_fields: ['tag_id', 'require_tag_scan'] },
      },
      [],
      [],
      TAGS,
    );
    const got = names(fields);
    expect(got).not.toContain('tag_id');
    expect(got).not.toContain('require_tag_scan');
    expect(got).toContain('area_id');
    expect(fields.length).toBe(
      taskSchema({ recurrence_type: 'triggered' }, [], [], TAGS).length - 2,
    );
  });
});

describe('taskFormData tag values', () => {
  it('leaves an unbound tag empty rather than blank-selected', () => {
    // `undefined`, not '' or null — ha-form renders a null as a selected "null".
    expect(taskFormData({}).tag_id).toBeUndefined();
    expect(taskFormData({ tag_id: null }).tag_id).toBeUndefined();
  });

  it('defaults require_tag_scan off', () => {
    expect(taskFormData({}).require_tag_scan).toBe(false);
    expect(taskFormData({ require_tag_scan: undefined }).require_tag_scan).toBe(false);
  });

  it('loads a task’s saved binding back into the form', () => {
    const data = taskFormData({ tag_id: 'tag_kitchen', require_tag_scan: true });
    expect(data.tag_id).toBe('tag_kitchen');
    expect(data.require_tag_scan).toBe(true);
  });
});

describe('buildTaskPayload tag binding', () => {
  const base = { name: 'Filter', recurrence_type: 'floating', interval: 1, unit: 'months' };

  it('sends both when a tag is bound and a scan is required', () => {
    const payload = buildTaskPayload({ ...base, tag_id: 'tag_kitchen', require_tag_scan: true });
    expect(payload.tag_id).toBe('tag_kitchen');
    expect(payload.require_tag_scan).toBe(true);
  });

  it('sends a bound tag with the lock off as exactly false', () => {
    const payload = buildTaskPayload({ ...base, tag_id: 'tag_kitchen', require_tag_scan: false });
    expect(payload.tag_id).toBe('tag_kitchen');
    expect(payload.require_tag_scan).toBe(false);
  });

  it('force-clears the lock when the tag is cleared', () => {
    // Otherwise the task demands a scan of a tag it no longer has — uncompletable
    // from every surface, with no control left in the form to undo it.
    for (const tag_id of [undefined, null, '']) {
      const payload = buildTaskPayload({ ...base, tag_id, require_tag_scan: true });
      expect(payload.tag_id, String(tag_id)).toBeNull();
      expect(payload.require_tag_scan, String(tag_id)).toBe(false);
    }
  });

  it('always round-trips the binding, so clearing it actually unbinds', () => {
    // `merge_update` only overwrites keys the payload carries — omitting a cleared
    // tag would silently keep the old one bound.
    const payload = buildTaskPayload(base);
    expect(payload).toHaveProperty('tag_id', null);
    expect(payload).toHaveProperty('require_tag_scan', false);
  });

  it('carries the binding on every task kind', () => {
    for (const recurrence_type of ['floating', 'fixed', 'one-off', 'sensor', 'triggered']) {
      const payload = buildTaskPayload({
        name: 'T',
        recurrence_type,
        tag_id: 'a1b2c3',
        require_tag_scan: true,
      });
      expect(payload.tag_id, recurrence_type).toBe('a1b2c3');
      expect(payload.require_tag_scan, recurrence_type).toBe(true);
    }
  });

  it('round-trips a binding through the form unchanged', () => {
    const task = { id: 't1', ...base, tag_id: 'tag_kitchen', require_tag_scan: true };
    const payload = buildTaskPayload({ ...task, ...taskFormData(task) });
    expect(payload.tag_id).toBe('tag_kitchen');
    expect(payload.require_tag_scan).toBe(true);
  });

  it('coerces a truthy non-boolean lock to a real boolean', () => {
    // ha-form hands back whatever the control produced; the store keeps a boolean.
    const payload = buildTaskPayload({ ...base, tag_id: 'a1b2c3', require_tag_scan: 'yes' });
    expect(payload.require_tag_scan).toBe(true);
  });
});

describe('api.getTags', () => {
  const fakeHass = (list) => {
    const calls = [];
    return {
      calls,
      callWS: vi.fn((msg) => {
        calls.push(msg);
        return Promise.resolve(list);
      }),
    };
  };

  it('asks HA for its tag registry', async () => {
    const hass = fakeHass([]);
    await api.getTags(hass);
    expect(hass.calls[0]).toEqual({ type: 'tag/list' });
  });

  it('maps tags to picker options, naming them where HA does', async () => {
    const hass = fakeHass([
      { id: 'tag_kitchen', name: 'Kitchen sticker' },
      { id: 'a1b2c3' },
      { id: 'blank', name: '' },
      { id: 'nulled', name: null },
    ]);
    // A tag with no name has nothing else to call it by, so the id stands in.
    expect(await api.getTags(hass)).toEqual([
      { value: 'tag_kitchen', label: 'Kitchen sticker' },
      { value: 'a1b2c3', label: 'a1b2c3' },
      { value: 'blank', label: 'blank' },
      { value: 'nulled', label: 'nulled' },
    ]);
  });

  it('yields no options when HA answers with something unusable', async () => {
    // The tag component may not be set up at all; the picker must survive it.
    for (const answer of [undefined, null, {}]) {
      expect(await api.getTags(fakeHass(answer))).toEqual([]);
    }
  });
});

describe('tagName', () => {
  it('names a tag the registry knows', () => {
    expect(tagName(TAGS, 'tag_kitchen')).toBe('Kitchen sticker');
  });

  it('falls back to the raw id for a tag the registry has not got', () => {
    expect(tagName(TAGS, 'unknown_tag')).toBe('unknown_tag');
    expect(tagName([], 'unknown_tag')).toBe('unknown_tag');
    expect(tagName(undefined, 'unknown_tag')).toBe('unknown_tag');
  });

  it('is empty for an unbound tag', () => {
    expect(tagName(TAGS, null)).toBe('');
    expect(tagName(TAGS, undefined)).toBe('');
    expect(tagName(TAGS, '')).toBe('');
  });
});

describe('scanRequired', () => {
  it('is true only with both a bound tag and the lock on', () => {
    expect(scanRequired({ tag_id: 'a1b2c3', require_tag_scan: true })).toBe(true);
    expect(scanRequired({ tag_id: 'a1b2c3', require_tag_scan: false })).toBe(false);
    // The lock without a tag would describe a task nothing could ever complete, so
    // it reads as "not locked" rather than "locked forever".
    expect(scanRequired({ tag_id: null, require_tag_scan: true })).toBe(false);
    expect(scanRequired({ tag_id: null, require_tag_scan: false })).toBe(false);
  });

  it('is false for a task with no tag fields at all', () => {
    expect(scanRequired({})).toBe(false);
  });

  it('returns a real boolean, not a truthy value', () => {
    // Callers put it straight into `a || b` chains and template branches.
    expect(scanRequired({ tag_id: 'a1b2c3', require_tag_scan: 'yes' })).toBe(true);
    expect(scanRequired({ tag_id: '', require_tag_scan: true })).toBe(false);
  });
});
