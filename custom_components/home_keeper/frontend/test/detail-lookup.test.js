import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, mountPanel, waitFor } from './panel-harness.js';

/**
 * A task that another surface added after the panel's last load.
 *
 * A companion tab can make a task (Home Keeper Library makes one for a loan) and then
 * open it with `host.openTask`. The panel still has the old task list, so the page
 * said "This item no longer exists" until a reload. The panel now loads once more for
 * an id that it does not know, shows a spinner during the load, and shows the gone
 * alert only if the item is still missing after it.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const NEW_TASK = {
  id: 'new1',
  name: 'Get the book back from Priya',
  recurrence_type: 'one-off',
  enabled: true,
  completions: [],
  next_due: '2026-10-12T09:00:00+00:00',
};

/** A hass whose task list grows after the first load, and that counts the loads. */
function growingHass() {
  const hass = makeHass({ tasks: [] });
  const base = hass.callWS.bind(hass);
  let lists = [[], [NEW_TASK]];
  hass.taskLoads = 0;
  hass.release = null;
  hass.callWS = (msg) => {
    if (msg.type !== 'home_keeper/get_tasks') return base(msg);
    const tasks = lists[Math.min(hass.taskLoads, lists.length - 1)];
    hass.taskLoads += 1;
    if (hass.taskLoads === 1) return Promise.resolve({ tasks });
    // Hold the second load until the test releases it, to see the spinner.
    return new Promise((resolve) => {
      hass.release = () => resolve({ tasks });
    });
  };
  hass.setLists = (next) => {
    lists = next;
  };
  return hass;
}

function goTo(panel, path) {
  panel.route = { prefix: '/home-keeper', path };
}

describe('a detail page for an id the panel does not know', () => {
  it('loads again, shows a spinner, then shows the task', async () => {
    const hass = growingHass();
    const { panel } = await mountPanel('/tasks', hass);
    expect(hass.taskLoads).toBe(1);

    goTo(panel, `/tasks/${NEW_TASK.id}`);
    const root = panel.shadowRoot;
    expect(hass.taskLoads, 'the panel should load again').toBe(2);
    expect(root.querySelector('.hk-loading ha-spinner'), 'a spinner during the load').toBeTruthy();
    expect(root.textContent).not.toContain('This item no longer exists.');

    hass.release();
    const card = await waitFor(() => root.querySelector('.hk-detail-card'), 3000);
    expect(card, 'the task page should paint after the load').toBeTruthy();
    expect(root.textContent).toContain(NEW_TASK.name);
    expect(root.querySelector('.hk-loading')).toBeNull();
  });

  it('shows the gone alert when the item is still missing after the load', async () => {
    const hass = growingHass();
    hass.setLists([[], []]);
    const { panel } = await mountPanel('/tasks', hass);

    goTo(panel, '/tasks/missing1');
    expect(hass.taskLoads).toBe(2);
    hass.release();
    const alert = await waitFor(
      () => panel.shadowRoot.textContent.includes('This item no longer exists.'),
      3000,
    );
    expect(alert, 'the gone alert after the load').toBeTruthy();
    expect(panel.shadowRoot.querySelector('.hk-loading')).toBeNull();
  });

  it('does not load again for an id that the panel has', async () => {
    const hass = growingHass();
    hass.setLists([[NEW_TASK], [NEW_TASK]]);
    const { panel } = await mountPanel('/tasks', hass);

    goTo(panel, `/tasks/${NEW_TASK.id}`);
    const card = await waitFor(() => panel.shadowRoot.querySelector('.hk-detail-card'), 3000);
    expect(card).toBeTruthy();
    expect(hass.taskLoads, 'a known id needs no second load').toBe(1);
  });
});
