import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

/**
 * Done on a counted wear item's replacement task, on all 3 surfaces that draw one.
 *
 * `docs/COUNTED_WEAR_ITEMS_PLAN.md` always said an early completion was allowed and
 * restarts the count, and `store.complete_task` has always honoured it — it stamps the
 * part's `last_replaced`, consumes a spare, and moves `last_completed`, which is the
 * instant `reconcile.cycle_start` measures the next count from. Only the panel
 * withheld the button, because `isMonitoredDormant` read every dormant `triggered`
 * task as waiting on somebody else. So renewing the jacket's coating at 10 of 25 wears
 * could not be recorded, and the count climbed past its target for ever.
 *
 * The mirror image of `declarative-task-detail.test.js`, which pins the cases that
 * must keep hiding Done. Each test here carries a negative control for exactly that
 * reason: one predicate serves both, and a change that opens this one too far shows up
 * as a control going green.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
  localStorage.removeItem('home-keeper.groupBy');
});

const ASSET = {
  id: 'a1',
  name: 'Rain jacket',
  kind: 'virtual',
  parts: [
    {
      id: 'p1',
      name: 'DWR coating',
      type: 'wear',
      replace_interval: 25,
      replace_unit: 'uses',
      use_noun: 'wears',
      use_task_name: 'Wear rain jacket',
    },
  ],
};

/** The replacement half, exactly as `reconcile_part_tasks` builds it: triggered,
 *  dormant, a non-manual part source, and no role (an absent role reads as replace). */
function replaceTask(overrides = {}) {
  return {
    id: 'rep1',
    name: 'Renew DWR coating (Rain jacket)',
    recurrence_type: 'triggered',
    next_due: null,
    enabled: true,
    completions: [],
    source: { part: { asset_id: 'a1', part_id: 'p1' } },
    ...overrides,
  };
}

/** A plain dormant triggered task — a battery reminder its owner arms. The control
 *  that must keep hiding Done on every surface. */
function ownedTask(overrides = {}) {
  return {
    id: 'bat1',
    name: 'Replace battery: Hallway smoke alarm',
    recurrence_type: 'triggered',
    next_due: null,
    enabled: true,
    completions: [],
    ...overrides,
  };
}

/** A task the user linked to the same part by hand. `set_task_consumable` writes the
 *  same source shape, flagged manual, and that task really is waiting on its owner. */
function manualLink(overrides = {}) {
  return {
    id: 'man1',
    name: 'Wash the jacket',
    recurrence_type: 'triggered',
    next_due: null,
    enabled: true,
    completions: [],
    source: { part: { asset_id: 'a1', part_id: 'p1', manual: true } },
    ...overrides,
  };
}

function makeHass(tasks) {
  return {
    language: 'en',
    states: {},
    devices: {},
    callWS(msg) {
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [ASSET] });
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

/** Mount a task's own page, settled. */
async function mountTask(tasks, id = tasks[0].id) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: `/tasks/${id}` };
  document.body.appendChild(panel);
  panel.hass = makeHass(tasks);
  const card = await waitFor(() => panel.shadowRoot?.querySelector('.hk-detail-card'), 5000);
  expect(card, 'the task page should paint').toBeTruthy();
  return panel;
}

/** Mount the task list, ungrouped so no row is folded into a collapsed section. */
async function mountList(tasks) {
  localStorage.setItem('home-keeper.groupBy', 'none');
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/tasks' };
  document.body.appendChild(panel);
  panel.hass = makeHass(tasks);
  const row = await waitFor(() => panel.shadowRoot?.querySelector('.hk-row-task'), 5000);
  expect(row, 'the task should have a row').toBeTruthy();
  return panel;
}

describe('the task page', () => {
  it('offers Done on a dormant counted replacement task', async () => {
    const panel = await mountTask([replaceTask()]);
    expect(panel.shadowRoot.querySelector('.d-done')).toBeTruthy();
  });

  // The row still says Monitored: the task *is* waiting on a count, it just has an
  // early way out. `dueLabel` answers the same word the old branch did, so the only
  // thing that changed on this page is the button.
  it('still reads Monitored beside the button', async () => {
    const panel = await mountTask([replaceTask()]);
    expect(panel.shadowRoot.textContent).toContain('Monitored');
  });

  it('keeps hiding Done on a plain dormant triggered task', async () => {
    const panel = await mountTask([ownedTask()]);
    expect(panel.shadowRoot.querySelector('.d-done')).toBeNull();
  });

  it('keeps hiding Done on a hand-linked task pointing at the same part', async () => {
    const panel = await mountTask([manualLink()]);
    expect(panel.shadowRoot.querySelector('.d-done')).toBeNull();
  });
});

describe('the task list row', () => {
  it('offers Done on a dormant counted replacement task', async () => {
    const panel = await mountList([replaceTask()]);
    expect(panel.shadowRoot.querySelector('.done-btn')).toBeTruthy();
  });

  it('keeps hiding Done on a plain dormant triggered task', async () => {
    const panel = await mountList([ownedTask()]);
    expect(panel.shadowRoot.querySelector('.done-btn')).toBeNull();
  });
});
