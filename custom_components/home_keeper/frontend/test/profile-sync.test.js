import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

// A profile's "Sync to a to-do list" group. Configuring it is a standing instruction
// to write Home Keeper's tasks onto somebody else's list, so the profile row has to
// make that legible before it is opened — hence the chip — and the group itself has
// to make it reversible: there is no delete button, so clearing the picker is the
// only off switch, and it has to actually reach the backend as an empty string.

beforeAll(() => definePanelStubs());

afterEach(() => {
  document.body.innerHTML = '';
});

const FILTER = {
  status: 'overdue',
  labels: [],
  areas: [],
  devices: [],
  exclude_labels: [],
  exclude_areas: [],
  exclude_devices: [],
};

const SYNCED = {
  id: 'p1',
  name: 'Overdue',
  filter: FILTER,
  sync: { entity_id: 'todo.family', two_way: true, vanish_as_completed: true },
};

const UNSYNCED = {
  id: 'p2',
  name: 'Weekend',
  filter: FILTER,
  sync: { entity_id: '', two_way: true, vanish_as_completed: true },
};

/** A `hass` whose options round-trip through a mutable store, the way the backend's
 *  `set_options` does — it answers with the options it just merged. */
function makeHass({ profiles = [], states = {} } = {}) {
  const calls = {};
  const options = {
    sync_problem_sensors: false,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_devices: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
    one_off_retention_days: 0,
    shopping_list_entity: '',
    profiles,
    notifications: [],
  };
  const hass = {
    language: 'en',
    states,
    devices: {},
    callWS(msg) {
      calls[msg.type] = (calls[msg.type] || 0) + 1;
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks: [] });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options, own_todo_entities: ['todo.home_keeper_tasks'] });
        case 'home_keeper/set_options':
          Object.assign(options, msg.options);
          // The backend mints an id for a profile saved without one.
          options.profiles = (options.profiles || []).map((p, i) => ({
            ...p,
            id: p.id || `srv${i}`,
          }));
          calls.lastSetOptions = msg.options;
          return Promise.resolve({ options });
        case 'home_keeper/get_companions':
          return Promise.resolve({ companions: [] });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        default:
          return Promise.resolve({});
      }
    },
  };
  return { hass, calls, options };
}

async function mountSettings(hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-profiles'));
  return panel;
}

const rows = (panel) => [...panel.shadowRoot.querySelectorAll('#hk-profiles .hk-item-card')];
const groupOf = (row) => row.querySelector('.hk-sync-group');
const syncForm = (row) => groupOf(row).querySelector('ha-form');
const filterForm = (row) => row.querySelector('.hk-item-body > ha-form');
const emit = (form, value) =>
  form.dispatchEvent(new CustomEvent('value-changed', { detail: { value } }));

describe('Settings tab — the profile sync group', () => {
  it('no longer ships a separate To-do list sync card', async () => {
    // The feature moved *inside* each profile; a leftover card would be a second,
    // competing place to configure the same thing.
    const { hass } = makeHass({ profiles: [SYNCED] });
    const panel = await mountSettings(hass);
    // Historical ids from the standalone mirror card this feature replaced; the
    // assertions guard against it coming back, so the old spellings stay.
    expect(panel.shadowRoot.querySelector('#hk-task-mirrors')).toBeNull();
    expect(panel.shadowRoot.querySelector('#hk-mirror-add')).toBeNull();
    const ids = [...panel.shadowRoot.querySelectorAll('ha-card')].map((c) => c.id);
    expect(ids).toEqual(expect.arrayContaining(['hk-profiles', 'hk-companions']));
    expect(ids).not.toContain('hk-task-mirrors');
  });

  it("sits below the profile's filters and above its Delete button", async () => {
    // Reading order is the design: what the profile selects, then where that goes,
    // then the destructive action last.
    const { hass } = makeHass({ profiles: [SYNCED] });
    const panel = await mountSettings(hass);
    const body = rows(panel)[0].querySelector('.hk-item-body');
    const kinds = [...body.children].map((el) => el.className || el.tagName.toLowerCase());
    expect(kinds).toEqual(['ha-form', 'hk-sync-group', 'hk-notify-delete']);
  });

  it('gives every profile its own group, and no Delete inside it', async () => {
    // Clearing the picker is the off switch; a Delete button would suggest the
    // group itself can be removed, which it can't.
    const { hass } = makeHass({ profiles: [SYNCED, UNSYNCED] });
    const panel = await mountSettings(hass);
    const all = rows(panel);
    expect(all.length).toBe(2);
    for (const row of all) {
      expect(groupOf(row)).toBeTruthy();
      expect(groupOf(row).textContent).toContain('Sync to a to-do list');
      expect(groupOf(row).querySelector('.hk-notify-delete')).toBeNull();
    }
  });

  it("seeds the form from the profile's stored sync, minus our own lists", async () => {
    const { hass } = makeHass({ profiles: [SYNCED] });
    const panel = await mountSettings(hass);
    const form = syncForm(rows(panel)[0]);
    expect(form.data).toEqual({
      entity_id: 'todo.family',
      two_way: true,
      vanish_as_completed: true,
    });
    // Syncing Home Keeper's own list onto itself is a loop.
    const entityField = form.schema.find((f) => f.name === 'entity_id');
    expect(entityField.selector.entity.exclude_entities).toEqual(['todo.home_keeper_tasks']);
    // No profile picker: the group is already inside the profile it belongs to.
    expect(form.schema.map((f) => f.name)).toEqual([
      'entity_id',
      'two_way',
      'vanish_as_completed',
    ]);
  });

  it('reads a profile saved without a sync block as off, both switches on', async () => {
    const { hass } = makeHass({ profiles: [{ id: 'p3', name: 'Old', filter: FILTER }] });
    const panel = await mountSettings(hass);
    expect(syncForm(rows(panel)[0]).data).toEqual({
      entity_id: '',
      two_way: true,
      vanish_as_completed: true,
    });
  });

  it('opens a configured sync and folds an unconfigured one', async () => {
    // A running sync is worth seeing at a glance; an empty one is just noise on a
    // profile the user opened to edit its filters.
    const { hass } = makeHass({ profiles: [SYNCED, UNSYNCED] });
    const panel = await mountSettings(hass);
    const [synced, unsynced] = rows(panel).map(groupOf);
    expect(synced.querySelector('.hk-item-body').style.display).toBe('');
    expect(synced.querySelector('.hk-item-header').getAttribute('aria-expanded')).toBe('true');
    expect(unsynced.querySelector('.hk-item-body').style.display).toBe('none');
    expect(unsynced.querySelector('.hk-item-header').getAttribute('aria-expanded')).toBe('false');
  });

  it('toggles the group open and shut from its header', async () => {
    const { hass } = makeHass({ profiles: [UNSYNCED] });
    const panel = await mountSettings(hass);
    const group = groupOf(rows(panel)[0]);
    const header = group.querySelector('.hk-item-header');
    const body = group.querySelector('.hk-item-body');
    const chevron = header.querySelector('.hk-section-chevron');
    expect(chevron.classList.contains('open')).toBe(false);

    header.click();
    expect(body.style.display).toBe('');
    expect(header.getAttribute('aria-expanded')).toBe('true');
    expect(chevron.classList.contains('open')).toBe(true);

    header.click();
    expect(body.style.display).toBe('none');
    expect(header.getAttribute('aria-expanded')).toBe('false');
    expect(chevron.classList.contains('open')).toBe(false);
  });

  it('remembers a collapse across a re-render, beating the open-by-default rule', async () => {
    // Adding a profile repaints the whole card. Re-deriving the default there would
    // shove a group the user just folded back open.
    const { hass, calls } = makeHass({ profiles: [SYNCED] });
    const panel = await mountSettings(hass);
    groupOf(rows(panel)[0]).querySelector('.hk-item-header').click();

    panel.shadowRoot.querySelector('#hk-profile-add').click();
    await waitFor(() => calls.lastSetOptions);
    const repainted = await waitFor(() => {
      const all = rows(panel);
      return all.length === 2 ? all : null;
    });
    expect(groupOf(repainted[0]).querySelector('.hk-item-body').style.display).toBe('none');
  });

  it('remembers an expand across a re-render, beating the folded-by-default rule', async () => {
    const { hass, calls } = makeHass({ profiles: [UNSYNCED] });
    const panel = await mountSettings(hass);
    groupOf(rows(panel)[0]).querySelector('.hk-item-header').click();

    panel.shadowRoot.querySelector('#hk-profile-add').click();
    await waitFor(() => calls.lastSetOptions);
    const repainted = await waitFor(() => {
      const all = rows(panel);
      return all.length === 2 ? all : null;
    });
    expect(groupOf(repainted[0]).querySelector('.hk-item-body').style.display).toBe('');
  });

  it("chips the profile row with the synced list's friendly name", async () => {
    const { hass } = makeHass({
      profiles: [SYNCED, UNSYNCED],
      states: { 'todo.family': { attributes: { friendly_name: 'Family list' } } },
    });
    const panel = await mountSettings(hass);
    const [synced, unsynced] = rows(panel);
    const chip = synced.querySelector('.hk-item-header .hk-sync-chip');
    expect(chip.textContent).toBe('Family list');
    expect(chip.getAttribute('title')).toBe('Syncs to Family list');
    expect(chip.getAttribute('aria-label')).toBe('Syncs to Family list');
    expect(chip.querySelector('ha-icon').getAttribute('icon')).toBe('mdi:swap-horizontal');
    // An unsynced profile shows nothing at all, so the chip's presence is the signal.
    expect(unsynced.querySelector('.hk-item-header .hk-sync-chip')).toBeNull();
  });

  it('falls back to the entity id for a list with no state yet', async () => {
    const { hass } = makeHass({ profiles: [SYNCED] });
    const panel = await mountSettings(hass);
    expect(rows(panel)[0].querySelector('.hk-sync-chip').textContent).toBe('todo.family');
  });

  it('escapes a list name before it reaches the chip', async () => {
    const { hass } = makeHass({
      profiles: [SYNCED],
      states: { 'todo.family': { attributes: { friendly_name: '<img src=x onerror=1>' } } },
    });
    const panel = await mountSettings(hass);
    const chip = rows(panel)[0].querySelector('.hk-sync-chip');
    expect(chip.querySelector('img')).toBeNull();
    expect(chip.textContent).toContain('<img src=x onerror=1>');
  });

  it('paints the chip in as soon as a list is picked, and out when cleared', async () => {
    const { hass } = makeHass({
      profiles: [UNSYNCED],
      states: { 'todo.family': { attributes: { friendly_name: 'Family list' } } },
    });
    const panel = await mountSettings(hass);
    const row = rows(panel)[0];
    expect(row.querySelector('.hk-sync-chip')).toBeNull();

    emit(syncForm(row), { entity_id: 'todo.family', two_way: true, vanish_as_completed: true });
    expect(row.querySelector('.hk-sync-chip').textContent).toBe('Family list');

    emit(syncForm(row), { entity_id: undefined, two_way: true, vanish_as_completed: true });
    expect(row.querySelector('.hk-sync-chip')).toBeNull();
  });

  it('saves the list the user picked onto that profile alone', async () => {
    const { hass, calls } = makeHass({ profiles: [UNSYNCED, SYNCED] });
    const panel = await mountSettings(hass);
    emit(syncForm(rows(panel)[0]), {
      entity_id: 'todo.groceries',
      two_way: false,
      vanish_as_completed: true,
    });
    await waitFor(() => calls.lastSetOptions);
    expect(calls.lastSetOptions.profiles[0].sync).toEqual({
      entity_id: 'todo.groceries',
      two_way: false,
      vanish_as_completed: true,
    });
    // The other profile is untouched.
    expect(calls.lastSetOptions.profiles[1].sync).toEqual(SYNCED.sync);
  });

  it('turns the sync off when the picker is cleared', async () => {
    // Clearing an entity picker emits `undefined`, which JSON drops on the way to the
    // backend — the key would never reach the saved profile and the old list would
    // quietly stay configured. Since the group has no other off switch, this is it.
    const { hass, calls } = makeHass({ profiles: [SYNCED] });
    const panel = await mountSettings(hass);
    emit(syncForm(rows(panel)[0]), {
      entity_id: undefined,
      two_way: true,
      vanish_as_completed: true,
    });
    await waitFor(() => calls.lastSetOptions);
    expect(calls.lastSetOptions.profiles[0].sync.entity_id).toBe('');
  });

  it("keeps the sync when the profile's filters are edited", async () => {
    // The filter form doesn't render the sync fields, so saving it alone would drop
    // them — a rename must not silently switch a running sync off.
    const { hass, calls } = makeHass({ profiles: [SYNCED] });
    const panel = await mountSettings(hass);
    emit(filterForm(rows(panel)[0]), { name: 'Renamed', status: 'all' });
    await waitFor(() => calls.lastSetOptions);
    expect(calls.lastSetOptions.profiles[0].name).toBe('Renamed');
    expect(calls.lastSetOptions.profiles[0].sync).toEqual(SYNCED.sync);
  });

  it('keeps an unsaved name edit when the sync changes inside the debounce', async () => {
    // Both forms save through one debounce key, so the later change decides what is
    // written. It has to carry the earlier one with it.
    const { hass, calls } = makeHass({ profiles: [SYNCED] });
    const panel = await mountSettings(hass);
    const row = rows(panel)[0];
    emit(filterForm(row), { name: 'Renamed', status: 'all' });
    emit(syncForm(row), { entity_id: 'todo.other', two_way: false, vanish_as_completed: false });
    await waitFor(() => calls.lastSetOptions);
    expect(calls.lastSetOptions.profiles[0].name).toBe('Renamed');
    expect(calls.lastSetOptions.profiles[0].filter.status).toBe('all');
    expect(calls.lastSetOptions.profiles[0].sync).toEqual({
      entity_id: 'todo.other',
      two_way: false,
      vanish_as_completed: false,
    });
  });

  it('adds a profile with no list picked and both switches on', async () => {
    const { hass, calls } = makeHass();
    const panel = await mountSettings(hass);
    panel.shadowRoot.querySelector('#hk-profile-add').click();
    await waitFor(() => calls.lastSetOptions);
    expect(calls.lastSetOptions.profiles[0].sync).toEqual({
      entity_id: '',
      two_way: true,
      vanish_as_completed: true,
    });
  });
});
