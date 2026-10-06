import { describe, expect, it } from 'vitest';
import {
  PANEL_HOST_API,
  PANEL_TAB_ID_RE,
  RESERVED_TAB_IDS,
  buildPath,
  normalizeTabPath,
  panelSubPath,
  parseRoute,
  visiblePanelTabs,
} from '../src/utils';

describe('normalizeTabPath', () => {
  it('gives the empty string for the tab root', () => {
    for (const p of ['', '/', '//', undefined, null, '/./', '/../..', '?q=1', '#x']) {
      expect(normalizeTabPath(p)).toBe('');
    }
  });
  it('keeps the segments with one leading slash and no trailing slash', () => {
    expect(normalizeTabPath('/a/b')).toBe('/a/b');
    expect(normalizeTabPath('a/b/')).toBe('/a/b');
    expect(normalizeTabPath('//a//b')).toBe('/a/b');
    expect(normalizeTabPath('/sub')).toBe('/sub');
  });
  it('removes dot segments, so a path can never leave the tab', () => {
    expect(normalizeTabPath('/../../config')).toBe('/config');
    expect(normalizeTabPath('/a/./b/../c')).toBe('/a/b/c');
    expect(normalizeTabPath('/a..b/.c')).toBe('/a..b/.c');
  });
  it('reads a backslash as a slash', () => {
    expect(normalizeTabPath('\\\\evil\\x')).toBe('/evil/x');
  });
  it('cuts off a query and a fragment', () => {
    expect(normalizeTabPath('/a/b?x=/c#d')).toBe('/a/b');
    expect(normalizeTabPath('/a#b/c')).toBe('/a');
  });
  it('keeps percent-encoded text as it is', () => {
    expect(normalizeTabPath('/a%2Fb/c%20d')).toBe('/a%2Fb/c%20d');
  });
});

describe('a companion tab location', () => {
  it('keeps an unknown first segment that has the shape of a tab id', () => {
    expect(parseRoute('/demo-tab/x')).toEqual({
      view: 'tab',
      detail: null,
      tab: 'demo-tab',
      path: '/x',
    });
    expect(parseRoute('/library')).toEqual({
      view: 'tab',
      detail: null,
      tab: 'library',
      path: '',
    });
    expect(parseRoute('library/a/b/')).toEqual({
      view: 'tab',
      detail: null,
      tab: 'library',
      path: '/a/b',
    });
  });
  it('reads the rest after leading slashes and spaces', () => {
    expect(parseRoute(' //library/books/12')).toEqual({
      view: 'tab',
      detail: null,
      tab: 'library',
      path: '/books/12',
    });
  });
  it('keeps the rest of the path normalized', () => {
    expect(parseRoute('/library/../tasks').path).toBe('/tasks');
    expect(parseRoute('/library//a').path).toBe('/a');
  });
  it('never reads a reserved segment as a tab', () => {
    expect(parseRoute('/tasks').view).toBe('tasks');
    expect(parseRoute('/appliances').view).toBe('appliances');
    expect(parseRoute('/settings').view).toBe('settings');
    expect([...RESERVED_TAB_IDS].slice(0, 3)).toEqual(['tasks', 'appliances', 'settings']);
  });
  it('keeps a reserved segment for a later page out of the tabs', () => {
    for (const id of ['apps', 'more', 'companions', 'search', 'help', 'dashboard', 'overview']) {
      expect(parseRoute(`/${id}`).view).toBe('tasks');
      expect(parseRoute(`/${id}/x`).tab).toBeUndefined();
    }
    expect(RESERVED_TAB_IDS).toContain('profiles');
    expect(RESERVED_TAB_IDS).toContain('notifications');
    expect(RESERVED_TAB_IDS).toContain('history');
    expect(RESERVED_TAB_IDS).toContain('calendar');
    expect(RESERVED_TAB_IDS).toHaveLength(14);
  });
  it('builds the path of a tab location', () => {
    expect(buildPath({ view: 'tab', detail: null, tab: 'library', path: '/a/b' })).toBe(
      '/library/a/b',
    );
    expect(buildPath({ view: 'tab', detail: null, tab: 'library', path: '' })).toBe('/library');
    expect(buildPath({ view: 'tab', detail: null, tab: 'library' })).toBe('/library');
    expect(buildPath({ view: 'tab', detail: null, tab: 'library', path: 'x/../../y' })).toBe(
      '/library/x/y',
    );
    expect(buildPath({ view: 'tab', detail: null })).toBe('/');
  });
  it('round-trips with parseRoute', () => {
    const locs = [
      { view: 'tab', detail: null, tab: 'library', path: '' },
      { view: 'tab', detail: null, tab: 'library', path: '/books' },
      { view: 'tab', detail: null, tab: 'demo-tab', path: '/x/y%20z' },
    ];
    for (const loc of locs) expect(parseRoute(buildPath(loc))).toEqual(loc);
  });
});

describe('the tab id pattern and the host API version', () => {
  it('accepts an id of 2 to 31 characters that starts with a letter', () => {
    for (const id of ['ab', 'library', 'demo-tab', 'a1', 'a'.repeat(31)]) {
      expect(PANEL_TAB_ID_RE.test(id)).toBe(true);
    }
    for (const id of ['a', 'A1', '1a', '-a', 'a_b', 'a'.repeat(32), 'a b', 'a.b']) {
      expect(PANEL_TAB_ID_RE.test(id)).toBe(false);
    }
  });
  it('is version 1', () => {
    expect(PANEL_HOST_API).toBe(1);
  });
});

describe('visiblePanelTabs', () => {
  const tab = (id, title, order = 100) => ({ id, title, order });
  it('sorts by order, then by title without case, then by id', () => {
    const tabs = [
      tab('zeta', 'Same'),
      tab('alpha', 'Same'),
      tab('b', 'books'),
      tab('first', 'Zebra', 10),
      tab('late', 'Apple', 200),
      tab('c', 'Books'),
    ];
    expect(visiblePanelTabs(tabs, []).map((t) => t.id)).toEqual([
      'first',
      'b',
      'c',
      'alpha',
      'zeta',
      'late',
    ]);
  });
  it('sorts equal ids last on a full tie', () => {
    const tabs = [tab('b', 'X'), tab('a', 'X'), tab('a', 'X')];
    expect(visiblePanelTabs(tabs, []).map((t) => t.id)).toEqual(['a', 'a', 'b']);
  });
  it('leaves out the hidden tabs', () => {
    const tabs = [tab('library', 'Library'), tab('garden', 'Garden')];
    expect(visiblePanelTabs(tabs, ['library']).map((t) => t.id)).toEqual(['garden']);
    expect(visiblePanelTabs(tabs, null).map((t) => t.id)).toEqual(['garden', 'library']);
    expect(visiblePanelTabs(tabs, undefined)).toHaveLength(2);
  });
  it('does not change the list it gets', () => {
    const tabs = [tab('b', 'B'), tab('a', 'A')];
    visiblePanelTabs(tabs, []);
    expect(tabs.map((t) => t.id)).toEqual(['b', 'a']);
  });
});

describe('panelSubPath', () => {
  const O = 'http://ha.local:8123';
  const P = '/home-keeper';
  it('gives the route after the panel prefix for a link on this origin', () => {
    expect(panelSubPath('/home-keeper/tasks/t1', O, P)).toBe('/tasks/t1');
    expect(panelSubPath(`${O}/home-keeper/demo-tab/x?y=1#z`, O, P)).toBe('/demo-tab/x');
    expect(panelSubPath('/home-keeper', O, P)).toBe('');
    expect(panelSubPath('/home-keeper/', O, P)).toBe('/');
  });
  it('gives null for a link outside the panel', () => {
    expect(panelSubPath('/home-keeper-e2e/card', O, P)).toBeNull();
    expect(panelSubPath('/config/integrations', O, P)).toBeNull();
    expect(panelSubPath('https://evil.example/home-keeper/tasks', O, P)).toBeNull();
    expect(panelSubPath('//evil.example/home-keeper/tasks', O, P)).toBeNull();
    expect(panelSubPath('http://[bad', O, P)).toBeNull();
  });
  it('resolves a relative link against the origin', () => {
    expect(panelSubPath('home-keeper/appliances', O, P)).toBe('/appliances');
  });
});
