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
function makeHass({ notifyResult = { matched: 3, sent: 't1' }, notifyError = null, gate } = {}) {
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
          return Promise.resolve({ tasks: [] });
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
  it('sits in the footer row, before Delete', async () => {
    // Reading order is the design: the safe action first, the destructive one last.
    const { hass } = makeHass();
    const panel = await mountSettings(hass);
    const actions = row(panel).querySelector('.hk-item-actions');
    expect([...actions.children].map((el) => el.className)).toEqual([
      'hk-notify-test',
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
      service_data: { notification: 'n1' },
      return_response: true,
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

  it('distinguishes "nothing was due" from a failure', async () => {
    // A run that matched nothing is a success, not an error. Reporting it as one would
    // send somebody hunting for a delivery problem that is not there.
    const { hass } = makeHass({ notifyResult: { matched: 0, sent: null } });
    const panel = await mountSettings(hass);
    const toasts = toastsOf(panel);
    testBtn(panel).click();
    await waitFor(() => toasts.some((m) => m.includes('No task is due')));
    expect(toasts.join('\n')).toContain('Home Keeper sent nothing.');
    expect(toasts.join('\n')).not.toContain('Notification sent.');
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
