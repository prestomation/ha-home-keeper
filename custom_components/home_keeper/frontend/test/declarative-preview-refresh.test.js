import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, emitChange, waitFor } from './panel-harness.js';

/**
 * The recipe dialog's live preview survives a trigger-mode change.
 *
 * Changing the Trigger mode dropdown re-renders the whole dialog from *inside* the
 * trigger section's change handler, because the mode decides which fields exist. The
 * rebuilt dialog schedules its own preview. Then the handler's own
 * `schedulePreview()` ran — from the closure of the dialog that had just been thrown
 * away — and replaced that pending timer with one pointing at the detached node.
 * `refreshPreview` skips a disconnected node, so neither preview ever landed and the
 * dialog sat on "Loading preview…" until it was closed.
 *
 * That is the same flow issue #230 reported (a Device Pulse recipe switched to
 * *state* mode), which is why it is worth a test of its own rather than trusting the
 * dialog's other coverage: the exploratory walk found it by waiting on the preview,
 * and the e2e spec never did — it switched the mode and pressed Save straight away.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const SPEC = {
  id: 'spec-1',
  name: 'Device Pulse',
  description: '',
  enabled: true,
  preset_id: 'device_pulse',
  selection: { target_integration: 'device_pulse', domain: 'sensor' },
  trigger: { mode: 'threshold', comparison: '>', value: 0, clear_on_recover: true },
  task_template: { name_template: 'Check on {{ friendly_name }}', notes_template: '' },
  per_entity_overrides: {},
};

/** Counts preview round trips so a test can tell "never asked" from "asked, lost". */
function makeDeclHass() {
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
            return Promise.resolve({ companions: [SPEC] });
          case 'home_keeper/preview_declarative_companion':
            previews.push(msg);
            return Promise.resolve({
              count: 2,
              over_cap: false,
              matched: [
                { entity_id: 'sensor.a_total_failed_pings', rendered_name: 'Check on A' },
                { entity_id: 'sensor.b_total_failed_pings', rendered_name: 'Check on B' },
              ],
            });
          case 'frontend/get_user_data':
            return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
          default:
            return Promise.resolve({});
        }
      },
    },
  };
}

/** Boot the panel on Settings and open the edit dialog for the seeded recipe. */
async function openEditDialog() {
  const { hass, previews } = makeDeclHass();
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  const edit = await waitFor(() => panel.shadowRoot?.querySelector('.hk-decl-edit'), 5000);
  expect(edit, 'the seeded recipe should render a row with an Edit button').toBeTruthy();
  edit.click();
  const dialog = await waitFor(() => panel.shadowRoot?.querySelector('ha-dialog.hk-decl-dialog'));
  expect(dialog, 'Edit should open the recipe dialog').toBeTruthy();
  return { panel, previews };
}

/** The dialog's preview node, whatever render owns it now. */
const previewNode = (panel) => panel.shadowRoot.querySelector('.hk-decl-preview');

/** The form for one dialog section, addressed the way the e2e spec addresses it. */
const sectionForm = (panel, key) =>
  panel.shadowRoot.querySelector(`[data-decl-section="${key}"]`);

describe('the recipe dialog’s live preview', () => {
  it('fills in when the dialog opens', async () => {
    const { panel } = await openEditDialog();
    const header = await waitFor(
      () => panel.shadowRoot.querySelector('.hk-decl-preview-header'),
      5000,
    );
    expect(header, 'the preview should replace its loading line').toBeTruthy();
    expect(header.textContent).toContain('2');
  });

  it('fills in again after the trigger mode changes', async () => {
    const { panel, previews } = await openEditDialog();
    await waitFor(() => panel.shadowRoot.querySelector('.hk-decl-preview-header'), 5000);
    const before = previews.length;

    // Switching the mode rebuilds the dialog, so the node this assertion reads is a
    // different element from the one above — which is the whole point.
    emitChange(sectionForm(panel, 'trigger'), { mode: 'state' });

    const header = await waitFor(
      () => panel.shadowRoot.querySelector('.hk-decl-preview-header'),
      5000,
    );
    expect(header, 'the preview stayed on its loading line after the mode change').toBeTruthy();
    expect(previews.length, 'the mode change should ask the backend again').toBeGreaterThan(before);
    // The rebuilt dialog is showing the new mode's fields, not the old mode's.
    expect(previewNode(panel).isConnected).toBe(true);
  });

  it('asks the backend with the rewritten trigger, not the old one', async () => {
    const { panel, previews } = await openEditDialog();
    await waitFor(() => panel.shadowRoot.querySelector('.hk-decl-preview-header'), 5000);

    emitChange(sectionForm(panel, 'trigger'), { mode: 'state' });
    await waitFor(() => panel.shadowRoot.querySelector('.hk-decl-preview-header'), 5000);

    const last = previews[previews.length - 1];
    expect(last.companion.trigger.mode).toBe('state');
    // The keys the new mode rejects went with the old mode (#230).
    expect(last.companion.trigger).not.toHaveProperty('comparison');
    expect(last.companion.trigger).not.toHaveProperty('value');
  });
});
