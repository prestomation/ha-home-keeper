import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

/**
 * The page of a task a declarative companion built (issue #231).
 *
 * A recipe materializes one managed sensor task per matching entity. The task is
 * Home Keeper's own — `managed_by.integration` is `home_keeper` and
 * `config_entry_id` is Home Keeper's entry — but `display_name` carries the
 * *recipe's* name. The page read that as a foreign integration and offered two ways
 * to nowhere: "Edit in Device Pulse", which opened the Home Keeper integration page,
 * and "Delete from Device Pulse instead", which named a place that does not exist.
 *
 * The same page also offered Done on a task the status chip called Monitored. A
 * dormant edge-mode sensor task is waiting for its condition; completing it wrote a
 * history entry and changed nothing, because `next_due_after_completion` leaves a
 * sensor task dormant.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const HK_ENTRY = 'hk-entry-1';

const SPEC = {
  id: 'spec-1',
  name: 'Device Pulse',
  description: '',
  enabled: true,
  preset_id: 'device_pulse',
  selection: { target_integration: 'device_pulse', domain: 'binary_sensor' },
  trigger: { mode: 'availability', for_seconds: 3600, clear_on_recover: true },
  task_template: { name_template: 'Check on {{ device_name }}', notes_template: '' },
  per_entity_overrides: {},
};

/** Exactly what `declarative_companions.build_managed_by` stamps on a materialized
 *  task: Home Keeper's own integration and entry, under the recipe's name. */
const MANAGED_BY = {
  integration: 'home_keeper',
  display_name: 'Device Pulse',
  config_entry_id: HK_ENTRY,
  deletion_protected: true,
  locked_fields: ['name', 'recurrence_type', 'device_id', 'area_id', 'sensor'],
  completion_blocked: false,
};

/** What the backend stamps once the recipe's trigger sets `clear_on_recover`. */
const BLOCKED_MANAGED_BY = {
  ...MANAGED_BY,
  completion_blocked: true,
  completion_prompt:
    'Opened by the “Device Pulse” recipe. Home Keeper completes this task when the watched condition recovers, so it cannot be marked done by hand.',
};

function task(overrides = {}) {
  return {
    id: 'decl1',
    name: 'Check on Hallway Sensor',
    recurrence_type: 'sensor',
    sensor: { entity_id: 'binary_sensor.hallway_ping', mode: 'availability' },
    enabled: true,
    completions: [],
    next_due: null,
    managed_by: MANAGED_BY,
    source: {
      declarative_companion: {
        spec_id: SPEC.id,
        entity_registry_id: 'ent-1',
        entity_id: 'binary_sensor.hallway_ping',
      },
    },
    ...overrides,
  };
}

/** A hass that knows Home Keeper's own config entry, so `_entryDomains` resolves —
 *  the state the old "Edit in X" deep link needed to appear at all. */
function makeHkHass(tasks, companions = [SPEC]) {
  return {
    language: 'en',
    states: {},
    devices: {},
    callWS(msg) {
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options: {} });
        case 'home_keeper/list_declarative_companions':
          return Promise.resolve({ companions });
        case 'config_entries/get':
          return Promise.resolve([
            { entry_id: HK_ENTRY, domain: 'home_keeper', state: 'loaded' },
          ]);
        case 'home_keeper/preview_declarative_companion':
          return Promise.resolve({ count: 0, over_cap: false, matched: [] });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        default:
          return Promise.resolve({});
      }
    },
  };
}

/** Mount the task's own page and return it once the detail card has painted. */
async function mountTask(tasks, companions) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: `/tasks/${tasks[0].id}` };
  document.body.appendChild(panel);
  panel.hass = makeHkHass(tasks, companions);
  const card = await waitFor(() => panel.shadowRoot?.querySelector('.hk-detail-card'), 5000);
  expect(card, 'the task page should paint').toBeTruthy();
  return panel;
}

describe('a declarative companion task’s page', () => {
  it('offers the recipe, not a deep link into an integration that is not there', async () => {
    const panel = await mountTask([task()]);
    const root = panel.shadowRoot;

    expect(root.querySelector('.d-open-in'), 'the deep link went to Home Keeper').toBeNull();
    const recipeBtn = root.querySelector('.d-edit-recipe');
    expect(recipeBtn, 'the page should offer the recipe that built this task').toBeTruthy();
    expect(recipeBtn.dataset.specId).toBe(SPEC.id);
    expect(root.textContent).not.toContain('Edit in Device Pulse');
  });

  // The recipe owns name, device, area and the sensor binding, and rewrites them
  // on every pass. An Edit dialog over those fields is a form whose Save is
  // undone by the next reconcile, so the page offers the recipe instead.
  it('offers no Edit or Delete on the task itself', async () => {
    const panel = await mountTask([task()]);

    expect(panel.shadowRoot.querySelector('.d-edit')).toBeNull();
    expect(panel.shadowRoot.querySelector('.d-del')).toBeNull();
    expect(panel.shadowRoot.querySelector('.d-edit-recipe')).toBeTruthy();
  });

  // Done on an armed task the recipe auto-clears is worse than a no-op: the
  // watcher will not re-arm while the condition stays true, so pressing it
  // dismisses a firmware update that is still pending. A greyed Done that
  // explains itself is the honest affordance.
  it('greys Done on an armed task rather than offering it', async () => {
    const panel = await mountTask([
      task({ next_due: '2026-06-01T00:00:00Z', managed_by: BLOCKED_MANAGED_BY }),
    ]);

    expect(panel.shadowRoot.querySelector('.d-done')).toBeNull();
    expect(panel.shadowRoot.querySelector('.d-done-blocked-wrap')).toBeTruthy();
    expect(panel.shadowRoot.textContent).toContain('recovers');
  });

  it('names the recipe as the way to remove the task', async () => {
    const panel = await mountTask([task()]);
    const caption = panel.shadowRoot.querySelector('.hk-managed-info');

    expect(caption).toBeTruthy();
    expect(caption.textContent).toContain('Device Pulse');
    expect(panel.shadowRoot.textContent).not.toContain('Delete from Device Pulse instead');
  });

  it('opens the recipe dialog when the button is pressed', async () => {
    const panel = await mountTask([task()]);

    panel.shadowRoot.querySelector('.d-edit-recipe').click();

    const dialog = await waitFor(
      () => panel.shadowRoot.querySelector('ha-dialog.hk-decl-dialog'),
      5000,
    );
    expect(dialog, 'the recipe editor should open over the task page').toBeTruthy();
  });

  // The recipe can be deleted while a task it built is still on screen. Falling back
  // to the generic captions beats offering an editor for a recipe that is gone.
  it('falls back to the managed captions when the recipe is no longer stored', async () => {
    const panel = await mountTask([task()], []);

    expect(panel.shadowRoot.querySelector('.d-edit-recipe')).toBeNull();
    expect(panel.shadowRoot.querySelector('.d-open-in'), 'Home Keeper is never the link').toBeNull();
  });

  // The deep link is suppressed for Home Keeper's *domain*, not for the recipe
  // source — so a task Home Keeper owns by some other route gets the same
  // treatment. Without that, "Edit in Home Keeper" would send the reader from the
  // panel to the integration page and back again.
  it('never deep-links to Home Keeper for a task it owns by another route', async () => {
    const panel = await mountTask([
      task({
        id: 'selfowned1',
        source: null,
        managed_by: { ...MANAGED_BY, deletion_protected: false },
      }),
    ]);

    expect(panel.shadowRoot.querySelector('.d-open-in')).toBeNull();
    // Not source-owned and not deletion-protected, so this one keeps the ordinary
    // task actions — the assertion above is about the link, not about them.
    expect(panel.shadowRoot.querySelector('.d-edit')).toBeTruthy();
  });

  it('hides Done while the task is monitored, and shows it once armed', async () => {
    const dormant = await mountTask([task()]);
    expect(dormant.shadowRoot.querySelector('.d-done'), 'nothing to do yet').toBeNull();
    expect(dormant.shadowRoot.textContent).toContain('Monitored');
    dormant.remove();

    const armed = await mountTask([task({ next_due: '2026-06-01T00:00:00Z' })]);
    expect(armed.shadowRoot.querySelector('.d-done'), 'the condition fired').toBeTruthy();
  });

  // The task list is a second surface with its own Done, so it needs its own guard:
  // the two used to share only the *shape* of the rule, not the rule.
  it('hides Done on the task list row too', async () => {
    // Group by nothing, so the row is not folded inside the collapsed Monitored
    // section the list opens with.
    localStorage.setItem('home-keeper.groupBy', 'none');
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/tasks' };
    document.body.appendChild(panel);
    panel.hass = makeHkHass([task()]);

    const row = await waitFor(() => panel.shadowRoot?.querySelector('.hk-row-task'), 5000);
    expect(row, 'the task should have a row').toBeTruthy();
    expect(panel.shadowRoot.querySelector('.done-btn')).toBeNull();
    localStorage.removeItem('home-keeper.groupBy');
  });

  // A meter is counting up to its target and the panel shows that countdown;
  // completing it early is real work that re-anchors the baseline.
  it('keeps Done on a dormant usage meter', async () => {
    const panel = await mountTask([
      task({
        id: 'meter1',
        sensor: {
          entity_id: 'sensor.pump_hours',
          mode: 'usage',
          target: 300,
          baseline: 0,
          unit: 'h',
        },
      }),
    ]);

    expect(panel.shadowRoot.querySelector('.d-done')).toBeTruthy();
  });
});
