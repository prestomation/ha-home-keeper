import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

/**
 * The page of a task whose companion claims every field.
 *
 * `managed_by.locked_fields` is a partial contract: the form drops the fields a
 * companion names and keeps the rest, so a glue that owns the name and the device
 * still leaves an edit form worth opening. Claim the lot, though, and every section
 * comes back empty — and Edit became a button that opened a drawer with no rows in it.
 *
 * The page withholds Edit in that case and names the owner instead, the same courtesy
 * a source-owned task already gets. Delete and the "Edit in X" deep link are untouched:
 * deletion protection is a separate declaration, and the integration's own UI is the
 * honest destination once the panel has nothing to offer.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const GLUE_ENTRY = 'glue-entry-1';

/** Every field the `triggered` branch of `taskSchemaSections` offers. */
const ALL_FIELDS = [
  'name',
  'notes',
  'device_id',
  'area_id',
  'tag_id',
  'require_tag_scan',
  'labels',
  'card_links',
];

/** What Battery Notes and Pawsistant actually ship: the fields they write, no more. */
const PARTIAL_FIELDS = ['name', 'notes', 'device_id', 'recurrence_type'];

function managedBy(lockedFields) {
  return {
    integration: 'home_keeper_battery_notes',
    display_name: 'Battery Notes',
    icon: 'mdi:battery-alert',
    config_entry_id: GLUE_ENTRY,
    deletion_protected: true,
    completion_prompt: 'Mark battery as replaced?',
    locked_fields: lockedFields,
  };
}

function task(lockedFields, overrides = {}) {
  return {
    id: 'bat1',
    name: 'Replace battery: Thermostat',
    recurrence_type: 'triggered',
    enabled: true,
    completions: [],
    next_due: '2026-01-01T00:00:00+00:00',
    managed_by: managedBy(lockedFields),
    source: { home_keeper_battery_notes: { device_id: 'thermostat', kind: 'replace' } },
    ...overrides,
  };
}

/** A hass whose loaded entries include the glue's, so the task is not an orphan and
 *  `_entryDomains` can resolve the "Edit in Battery Notes" deep link. */
function makeHass(tasks, entryState = 'loaded') {
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
          return Promise.resolve({ companions: [] });
        case 'config_entries/get':
          return Promise.resolve([
            { entry_id: GLUE_ENTRY, domain: 'home_keeper_battery_notes', state: entryState },
          ]);
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        default:
          return Promise.resolve({});
      }
    },
  };
}

async function mountTask(t, entryState) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: `/tasks/${t.id}` };
  document.body.appendChild(panel);
  panel.hass = makeHass([t], entryState);
  const card = await waitFor(() => panel.shadowRoot?.querySelector('.hk-detail-card'), 5000);
  expect(card, 'the task page should paint').toBeTruthy();
  return panel;
}

describe('a task whose companion locks every field', () => {
  it('offers no Edit, because the form would open empty', async () => {
    const panel = await mountTask(task(ALL_FIELDS));
    expect(panel.shadowRoot.querySelector('.d-edit')).toBeNull();
  });

  it('names the companion rather than leaving a gap where Edit was', async () => {
    const panel = await mountTask(task(ALL_FIELDS));
    // Match the caption's own text, not just the class: the delete-blocked caption
    // wears `.hk-managed-info` too, so a bare class check passes with no guard at all.
    const captions = [
      ...panel.shadowRoot.querySelectorAll('.hk-detail-actions .hk-managed-info'),
    ].map((el) => el.textContent);
    expect(captions, 'the page should say why Edit is missing').toContain(
      'Battery Notes sets every field on this task.',
    );
  });

  it('keeps the deep link into the integration that does own the fields', async () => {
    const panel = await mountTask(task(ALL_FIELDS));
    const openIn = panel.shadowRoot.querySelector('.d-open-in');
    expect(openIn, 'the integration is where these fields are edited').toBeTruthy();
    expect(openIn.dataset.domain).toBe('home_keeper_battery_notes');
  });

  it('still refuses a copy, and still says deletion belongs to the companion', async () => {
    const panel = await mountTask(task(ALL_FIELDS));
    const root = panel.shadowRoot;
    expect(root.querySelector('.d-dup'), 'a managed task is not copyable').toBeNull();
    expect(root.querySelector('.d-dup-blocked')).toBeTruthy();
    expect(root.querySelector('.d-del'), 'deletion is protected').toBeNull();
  });

  // Deletion protection lifts when the owner goes away, but the locked fields are
  // stored on the task and do not — so the form is still empty and Edit stays away.
  // Delete coming back is what an orphan actually needs.
  it('keeps Edit away when the companion is gone, and lets Delete back', async () => {
    const panel = await mountTask(task(ALL_FIELDS), 'not_loaded');
    const root = panel.shadowRoot;
    expect(root.querySelector('.d-edit')).toBeNull();
    expect(root.querySelector('.d-del'), 'an orphaned task must be removable').toBeTruthy();
  });
});

describe('a task whose companion locks only what it writes', () => {
  it('keeps Edit, because area, labels and the tag are still the user’s', async () => {
    const panel = await mountTask(task(PARTIAL_FIELDS));
    expect(panel.shadowRoot.querySelector('.d-edit')).toBeTruthy();
  });

  it('adds no caption where there is nothing to explain', async () => {
    const panel = await mountTask(task(PARTIAL_FIELDS));
    const actions = panel.shadowRoot.querySelector('.hk-detail-actions');
    expect(actions.textContent).not.toContain('sets every field');
  });
});
