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
 * With `slowFirst`, the first write's answer comes late. The panel used to send the
 * second write before that answer, so the two answers could arrive out of order. The
 * panel now queues its option writes (X12-2), so the second write goes only after
 * the first answer, but the rows edited in between must still all be kept.
 *
 * `hold(n)` returns a promise the nth write waits on before answering, for watching the
 * in-flight state. `fail` rejects every write with that message. `notLoaded` fails
 * that many writes with `not_loaded`, the way a write sent during a reload fails.
 * `log` records each write as it is sent and each answer as it is given.
 */
function makeHass(notifications, { slowFirst = false, hold, fail, notLoaded = 0 } = {}) {
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
  const log = [];
  let nextId = 0;
  let notLoadedLeft = notLoaded;
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
          if (notLoadedLeft > 0) {
            notLoadedLeft -= 1;
            log.push('not_loaded');
            const err = new Error("Home Keeper isn't loaded right now.");
            err.code = 'not_loaded';
            return Promise.reject(err);
          }
          saves.push(structuredClone(msg.options));
          const n = saves.length;
          log.push(`send ${n}`);
          if (fail) return Promise.reject(new Error(fail));
          const held = hold?.(saves.length);
          if (held) {
            return held.then(() => {
              for (const list of Object.values(msg.options)) {
                if (!Array.isArray(list)) continue;
                for (const row of list) if (row && row.id === '') row.id = `gen${(nextId += 1)}`;
              }
              Object.assign(options, msg.options);
              return { options: structuredClone(options) };
            });
          }
          // Applied on arrival, like the backend — which also names any row that
          // arrived without an id, the way `normalize_notification` does.
          for (const list of Object.values(msg.options)) {
            if (!Array.isArray(list)) continue;
            for (const row of list) if (row && row.id === '') row.id = `gen${(nextId += 1)}`;
          }
          Object.assign(options, msg.options);
          const answer = { options: structuredClone(options) };
          const delay = slowFirst && n === 1 ? 80 : 0;
          return new Promise((r) =>
            setTimeout(() => {
              log.push(`answer ${n}`);
              r(answer);
            }, delay),
          );
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
  return { hass, options, saves, log, panelIds: () => options.notifications.map((n) => n.id) };
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

/** The `ha-form` in *row* that owns *field*.
 *
 *  A notification row is three forms, not one: the profile picker, the delivery
 *  fields, and the triggers under their own heading. Each is seeded with only its own
 *  fields and is authoritative for only those, so an edit has to go to the form that
 *  owns it. Found by which seed carries the key, so the split can move without this
 *  helper naming an index. */
const formFor = (row, field) =>
  [...row.querySelectorAll('ha-form')].find((f) => f.data && field in f.data);

/** What the Notifications card is currently saying about itself, or '' before it has
 *  ever saved. This replaced a toast, so it is the only success feedback there is. */
const status = (panel, cardId = 'hk-notifications') =>
  panel.shadowRoot.getElementById(cardId)?.querySelector('.hk-save-status')?.textContent ?? '';

/** Edit one row the way `ha-form` does — the whole form value, one field changed. */
function edit(panel, index, patch) {
  const row = rows(panel)[index];
  for (const [field, value] of Object.entries(patch)) {
    const form = formFor(row, field);
    form.dispatchEvent(
      new CustomEvent('value-changed', { detail: { value: { ...form.data, [field]: value } } }),
    );
  }
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
    // Two rows can save at once. The first answer is out of date by the time it lands:
    // the second row has already put its own value in the panel's copy of the options.
    // Writing that answer back put the copy back to before the later row saved, and the
    // next row to build a list from that copy wrote the staleness to disk. The third
    // edit here is what turns a stale copy into a value lost for good.
    const { hass, options } = makeHass(
      [notification('n1', 'A'), notification('n2', 'B'), notification('n3', 'C')],
      { slowFirst: true },
    );
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Alpha' });
    edit(panel, 1, { channel: 'Beta' });
    await waitFor(() => options.notifications[1].channel === 'Beta');
    edit(panel, 2, { channel: 'Gamma' });

    await waitFor(() => options.notifications[2].channel === 'Gamma');
    expect(options.notifications.map((n) => n.channel)).toEqual(['Alpha', 'Beta', 'Gamma']);
  });

  it('still reports itself for a save another row overtook', async () => {
    // Being overtaken is not a failure. Only the stale copy of the options is dropped:
    // an add still expands its new row and the card still settles to Saved, or pressing
    // *Add notification* while another row's autosave is in flight would look like it
    // did nothing.
    const { hass, options } = makeHass(
      [notification('n1', 'A'), notification('n2', 'B')],
      { slowFirst: true },
    );
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Alpha' });
    edit(panel, 1, { channel: 'Beta' });

    await waitFor(() => status(panel) === 'Saved');
    expect(status(panel)).toBe('Saved');
    expect(options.notifications.map((n) => n.channel)).toEqual(['Alpha', 'Beta']);
  });

  it('expands the row each add created, not whichever landed last', async () => {
    // An add sends a row with a blank id and learns the real one from its own answer.
    // Two adds in quick succession means the second answer holds both new rows, so an
    // add reading the shared options would open the other one's row — and reading them
    // before any answer landed would put the blank id in the set for good.
    const { hass, panelIds } = makeHass([notification('n1', 'A')], { slowFirst: true });
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

describe('Settings — how an autosave reports itself', () => {
  it('says nothing until the card has actually saved something', async () => {
    // The status reports an operation the user did not ask about, so a card nobody has
    // touched must be silent. A permanent "Saved" on a fresh install would be noise.
    const { hass } = makeHass([notification('n1', 'A')]);
    const panel = await mountSettings(hass);
    expect(status(panel)).toBe('');
    expect(status(panel, 'hk-settings')).toBe('');
  });

  it('shows Saving while the write is in flight, then Saved', async () => {
    let release;
    const gate = new Promise((r) => {
      release = r;
    });
    const { hass } = makeHass([notification('n1', 'A')], { hold: () => gate });
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Trash' });
    await waitFor(() => status(panel) === 'Saving…');
    expect(status(panel)).toBe('Saving…');
    release();
    await waitFor(() => status(panel) === 'Saved');
    expect(status(panel)).toBe('Saved');
  });

  it('raises no toast when a save works', async () => {
    // The whole point of the change: three rows configured in a row used to queue three
    // toasts across the bottom of a phone, over the form still being edited.
    const { hass, options } = makeHass([notification('n1', 'A'), notification('n2', 'B')]);
    const panel = await mountSettings(hass);
    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));

    edit(panel, 0, { channel: 'Trash' });
    edit(panel, 1, { channel: 'Meds' });

    await waitFor(() => options.notifications.every((n) => n.channel));
    await waitFor(() => status(panel) === 'Saved');
    expect(toasts, `unexpected toast(s): ${toasts.join(' | ')}`).toEqual([]);
  });

  it('stays on Saving until the last of several writes has answered', async () => {
    // Two rows saving at once are one operation to the person watching. Flicking to
    // Saved while the second is still going would be a lie.
    let release;
    const gate = new Promise((r) => {
      release = r;
    });
    const { hass } = makeHass([notification('n1', 'A'), notification('n2', 'B')], {
      hold: (n) => (n === 1 ? gate : null),
    });
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Trash' });
    edit(panel, 1, { channel: 'Meds' });
    await waitFor(() => status(panel) === 'Saving…');
    // The second write has been answered; the first is still open, so the card must not
    // claim to be saved yet.
    expect(status(panel)).toBe('Saving…');
    release();
    await waitFor(() => status(panel) === 'Saved');
  });

  it('says Not saved on a failure, and still toasts the reason', async () => {
    // A failure is the one thing a toast could never say afterwards: it vanishes, and
    // the card then looks exactly like a saved one. The status stays put; the toast
    // carries the backend's own message, which the status has no room for.
    const { hass } = makeHass([notification('n1', 'A')], { fail: 'Not authorised' });
    const panel = await mountSettings(hass);
    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));

    edit(panel, 0, { channel: 'Trash' });

    await waitFor(() => status(panel) === 'Not saved');
    expect(status(panel)).toBe('Not saved');
    expect(toasts).toContain('Not authorised');
  });

  it('reports an option card too, not just the rows', async () => {
    // The option cards save through `saveOptions` and the row lists through
    // `persistOptionList`. Both report the same way: fixing only Profiles and
    // Notifications would trade one inconsistency for another.
    const { hass } = makeHass([notification('n1', 'A')]);
    const panel = await mountSettings(hass);
    const form = panel.shadowRoot.querySelector('#hk-settings ha-form');
    form.dispatchEvent(
      new CustomEvent('value-changed', {
        detail: { value: { ...form.data, sync_problem_sensors: true } },
      }),
    );
    await waitFor(() => status(panel, 'hk-settings') === 'Saved');
    expect(status(panel, 'hk-settings')).toBe('Saved');
    // …and it did not leak into the Notifications card.
    expect(status(panel)).toBe('');
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

/** Emit a change from *form* the way `ha-form` does: its whole `data`, one field set. */
function change(form, patch) {
  const value = { ...form.data, ...patch };
  form.data = value;
  form.dispatchEvent(new CustomEvent('value-changed', { detail: { value } }));
}

const generalForm = (panel) => panel.shadowRoot.querySelector('#hk-settings-general ha-form');
const cardForms = (panel, id) => [...panel.shadowRoot.querySelectorAll(`#${id} ha-form`)];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

describe('Settings option cards — each card saves only its own fields (F03-1)', () => {
  it('seeds each option form with its own fields only', async () => {
    const { hass } = makeHass([notification('n1', 'A')]);
    const panel = await mountSettings(hass);
    expect(Object.keys(generalForm(panel).data)).toEqual(['one_off_retention_days']);
    const [toggle, exclusions] = cardForms(panel, 'hk-settings');
    expect(Object.keys(toggle.data)).toEqual(['sync_problem_sensors']);
    expect(Object.keys(exclusions.data)).not.toContain('sync_problem_sensors');
    expect(Object.keys(exclusions.data)).not.toContain('notifications');
    const [shopping] = cardForms(panel, 'hk-settings-shopping');
    expect(Object.keys(shopping.data).sort()).toEqual([
      'shopping_line_style',
      'shopping_list_entity',
    ]);
  });

  it('keeps the sync switch on when an exclusion changes after it', async () => {
    // Both forms of the Problem card were seeded with the options as drawn, so the
    // exclusions form sent `sync_problem_sensors: false` back, and the reload removed
    // every synced task while the switch still showed on.
    const { hass, options, saves } = makeHass([notification('n1', 'A')]);
    const panel = await mountSettings(hass);
    const [toggle, exclusions] = cardForms(panel, 'hk-settings');

    change(toggle, { sync_problem_sensors: true });
    await waitFor(() => options.sync_problem_sensors === true);
    change(exclusions, { problem_sensor_exclude_areas: ['garage'] });
    await waitFor(() => saves.length === 2);
    await waitFor(() => status(panel, 'hk-settings') === 'Saved');

    expect(options.sync_problem_sensors).toBe(true);
    expect(options.problem_sensor_exclude_areas).toEqual(['garage']);
    expect(saves[1]).not.toHaveProperty('sync_problem_sensors');
  });

  it('leaves a notification alone when another card saves after it', async () => {
    // Configure a notification, then change a card: that card sent its copy of the
    // notifications as drawn, and the configured row went back to blank.
    const { hass, options, saves } = makeHass([notification('n1', 'A')]);
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Trash' });
    await waitFor(() => options.notifications[0].channel === 'Trash');
    const [skipsnooze] = cardForms(panel, 'hk-settings-skipsnooze');
    change(skipsnooze, { allow_snooze: false });
    await waitFor(() => options.allow_snooze === false);
    await waitFor(() => status(panel, 'hk-settings-skipsnooze') === 'Saved');

    expect(options.notifications[0].channel).toBe('Trash');
    expect(options.profiles).toEqual([PROFILE]);
    // The card sent its own field and no copy of the notifications or the profiles.
    expect(saves[saves.length - 1]).toEqual({ allow_snooze: false });
  });

  it('sends only the two shopping keys, and keeps a saved style when a list is picked', async () => {
    const { hass, options, saves } = makeHass([notification('n1', 'A')]);
    options.shopping_line_style = 'product_only';
    const panel = await mountSettings(hass);
    const [shopping] = cardForms(panel, 'hk-settings-shopping');

    change(shopping, { shopping_list_entity: 'todo.groceries' });
    await waitFor(() => saves.length === 1);

    expect(saves[0]).toEqual({
      shopping_list_entity: 'todo.groceries',
      shopping_line_style: 'product_only',
    });
    // The form keeps only its own keys after the change, too.
    expect(Object.keys(shopping.data).sort()).toEqual([
      'shopping_line_style',
      'shopping_list_entity',
    ]);
  });

  it('still sends an empty list picker as the empty string', async () => {
    const { hass, options, saves } = makeHass([notification('n1', 'A')]);
    options.shopping_list_entity = 'todo.groceries';
    const panel = await mountSettings(hass);
    const [shopping] = cardForms(panel, 'hk-settings-shopping');

    change(shopping, { shopping_list_entity: undefined });
    await waitFor(() => saves.length === 1);
    expect(saves[0].shopping_list_entity).toBe('');
  });
});

describe('Settings → General — the retention box saves on leave (X12-1)', () => {
  it('does not save the partial values typed on the way to a number', async () => {
    // Each save reloads the entry, and the purge in that reload ran with the partial
    // value: typing "30" deleted every one-off completed more than 3 days ago.
    const { hass, saves } = makeHass([notification('n1', 'A')]);
    const panel = await mountSettings(hass);
    const form = generalForm(panel);

    change(form, { one_off_retention_days: 3 });
    change(form, { one_off_retention_days: 30 });
    await sleep(50);
    expect(saves).toEqual([]);

    form.dispatchEvent(new FocusEvent('focusout', { bubbles: true, composed: true }));
    await waitFor(() => saves.length === 1);
    expect(saves).toEqual([{ one_off_retention_days: 30 }]);
  });

  it('saves on Enter', async () => {
    const { hass, saves } = makeHass([notification('n1', 'A')]);
    const panel = await mountSettings(hass);
    const form = generalForm(panel);

    change(form, { one_off_retention_days: 14 });
    form.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    await sleep(50);
    expect(saves).toEqual([]);
    form.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await waitFor(() => saves.length === 1);
    expect(saves).toEqual([{ one_off_retention_days: 14 }]);
  });

  it('saves a value once, however often focus leaves', async () => {
    const { hass, saves } = makeHass([notification('n1', 'A')]);
    const panel = await mountSettings(hass);
    const form = generalForm(panel);

    form.dispatchEvent(new FocusEvent('focusout'));
    change(form, { one_off_retention_days: 7 });
    form.dispatchEvent(new FocusEvent('focusout'));
    form.dispatchEvent(new FocusEvent('focusout'));
    await waitFor(() => status(panel, 'hk-settings-general') === 'Saved');
    await sleep(50);
    expect(saves).toEqual([{ one_off_retention_days: 7 }]);
  });

  it('stops the box at the backend maximum (B19-1)', async () => {
    const { hass } = makeHass([notification('n1', 'A')]);
    const panel = await mountSettings(hass);
    const [field] = generalForm(panel).schema;
    expect(field.selector.number).toMatchObject({ min: 0, max: 3650 });
  });
});

describe('Settings — option writes go one at a time (X12-2)', () => {
  it('sends a second write only after the first has answered', async () => {
    // Each write reloads the entry, and a write sent during that reload failed with
    // not_loaded: turning off Snooze and then Skip within a second lost the second.
    const { hass, options, log } = makeHass([notification('n1', 'A')], { slowFirst: true });
    const panel = await mountSettings(hass);
    const [form] = cardForms(panel, 'hk-settings-skipsnooze');

    change(form, { allow_snooze: false });
    change(form, { allow_skip: false });
    await waitFor(() => log.length === 4);

    expect(log).toEqual(['send 1', 'answer 1', 'send 2', 'answer 2']);
    expect(options.allow_snooze).toBe(false);
    expect(options.allow_skip).toBe(false);
  });

  it('tries a write again when the entry is reloading', async () => {
    const { hass, options, log } = makeHass([notification('n1', 'A')], { notLoaded: 1 });
    const panel = await mountSettings(hass);
    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
    const [form] = cardForms(panel, 'hk-settings-skipsnooze');

    change(form, { allow_skip: false });
    await waitFor(() => status(panel, 'hk-settings-skipsnooze') === 'Saved', 4000);

    expect(log).toEqual(['not_loaded', 'send 1', 'answer 1']);
    expect(options.allow_skip).toBe(false);
    expect(toasts).toEqual([]);
  });

  it('drops the armed autosave of a row when Test saves that row', async () => {
    // Test saves the row, then the armed autosave fired into the reload that save
    // started, and the card said Not saved for a value that was saved.
    const { hass, options, saves } = makeHass([notification('n1', 'A')]);
    const panel = await mountSettings(hass);

    edit(panel, 0, { channel: 'Trash' });
    rows(panel)[0].querySelector('.hk-notify-test').click();
    await waitFor(() => saves.length === 1);
    await sleep(800);

    expect(saves).toHaveLength(1);
    expect(options.notifications[0].channel).toBe('Trash');
  });
});
