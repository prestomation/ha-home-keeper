import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

// The Test button on a saved notification. Delivery is the one part of Home Keeper a
// user cannot verify from the panel: the channel, the urgency and the target only show
// what they do on the phone itself. Test sends the notification now, so the answer
// arrives on the phone instead of waiting for a task to come due.
//
// Two things it has to get right. It sends through `home_keeper.notify`, the same
// service an automation calls, so the test and the real thing cannot drift. And it
// saves the row first, because that service reads the notification back out of stored
// options — testing an unsaved channel would report success for the old delivery.

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

const NOTIFICATION = {
  id: 'n1',
  name: 'Walk my chores',
  profile_id: 'p1',
  targets: ['mobile_app_phone'],
  actions: ['complete', 'snooze'],
  style: 'walk',
  channel: 'Chores',
  urgency: 'high',
  snooze_hours: 24,
  auto: { overdue: false, due_soon: false },
};

/**
 * A `hass` that records every call and answers `home_keeper.notify` the way the real
 * service does. `notifyResult` sets what that run reports.
 *
 * Note the shape: `sent` is the **task id** a walk surfaced (`null` for a digest, or
 * for a queue that was empty), not a count — `matched` is the count. An earlier
 * fixture here invented `sent: 1`, and the panel read that number as "one went out",
 * so every real delivery reported "no task is due" (#255). A fixture that does not
 * match the service is worse than no fixture: it makes the broken read pass.
 */
function makeHass({
  notifyResult = { matched: 3, sent: 't1' },
  notifyError = null,
  gate,
  // What the profile has to match against. The default is empty, which is exactly the
  // state that used to make Test useless — a notification is configured before
  // anything is due — so it is the right default for this file.
  tasks = [],
} = {}) {
  const calls = [];
  const options = {
    sync_problem_sensors: false,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_devices: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
    one_off_retention_days: 0,
    shopping_list_entity: '',
    profiles: [PROFILE],
    notifications: [NOTIFICATION],
  };
  const hass = {
    language: 'en',
    states: { 'notify.mobile_app_phone': { entity_id: 'notify.mobile_app_phone' } },
    devices: {},
    callWS(msg) {
      calls.push(msg);
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'home_keeper/get_options':
          return Promise.resolve({ options, own_todo_entities: [] });
        case 'home_keeper/set_options':
          Object.assign(options, msg.options);
          return Promise.resolve({ options });
        case 'home_keeper/get_companions':
          return Promise.resolve({ companions: [] });
        case 'frontend/get_user_data':
          return Promise.resolve({ value: true });
        case 'call_service':
          if (notifyError) return Promise.reject(new Error(notifyError));
          // `gate` holds the send open so a test can observe the in-flight state; the
          // default stub resolves inside one microtask, which is too fast to see.
          return (gate ?? Promise.resolve()).then(() => ({ response: notifyResult }));
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
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-notifications'));
  return panel;
}

const row = (panel) => panel.shadowRoot.querySelector('#hk-notifications .hk-item-card');
const testBtn = (panel) => row(panel).querySelector('.hk-notify-test');
const altBtn = (panel) => row(panel).querySelector('.hk-notify-test-alt');
const form = (panel) => row(panel).querySelector('.hk-item-body > ha-form');
const serviceCalls = (calls) => calls.filter((c) => c.type === 'call_service');

/** Collect the panel's toasts. `toast()` fires HA's own `hass-notification` event
 *  rather than rendering anything, so the event is the only place to read it. */
function toastsOf(panel) {
  const seen = [];
  panel.addEventListener('hass-notification', (e) => seen.push(e.detail.message));
  return seen;
}

describe('Settings → Notifications — the Test button', () => {
  it('sits in the footer row, with its pair, before Delete', async () => {
    // Reading order is the design: the two safe actions first, the destructive one
    // last. The pair is read by its first class so the state-dependent
    // `hk-blocked-wrap` does not have to be spelled out here — the state tests below
    // own that.
    const { hass } = makeHass();
    const panel = await mountSettings(hass);
    const actions = row(panel).querySelector('.hk-item-actions');
    expect([...actions.children].map((el) => el.classList[0])).toEqual([
      'hk-notify-test',
      'hk-notify-test-alt',
      'hk-notify-delete',
    ]);
    expect(testBtn(panel).textContent).toBe('Test');
  });

  it('sends through home_keeper.notify, naming this notification', async () => {
    // Through the service, not a websocket command of its own: an automation and the
    // Test button have to exercise one delivery path or the test proves nothing.
    const { hass, calls } = makeHass();
    const panel = await mountSettings(hass);
    testBtn(panel).click();
    await waitFor(() => serviceCalls(calls).length);
    expect(serviceCalls(calls)[0]).toMatchObject({
      domain: 'home_keeper',
      service: 'notify',
      return_response: true,
    });
    // Asserted exactly, not with toMatchObject: the two overrides are what make Test
    // deliver in every profile state, and a partial match would pass without them.
    expect(serviceCalls(calls)[0].service_data).toEqual({
      notification: 'n1',
      status: 'all',
      when_empty: 'all_clear',
    });
  });

  it('saves the row before it sends', async () => {
    // The service resolves the notification from stored options, so an edit still
    // sitting in the debounce would send the *previous* channel and report success.
    const { hass, calls, options } = makeHass();
    const panel = await mountSettings(hass);
    form(panel).dispatchEvent(
      new CustomEvent('value-changed', {
        detail: { value: { ...NOTIFICATION, channel: 'Medication', urgency: 'critical' } },
      }),
    );
    testBtn(panel).click();
    await waitFor(() => serviceCalls(calls).length);
    expect(options.notifications[0]).toMatchObject({
      channel: 'Medication',
      urgency: 'critical',
    });
    // …and the save really did land first, not after the send.
    const saveAt = calls.findIndex((c) => c.type === 'home_keeper/set_options');
    const sendAt = calls.findIndex((c) => c.type === 'call_service');
    expect(saveAt).toBeGreaterThan(-1);
    expect(saveAt).toBeLessThan(sendAt);
  });

  it('holds itself down so a double-press does not send twice', async () => {
    // Every press delivers a real notification to a real phone, and a save plus a send
    // is slow enough to look unresponsive, so the second press of an impatient
    // double-press has to be dropped rather than queued.
    let release;
    const gate = new Promise((r) => {
      release = r;
    });
    const { hass, calls } = makeHass({ gate });
    const panel = await mountSettings(hass);
    const btn = testBtn(panel);
    btn.click();
    await waitFor(() => serviceCalls(calls).length);
    // Still in flight: the button is held down and further presses are dropped.
    expect(btn.hasAttribute('disabled')).toBe(true);
    btn.click();
    btn.click();
    release();
    await waitFor(() => !btn.hasAttribute('disabled'));
    expect(serviceCalls(calls)).toHaveLength(1);
    // …and it comes back for the next press rather than staying dead.
    btn.click();
    await waitFor(() => serviceCalls(calls).length === 2);
  });

  it('comes back after a failed send', async () => {
    // A button left disabled by an error is worse than the error: the delivery cannot
    // be retried once the target is fixed.
    const { hass } = makeHass({ notifyError: 'nope' });
    const panel = await mountSettings(hass);
    const btn = testBtn(panel);
    btn.click();
    await waitFor(() => !btn.hasAttribute('disabled'));
  });

  it('says a notification went out', async () => {
    // `waitFor` answers null on a timeout rather than throwing, so it is a wait and
    // never an assertion. Every toast case below states what it expects afterwards —
    // without that, this test sat green through the whole of #255.
    const { hass } = makeHass({ notifyResult: { matched: 3, sent: 't1' } });
    const panel = await mountSettings(hass);
    const toasts = toastsOf(panel);
    testBtn(panel).click();
    await waitFor(() => toasts.includes('Notification sent.'));
    expect(toasts).toContain('Notification sent.');
    expect(toasts.join('\n')).not.toContain('sent nothing');
  });

  it('says a digest went out, though it walked to no task', async () => {
    // A digest is one summary of everything due, so it names no task and answers
    // `sent: null` on a run that delivered. `matched` is the only count of what went
    // out, which is why the toast reads that and not `sent`.
    const { hass } = makeHass({ notifyResult: { matched: 3, sent: null } });
    const panel = await mountSettings(hass);
    const toasts = toastsOf(panel);
    testBtn(panel).click();
    await waitFor(() => toasts.includes('Notification sent.'));
    expect(toasts).toContain('Notification sent.');
    expect(toasts.join('\n')).not.toContain('sent nothing');
  });

  it('names the all-clear card rather than reporting nothing sent', async () => {
    // `matched: 0` no longer means nothing went out. Test asks for
    // `when_empty: all_clear`, so an empty queue delivers the "All caught up" card and
    // the toast has to say which card landed — reporting "sent nothing" would send
    // somebody hunting for a delivery problem that is not there.
    const { hass } = makeHass({ notifyResult: { matched: 0, sent: null } });
    const panel = await mountSettings(hass);
    const toasts = toastsOf(panel);
    testBtn(panel).click();
    await waitFor(() => toasts.some((m) => m.includes('All-clear')));
    expect(toasts.join('\n')).not.toContain('sent nothing');
    expect(toasts.join('\n')).not.toContain('Notification sent.');
  });

  // ── the button beside Test ──────────────────────────────────────────────────
  //
  // It offers whichever of the two cards the live state is *not* about to send, so a
  // user can see both without editing their data to get there.

  const A_TASK = {
    id: 't1',
    name: 'Take the bins out',
    enabled: true,
    next_due: '2099-01-01T09:00:00+00:00',
    labels: [],
  };

  it('offers the all-clear when the profile has a task to send', async () => {
    // A task that is not due for decades still makes a real card reachable: Test sends
    // `status: all`, so what the profile *saves* as its status does not limit it.
    const { hass, calls } = makeHass({ tasks: [A_TASK] });
    const panel = await mountSettings(hass);
    const alt = altBtn(panel);
    expect(alt.textContent).toBe('Test all clear');
    expect(alt.classList.contains('hk-blocked-wrap')).toBe(false);
    expect(alt.querySelector('ha-button').hasAttribute('disabled')).toBe(false);

    alt.click();
    await waitFor(() => serviceCalls(calls).length);
    // `none` matches nothing on purpose, so the all-clear is what lands.
    expect(serviceCalls(calls)[0].service_data).toEqual({
      notification: 'n1',
      status: 'none',
      when_empty: 'all_clear',
    });
  });

  it('offers a task card, greyed with a reason, when the profile has none', async () => {
    // Test can only deliver the all-clear here, so the offer would be a task card —
    // and there is nothing to build one from. A greyed button with a reason beats a
    // live one that cannot do what it says.
    const { hass, calls } = makeHass();
    const panel = await mountSettings(hass);
    const toasts = toastsOf(panel);
    const alt = altBtn(panel);
    expect(alt.textContent).toBe('Test a task');
    expect(alt.classList.contains('hk-blocked-wrap')).toBe(true);
    expect(alt.querySelector('ha-button').hasAttribute('disabled')).toBe(true);
    expect(alt.getAttribute('title')).toContain('No task matches this profile');

    alt.click();
    await waitFor(() => toasts.length);
    expect(toasts.join('\n')).toContain('No task matches this profile');
    // The press explains itself; it must not also deliver.
    expect(serviceCalls(calls)).toHaveLength(0);
  });

  it('follows the profile picked in the form, with no re-render', async () => {
    // The assertion that protects the design. A form edit saves with `render: false`,
    // and a later `set hass` only pushes into `_liveHassEls`, so nothing repaints this
    // row on its own — the footer is refreshed from the form's own change handler. Move
    // the row onto a profile whose filter excludes the one task and the offer flips.
    const { hass } = makeHass({ tasks: [A_TASK] });
    const panel = await mountSettings(hass);
    expect(altBtn(panel).textContent).toBe('Test all clear');

    // A second profile that no task can satisfy.
    panel._options.profiles = [
      ...panel._options.profiles,
      { ...PROFILE, id: 'p2', name: 'Nothing', filter: { ...PROFILE.filter, devices: ['nope'] } },
    ];
    form(panel).dispatchEvent(
      new CustomEvent('value-changed', {
        detail: { value: { ...NOTIFICATION, profile_id: 'p2' } },
      }),
    );
    await waitFor(() => altBtn(panel).textContent === 'Test a task');
    expect(altBtn(panel).classList.contains('hk-blocked-wrap')).toBe(true);
  });

  it("shows the backend's own message when the send fails", async () => {
    // A notification with no target fails with a localized error from the service.
    // Swallowing it would leave the button looking like it worked.
    const { hass } = makeHass({ notifyError: 'No notify targets are configured' });
    const panel = await mountSettings(hass);
    const toasts = toastsOf(panel);
    testBtn(panel).click();
    await waitFor(() => toasts.some((m) => m.includes('notify targets')));
    expect(toasts.join('\n')).not.toContain('Notification sent.');
  });
});
