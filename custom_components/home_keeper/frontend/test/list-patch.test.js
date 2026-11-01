/**
 * The task list keeps the rows that did not change (`panel-list-patch.ts`).
 *
 * The claim is about a whole domain: after any chain of searches, scope changes, group
 * changes and task changes, the patched list holds the DOM that a new draw would hold.
 * The first test checks that on a seeded random chain. The others pin the 3 things that a
 * patch can get wrong while that stays true: a row that is rebuilt although it did not
 * change, a row that is bound twice, and a page that is rebuilt although only the tasks
 * changed.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { definePanelStubs, makeHass, mountPanel } from './panel-harness.js';
import { tasksList } from '../src/panel-lists.ts';
import { adoptPatchedList, isPatchedList, suspendPatchedList } from '../src/panel-list-patch.ts';

vi.mock('../src/panel-styles.ts', () => ({ STYLES: '', TASK_CARD_INLINE_CHIPS: 2 }));

const DAY = 86400000;
const NAMES = ['Clean gutters', 'Replace filter', 'Test alarm', 'Descale kettle', 'Check tires'];

function makeTasks(n) {
  const now = Date.now();
  return Array.from({ length: n }, (_, i) => ({
    id: `t${i}`,
    name: `${NAMES[i % NAMES.length]} ${i}`,
    completions: [],
    enabled: true,
    recurrence_type: 'interval',
    // Spread over overdue, soon and later.
    next_due: new Date(now + ((i % 9) - 3) * 10 * DAY).toISOString(),
  }));
}

/** The markup of a list with the white space between tags taken out. */
const norm = (html) => html.replace(/>\s+</g, '><').trim();
const fresh = (panel) => {
  const box = document.createElement('div');
  box.innerHTML = tasksList(panel);
  return norm(box.innerHTML);
};
/** Where 2 strings first differ, with the text around it, for a failure message. */
const where = (a, b) => {
  let i = 0;
  while (i < a.length && a[i] === b[i]) i++;
  return `at ${i}: drawn "${a.slice(Math.max(0, i - 60), i + 140)}" / new "${b.slice(Math.max(0, i - 60), i + 140)}"`;
};
const drawn = (panel) => norm(panel.shadowRoot.getElementById('hk-list').innerHTML);

/** A small seeded generator, so a failure repeats. */
function rng(seed) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
}

beforeAll(definePanelStubs);
beforeEach(() => localStorage.clear());
afterEach(() => {
  document.body.innerHTML = '';
  localStorage.clear();
});

async function mount(tasks) {
  const { panel } = await mountPanel('/tasks', makeHass({ tasks }));
  return panel;
}

describe('a patched list equals a new draw', () => {
  it('after a seeded chain of searches, scopes, groups and task changes', async () => {
    const panel = await mount(makeTasks(40));
    const rand = rng(7);
    const pick = (a) => a[Math.floor(rand() * a.length)];
    const steps = [];
    for (let i = 0; i < 60; i++) {
      const op = pick(['query', 'query', 'query', 'group', 'filter', 'rename', 'remove', 'add', 'due']);
      steps.push(op);
      if (op === 'query') panel._setQuery(pick(['', 'c', 'cl', 'zzz', 'alarm 2', 'replace', '1', '']));
      else if (op === 'group') panel._setGroupBy(pick(['status', 'none', 'area']));
      else if (op === 'filter') panel._setFilter(pick(['all', 'overdue', 'soon']));
      else {
        const tasks = [...panel._tasks];
        const k = Math.floor(rand() * tasks.length);
        if (op === 'rename' && tasks[k]) tasks[k] = { ...tasks[k], name: `${pick(NAMES)} ${i}` };
        else if (op === 'remove' && tasks.length > 5) tasks.splice(k, 1);
        else if (op === 'add') tasks.push(makeTasks(1).map((x) => ({ ...x, id: `n${i}`, name: `New ${i}` }))[0]);
        else if (op === 'due' && tasks[k]) {
          tasks[k] = { ...tasks[k], next_due: new Date(Date.now() + (k % 7) * 20 * DAY - 40 * DAY).toISOString() };
        }
        panel._tasks = tasks;
        panel._render();
      }
      const [a, b] = [drawn(panel), fresh(panel)];
      expect(a === b, `after step ${i} (${steps.join(',')}) ${where(a, b)}`).toBe(true);
    }
  });
});

describe('a row that did not change is kept', () => {
  it('keeps its element through a search and back', async () => {
    const panel = await mount(makeTasks(12));
    const row = () => panel.shadowRoot.querySelector('.hk-card[data-id="t1"]');
    const first = row();
    expect(first).toBeTruthy();
    panel._setQuery('gutters');
    expect(row(), 'a search that skips the row takes it out').toBeNull();
    panel._setQuery('');
    expect(row(), 'it comes back as the same element').toBe(first);
  });

  it('keeps its element through a search that matches nothing', async () => {
    const panel = await mount(makeTasks(12));
    const first = panel.shadowRoot.querySelector('.hk-card[data-id="t1"]');
    panel._setQuery('zzz');
    expect(panel.shadowRoot.querySelector('.hk-card')).toBeNull();
    expect(panel.shadowRoot.querySelector('#hk-show-all'), 'the way out is there').toBeTruthy();
    panel._setQuery('');
    expect(panel.shadowRoot.querySelector('.hk-card[data-id="t1"]')).toBe(first);
  });

  it('keeps its element through a render, and builds the one that changed', async () => {
    const panel = await mount(makeTasks(12));
    const q = (id) => panel.shadowRoot.querySelector(`.hk-card[data-id="${id}"]`);
    const [a, b] = [q('t1'), q('t2')];
    panel._tasks = panel._tasks.map((x) => (x.id === 't2' ? { ...x, name: 'Renamed task' } : x));
    panel._render();
    expect(q('t1')).toBe(a);
    expect(q('t2')).not.toBe(b);
    expect(q('t2').textContent).toContain('Renamed task');
  });

  it('keeps the page around the list when only the tasks change', async () => {
    const panel = await mount(makeTasks(12));
    const bar = panel.shadowRoot.querySelector('.hk-toolbar');
    const search = panel.shadowRoot.querySelector('.hk-search-input');
    panel._tasks = panel._tasks.filter((x) => x.id !== 't3');
    panel._render();
    expect(panel.shadowRoot.querySelector('.hk-toolbar')).toBe(bar);
    expect(panel.shadowRoot.querySelector('.hk-search-input')).toBe(search);
    expect(panel.shadowRoot.querySelector('.hk-card[data-id="t3"]')).toBeNull();
  });

  it('draws the page again when more than the tasks changed', async () => {
    const panel = await mount(makeTasks(12));
    const bar = panel.shadowRoot.querySelector('.hk-toolbar');
    panel._setGroupBy('none');
    expect(panel.shadowRoot.querySelector('.hk-toolbar')).not.toBe(bar);
  });

  it('writes the new pill counts into the page that it keeps', async () => {
    const panel = await mount(makeTasks(12));
    const count = () => panel.shadowRoot.querySelector('.hk-seg-btn[data-seg-val="all"] .hk-seg-count').textContent;
    expect(count()).toBe('12');
    panel._tasks = panel._tasks.slice(0, 7);
    panel._render();
    expect(count()).toBe('7');
  });
});

describe('a row is bound once', () => {
  it('completes a task once after a render that kept its row', async () => {
    const panel = await mount(makeTasks(6));
    const complete = vi.spyOn(panel, '_complete').mockResolvedValue(undefined);
    for (let i = 0; i < 3; i++) {
      panel._tasks = [...panel._tasks];
      panel._render();
    }
    panel._setQuery('');
    panel.shadowRoot.querySelector('.hk-card[data-id="t1"] .done-btn').click();
    expect(complete).toHaveBeenCalledTimes(1);
  });

  it('opens a task once after a search that parked and restored its row', async () => {
    const panel = await mount(makeTasks(6));
    const open = vi.spyOn(panel, '_openDetail').mockImplementation(() => {});
    panel._setQuery('zzz');
    panel._setQuery('');
    panel.shadowRoot.querySelector('.hk-card[data-id="t1"] .detail-open').click();
    expect(open).toHaveBeenCalledTimes(1);
  });
});

describe('a task that is gone is not kept', () => {
  it('drops a parked row when its task is deleted', async () => {
    const panel = await mount(makeTasks(6));
    panel._setQuery('zzz');
    panel._tasks = panel._tasks.filter((x) => x.id !== 't1');
    panel._setQuery('');
    expect(panel.shadowRoot.querySelector('.hk-card[data-id="t1"]')).toBeNull();
    expect(drawn(panel)).toBe(fresh(panel));
  });
});

describe('the groups and the head follow the tasks', () => {
  const section = (panel, key) => panel.shadowRoot.querySelector(`details[data-group-key="${key}"]`);

  it('updates a group count in the section that it keeps', async () => {
    const panel = await mount(makeTasks(12));
    const key = 'status:overdue';
    const kept = section(panel, key);
    const was = Number(kept.querySelector('.hk-group-count').textContent);
    const gone = panel._tasks.find((x) => kept.contains(panel.shadowRoot.querySelector(`.hk-card[data-id="${x.id}"]`)));
    panel._tasks = panel._tasks.filter((x) => x.id !== gone.id);
    panel._render();
    expect(section(panel, key)).toBe(kept);
    expect(kept.querySelector('.hk-group-count').textContent).toBe(String(was - 1));
  });

  it('opens and shuts a kept section from the collapse memory, and a search opens it', async () => {
    const panel = await mount(makeTasks(12));
    const key = 'status:overdue';
    const kept = section(panel, key);
    expect(kept.open).toBe(true);
    panel._collapsed.add(key);
    panel._tasks = [...panel._tasks];
    panel._render();
    expect(section(panel, key)).toBe(kept);
    expect(kept.open).toBe(false);
    panel._setQuery('a');
    expect(kept.open, 'a search opens every section').toBe(true);
    panel._setQuery('');
    expect(kept.open).toBe(false);
  });

  it('moves a row to the section of its new status and drops a section that is empty', async () => {
    const panel = await mount(makeTasks(12));
    const keys = () => [...panel.shadowRoot.querySelectorAll('details.hk-group')].map((d) => d.dataset.groupKey);
    const before = keys();
    panel._tasks = panel._tasks.map((x) => ({ ...x, next_due: new Date(Date.now() + 90 * DAY).toISOString() }));
    panel._render();
    expect(keys()).not.toEqual(before);
    expect(keys().some((k) => k === 'status:overdue')).toBe(false);
    panel._setGroupBy('none');
    expect(panel.shadowRoot.querySelector('details.hk-group')).toBeNull();
    expect(panel.shadowRoot.querySelectorAll('#hk-list > .hk-card').length).toBe(12);
    panel._setGroupBy('status');
    expect(panel.shadowRoot.querySelectorAll('#hk-list > .hk-card').length).toBe(0);
  });

  it('builds the head again when its markup changes, and keeps the rows', async () => {
    const panel = await mount(makeTasks(12));
    const row = panel.shadowRoot.querySelector('.hk-card[data-id="t1"]');
    panel._introDismissed = false;
    panel._tasks = [...panel._tasks];
    panel._render();
    expect(panel.shadowRoot.querySelector('#hk-list .hk-intro')).toBeTruthy();
    expect(panel.shadowRoot.querySelector('.hk-card[data-id="t1"]')).toBe(row);
    panel._introDismissed = true;
    panel._tasks = [...panel._tasks];
    panel._render();
    expect(panel.shadowRoot.querySelector('#hk-list .hk-intro')).toBeNull();
    expect(drawn(panel)).toBe(fresh(panel));
  });
});

describe('adopting and suspending a list', () => {
  it('adopts only a list that the patch built', async () => {
    const panel = await mount(makeTasks(4));
    const list = panel.shadowRoot.getElementById('hk-list');
    expect(isPatchedList(list)).toBe(true);
    const spot = document.createElement('div');
    const plain = document.createElement('div');
    document.body.append(spot);
    expect(adoptPatchedList(null, spot)).toBe(false);
    expect(adoptPatchedList(plain, spot)).toBe(false);
    expect(spot.isConnected).toBe(true);
    expect(adoptPatchedList(list, spot)).toBe(true);
    expect(spot.isConnected).toBe(false);
    expect(list.isConnected).toBe(true);
  });

  it('keeps the rows of a list that shows the empty message', async () => {
    const panel = await mount(makeTasks(4));
    const list = panel.shadowRoot.getElementById('hk-list');
    const row = list.querySelector('.hk-card[data-id="t1"]');
    suspendPatchedList(document.createElement('div'));
    panel._setQuery('zzz');
    expect(list.querySelector('.hk-card')).toBeNull();
    panel._setQuery('');
    expect(list.querySelector('.hk-card[data-id="t1"]')).toBe(row);
    expect(drawn(panel)).toBe(fresh(panel));
  });
});
