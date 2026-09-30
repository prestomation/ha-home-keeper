import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, emitChange, waitFor } from './panel-harness.js';

/**
 * F06-1: "Clear on recover" off must round-trip through the companion dialog.
 *
 * `normalize_sensor` stores the flag only when it is on in the state, threshold and
 * template modes, so a stored trigger with no key means "off". The dialog read the
 * missing key as on, and any edit in the Trigger section (a hold, say) wrote it back
 * as on. Availability is the one mode whose default is on.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

function specWith(trigger) {
  return {
    id: 'spec-1',
    name: 'Leak watch',
    description: '',
    enabled: true,
    selection: { domain: 'binary_sensor' },
    trigger,
    task_template: { name_template: 'Check {{ friendly_name }}', notes_template: '' },
    per_entity_overrides: {},
  };
}

function makeHass(spec) {
  const previews = [];
  return {
    previews,
    hass: {
      language: 'en',
      states: {},
      devices: {},
      callWS(msg) {
        switch (msg.type) {
          case 'home_keeper/get_tasks':
            return Promise.resolve({ tasks: [] });
          case 'home_keeper/get_assets':
            return Promise.resolve({ assets: [] });
          case 'home_keeper/get_options':
            return Promise.resolve({ options: {} });
          case 'home_keeper/list_declarative_companions':
            return Promise.resolve({ companions: [spec] });
          case 'home_keeper/preview_declarative_companion':
            previews.push(msg);
            return Promise.resolve({ count: 0, over_cap: false, matched: [] });
          case 'frontend/get_user_data':
            return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
          default:
            return Promise.resolve({});
        }
      },
    },
  };
}

async function openEdit(trigger) {
  const { hass, previews } = makeHass(specWith(trigger));
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  const edit = await waitFor(() => panel.shadowRoot?.querySelector('.hk-decl-edit'), 5000);
  expect(edit).toBeTruthy();
  edit.click();
  const form = await waitFor(() =>
    panel.shadowRoot?.querySelector('[data-decl-section="trigger"]'),
  );
  expect(form).toBeTruthy();
  return { panel, form, previews };
}

describe('F06-1: clear on recover in the companion dialog', () => {
  it('shows a state trigger with no stored flag as off', async () => {
    const { form } = await openEdit({ mode: 'state', state: 'on' });
    expect(form.data.clear_on_recover).toBe(false);
  });

  it('keeps it off when the user edits only the hold', async () => {
    const { panel, form, previews } = await openEdit({ mode: 'state', state: 'on' });
    emitChange(form, { for_seconds: 120 });
    await waitFor(() => previews.some((p) => p.companion?.trigger?.for_seconds === 120), 3000);
    const last = previews[previews.length - 1];
    expect(last.companion.trigger.for_seconds).toBe(120);
    expect(last.companion.trigger.clear_on_recover).toBe(false);
    expect(panel.isConnected).toBe(true);
  });

  it('shows a stored on as on', async () => {
    const { form } = await openEdit({ mode: 'threshold', comparison: '>', value: 0, clear_on_recover: true });
    expect(form.data.clear_on_recover).toBe(true);
  });

  it('shows an availability trigger with no stored flag as on (its default)', async () => {
    const { form } = await openEdit({ mode: 'availability' });
    expect(form.data.clear_on_recover).toBe(true);
  });

  it('shows an availability trigger stored off as off', async () => {
    const { form } = await openEdit({ mode: 'availability', clear_on_recover: false });
    expect(form.data.clear_on_recover).toBe(false);
  });
});
