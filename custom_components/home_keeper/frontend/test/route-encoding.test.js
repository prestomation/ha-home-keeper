import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { buildPath, parseRoute, ASSET_TABS, TASK_TABS } from '../src/utils.ts';

/**
 * A panel URL goes through the browser before the panel reads it again: `pushState`
 * parses it as a URL, and Home Assistant gives the panel `location.pathname`, which
 * is percent-encoded and has no `.` or `..` segment. These tests send each path through
 * the same URL parser, so a round trip that works only on paper fails here.
 */
const PREFIX = '/home-keeper';

/** The route path that the panel gets back after the browser opens *path*. */
function viaBrowser(path) {
  const url = new URL(`${PREFIX}${path}`, 'http://hass.local');
  return url.pathname.slice(PREFIX.length);
}

const roundTrip = (loc) => parseRoute(viaBrowser(buildPath(loc)));

describe('route encoding: odd characters and odd ids', () => {
  it('keeps a companion tab path with a letter outside ASCII', () => {
    const loc = { view: 'tab', detail: null, tab: 'garden', path: '/café' };
    expect(roundTrip(loc)).toEqual(loc);
  });

  it('keeps a tab path segment with a percent sign or a space', () => {
    const loc = { view: 'tab', detail: null, tab: 'garden', path: '/50%off/a b' };
    expect(roundTrip(loc)).toEqual(loc);
  });

  it('keeps a part id that is a dot segment', () => {
    for (const part of ['.', '..']) {
      const loc = { view: 'appliances', detail: { kind: 'asset', id: 'A1', tab: 'parts', part } };
      expect(roundTrip(loc)).toEqual(loc);
    }
  });

  it('keeps task and appliance ids that are dot segments', () => {
    for (const id of ['.', '..']) {
      const task = { view: 'tasks', detail: { kind: 'task', id, tab: 'schedule' } };
      expect(roundTrip(task)).toEqual(task);
      const asset = { view: 'appliances', detail: { kind: 'asset', id, tab: 'parts' } };
      expect(roundTrip(asset)).toEqual(asset);
    }
  });

  it('keeps an id that starts with the escape mark', () => {
    for (const id of ['~', '~.', '~..', '~~..']) {
      const loc = { view: 'tasks', detail: { kind: 'task', id, tab: 'schedule' } };
      expect(roundTrip(loc)).toEqual(loc);
    }
  });

  it('opens an appliance whose id is the word "parts", not the parts overview', () => {
    const loc = { view: 'appliances', detail: { kind: 'asset', id: 'parts', tab: 'parts' } };
    expect(roundTrip(loc)).toEqual(loc);
    const part = { ...loc, detail: { ...loc.detail, part: 'p1' } };
    expect(roundTrip(part)).toEqual(part);
    // The overview itself stays where it was.
    expect(buildPath({ view: 'appliances', detail: null, parts: true })).toBe('/appliances/parts');
    expect(parseRoute('/appliances/parts')).toEqual({ view: 'appliances', detail: null, parts: true });
  });

  it('keeps ids that look like other routes or sub-tabs', () => {
    for (const id of ['tasks', 'settings', 'appliances', 'history', 'notes', 'documents']) {
      const task = { view: 'tasks', detail: { kind: 'task', id, tab: 'schedule' } };
      expect(roundTrip(task)).toEqual(task);
      const asset = { view: 'appliances', detail: { kind: 'asset', id, tab: 'parts' } };
      expect(roundTrip(asset)).toEqual(asset);
    }
  });

  it('reads the old links the same as before', () => {
    expect(parseRoute('/tasks/abc%20d')).toEqual({
      view: 'tasks',
      detail: { kind: 'task', id: 'abc d', tab: 'schedule' },
    });
    expect(parseRoute('/appliances/a~b/parts/p~q').detail).toEqual({
      kind: 'asset',
      id: 'a~b',
      tab: 'parts',
      part: 'p~q',
    });
    expect(parseRoute('/garden/a/b')).toEqual({ view: 'tab', detail: null, tab: 'garden', path: '/a/b' });
  });
});

// Ids are any non-empty text. An empty id has no URL of its own.
const id = fc.string({ minLength: 1, maxLength: 12, unit: 'grapheme-composite' });
const segment = fc
  .oneof(fc.string({ minLength: 1, maxLength: 8, unit: 'grapheme-composite' }), fc.constantFrom('.', '..', '~..'))
  .filter((s) => !/[/\\?#]/.test(s) && s !== '.' && s !== '..');

const location = fc.oneof(
  fc.record({
    view: fc.constant('tasks'),
    detail: fc.record({ kind: fc.constant('task'), id, tab: fc.constantFrom(...TASK_TABS) }),
  }),
  fc.record({
    view: fc.constant('appliances'),
    detail: fc.record({ kind: fc.constant('asset'), id, tab: fc.constantFrom(...ASSET_TABS) }),
  }),
  fc.record({
    view: fc.constant('appliances'),
    detail: fc.record({ kind: fc.constant('asset'), id, tab: fc.constant('parts'), part: id }),
  }),
  fc.record({
    view: fc.constant('tab'),
    detail: fc.constant(null),
    tab: fc.constantFrom('garden', 'pool-care'),
    path: fc.array(segment, { maxLength: 3 }).map((s) => (s.length ? `/${s.join('/')}` : '')),
  }),
);

describe('route encoding: property', () => {
  it('gives back the same location after a trip through the browser', () => {
    fc.assert(
      fc.property(location, (loc) => {
        expect(roundTrip(loc)).toEqual(loc);
      }),
    );
  });

  it('gives a path that the browser does not change', () => {
    fc.assert(
      fc.property(location, (loc) => {
        const path = buildPath(loc);
        expect(viaBrowser(path)).toBe(path);
      }),
    );
  });
});
