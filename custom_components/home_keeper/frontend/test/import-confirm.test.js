import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';

// Import writes to the records that match, and the export taken before is the only way
// back. So the Import button asks first: it says how many records are new and how many
// are updated (from the preview), and that the export is the backup.

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
  document.querySelectorAll('.hk-confirm-scrim').forEach((el) => el.remove());
});

const REPORT = {
  ok: true,
  dry_run: true,
  counts: {
    appliances: { created: 0, updated: 1 },
    tasks: { created: 2, updated: 3 },
    completions: 0,
    skips: 0,
  },
  records: [],
  problems: [],
};

async function mountTransfer() {
  const hass = makeHass({ tasks: [] });
  const base = hass.callWS;
  const imports = [];
  hass.callWS = (msg) => {
    if (msg.type === 'home_keeper/import_data') {
      imports.push(!!msg.dry_run);
      return Promise.resolve({ ...REPORT, dry_run: !!msg.dry_run });
    }
    return base(msg);
  };
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings/transfer' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#transfer-import'));
  panel._transfer.text = 'home_keeper:\n  format: 1\n';
  await panel._previewImport();
  return { panel, imports };
}

const scrim = () => document.querySelector('.hk-confirm-scrim');
const button = (label) =>
  [...document.querySelectorAll('.hk-confirm-scrim ha-button')].find((b) => b.textContent === label);
const importButton = (panel) => panel.shadowRoot.querySelector('#transfer-import');
const settle = () => new Promise((r) => setTimeout(r, 30));

describe('Import asks first', () => {
  it('shows the counts of the preview and names the export as the backup', async () => {
    const { panel, imports } = await mountTransfer();
    expect(imports).toEqual([true]);
    importButton(panel).click();

    expect(scrim()).toBeTruthy();
    expect(document.querySelector('#hk-confirm-title').textContent).toBe('Import this document?');
    const body = document.querySelector('#hk-confirm-body').textContent.split('\n');
    expect(body[0]).toBe('New records: 2. Updated records: 4.');
    expect(body[1]).toContain('export is the only way back');
    expect(button('Import')).toBeTruthy();
    // Nothing is written yet: only the preview has run.
    expect(imports).toEqual([true]);
  });

  it('imports only from the Import button of the dialog', async () => {
    const { panel, imports } = await mountTransfer();
    importButton(panel).click();
    button('Import').click();
    await waitFor(() => imports.length === 2);
    expect(imports).toEqual([true, false]);
  });

  it('writes nothing on Cancel, on Escape or on a tap outside', async () => {
    const { panel, imports } = await mountTransfer();
    for (const close of [
      () => button('Cancel').click(),
      () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })),
      () => scrim().click(),
    ]) {
      importButton(panel).click();
      expect(scrim()).toBeTruthy();
      close();
      expect(scrim()).toBeNull();
    }
    await settle();
    expect(imports).toEqual([true]);
  });
});
