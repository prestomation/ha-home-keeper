import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { scopeMatches } from '../src/panel-controls.ts';
import { groupTasks, statusBucket } from '../src/card-filter.ts';
import { definePanelStubs, waitFor } from './panel-harness.js';

/**
 * A switched-off task in the panel (issue #344).
 *
 * `enabled` is a stored field every schedule surface already honoured — the to-do
 * list, the calendar, the per-task entities, the profiles, the announcements — and
 * nothing a user could reach ever wrote it. It ships as a field on
 * `home_keeper.update_task`, so an automation can follow a helper: a pool's tasks
 * go off when the pool closes and come back when it opens.
 *
 * The panel never reads it, which is what these tests are about. Switching a task
 * off does **not** move `next_due`, so the stored date keeps ageing against a task
 * that announces nothing and holds no entities. Left alone, a pool task switched off
 * in October sits in the Overdue pill all winter, counting past a hundred days late,
 * above work nobody can do.
 *
 * So the pills drop it and All keeps it. All keeping it is the load-bearing half:
 * the panel offers no way to switch a task off, so a service call aimed at the wrong
 * task would stranded it with no way back. The page of a switched-off task carries
 * the one control the panel does offer — Enable.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const NOW = new Date('2026-02-13T10:00:00Z').getTime();

/** A pool task switched off for the winter, four months past its stored date. */
function offTask(overrides = {}) {
  return {
    id: 'backwash',
    name: 'Backwash the filter',
    recurrence_type: 'floating',
    interval: 2,
    unit: 'weeks',
    enabled: false,
    next_due: '2026-10-15T10:00:00Z',
    completions: [],
    ...overrides,
  };
}

describe('statusBucket on a switched-off task', () => {
  it('gives it a section of its own rather than heading Overdue', () => {
    const off = offTask({ next_due: '2025-10-15T10:00:00Z' });
    expect(statusBucket(off, NOW)).toBe('disabled');
    // Without the field it is exactly what it looks like: months late.
    expect(statusBucket({ ...off, enabled: true }, NOW)).toBe('overdue');
  });

  it('beats every other section a task could land in', () => {
    // Each of these wins its own branch further down, and each would put a
    // switched-off task under a heading that promises something to do.
    const cases = [
      { recurrence_type: 'sensor', next_due: null },
      { recurrence_type: 'use', next_due: null },
      { recurrence_type: 'one-off', next_due: null, source: { buy: { asset_id: 'a', part_id: 'p' } } },
      { next_due: '2026-12-01T10:00:00Z' },
      { next_due: null },
    ];
    for (const c of cases) {
      expect(statusBucket({ ...c, enabled: false }, NOW, { completed: true })).toBe('disabled');
    }
  });

  it('reads an absent field as on, so nothing stored before the field moves', () => {
    const late = { next_due: '2025-10-15T10:00:00Z' };
    expect(statusBucket(late, NOW)).toBe('overdue');
  });
});

describe('the dashboard card groups a switched-off task too', () => {
  // The card shows these rows only when its own `show_disabled` is on, but when it
  // does they need the same section the panel gives them. The card builds its sections
  // from STATUS_ORDER alone, so a bucket with no row there matches nothing and the
  // task disappears from a card that was configured to show it.
  it('puts it under its own section, last, with its own label', () => {
    const off = offTask({ next_due: '2025-10-15T10:00:00Z' });
    const live = { id: 'gutters', name: 'Clean gutters', next_due: '2025-10-01T10:00:00Z' };
    const groups = groupTasks([live, off], 'status', undefined, undefined, NOW);
    const keys = groups.map((g) => g.key);
    expect(keys).toContain('status:disabled');
    expect(keys.at(-1), 'nothing to do, so nothing above the sections you act on').toBe(
      'status:disabled',
    );
    const group = groups.find((g) => g.key === 'status:disabled');
    expect(group.label).toBe('Disabled');
    expect(group.items).toEqual([off]);
    // And the live task is still filed as late work, in a section of its own.
    expect(groups.find((g) => g.key === 'status:overdue').items).toEqual([live]);
  });

  it('builds no such section when nothing is switched off', () => {
    const live = { id: 'gutters', next_due: '2025-10-01T10:00:00Z' };
    const keys = groupTasks([live], 'status', undefined, undefined, NOW).map((g) => g.key);
    expect(keys).not.toContain('status:disabled');
  });
});

describe('scopeMatches on a switched-off task', () => {
  it('drops it from every pill but All', () => {
    // Its date is four months stale, so `overdue` and `soon` would both claim it.
    const off = offTask({ next_due: '2025-10-15T10:00:00Z' });
    expect(scopeMatches(off, 'overdue', NOW)).toBe(false);
    expect(scopeMatches(off, 'soon', NOW)).toBe(false);
    expect(scopeMatches(off, 'all', NOW)).toBe(true);
  });

  it('drops a switched-off buy reminder and wear item from their own pills too', () => {
    // Shopping and Counted are pills like any other: a part nobody is going to buy
    // and a wear item nobody is counting do not belong in either.
    const buy = offTask({
      recurrence_type: 'one-off',
      source: { buy: { asset_id: 'a1', part_id: 'p1' } },
    });
    const use = offTask({ recurrence_type: 'use', next_due: null });
    expect(scopeMatches(buy, 'shopping', NOW)).toBe(false);
    expect(scopeMatches(use, 'counted', NOW)).toBe(false);
    expect(scopeMatches(buy, 'all', NOW)).toBe(true);
    expect(scopeMatches(use, 'all', NOW)).toBe(true);
  });

  it('leaves a task alone when the field is absent or true', () => {
    // Every task stored before the field shipped carries no `enabled` key, so only an
    // explicit `false` is off. Reading a missing key as off would empty the panel.
    const late = { ...offTask({ next_due: '2025-10-15T10:00:00Z' }), enabled: undefined };
    expect(scopeMatches(late, 'overdue', NOW)).toBe(true);
    expect(scopeMatches({ ...late, enabled: true }, 'overdue', NOW)).toBe(true);
  });
});

function makeHass(tasks) {
  return {
    language: 'en',
    states: {},
    devices: {},
    areas: {},
    callWS(msg) {
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options: {} });
        case 'home_keeper/list_declarative_companions':
          return Promise.resolve({ companions: [] });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        default:
          return Promise.resolve({});
      }
    },
  };
}

async function mountDetail(tasks) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: `/tasks/${tasks[0].id}` };
  document.body.appendChild(panel);
  panel.hass = makeHass(tasks);
  await waitFor(() => panel.shadowRoot?.querySelector('.hk-detail-card'), 5000);
  return panel;
}

describe('the page of a switched-off task', () => {
  it('says the task is off, and offers Enable', async () => {
    const panel = await mountDetail([offTask()]);
    const root = panel.shadowRoot;
    const banner = root.querySelector('.hk-disabled-banner');
    expect(banner, 'a switched-off task should say so on its own page').toBeTruthy();
    expect(banner.textContent).toContain('This task is disabled');
    expect(root.querySelector('.d-enable'), 'the way back is the panel’s job').toBeTruthy();
  });

  it('offers no way to switch a task off', async () => {
    // Deliberate, and the reason the banner exists. Turning a task off is a service
    // call. A control that hides a task from every list on one mis-tap is worse than
    // one that takes an automation to reach.
    const panel = await mountDetail([offTask({ enabled: true })]);
    const root = panel.shadowRoot;
    expect(root.querySelector('.hk-disabled-banner')).toBeNull();
    expect(root.querySelector('.d-enable')).toBeNull();
    expect(root.textContent).not.toContain('Disable');
  });

  it('switches the task back on without moving its due date', async () => {
    // The stored date is what `home_keeper.set_due_today` is for. Enable must not
    // quietly reschedule: an automation that pairs the two decides that, not us.
    const sent = [];
    const panel = await mountDetail([offTask()]);
    const hass = panel.hass;
    panel.hass = {
      ...hass,
      callWS(msg) {
        if (msg.type === 'home_keeper/update_task') {
          sent.push(msg);
          return Promise.resolve({ task: { ...offTask(), enabled: true } });
        }
        return hass.callWS(msg);
      },
    };
    await waitFor(() => panel.shadowRoot?.querySelector('.d-enable'), 5000);
    panel.shadowRoot.querySelector('.d-enable').click();
    await waitFor(() => (sent.length ? sent : null), 5000);
    expect(sent[0].task_id).toBe('backwash');
    expect(sent[0].updates).toEqual({ enabled: true });
  });
});

async function mountList(tasks) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/tasks' };
  document.body.appendChild(panel);
  panel.hass = makeHass(tasks);
  await waitFor(() => panel.shadowRoot?.querySelector('[data-seg="filter"]'), 5000);
  return panel;
}

/** The count printed on one scope pill, as the list row promises it. */
function pillCount(root, value) {
  const btn = root.querySelector(`[data-seg="filter"] [data-seg-val="${value}"]`);
  return Number(btn?.querySelector('.hk-seg-count')?.textContent ?? '-1');
}

describe('the task list with a switched-off task in it', () => {
  const live = {
    id: 'gutters',
    name: 'Clean gutters',
    recurrence_type: 'floating',
    interval: 6,
    unit: 'months',
    enabled: true,
    next_due: '2026-02-09T10:00:00Z',
    completions: [],
  };

  it('leaves it out of the Overdue count, and keeps it in All', async () => {
    // Both tasks carry a stale date. Only the live one is late work.
    const panel = await mountList([live, offTask({ next_due: '2025-10-15T10:00:00Z' })]);
    const root = panel.shadowRoot;
    expect(pillCount(root, 'overdue')).toBe(1);
    expect(pillCount(root, 'all')).toBe(2);
  });

  it('shows the row as Disabled, with no due date on it', async () => {
    // The stored date is frozen, so printing it would state a deadline Home Keeper
    // will not keep. The chip is the whole answer.
    const panel = await mountList([offTask({ next_due: '2025-10-15T10:00:00Z' })]);
    const root = panel.shadowRoot;
    const row = await waitFor(() => root.querySelector('.hk-card[data-id="backwash"]'), 5000);
    expect(row.querySelector('.hk-status').innerHTML).toContain('label="Disabled"');
    expect(row.querySelector('.hk-status').innerHTML).toContain('class="hk-disabled"');
    // The meta line carries the schedule and nothing more: no date, no day count.
    const meta = row.querySelector('.hk-meta').textContent;
    expect(meta).toContain('Every 2 weeks');
    expect(meta).not.toContain('2025');
    expect(meta).not.toMatch(/due/i);
    // And the row is not painted as late work.
    expect(row.classList.contains('overdue')).toBe(false);
  });
});
