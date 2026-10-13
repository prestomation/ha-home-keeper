import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { HomeKeeperCard } from '../src/card.ts';

// #446: a task's device chip on the card is a link, the same as on the panel. It
// opens the appliance page if an appliance has the device. The panel shows that
// page to every user (#444). Else an admin gets the device page, which is
// admin-only, so for other users the chip is then plain. The row shows 1 chip for
// the place: the device chip if the task has a device, else the area chip.
beforeAll(() => {
  for (const tag of ['ha-card', 'ha-icon-button', 'ha-assist-chip', 'ha-alert', 'ha-spinner', 'ha-icon']) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-card')) {
    customElements.define('home-keeper-card', HomeKeeperCard);
  }
});

afterEach(() => {
  document.body.innerHTML = '';
  history.replaceState(null, '', '/');
});

async function waitFor(fn, timeout = 2000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (fn()) return true;
    await new Promise((r) => setTimeout(r, 20));
  }
  return false;
}

const task = {
  id: 't1',
  name: 'Clean filter',
  recurrence_type: 'floating',
  interval: 1,
  unit: 'months',
  next_due: new Date(Date.now() + 86_400_000).toISOString(),
  completions: [],
  device_id: 'dev1',
  area_id: 'kitchen',
};

function mount({ admin, assets = [], config = {}, row = task }) {
  const card = document.createElement('home-keeper-card');
  card.setConfig({ type: 'custom:home-keeper-card', ...config });
  document.body.appendChild(card);
  const calls = [];
  card.hass = {
    language: 'en',
    user: { is_admin: admin },
    devices: { dev1: { id: 'dev1', name: 'Dishwasher' } },
    areas: { kitchen: { area_id: 'kitchen', name: 'Kitchen' } },
    callWS: async (msg) => {
      calls.push(msg.type);
      if (msg.type === 'home_keeper/get_assets') return { assets };
      return { tasks: [row] };
    },
  };
  return { card, calls };
}

const chips = (card) => [...card.shadowRoot.querySelectorAll('.hk-row ha-assist-chip')];

describe('card device chip (#446)', () => {
  it('opens the appliance page for an admin when an appliance has the device', async () => {
    const { card } = mount({ admin: true, assets: [{ id: 'a1', name: 'Dishwasher', device_id: 'dev1' }] });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-device-chip'));
    const chip = card.shadowRoot.querySelector('.hk-device-chip');
    expect(chip.getAttribute('label')).toBe('Dishwasher');
    expect(chip.dataset.href).toBe('/home-keeper/appliances/a1');
    const events = [];
    window.addEventListener('location-changed', (e) => events.push(e), { once: true });
    chip.click();
    expect(location.pathname).toBe('/home-keeper/appliances/a1');
    expect(events).toHaveLength(1);
  });

  it('opens the device page for an admin when no appliance has the device', async () => {
    const { card } = mount({ admin: true });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-device-chip'));
    const chip = card.shadowRoot.querySelector('.hk-device-chip');
    expect(chip.dataset.href).toBe('/config/devices/device/dev1');
    chip.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(location.pathname).toBe('/config/devices/device/dev1');
  });

  it('shows only the device chip when the task has an area and a device', async () => {
    const { card } = mount({ admin: true });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-device-chip'));
    const labels = chips(card).map((c) => c.getAttribute('label'));
    expect(labels).toContain('Dishwasher');
    expect(labels).not.toContain('Kitchen');
  });

  it('shows only the device chip for a non-admin when the task has an area and a device', async () => {
    const { card } = mount({ admin: false });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-row'));
    const labels = chips(card).map((c) => c.getAttribute('label'));
    expect(labels).toContain('Dishwasher');
    expect(labels).not.toContain('Kitchen');
  });

  it('shows the area chip when the task has an area and no device', async () => {
    const { card } = mount({ admin: true, row: { ...task, device_id: null } });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-row'));
    const labels = chips(card).map((c) => c.getAttribute('label'));
    expect(labels).toContain('Kitchen');
    expect(labels).not.toContain('Dishwasher');
    expect(card.shadowRoot.querySelector('.hk-device-chip')).toBeNull();
  });

  it('shows the area chip when the device name does not resolve', async () => {
    const { card } = mount({ admin: true, row: { ...task, device_id: 'gone' } });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-row'));
    const labels = chips(card).map((c) => c.getAttribute('label'));
    expect(labels).toContain('Kitchen');
    expect(card.shadowRoot.querySelector('.hk-device-chip')).toBeNull();
  });

  it('shows the device chip when the task has a device and no area', async () => {
    const { card } = mount({ admin: true, row: { ...task, area_id: null } });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-device-chip'));
    const labels = chips(card).map((c) => c.getAttribute('label'));
    expect(labels).toContain('Dishwasher');
    expect(labels).not.toContain('Kitchen');
  });

  it('shows no place chip when the task has no area and no device', async () => {
    const { card } = mount({ admin: true, row: { ...task, area_id: null, device_id: null } });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-row'));
    const labels = chips(card).map((c) => c.getAttribute('label'));
    expect(labels).not.toContain('Dishwasher');
    expect(labels).not.toContain('Kitchen');
  });

  it('opens the appliance page for a non-admin too (#444)', async () => {
    const { card, calls } = mount({
      admin: false,
      assets: [{ id: 'a1', name: 'Dishwasher', device_id: 'dev1' }],
    });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-device-chip'));
    const chip = card.shadowRoot.querySelector('.hk-device-chip');
    expect(chip.dataset.href).toBe('/home-keeper/appliances/a1');
    expect(calls).toContain('home_keeper/get_assets');
  });

  it('is a plain chip for a non-admin when no appliance has the device', async () => {
    const { card } = mount({ admin: false });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-row'));
    expect(card.shadowRoot.querySelector('.hk-device-chip')).toBeNull();
    expect(chips(card).map((c) => c.getAttribute('label'))).toContain('Dishwasher');
  });

  it('shows no place chip when show_area is off', async () => {
    const { card } = mount({ admin: true, config: { show_area: false } });
    await waitFor(() => card.shadowRoot?.querySelector('.hk-row'));
    const labels = chips(card).map((c) => c.getAttribute('label'));
    expect(labels).not.toContain('Dishwasher');
    expect(labels).not.toContain('Kitchen');
  });
});
