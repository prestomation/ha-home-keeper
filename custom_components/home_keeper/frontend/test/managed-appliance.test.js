/**
 * An appliance an integration owns.
 *
 * Battery Notes keeps a "Batteries" appliance with one part per battery type: it
 * writes the name and the part list, and it rewrites both on every reconcile pass.
 * The counts are the user's and always were — how many AAA are in the drawer, at
 * what point to buy more, how big a pack is.
 *
 * So the page splits along that line. The chip says who owns it, a caption says what
 * is theirs and what is still the user's, Edit and Delete go (they would edit a name
 * the owner rewrites, or delete an appliance it recreates), Archive stays, Add part
 * goes, and every stock control stays exactly where it was.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, waitFor } from './panel-harness.js';

beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const GLUE_ENTRY = 'glue-entry-1';

const OWNER = {
  integration: 'home_keeper_battery_notes',
  display_name: 'Battery Notes',
  icon: 'mdi:battery-alert',
  config_entry_id: GLUE_ENTRY,
  deletion_protected: true,
  locked_fields: ['name', 'parts'],
};

/** The pool as the glue keeps it: AAA counted and low, 9V added but not yet counted. */
function batteries(overrides = {}) {
  return {
    id: 'a-bat',
    name: 'Batteries',
    kind: 'virtual',
    parts: [
      {
        id: 'p-aaa',
        name: 'AAA',
        type: 'consumable',
        stock: 2,
        reorder_at: 4,
        restock_quantity: 12,
        notes: 'Used by 4 devices · 7 installed — Front door sensor (2)',
      },
      {
        id: 'p-9v',
        name: '9V',
        type: 'consumable',
        stock: null,
        notes: 'Used by 1 device · 1 installed — Smoke detector (1)',
      },
    ],
    metadata: [],
    managed_by: OWNER,
    source: { home_keeper_battery_notes: { role: 'battery_stock' } },
    ...overrides,
  };
}

/** An appliance the user made, for the "nothing changed here" half of each check. */
const OWN_ASSET = {
  id: 'a-own',
  name: 'Garage water heater',
  kind: 'virtual',
  parts: [{ id: 'p-anode', name: 'Anode rod', type: 'consumable', stock: 1, notes: 'Magnesium' }],
  metadata: [],
};

const REPLACE_TASK = {
  id: 't-door',
  name: 'Replace battery: Front door sensor',
  recurrence_type: 'triggered',
  enabled: true,
  completions: [],
  next_due: '2026-01-01T00:00:00+00:00',
  source: { part: { asset_id: 'a-bat', part_id: 'p-aaa', manual: true, quantity: 2 } },
};

function makeHass({ tasks = [], assets = [], entryState = 'loaded' } = {}) {
  return {
    language: 'en',
    states: {},
    devices: {},
    callWS(msg) {
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets });
        case 'home_keeper/get_options':
          return Promise.resolve({ options: {} });
        case 'home_keeper/list_declarative_companions':
          return Promise.resolve({ companions: [] });
        case 'config_entries/get':
          return Promise.resolve([
            { entry_id: GLUE_ENTRY, domain: 'home_keeper_battery_notes', state: entryState },
          ]);
        case 'frontend/get_user_data':
          return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
        default:
          return Promise.resolve({});
      }
    },
  };
}

async function mountAt(path, hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  const head = await waitFor(() => panel.shadowRoot?.querySelector('.hk-detail-card'), 5000);
  expect(head, `the ${path} page should paint`).toBeTruthy();
  return panel;
}

/** A list view has no detail card; its first paint is the Add button. */
async function mountList(path, hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = hass;
  const add = await waitFor(() => panel.shadowRoot?.querySelector('#add-btn'), 5000);
  expect(add, `the ${path} list should paint`).toBeTruthy();
  return panel;
}

const chipLabels = (root, selector) =>
  [...root.querySelectorAll(`${selector} ha-assist-chip`)].map((c) => c.getAttribute('label'));

describe('the head of an appliance an integration owns', () => {
  it('names the owner on a chip', async () => {
    const panel = await mountAt('/appliances/a-bat', makeHass({ assets: [batteries()] }));
    expect(chipLabels(panel.shadowRoot, '.hk-asset-head .hk-chips')).toContain(
      'Managed by Battery Notes',
    );
  });

  it('says what is the owner’s and what is still the user’s', async () => {
    const panel = await mountAt('/appliances/a-bat', makeHass({ assets: [batteries()] }));
    const captions = [
      ...panel.shadowRoot.querySelectorAll('.hk-detail-actions .hk-managed-info'),
    ].map((el) => el.textContent.trim());
    expect(captions).toContain('Battery Notes sets the name and the part list. You set the counts.');
  });

  it('withholds Edit and Delete, and keeps Archive', async () => {
    const panel = await mountAt('/appliances/a-bat', makeHass({ assets: [batteries()] }));
    const root = panel.shadowRoot;
    // Edit would open a drawer over a name the next reconcile rewrites; Delete would
    // remove an appliance the owner puts straight back.
    expect(root.querySelector('.d-edit')).toBeNull();
    expect(root.querySelector('.d-del')).toBeNull();
    // Hiding an appliance is the user's call whoever owns it.
    expect(root.querySelector('.d-archive')).toBeTruthy();
  });

  it('says the owner is offline once its integration is gone', async () => {
    const panel = await mountAt(
      '/appliances/a-bat',
      makeHass({ assets: [batteries()], entryState: 'not_loaded' }),
    );
    expect(chipLabels(panel.shadowRoot, '.hk-asset-head .hk-chips')).toContain(
      'Integration offline',
    );
  });

  it('keeps Edit and Delete when the owner writes no name', async () => {
    // `locked_fields` is a partial contract: an owner that only keeps the part list
    // in step leaves the appliance's own identity to the user.
    const partsOnly = batteries({
      managed_by: { ...OWNER, locked_fields: ['parts'] },
    });
    const panel = await mountAt('/appliances/a-bat', makeHass({ assets: [partsOnly] }));
    expect(panel.shadowRoot.querySelector('.d-edit')).toBeTruthy();
    expect(panel.shadowRoot.querySelector('.d-del')).toBeTruthy();
    // The chip still names who keeps the list.
    expect(chipLabels(panel.shadowRoot, '.hk-asset-head .hk-chips')).toContain(
      'Managed by Battery Notes',
    );
  });

  it('leaves an appliance nobody owns exactly as it was', async () => {
    const panel = await mountAt('/appliances/a-own', makeHass({ assets: [OWN_ASSET] }));
    const root = panel.shadowRoot;
    expect(root.querySelector('.d-edit')).toBeTruthy();
    expect(root.querySelector('.d-del')).toBeTruthy();
    expect(root.querySelector('.hk-detail-actions .hk-managed-info')).toBeNull();
    expect(chipLabels(root, '.hk-asset-head .hk-chips')).not.toContain('Managed by Battery Notes');
  });
});

describe('the parts of an appliance whose list its owner writes', () => {
  it('replaces Add part with who writes the list', async () => {
    const panel = await mountAt('/appliances/a-bat', makeHass({ assets: [batteries()] }));
    const root = panel.shadowRoot;
    // A part added here would be deleted by the owner's next pass.
    expect(root.querySelector('.d-add-part')).toBeNull();
    const caption = root.querySelector('.hk-section-row .hk-managed-info');
    expect(caption?.textContent.trim()).toBe('Part list set by Battery Notes');
  });

  it('keeps every stock control, because the counts are the user’s', async () => {
    const panel = await mountAt('/appliances/a-bat', makeHass({ assets: [batteries()] }));
    const stepper = panel.shadowRoot.querySelector('.hk-stock[data-part="p-aaa"]');
    expect(stepper, 'the counted part still has its stepper').toBeTruthy();
    expect(stepper.querySelector('.hk-stock-input').value).toBe('2');
    // Still low against the threshold the user set, still saying so.
    expect(stepper.classList.contains('low')).toBe(true);
  });

  it('offers Start counting on a part the owner has just added', async () => {
    const panel = await mountAt('/appliances/a-bat', makeHass({ assets: [batteries()] }));
    const rows = [...panel.shadowRoot.querySelectorAll('.hk-part-row')];
    const start = panel.shadowRoot.querySelectorAll('.hk-start-counting');
    expect(start).toHaveLength(1);
    expect(start[0].textContent.trim()).toBe('Start counting');
    // On the untracked row, and on that row alone: a counted part has a stepper.
    expect(start[0].dataset.partIdx).toBe('1');
    expect(rows[1].contains(start[0])).toBe(true);
    expect(rows[1].querySelector('.hk-stock')).toBeNull();
  });

  it('opens that part in the editor, where the first number starts the count', async () => {
    const panel = await mountAt('/appliances/a-bat', makeHass({ assets: [batteries()] }));
    panel.shadowRoot.querySelector('.hk-start-counting').click();
    const form = await waitFor(() => panel.shadowRoot?.querySelector('#hk-asset-form'));
    expect(form, 'the appliance drawer should open').toBeTruthy();
    expect(panel._assetEdit.openPart).toBe(1);
  });

  it('reads the owner’s usage line a shade quieter than a note the user wrote', async () => {
    const owned = await mountAt('/appliances/a-bat', makeHass({ assets: [batteries()] }));
    const usage = owned.shadowRoot.querySelector('.hk-part-notes.hk-part-usage');
    expect(usage, 'the owner’s note carries the usage class').toBeTruthy();
    expect(usage.textContent).toContain('Used by 4 devices');
  });

  it('leaves Add part, and the plain note, on an appliance nobody owns', async () => {
    const panel = await mountAt('/appliances/a-own', makeHass({ assets: [OWN_ASSET] }));
    const root = panel.shadowRoot;
    expect(root.querySelector('.d-add-part')).toBeTruthy();
    expect(root.querySelector('.hk-section-row .hk-managed-info')).toBeNull();
    expect(root.querySelector('.hk-part-notes')).toBeTruthy();
    expect(root.querySelector('.hk-part-usage')).toBeNull();
    expect(root.querySelector('.hk-start-counting')).toBeNull();
  });
});

describe('the drawer for an owned appliance', () => {
  it('offers the counts and withholds the owner’s fields', async () => {
    // Reached from the appliance list rather than the page, which withholds Edit.
    const panel = await mountList('/appliances', makeHass({ assets: [batteries()] }));
    panel._openEditAsset(batteries(), { part: 0 });
    const form = await waitFor(() => panel.shadowRoot?.querySelector('#hk-asset-form'));
    expect(form).toBeTruthy();
    const root = panel.shadowRoot;
    // No way to add a row the owner would delete, and no way to delete one it
    // would put back.
    expect(root.querySelector('#a-add-part')).toBeNull();
    expect(root.querySelector('.part-del')).toBeNull();
    // The rows themselves are still there, one form each, so the counts can be typed.
    expect(root.querySelectorAll('details.hk-part')).toHaveLength(2);
  });

  it('keeps both controls on an appliance nobody owns', async () => {
    const panel = await mountList('/appliances', makeHass({ assets: [OWN_ASSET] }));
    panel._openEditAsset(OWN_ASSET, { part: 0 });
    await waitFor(() => panel.shadowRoot?.querySelector('#hk-asset-form'));
    expect(panel.shadowRoot.querySelector('#a-add-part')).toBeTruthy();
    expect(panel.shadowRoot.querySelector('.part-del')).toBeTruthy();
  });
});

describe('the stock chip on a task that spends spares', () => {
  const rowChips = (panel, id) =>
    [...panel.shadowRoot.querySelectorAll(`ha-card.hk-card[data-id="${id}"] .hk-chips ha-assist-chip`)]
      .map((c) => c.getAttribute('label'));

  it('says what one completion takes and what is left', async () => {
    const panel = await mountList(
      '/tasks',
      makeHass({ tasks: [REPLACE_TASK], assets: [batteries()] }),
    );
    await waitFor(() => panel.shadowRoot?.querySelector('ha-card.hk-card'));
    expect(rowChips(panel, 't-door')).toContain('Takes 2 AAA · 2 left');
  });

  it('carries the same chip onto the task’s own page', async () => {
    const panel = await mountAt(
      '/tasks/t-door',
      makeHass({ tasks: [REPLACE_TASK], assets: [batteries()] }),
    );
    expect(chipLabels(panel.shadowRoot, '.hk-asset-head .hk-chips')).toContain(
      'Takes 2 AAA · 2 left',
    );
  });

  it('falls back to the part’s own amount when the link names none', async () => {
    const noQty = {
      ...REPLACE_TASK,
      source: { part: { asset_id: 'a-bat', part_id: 'p-aaa', manual: true } },
    };
    const pool = batteries();
    pool.parts[0].consume_quantity = 4;
    const panel = await mountAt('/tasks/t-door', makeHass({ tasks: [noQty], assets: [pool] }));
    expect(chipLabels(panel.shadowRoot, '.hk-asset-head .hk-chips')).toContain(
      'Takes 4 AAA · 2 left',
    );
  });

  it('takes one whole spare when neither says otherwise', async () => {
    const noQty = {
      ...REPLACE_TASK,
      source: { part: { asset_id: 'a-bat', part_id: 'p-aaa', manual: true } },
    };
    const panel = await mountAt('/tasks/t-door', makeHass({ tasks: [noQty], assets: [batteries()] }));
    expect(chipLabels(panel.shadowRoot, '.hk-asset-head .hk-chips')).toContain(
      'Takes 1 AAA · 2 left',
    );
  });

  it('carries the unit on a part that is measured rather than counted', async () => {
    const pool = batteries();
    pool.parts[0] = { ...pool.parts[0], name: 'Coolant', stock: 750, stock_unit: 'ml' };
    const task = {
      ...REPLACE_TASK,
      source: { part: { asset_id: 'a-bat', part_id: 'p-aaa', manual: true, quantity: 250 } },
    };
    const panel = await mountAt('/tasks/t-door', makeHass({ tasks: [task], assets: [pool] }));
    expect(chipLabels(panel.shadowRoot, '.hk-asset-head .hk-chips')).toContain(
      'Takes 250 ml Coolant · 750 ml left',
    );
  });

  it('says nothing about a part that tracks no stock', async () => {
    // "Takes 1 9V · left" about a shelf nobody counts is worse than no chip.
    const untracked = {
      ...REPLACE_TASK,
      source: { part: { asset_id: 'a-bat', part_id: 'p-9v', manual: true } },
    };
    const panel = await mountAt(
      '/tasks/t-door',
      makeHass({ tasks: [untracked], assets: [batteries()] }),
    );
    const labels = chipLabels(panel.shadowRoot, '.hk-asset-head .hk-chips');
    expect(labels.some((l) => l.includes('Takes'))).toBe(false);
  });

  it('says nothing when the part, or the appliance, has gone', async () => {
    const gone = {
      ...REPLACE_TASK,
      source: { part: { asset_id: 'a-bat', part_id: 'p-missing', manual: true, quantity: 2 } },
    };
    const panel = await mountAt('/tasks/t-door', makeHass({ tasks: [gone], assets: [batteries()] }));
    expect(
      chipLabels(panel.shadowRoot, '.hk-asset-head .hk-chips').some((l) => l.includes('Takes')),
    ).toBe(false);

    const noAsset = await mountAt('/tasks/t-door', makeHass({ tasks: [REPLACE_TASK], assets: [] }));
    expect(
      chipLabels(noAsset.shadowRoot, '.hk-asset-head .hk-chips').some((l) => l.includes('Takes')),
    ).toBe(false);
  });

  it('leaves a task with no consumable link alone', async () => {
    const plain = { ...REPLACE_TASK, source: null };
    const panel = await mountAt('/tasks/t-door', makeHass({ tasks: [plain], assets: [batteries()] }));
    expect(
      chipLabels(panel.shadowRoot, '.hk-asset-head .hk-chips').some((l) => l.includes('Takes')),
    ).toBe(false);
  });
});
