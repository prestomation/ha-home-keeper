import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

/**
 * Duplicate opens the *create* form prefilled with a copy of a task (#279).
 *
 * The whole mechanism is that the seeded task has no `id`, so `_submitForm` takes its
 * `addTask` branch — which means the assertions that matter are "what does the drawer
 * hold" and "which websocket command did Create actually issue". A test that only
 * checked the button renders would pass while Duplicate silently overwrote the
 * original.
 *
 * The other half is refusal. A task Home Keeper doesn't own keeps a greyed Duplicate
 * that explains itself, so every blocked kind is asserted here too: an owner would
 * otherwise find its row quietly forked into an unowned lookalike.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const PLAIN = {
  id: 't1',
  name: 'Water flowers',
  notes: 'Deep soak, not a sprinkle.',
  recurrence_type: 'sensor',
  device_id: 'dev1',
  area_id: 'area1',
  completion_detail: 'none',
  last_completed: '2026-08-01T10:00:00+00:00',
  next_due: '2026-08-04T10:00:00+00:00',
  completions: [{ date: '2026-08-01T10:00:00+00:00' }],
  tag_id: 'tag-abc',
  require_tag_scan: true,
  enabled: true,
  sensor: {
    entity_id: 'sensor.plant_moisture',
    mode: 'threshold',
    comparison: '<=',
    value: 30,
    for_seconds: 600,
    clear_on_recover: true,
    baseline: 42,
  },
};

/** A hass that records every websocket command, so Create can be checked by name. */
function makeHass(tasks) {
  const calls = {};
  return {
    hass: {
      language: 'en',
      states: {},
      devices: {},
      callWS(msg) {
        calls[msg.type] = (calls[msg.type] || 0) + 1;
        calls.last = msg;
        switch (msg.type) {
          case 'home_keeper/get_tasks':
            return Promise.resolve({ tasks });
          case 'home_keeper/get_assets':
            return Promise.resolve({ assets: [] });
          case 'home_keeper/get_options':
            return Promise.resolve({ options: {} });
          case 'home_keeper/add_task':
            return Promise.resolve({ task: { ...msg.task, id: 'new-1' } });
          case 'frontend/get_user_data':
            return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
          default:
            return Promise.resolve({});
        }
      },
    },
    calls,
  };
}

async function openTask(task) {
  const { hass, calls } = makeHass([task]);
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: `/tasks/${task.id}` };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('.hk-detail-actions'));
  return { panel, calls };
}

describe('Duplicate a task from its page (#279)', () => {
  it('offers a live Duplicate on a task Home Keeper owns', async () => {
    const { panel } = await openTask(PLAIN);
    expect(panel.shadowRoot.querySelector('.d-dup')).not.toBeNull();
    expect(panel.shadowRoot.querySelector('.d-dup-blocked')).toBeNull();
  });

  it('seeds the create drawer with a copy, and leaves the page where it was', async () => {
    const { panel } = await openTask(PLAIN);
    const before = window.location.pathname;
    panel.shadowRoot.querySelector('.d-dup').click();

    const form = await waitFor(() => panel.shadowRoot?.querySelector('#hk-form'));
    expect(form, 'Duplicate should open the drawer').toBeTruthy();
    // The whole mechanism: no id means `_submitForm` creates rather than updates.
    expect(panel._edit.task.id).toBeUndefined();
    expect(panel._edit.task.name).toBe('Water flowers (copy)');
    // The rule is copied…
    expect(panel._edit.task.notes).toBe('Deep soak, not a sprinkle.');
    expect(panel._edit.task.recurrence_type).toBe('sensor');
    expect(panel._edit.task.device_id).toBe('dev1');
    expect(panel._edit.task.sensor).toEqual({
      entity_id: 'sensor.plant_moisture',
      mode: 'threshold',
      comparison: '<=',
      value: 30,
      for_seconds: 600,
      clear_on_recover: true,
    });
    // …the record is not. `last_completed` and `tag_id` are controls the form itself
    // renders, so it writes them back onto the edit state; what matters is that they
    // come up *empty* rather than pre-filled from the original.
    expect(panel._edit.task.last_completed).toBeFalsy();
    expect(panel._edit.task.tag_id).toBeFalsy();
    expect(panel._edit.task.require_tag_scan).toBeFalsy();
    for (const key of ['completions', 'next_due']) {
      expect(panel._edit.task, `a copy must not carry ${key}`).not.toHaveProperty(key);
    }
    // Duplicating does not navigate: the task's own page is already the tasks view,
    // so the drawer opens beside what you were reading.
    expect(panel._detail).toEqual({ kind: 'task', id: 't1' });
    expect(window.location.pathname).toBe(before);
  });

  it('renders as a new task, not as an edit of the original', async () => {
    const { panel } = await openTask(PLAIN);
    panel.shadowRoot.querySelector('.d-dup').click();
    await waitFor(() => panel.shadowRoot?.querySelector('#hk-form'));

    expect(panel.shadowRoot.querySelector('#f-save').textContent).toContain('Create');
    // A draft has nothing to delete and no history to show.
    expect(panel.shadowRoot.querySelector('.f-del')).toBeNull();
  });

  it('creates a second task rather than overwriting the original', async () => {
    const { panel, calls } = await openTask(PLAIN);
    panel.shadowRoot.querySelector('.d-dup').click();
    await waitFor(() => panel.shadowRoot?.querySelector('#hk-form'));

    panel.shadowRoot.querySelector('#f-save').click();
    await waitFor(() => calls['home_keeper/add_task']);

    expect(calls['home_keeper/add_task']).toBe(1);
    expect(calls['home_keeper/update_task']).toBeUndefined();
    const sent = calls.last.task;
    expect(sent.name).toBe('Water flowers (copy)');
    expect(sent).not.toHaveProperty('last_completed');
    expect(sent.tag_id).toBeNull();
    expect(sent.require_tag_scan).toBe(false);
    expect(sent.sensor).not.toHaveProperty('baseline');
  });

  it('does not strip the original task while copying it', async () => {
    const { panel } = await openTask(PLAIN);
    panel.shadowRoot.querySelector('.d-dup').click();
    await waitFor(() => panel.shadowRoot?.querySelector('#hk-form'));
    // The seed shallow-copies the binding; sharing it would clear the baseline of
    // the task still sitting in the panel's own list.
    expect(panel._tasks[0].sensor.baseline).toBe(42);
    expect(panel._tasks[0].tag_id).toBe('tag-abc');
  });
});

describe('A task Home Keeper does not own keeps a greyed Duplicate', () => {
  const cases = [
    [
      'a reconciler wear part',
      { ...PLAIN, source: { part: { asset_id: 'a1', part_id: 'p1' } } },
      "This can't be duplicated in Home Keeper. It's kept in step by the integration or wear item that created it.",
    ],
    [
      'a synced problem sensor',
      { ...PLAIN, source: { problem_sensor: { entity_id: 'binary_sensor.sump' } } },
      "This can't be duplicated in Home Keeper. It's kept in step by the integration or wear item that created it.",
    ],
    [
      'an integration-managed task',
      { ...PLAIN, managed_by: { display_name: 'Pawsistant', config_entry_id: 'ce1' } },
      'Managed by Pawsistant. Create the copy there instead.',
    ],
    [
      // Blocked on the recurrence type, not on ownership: a triggered task's payload
      // carries no schedule, so a copy would be inferred as a one-off due today.
      'a condition-driven task with no declared owner',
      { id: 't1', name: 'Water flowers', recurrence_type: 'triggered' },
      "This can't be duplicated in Home Keeper. It's kept in step by the integration or wear item that created it.",
    ],
  ];

  it.each(cases)('greys Duplicate for %s and explains on tap', async (_label, task, reason) => {
    const { panel, calls } = await openTask(task);

    const blocked = panel.shadowRoot.querySelector('.d-dup-blocked');
    expect(blocked, 'a task Home Keeper does not own shows a disabled Duplicate').toBeTruthy();
    expect(panel.shadowRoot.querySelector('.d-dup')).toBeNull();
    expect(blocked.querySelector('ha-button').hasAttribute('disabled')).toBe(true);
    expect(blocked.getAttribute('title')).toBe(reason);

    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
    blocked.click();
    await new Promise((r) => setTimeout(r, 20));
    expect(toasts).toEqual([reason]);
    // Refusing is not a silent no-op, and it certainly is not a create.
    expect(calls['home_keeper/add_task']).toBeUndefined();
    expect(panel.shadowRoot.querySelector('#hk-form')).toBeNull();
  });

  it('answers the keyboard too, not just the mouse', async () => {
    // `role="button"` promises Enter and Space work. The inner ha-button is disabled
    // and swallows events, so the span has to carry them itself.
    const { panel } = await openTask({
      ...PLAIN,
      managed_by: { display_name: 'Pawsistant', config_entry_id: 'ce1' },
    });
    const blocked = panel.shadowRoot.querySelector('.d-dup-blocked');
    expect(blocked.getAttribute('role')).toBe('button');
    expect(blocked.getAttribute('tabindex')).toBe('0');

    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
    blocked.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    blocked.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    await new Promise((r) => setTimeout(r, 20));
    expect(toasts).toEqual([
      'Managed by Pawsistant. Create the copy there instead.',
      'Managed by Pawsistant. Create the copy there instead.',
    ]);
  });

  it('still offers Edit beside the greyed Duplicate for a managed task', async () => {
    // A managed task is editable — only copying is refused. The button has to land in
    // the branch that keeps Edit and Delete, not replace it.
    const { panel } = await openTask({
      ...PLAIN,
      managed_by: { display_name: 'Pawsistant', config_entry_id: 'ce1' },
    });
    expect(panel.shadowRoot.querySelector('.d-edit')).not.toBeNull();
    expect(panel.shadowRoot.querySelector('.d-dup-blocked')).not.toBeNull();
  });

  it('keeps a manual consumable link copyable — the user made that link', async () => {
    const { panel } = await openTask({
      ...PLAIN,
      source: { part: { asset_id: 'a1', part_id: 'p1', manual: true } },
    });
    expect(panel.shadowRoot.querySelector('.d-dup')).not.toBeNull();
    expect(panel.shadowRoot.querySelector('.d-dup-blocked')).toBeNull();
  });
});
