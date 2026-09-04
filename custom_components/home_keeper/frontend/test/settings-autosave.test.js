import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

// The Settings tab autosaves each row's `ha-form` on a debounce, so nothing in
// Profiles or Notifications has a Save button. That makes the debounce the whole
// durability story for those two cards, and it used to lose edits (#255): the timer
// was keyed by the *list*, so a second row touched inside the window cancelled the
// first row's pending save, and the payload had been built from a snapshot of the
// options taken before that row was edited. The user saw "Saved" and the value was
// gone on the next load.
//
// Two rows edited in quick succession is the ordinary case for this card — configure
// one notification, then the next — so it is worth a test of its own rather than
// leaving it to the panel's other suites, none of which open two rows.

beforeAll(() => definePanelStubs());

afterEach(() => {
  document.body.innerHTML = '';
});

const PROFILE = {
  id: 'p1',
  name: 'Everything',
  filter: {
    status: 'all',
    labels: [],
    areas: [],
    devices: [],
    exclude_labels: [],
    exclude_areas: [],
    exclude_devices: [],
  },
  sync: { entity_id: '', two_way: true, vanish_as_completed: true },
};

const notification = (id, name) => ({
  id,
  name,
  profile_id: 'p1',
  targets: ['mobile_app_phone'],
  actions: ['complete'],
  style: 'walk',
  channel: '',
  urgency: 'normal',
  snooze_hours: 24,
  auto: { overdue: false, due_soon: false },
});

/**
 * A `hass` whose `set_options` merges like the backend's, so a write that drops a key
 * is visible here exactly as it would be after a reload. Each answer carries a snapshot
 * of the options as they stood when that write was applied, which is what makes a
 * late-arriving answer a *stale* one rather than merely an old copy of the same thing.
 *
 * With `outOfOrder`, the first write's answer is held until the second has been
 * answered. Writes still apply in arrival order — only the answers are reordered, which
 * is all a websocket guarantees.
 */
function makeHass(notifications, { outOfOrder = false } = {}) {
  const options = {
    sync_problem_sensors: false,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_devices: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
    one_off_retention_days: 0,
    shopping_list_entity: '',
    profiles: [PROFILE],
    notifications,
  };
  const saves = [];
  let nextId = 0;
  let releaseFirst;
  const firstAnswer = new Promise((r) => {
    releaseFirst = r;
  });
  const hass = {
    language: 'en',
    states: { 'notify.mobile_app_phone': { entity_id: 'notify.mobile_app_phone' } },
    devices: {},
    callWS(msg) {
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks: [] });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options, own_todo_entities: [] });
        case 'home_keeper/set_options': {
          saves.push(structuredClone(msg.options));
          // Applied on arrival, like the backend — which also names any row that
          // arrived without an id, the way `normalize_notification` does.
          for (const list of Object.values(msg.options)) {
            if (!Array.isArray(list)) continue;
            for (const row of list) if (row && row.id === '') row.id = `gen${(nextId += 1)}`;
          }
          Object.assign(options, msg.options);
          const answer = { options: structuredClone(options) };
          if (!outOfOrder) return Promise.resolve(answer);
          if (saves.length === 1) return firstAnswer.then(() => answer);
          if (saves.length === 2) return Promise.resolve(answer).then((a) => (releaseFirst(), a));
          return Promise.resolve(answer);
        }
        case 'home_keeper/get_companions':
          return Promise.resolve({ companions: [] });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: true });
        default:
          return Promise.resolve({});
      }
    },
  };
  return { hass, options, saves, panelIds: () => options.notifications.map((n) => n.id) };
}

async function mountSettings(hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-notifications'));
  return panel;
}

const rows = (panel) => [...panel.shadowRoot.querySelectorAll('#hk-notifications .hk-item-card')];
const formOf = (row) => row.querySelector('.hk-item-body > ha-form');

/** Edit one row the way `ha-form` does — the whole form value, one field changed. */
function edit(panel, index, patch) {
  const row = rows(panel)[index];
  const form = formOf(row);
  form.dispatchEvent(
    new CustomEvent('value-changed', { detail: { value: { ...form.data, ...patch } } }),
  );
}

describe('Settings → Notifications — autosave across rows', () => {
  it('keeps both edits when a second row is touched inside the debounce window', async () => {
    // The reported failure: configure one notification, start on the next before the
    // first has saved, and the first one's channel is silently back to empty.
    const { hass, options } = makeHass([notification('n1', 'Bins'), notification('n2', 'Meds')]);
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Trash' });
    edit(panel, 1, { channel: 'Medication' });

    await waitFor(() => options.notifications.every((n) => n.channel));
    expect(options.notifications.map((n) => n.channel)).toEqual(['Trash', 'Medication']);
  });

  it('drops an out-of-date answer instead of writing it back over a newer row', async () => {
    // Two rows can have writes in flight at once, and a websocket does not promise the
    // answers come back in the order they were sent. An early answer landing last used
    // to put the panel's own copy of the options back to before the later row saved,
    // and the next row to build a list from that copy wrote the staleness to disk. The
    // third edit here is what turns a stale copy into a value lost for good.
    const { hass, options } = makeHass(
      [notification('n1', 'A'), notification('n2', 'B'), notification('n3', 'C')],
      { outOfOrder: true },
    );
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Alpha' });
    edit(panel, 1, { channel: 'Beta' });
    await waitFor(() => options.notifications[1].channel === 'Beta');
    edit(panel, 2, { channel: 'Gamma' });

    await waitFor(() => options.notifications[2].channel === 'Gamma');
    expect(options.notifications.map((n) => n.channel)).toEqual(['Alpha', 'Beta', 'Gamma']);
  });

  it('still says Saved for a save another row overtook', async () => {
    // Being overtaken is not a failure. Only the stale copy of the options is dropped:
    // an add still expands its new row and every save still reports itself, or pressing
    // *Add notification* while another row's autosave is in flight would look like it
    // did nothing.
    const { hass, options } = makeHass(
      [notification('n1', 'A'), notification('n2', 'B')],
      { outOfOrder: true },
    );
    const panel = await mountSettings(hass);
    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));

    edit(panel, 0, { channel: 'Alpha' });
    edit(panel, 1, { channel: 'Beta' });

    await waitFor(() => toasts.filter((m) => m === 'Saved').length === 2);
    expect(toasts.filter((m) => m === 'Saved')).toHaveLength(2);
    expect(options.notifications.map((n) => n.channel)).toEqual(['Alpha', 'Beta']);
  });

  it('expands the row each add created, not whichever landed last', async () => {
    // An add sends a row with a blank id and learns the real one from its own answer.
    // Two adds in quick succession means the second answer holds both new rows, so an
    // add reading the shared options would open the other one's row — and reading them
    // before any answer landed would put the blank id in the set for good.
    const { hass, panelIds } = makeHass([notification('n1', 'A')], { outOfOrder: true });
    const panel = await mountSettings(hass);
    const add = () => panel.shadowRoot.querySelector('#hk-notify-add');

    add().click();
    add().click();

    // Wait on the expansions, not on the stored rows: the double applies a write on
    // arrival, so the rows exist before either answer has come back.
    await waitFor(() => panel._itemExpanded.size >= 2);
    const ids = panelIds();
    // Both new rows are open, and no blank id was ever recorded.
    expect([...panel._itemExpanded]).toEqual(expect.arrayContaining([ids[1], ids[2]]));
    expect([...panel._itemExpanded]).not.toContain('');
  });

  it('saves each row once rather than re-writing the whole card per row', async () => {
    // A per-row timer must not become a per-row *storm*: each row still coalesces its
    // own keystrokes, so two edited rows are two writes, not four.
    const { hass, saves, options } = makeHass([
      notification('n1', 'Bins'),
      notification('n2', 'Meds'),
    ]);
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Tr' });
    edit(panel, 0, { channel: 'Trash' });
    edit(panel, 1, { channel: 'Me' });
    edit(panel, 1, { channel: 'Medication' });

    await waitFor(() => options.notifications.every((n) => n.channel));
    expect(saves).toHaveLength(2);
  });
});

describe('Settings → Profiles — autosave across rows', () => {
  it('keeps both renames when two profiles are edited in quick succession', async () => {
    // Profiles autosave through the same helper, so they had the same defect.
    const second = { ...PROFILE, id: 'p2', name: 'Downstairs' };
    const { hass, options } = makeHass([notification('n1', 'Bins')]);
    options.profiles = [PROFILE, second];
    const panel = await mountSettings(hass);

    const profileRows = [...panel.shadowRoot.querySelectorAll('#hk-profiles .hk-item-card')];
    expect(profileRows).toHaveLength(2);
    for (const [i, name] of [
      [0, 'Everything renamed'],
      [1, 'Downstairs renamed'],
    ]) {
      const form = profileRows[i].querySelector('.hk-item-body > ha-form');
      form.dispatchEvent(
        new CustomEvent('value-changed', { detail: { value: { ...form.data, name } } }),
      );
    }

    await waitFor(() => options.profiles.every((p) => p.name.endsWith('renamed')));
    expect(options.profiles.map((p) => p.name)).toEqual([
      'Everything renamed',
      'Downstairs renamed',
    ]);
  });
});
