/**
 * Where a device chip goes, and how it says so.
 *
 * The chip means different things on different surfaces. On a *task* it means "the
 * appliance this work is about", so it opens that appliance's Home Keeper page — a
 * Home Assistant device page knows nothing about Home Keeper and was never the useful
 * answer there. On an *appliance* it means "the Home Assistant device behind this",
 * so it keeps the device page. A chip that leaves the panel is marked, so the two are
 * told apart before the click.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, mountPanel, waitFor } from './panel-harness.js';

/** A detail page has no Add button, so it cannot go through `mountPanel`. */
async function mountAt(path, hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  return panel;
}

const DEVICES = {
  dev1: { id: 'dev1', name_by_user: 'Garage water heater', config_entries: [] },
  loose: { id: 'loose', name_by_user: 'Hallway thermostat', config_entries: [] },
};

const ASSETS = [
  { id: 'asset1', name: 'Garage water heater', kind: 'existing', device_id: 'dev1' },
];

const TASKS = [
  { id: 't-claimed', name: 'Replace anode rod', device_id: 'dev1', recurrence_type: 'fixed' },
  { id: 't-loose', name: 'Bleed radiator', device_id: 'loose', recurrence_type: 'fixed' },
];

function hass() {
  const h = makeHass({ tasks: TASKS, assets: ASSETS });
  h.devices = DEVICES;
  return h;
}

/** The device chip on the row for *taskId*, wrapper and all. */
function chipFor(panel, taskId) {
  return panel.shadowRoot.querySelector(
    `ha-card.hk-card[data-id="${taskId}"] .hk-device-chip`,
  );
}

describe('device chip destinations', () => {
  beforeEach(() => {
    definePanelStubs();
    history.replaceState(null, '', '/home-keeper/tasks');
  });
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('points a task row at the appliance that claims its device', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    const chip = chipFor(panel, 't-claimed');
    expect(chip.dataset.assetId).toBe('asset1');
    // It stays in the panel, so it carries no leaves-the-panel mark.
    expect(chip.closest('.hk-chip-ext')).toBeNull();
  });

  it('falls back to the device page, and marks it, when no appliance claims the device', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    const chip = chipFor(panel, 't-loose');
    expect(chip.dataset.assetId).toBeUndefined();
    expect(chip.dataset.deviceId).toBe('loose');
    expect(chip.closest('.hk-chip-ext')).not.toBeNull();
  });

  it('opens the appliance page on click, without also opening the task', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    chipFor(panel, 't-claimed').click();
    // The appliance, not `/home-keeper/tasks/t-claimed` — the chip's click must not
    // reach the row opener it sits beside.
    expect(location.pathname).toBe('/home-keeper/appliances/asset1');
  });

  it('sends an unclaimed device to its Home Assistant page', async () => {
    const { panel } = await mountPanel('/tasks', hass());
    chipFor(panel, 't-loose').click();
    expect(location.pathname).toBe('/config/devices/device/loose');
  });

  it('points the task detail page at the appliance too', async () => {
    const panel = await mountAt('/tasks/t-claimed', hass());
    const chip = await waitFor(() =>
      panel.shadowRoot?.querySelector('.hk-device-chip'),
    );
    expect(chip, 'the task page should render its device chip').toBeTruthy();
    expect(chip.dataset.assetId).toBe('asset1');
  });

  it('keeps the appliance list pointed at the Home Assistant device page', async () => {
    const { panel } = await mountPanel('/appliances', hass());
    const chip = await waitFor(() =>
      panel.shadowRoot.querySelector('ha-card.hk-card[data-id="asset1"] .hk-device-chip'),
    );
    // From an appliance the chip means the device behind it, so it leaves the panel
    // and says so.
    expect(chip.dataset.assetId).toBeUndefined();
    expect(chip.closest('.hk-chip-ext')).not.toBeNull();
    chip.click();
    expect(location.pathname).toBe('/config/devices/device/dev1');
  });
});
