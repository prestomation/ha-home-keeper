import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';

/**
 * Editing opens beside the page you pressed Edit on.
 *
 * Edit used to navigate: from a task's own page it went back to the task list and
 * opened the drawer there, so the history, the notes and the schedule that explain
 * the values being edited all went off screen at the moment they were most useful.
 * The form now mounts next to the detail and the location does not move.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const TASK = {
  id: 't1',
  name: 'Replace fridge filter',
  recurrence_type: 'floating',
  interval: 1,
  unit: 'months',
  enabled: true,
  completions: [],
};

const ASSET = { id: 'a1', name: 'Garage water heater', kind: 'virtual', parts: [], metadata: [] };

async function mountAt(path, hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  const edit = await waitFor(() => panel.shadowRoot?.querySelector('.d-edit'));
  expect(edit, `the ${path} detail page should render its Edit button`).toBeTruthy();
  return { panel, edit };
}

describe('Editing from a detail page', () => {
  it('opens the task form beside the page, without leaving it', async () => {
    const { panel, edit } = await mountAt('/tasks/t1', makeHass({ tasks: [TASK] }));
    const before = location.pathname;

    edit.click();

    const form = await waitFor(() => panel.shadowRoot?.querySelector('#hk-form'));
    expect(form, 'the task form should mount in the drawer').toBeTruthy();
    expect(panel.shadowRoot.querySelector('.hk-drawer[data-open]')).toBeTruthy();
    // The page is still the task's own page: still a detail, still its URL.
    expect(panel._detail).toEqual({ kind: 'task', id: 't1' });
    expect(location.pathname).toBe(before);
    expect(panel.shadowRoot.querySelector('.hk-wrap').dataset.detail).toBe('task');
    expect(panel.shadowRoot.textContent).toContain('Replace fridge filter');
  });

  it('opens the appliance form beside its page, without leaving it', async () => {
    const { panel, edit } = await mountAt('/appliances/a1', makeHass({ assets: [ASSET] }));
    const before = location.pathname;

    edit.click();

    const form = await waitFor(() => panel.shadowRoot?.querySelector('#hk-asset-form'));
    expect(form, 'the appliance form should mount in the drawer').toBeTruthy();
    expect(panel._detail?.id).toBe('a1');
    expect(location.pathname).toBe(before);
    expect(panel.shadowRoot.querySelector('.hk-wrap').dataset.detail).toBe('asset');
  });

  it('drops the drawer History button on the page it would lead to', async () => {
    // History is a way to the task's own page. Pressed from that page it is a button
    // that does nothing, and the history it names is already under the form.
    const { panel, edit } = await mountAt('/tasks/t1', makeHass({ tasks: [TASK] }));
    edit.click();
    await waitFor(() => panel.shadowRoot?.querySelector('#hk-form'));
    expect(panel.shadowRoot.querySelector('.hk-drawer-history')).toBeNull();
    // The footer is still there, with the destructive action it carries.
    expect(panel.shadowRoot.querySelector('.hk-drawer-delete')).toBeTruthy();
  });

  it('closes back onto the detail page rather than a list', async () => {
    const { panel, edit } = await mountAt('/tasks/t1', makeHass({ tasks: [TASK] }));
    edit.click();
    await waitFor(() => panel.shadowRoot?.querySelector('#hk-form'));

    panel.shadowRoot.getElementById('f-cancel').click();

    await waitFor(() => !panel.shadowRoot?.querySelector('#hk-form'));
    expect(panel.shadowRoot.querySelector('.hk-drawer[data-open]')).toBeNull();
    expect(panel._detail).toEqual({ kind: 'task', id: 't1' });
    expect(panel.shadowRoot.querySelector('.d-edit'), 'still the detail page').toBeTruthy();
  });

  it('still navigates when the form does not belong to the open page', async () => {
    // The task form only mounts on the tasks view, so editing a task from anywhere
    // else is a navigation — and the pending edit is what carries it across.
    const { panel } = await mountAt('/appliances/a1', makeHass({ assets: [ASSET], tasks: [TASK] }));

    panel._openEdit(TASK);

    expect(panel._edit.open, 'the form waits for the location to settle').toBe(false);
    expect(panel._pendingEdit?.id).toBe('t1');
    expect(location.pathname).toBe('/home-keeper/tasks');
  });
});
