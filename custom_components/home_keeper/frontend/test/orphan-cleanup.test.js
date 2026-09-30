import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, mountPanel, waitFor } from './panel-harness.js';

/**
 * F07-5 / X08-1: "Remove orphaned tasks".
 *
 * The button deleted every orphaned managed task at once, with no confirmation, one
 * `delete_task` call (and one entry reload) per task. When the loaded-entries lookup
 * failed, every managed task read as orphaned. Now it asks first, sends one bulk call,
 * and a failed lookup shows no orphans.
 */

beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
  document.querySelectorAll('.hk-confirm-scrim').forEach((el) => el.remove());
});

const mkManaged = (id, entry) => ({
  id,
  name: `Replace battery ${id}`,
  recurrence_type: 'floating',
  interval: 6,
  unit: 'months',
  next_due: '2030-01-01T00:00:00+00:00',
  completions: [],
  managed_by: { integration: 'glue', display_name: 'Glue', config_entry_id: entry },
});

const TASKS = [mkManaged('t1', 'gone'), mkManaged('t2', 'gone'), mkManaged('t3', 'live')];

function makeHass({ entriesFail = false } = {}) {
  const calls = [];
  const hass = {
    language: 'en',
    states: {},
    devices: {},
    callWS(msg) {
      calls.push(msg.type);
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks: TASKS });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options: {} });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        case 'config_entries/get':
          return entriesFail
            ? Promise.reject(new Error('not allowed'))
            : Promise.resolve([{ entry_id: 'live', state: 'loaded', domain: 'glue' }]);
        case 'home_keeper/delete_orphaned_tasks':
          return Promise.resolve({ deleted: ['t1', 't2'] });
        default:
          return Promise.resolve({});
      }
    },
  };
  return { hass, calls };
}

const scrim = () => document.querySelector('.hk-confirm-scrim');
const confirmButton = (text) =>
  [...(scrim()?.querySelectorAll('ha-button') || [])].find((b) => b.textContent === text);
const count = (calls, type) => calls.filter((c) => c === type).length;

describe('F07-5: Remove orphaned tasks', () => {
  it('asks first, naming the count, and deletes nothing on Cancel', async () => {
    const { hass, calls } = makeHass();
    const { panel } = await mountPanel('/tasks', hass);
    const btn = await waitFor(() => panel.shadowRoot.querySelector('#cleanup-orphans-btn'));
    expect(btn, 'two orphans show the banner').toBeTruthy();
    btn.click();
    expect(scrim().querySelector('h2').textContent).toBe('Delete 2 orphaned tasks?');
    expect(scrim().querySelector('p').textContent).toBe(
      '2 tasks are managed by integrations that are no longer installed. This cannot be undone.',
    );
    confirmButton('Cancel').click();
    expect(count(calls, 'home_keeper/delete_orphaned_tasks')).toBe(0);
    expect(count(calls, 'home_keeper/delete_task')).toBe(0);
  });

  it('X08-1: sends one bulk call on Delete, not one delete per task', async () => {
    const { hass, calls } = makeHass();
    const { panel } = await mountPanel('/tasks', hass);
    (await waitFor(() => panel.shadowRoot.querySelector('#cleanup-orphans-btn'))).click();
    confirmButton('Delete').click();
    await waitFor(() => count(calls, 'home_keeper/delete_orphaned_tasks'));
    expect(count(calls, 'home_keeper/delete_orphaned_tasks')).toBe(1);
    expect(count(calls, 'home_keeper/delete_task')).toBe(0);
  });

  it('shows no orphans when the loaded-entries lookup fails', async () => {
    const { hass } = makeHass({ entriesFail: true });
    const { panel } = await mountPanel('/tasks', hass);
    await waitFor(() => panel.shadowRoot.querySelectorAll('#hk-list ha-card.hk-card').length === 3);
    expect(panel.shadowRoot.querySelector('#cleanup-orphans-btn')).toBeNull();
    expect(panel.shadowRoot.querySelector('.hk-orphan-banner')).toBeNull();
  });
});
