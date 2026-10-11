/**
 * Settings → Import and export.
 *
 * The behaviour worth pinning is the two-step gate. An import writes tasks and
 * appliances wholesale, and the document is often generated rather than typed, so
 * Import must stay disabled until a preview of *exactly this text* came back clean —
 * and editing the text has to take that permission away again.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { HomeKeeperPanel } from '../src/panel.ts';

beforeAll(() => {
  for (const tag of [
    'ha-card',
    'ha-form',
    'ha-button',
    'ha-icon-button',
    'ha-tab-group',
    'ha-tab-group-tab',
    'ha-alert',
    'ha-assist-chip',
    'ha-menu-button',
    'ha-svg-icon',
    'ha-spinner',
    'ha-icon',
  ]) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-panel')) {
    customElements.define('home-keeper-panel', HomeKeeperPanel);
  }
});

async function waitFor(fn, timeout = 2000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const v = fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, 20));
  }
  return null;
}

const OK_REPORT = {
  ok: true,
  dry_run: true,
  counts: { appliances: { created: 0, updated: 0 }, tasks: { created: 2, updated: 1 }, completions: 5, skips: 0 },
  records: [],
  problems: [],
};

const BAD_REPORT = {
  ok: false,
  dry_run: true,
  counts: { appliances: { created: 0, updated: 0 }, tasks: { created: 0, updated: 0 }, completions: 0, skips: 0 },
  records: [],
  problems: [
    { section: 'tasks', index: 1, path: 'tasks[1].interval', message: 'interval must be at least 1', severity: 'error' },
    { section: 'tasks', index: 0, path: 'tasks[0].priority', message: '"priority" is not a field this version reads', severity: 'warning' },
  ],
};

function makeHass(report = OK_REPORT) {
  const calls = [];
  const hass = {
    language: 'en',
    states: {},
    callWS(msg) {
      calls.push(msg);
      switch (msg.type) {
        case 'home_keeper/get_tasks':
          return Promise.resolve({ tasks: [] });
        case 'home_keeper/get_assets':
          return Promise.resolve({ assets: [] });
        case 'config_entries/get':
          return Promise.resolve([]);
        case 'config/label_registry/list':
          return Promise.resolve([]);
        case 'home_keeper/get_options':
          return Promise.resolve({
            options: {
              sync_problem_sensors: false,
              problem_sensor_exclude_entities: [],
              problem_sensor_exclude_areas: [],
              problem_sensor_exclude_labels: [],
              dismissed_companions: [],
            },
          });
        case 'home_keeper/get_companions':
          return Promise.resolve({ companions: [] });
        case 'home_keeper/export_data':
          return Promise.resolve({
            document: { home_keeper: { format: 1 } },
            yaml: '# yaml-language-server: $schema=https://example/s.json\nhome_keeper:\n  format: 1\n',
          });
        case 'home_keeper/import_data':
          return Promise.resolve({ ...report, dry_run: !!msg.dry_run });
        default:
          return Promise.resolve({});
      }
    },
  };
  return { hass, calls };
}

afterEach(() => {
  document.body.innerHTML = '';
});

async function mount(hass) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('#hk-transfer'));
  return panel;
}

const buttons = (root) => ({
  preview: root.querySelector('#transfer-preview'),
  run: root.querySelector('#transfer-import'),
  exportBtn: root.querySelector('#transfer-export'),
});

async function type(panel, text) {
  const box = panel.shadowRoot.querySelector('#transfer-text');
  box.value = text;
  box.dispatchEvent(new Event('input'));
  await Promise.resolve();
}

describe('Settings — Import and export', () => {
  it('renders the card with both halves', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    const root = panel.shadowRoot;
    expect(root.querySelector('#hk-transfer')).toBeTruthy();
    expect(buttons(root).exportBtn).toBeTruthy();
    expect(root.querySelector('#transfer-text')).toBeTruthy();
    expect(root.querySelector('#transfer-pick')).toBeTruthy();
  });

  it('uses a native textarea, so the box shows without a lazy HA element', async () => {
    // HA loads ha-textarea lazily and the panel does not load it. This file registers
    // no ha-textarea, so only a native element can render a usable box here.
    const { hass } = makeHass();
    const panel = await mount(hass);
    const root = panel.shadowRoot;
    const box = root.querySelector('#transfer-text');
    expect(box.tagName).toBe('TEXTAREA');
    expect(box.classList.contains('hk-note-input')).toBe(true);
    expect(box.disabled).toBe(false);
    const label = root.querySelector('label[for="transfer-text"]');
    expect(label?.textContent).toBe('Document');
    const help = root.querySelector(`#${box.getAttribute('aria-describedby')}`);
    expect(help?.textContent).toBe(
      'The contents of an exported file, or a file written in the same shape.',
    );
  });

  it('escapes the label and the helper text', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    const root = panel.shadowRoot;
    expect(root.querySelector('label[for="transfer-text"] *')).toBeNull();
    expect(root.querySelector('#transfer-text-help *')).toBeNull();
  });

  it('disables the box while a preview runs and keeps the text', async () => {
    const { hass } = makeHass();
    let release;
    const callWS = hass.callWS;
    hass.callWS = (msg) =>
      msg.type === 'home_keeper/import_data'
        ? new Promise((r) => { release = () => r(callWS(msg)); })
        : callWS(msg);
    const panel = await mount(hass);
    await type(panel, 'tasks: []\n');
    const pending = panel._previewImport();
    const busyBox = await waitFor(() => panel.shadowRoot.querySelector('#transfer-text[disabled]'));
    expect(busyBox).toBeTruthy();
    expect(busyBox.value).toBe('tasks: []\n');
    release();
    await pending;
    const box = panel.shadowRoot.querySelector('#transfer-text');
    expect(box.disabled).toBe(false);
    expect(box.value).toBe('tasks: []\n');
  });

  it('links to the documentation for the file format', async () => {
    // The card asks a user to understand a file format. The link is the only thing on
    // it that says where that format is written down, and it is markup rather than
    // behaviour, so nothing else here would notice it going missing.
    const { hass } = makeHass();
    const panel = await mount(hass);
    const link = panel.shadowRoot.querySelector('#hk-transfer a[href]');
    expect(link).toBeTruthy();
    expect(link.getAttribute('href')).toBe(
      'https://prestomation.github.io/ha-home-keeper/docs/guide/import-export',
    );
    // Opened in a new tab, and without handing the docs site a window opener.
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
  });

  it('disables both import buttons until there is a document', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    const { preview, run } = buttons(panel.shadowRoot);
    expect(preview.hasAttribute('disabled')).toBe(true);
    expect(run.hasAttribute('disabled')).toBe(true);
  });

  it('enables Preview once text is entered, but not Import', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    await type(panel, '{"home_keeper":{"format":1}}');
    const { preview, run } = buttons(panel.shadowRoot);
    expect(preview.hasAttribute('disabled')).toBe(false);
    // Import is still shut: nothing has told the user what it would do yet.
    expect(run.hasAttribute('disabled')).toBe(true);
  });

  it('previews as a dry run and only then unlocks Import', async () => {
    const { hass, calls } = makeHass();
    const panel = await mount(hass);
    await type(panel, '{"home_keeper":{"format":1}}');
    await panel._previewImport();
    const imports = calls.filter((c) => c.type === 'home_keeper/import_data');
    expect(imports).toHaveLength(1);
    expect(imports[0].dry_run).toBe(true);
    expect(buttons(panel.shadowRoot).run.hasAttribute('disabled')).toBe(false);
  });

  it('shows what a preview would change', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    await type(panel, '{"home_keeper":{"format":1}}');
    await panel._previewImport();
    const root = panel.shadowRoot;
    const cells = (part) =>
      [...root.querySelectorAll(`tr[data-part="${part}"] td`)].map((td) => td.textContent);
    expect(cells('tasks').slice(0, 2)).toEqual(['2', '1']);
    expect(cells('appliances').slice(0, 2)).toEqual(['0', '0']);
    expect(cells('tasks')[2]).toContain('History entries: 5');
  });

  it('keeps Import shut when the preview found errors, and lists them', async () => {
    const { hass } = makeHass(BAD_REPORT);
    const panel = await mount(hass);
    await type(panel, '{"home_keeper":{"format":1}}');
    await panel._previewImport();
    const root = panel.shadowRoot;
    expect(buttons(root).run.hasAttribute('disabled')).toBe(true);
    const text = root.querySelector('#hk-transfer').textContent;
    expect(text).toContain('tasks[1].interval');
    expect(text).toContain('interval must be at least 1');
    // A warning is reported too — a field nobody read is data that did not arrive.
    expect(text).toContain('tasks[0].priority');
  });

  it('lists errors before warnings', async () => {
    const { hass } = makeHass(BAD_REPORT);
    const panel = await mount(hass);
    await type(panel, '{"home_keeper":{"format":1}}');
    await panel._previewImport();
    const items = [...panel.shadowRoot.querySelectorAll('td.hk-transfer-notes li')];
    expect(items.map((li) => li.className)).toEqual(['error', 'warning']);
  });

  it('withdraws Import the moment the document is edited', async () => {
    // Otherwise a preview of one document would license importing another.
    const { hass } = makeHass();
    const panel = await mount(hass);
    await type(panel, '{"home_keeper":{"format":1}}');
    await panel._previewImport();
    expect(buttons(panel.shadowRoot).run.hasAttribute('disabled')).toBe(false);

    await type(panel, '{"home_keeper":{"format":1},"tasks":[]}');
    expect(buttons(panel.shadowRoot).run.hasAttribute('disabled')).toBe(true);
    expect(panel._transfer.report).toBeNull();
  });

  it('sends the pasted text over as text, so one parser reads it', async () => {
    // There is no YAML parser in the bundle. The backend reads the file, which is why
    // a syntax error can come back naming a line and a column — something a parse in
    // the browser could not have produced.
    const { hass, calls } = makeHass();
    const panel = await mount(hass);
    await type(panel, 'tasks:\n  - name: A\n');
    await panel._previewImport();
    const imports = calls.filter((c) => c.type === 'home_keeper/import_data');
    expect(imports).toHaveLength(1);
    expect(imports[0].document).toBe('tasks:\n  - name: A\n');
  });

  it('renders a syntax error the backend located', async () => {
    const { hass } = makeHass({
      ...BAD_REPORT,
      problems: [
        {
          section: 'home_keeper',
          index: null,
          path: 'line 3, column 4',
          message: 'this file is not valid YAML: bad indentation. Check the indentation.',
          severity: 'error',
        },
      ],
    });
    const panel = await mount(hass);
    await type(panel, 'tasks:\n  - name: A\n   bad: B\n');
    await panel._previewImport();
    const card = panel.shadowRoot.querySelector('#hk-transfer').textContent;
    expect(card).toContain('line 3, column 4');
    expect(card).toContain('not valid YAML');
    expect(buttons(panel.shadowRoot).run.hasAttribute('disabled')).toBe(true);
  });

  it('runs the real import with dry_run off', async () => {
    const { hass, calls } = makeHass({ ...OK_REPORT, dry_run: false });
    const panel = await mount(hass);
    await type(panel, '{"home_keeper":{"format":1}}');
    await panel._previewImport();
    await panel._runImport();
    const imports = calls.filter((c) => c.type === 'home_keeper/import_data');
    expect(imports.map((c) => c.dry_run)).toEqual([true, false]);
  });

  it('re-reads tasks and appliances after a real import', async () => {
    // The import rewrote both wholesale, so the panel's copy is the stale one.
    const { hass, calls } = makeHass({ ...OK_REPORT, dry_run: false });
    const panel = await mount(hass);
    await type(panel, '{"home_keeper":{"format":1}}');
    const before = calls.filter((c) => c.type === 'home_keeper/get_tasks').length;
    await panel._runImport();
    const after = calls.filter((c) => c.type === 'home_keeper/get_tasks').length;
    expect(after).toBeGreaterThan(before);
  });

  it('takes the error message down as soon as the document is edited', async () => {
    // The error alert is drawn beside the report rather than inside it, so the
    // handler that clears the report has to clear this too. It did not, and the
    // message outlived its text: a refusal stayed on screen, still describing a
    // document the reader had already replaced.
    const { hass } = makeHass();
    const panel = await mount(hass);
    await type(panel, 'x'.repeat(5 * 1024 * 1024));
    await panel._previewImport();
    expect(panel.shadowRoot.querySelector('.hk-transfer-error')).toBeTruthy();
    await type(panel, '{"home_keeper":{"format":1}}');
    expect(panel.shadowRoot.querySelector('.hk-transfer-error')).toBe(null);
    expect(panel._transfer.error).toBe('');
  });

  it('shuts Import once the import has run, so it cannot be applied twice', async () => {
    // The report left behind by a finished import is not a preview. Pressing a still
    // lit Import ran the document a second time, and a document holding two records
    // of one name then failed on the ambiguity the first press had created.
    const { hass } = makeHass({ ...OK_REPORT, dry_run: false });
    const panel = await mount(hass);
    await type(panel, '{"home_keeper":{"format":1}}');
    await panel._runImport();
    expect(panel._transfer.report?.ok).toBe(true);
    expect(buttons(panel.shadowRoot).run.hasAttribute('disabled')).toBe(true);
    // Preview stays available, so the way forward is to look again first.
    expect(buttons(panel.shadowRoot).preview.hasAttribute('disabled')).toBe(false);
  });

  it('asks the backend for the export when Export is pressed', async () => {
    const { hass, calls } = makeHass();
    const panel = await mount(hass);
    await panel._exportData();
    expect(calls.some((c) => c.type === 'home_keeper/export_data')).toBe(true);
  });

  // ── The websocket ceiling ─────────────────────────────────────────────────
  //
  // Found by pasting a 5 MB document into the running panel. Home Assistant does not
  // fail the command past aiohttp's 4 MiB default: it closes the connection
  // ("Decompressed message exceeds size limit 4194304"), so the card could only show
  // a generic failure, and pressing the button again dropped the connection again.
  // The backend's own 8 MiB message sits on the far side of a socket the document
  // cannot cross.

  it('refuses a document too large for the websocket, without sending it', async () => {
    const { hass, calls } = makeHass();
    const panel = await mount(hass);
    await type(panel, 'x'.repeat(5 * 1024 * 1024));
    await panel._previewImport();
    expect(calls.some((c) => c.type === 'home_keeper/import_data')).toBe(false);
    const alert = panel.shadowRoot.querySelector('#hk-transfer ha-alert');
    expect(alert?.getAttribute('alert-type')).toBe('error');
    // The number in the message is the panel's ceiling, not the backend's 8.
    expect(alert.textContent).toContain('4');
    expect(panel._transfer.report).toBe(null);
  });

  it('holds Import shut after refusing an oversized document', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    await type(panel, 'x'.repeat(5 * 1024 * 1024));
    await panel._previewImport();
    expect(buttons(panel.shadowRoot).run.hasAttribute('disabled')).toBe(true);
  });

  it('sends a document that fits', async () => {
    // The other side of the boundary: the guard must not refuse an ordinary file.
    const { hass, calls } = makeHass();
    const panel = await mount(hass);
    await type(panel, '{"home_keeper":{"format":1}}');
    await panel._previewImport();
    expect(calls.some((c) => c.type === 'home_keeper/import_data')).toBe(true);
  });

  it('saves the export as a YAML file', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    const saved = [];
    panel._downloadFile = (name, contents, mime) => saved.push({ name, contents, mime });
    await panel._exportData();
    expect(saved).toHaveLength(1);
    expect(saved[0].name).toMatch(/^home-keeper-\d{4}-\d{2}-\d{2}\.yaml$/);
    expect(saved[0].mime).toBe('application/yaml');
    // The modeline the backend writes rides through untouched: it is what makes an
    // exported file self-validating in an editor.
    expect(saved[0].contents).toContain('# yaml-language-server: $schema=');
  });
});

describe('F03-4: the import file picker', () => {
  /** Pick *file* on the card's hidden file input. */
  async function pick(panel, file) {
    const picker = panel.shadowRoot.querySelector('#hk-transfer input[type="file"]')
      ?? panel.shadowRoot.querySelector('input[type="file"]');
    expect(picker, 'the card should hold a file picker').toBeTruthy();
    Object.defineProperty(picker, 'files', { value: [file], configurable: true });
    picker.dispatchEvent(new Event('change'));
    await new Promise((r) => setTimeout(r, 0));
  }

  it('refuses a file over the limit before it reads it', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    let read = 0;
    const big = {
      name: 'big.yaml',
      size: 8 * 1024 * 1024 + 1,
      text: () => {
        read++;
        return Promise.resolve('x');
      },
    };
    await pick(panel, big);
    expect(read).toBe(0);
    expect(panel._transfer.text).toBe('');
    expect(panel._transfer.file).toBe(null);
    expect(panel._transfer.error).toBe(
      'This file is over the 8 MB limit. Split it into smaller files.',
    );
    // A file at the limit is read.
    await pick(panel, { ...big, size: 4 * 1024 * 1024 });
    expect(read).toBe(1);
    expect(panel._transfer.text).toBe('x');
    expect(panel._transfer.error).toBe('');
  });

  it('keeps a text file over the websocket limit for the upload, unread', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    let read = 0;
    const file = {
      name: 'large.yaml',
      size: 4 * 1024 * 1024 + 1,
      text: () => {
        read++;
        return Promise.resolve('x');
      },
    };
    await pick(panel, file);
    expect(read).toBe(0);
    expect(panel._transfer.file).toBe(file);
    expect(panel._transfer.error).toBe('');
    const root = panel.shadowRoot;
    // The text box is gone, the file name shows, and Preview is on.
    expect(root.querySelector('#transfer-text')).toBe(null);
    expect(root.querySelector('.hk-transfer-file').textContent).toBe('large.yaml');
    expect(buttons(root).preview.hasAttribute('disabled')).toBe(false);
    expect(buttons(root).run.hasAttribute('disabled')).toBe(true);
  });

  it('refuses a bundle over the bundle limit', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    await pick(panel, { name: 'home.zip', size: 500 * 1024 * 1024 + 1, text: () => Promise.resolve('') });
    expect(panel._transfer.file).toBe(null);
    expect(panel._transfer.error).toContain('500 MB');
  });

  it('clears a chosen file and shows the text box again', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    await pick(panel, { name: 'home.zip', size: 10, text: () => Promise.resolve('') });
    panel.shadowRoot.querySelector('#transfer-clear').click();
    await Promise.resolve();
    expect(panel._transfer.file).toBe(null);
    expect(panel._transfer.filename).toBe('');
    expect(panel.shadowRoot.querySelector('#transfer-text')).toBeTruthy();
    expect(buttons(panel.shadowRoot).preview.hasAttribute('disabled')).toBe(true);
  });

  it('says so when the read fails', async () => {
    const { hass } = makeHass();
    const panel = await mount(hass);
    await pick(panel, {
      name: 'gone.yaml',
      size: 10,
      text: () => Promise.reject(new Error('The file is gone')),
    });
    expect(panel._transfer.error).toBe('The panel cannot read the file: The file is gone');
    expect(panel.shadowRoot.querySelector('#hk-transfer').textContent).toContain(
      'The panel cannot read the file',
    );
  });
});

// ── Sources, bundles and companions ──────────────────────────────────────────

const PAWSISTANT = {
  domain: 'pawsistant',
  name: 'Pawsistant',
  status: 'connected',
  capabilities: ['care_schedules', 'import_export'],
};

/** A hass whose companion list and export document can be set per test. */
function makeCompanionHass({ companions = [PAWSISTANT], document, report = OK_REPORT } = {}) {
  const base = makeHass(report);
  const callWS = base.hass.callWS.bind(base.hass);
  base.hass.callWS = (msg) => {
    if (msg.type === 'home_keeper/get_companions') {
      base.calls.push(msg);
      return Promise.resolve({ companions });
    }
    if (msg.type === 'home_keeper/export_data') {
      base.calls.push(msg);
      return Promise.resolve({
        document: document ?? Object.fromEntries((msg.include ?? []).map((k) => [k, []])),
        yaml: 'home_keeper:\n  format: 1\n',
      });
    }
    return callWS(msg);
  };
  return base;
}

const sourceBoxes = (root) =>
  Object.fromEntries(
    [...root.querySelectorAll('input[data-transfer-source]')].map((box) => [
      box.dataset.transferSource,
      box,
    ]),
  );

async function toggle(panel, key) {
  const box = sourceBoxes(panel.shadowRoot)[key];
  box.checked = !box.checked;
  box.dispatchEvent(new Event('change'));
  await Promise.resolve();
}

describe('Import and export: the export list', () => {
  it('lists Home Keeper, each companion that joins the export, the files and the settings', async () => {
    const { hass } = makeCompanionHass({
      companions: [
        PAWSISTANT,
        { domain: 'no_cap', name: 'No capability', status: 'connected', capabilities: [] },
        { domain: 'later', name: 'Suggested', status: 'suggested', capabilities: ['import_export'] },
      ],
    });
    const panel = await mount(hass);
    await waitFor(() => sourceBoxes(panel.shadowRoot).pawsistant);
    const boxes = sourceBoxes(panel.shadowRoot);
    expect(Object.keys(boxes)).toEqual(['home_keeper', 'pawsistant', 'files', 'settings']);
    expect(boxes.home_keeper.checked).toBe(true);
    expect(boxes.pawsistant.checked).toBe(true);
    // A bundle always holds the files, so the row is on and cannot be cleared.
    expect(boxes.files.checked).toBe(true);
    expect(boxes.files.disabled).toBe(true);
    // The settings are off until the user asks for them.
    expect(boxes.settings.checked).toBe(false);
    const card = panel.shadowRoot.querySelector('#hk-transfer').textContent;
    expect(card).toContain('Pawsistant');
    expect(card).toContain('Bundle only');
    expect(card).not.toContain('No capability');
  });

  it('escapes a companion name', async () => {
    const { hass } = makeCompanionHass({
      companions: [{ ...PAWSISTANT, name: '<img src=x onerror=alert(1)>' }],
    });
    const panel = await mount(hass);
    await waitFor(() => sourceBoxes(panel.shadowRoot).pawsistant);
    expect(panel.shadowRoot.querySelector('#hk-transfer img')).toBe(null);
    expect(panel.shadowRoot.querySelector('#hk-transfer').textContent).toContain('<img src=x');
  });

  it('exports the checked data rows as YAML and says what the file holds', async () => {
    const { hass, calls } = makeCompanionHass();
    const panel = await mount(hass);
    await waitFor(() => sourceBoxes(panel.shadowRoot).pawsistant);
    panel._downloadFile = () => {};
    await panel._exportData();
    const sent = calls.filter((c) => c.type === 'home_keeper/export_data');
    expect(sent.at(-1).include).toEqual(['appliances', 'tasks', 'pawsistant']);
    expect(panel.shadowRoot.querySelector('.hk-transfer-exported').textContent).toBe(
      'Exported: Tasks and appliances and Pawsistant.',
    );
  });

  it('names a companion that the file does not hold', async () => {
    const { hass } = makeCompanionHass({ document: { home_keeper: {}, tasks: [], appliances: [] } });
    const panel = await mount(hass);
    await waitFor(() => sourceBoxes(panel.shadowRoot).pawsistant);
    panel._downloadFile = () => {};
    await panel._exportData();
    expect(panel._transfer.exported).toBe(
      'Exported: Tasks and appliances. Not in the file: Pawsistant. The log has the reason.',
    );
  });

  it('sends only the rows that stay checked', async () => {
    const { hass, calls } = makeCompanionHass();
    const panel = await mount(hass);
    await waitFor(() => sourceBoxes(panel.shadowRoot).pawsistant);
    panel._downloadFile = () => {};
    await toggle(panel, 'home_keeper');
    await panel._exportData();
    expect(calls.filter((c) => c.type === 'home_keeper/export_data').at(-1).include).toEqual([
      'pawsistant',
    ]);
  });

  it('turns off a button that has no section to export', async () => {
    const { hass, calls } = makeCompanionHass();
    const panel = await mount(hass);
    await waitFor(() => sourceBoxes(panel.shadowRoot).pawsistant);
    await toggle(panel, 'home_keeper');
    await toggle(panel, 'pawsistant');
    const root = panel.shadowRoot;
    expect(root.querySelector('#transfer-export').hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('#transfer-export-bundle').hasAttribute('disabled')).toBe(true);
    await panel._exportData();
    expect(calls.some((c) => c.type === 'home_keeper/export_data')).toBe(false);
    // The settings alone are a bundle, never a YAML file.
    await toggle(panel, 'settings');
    expect(root.querySelector('#transfer-export').hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('#transfer-export-bundle').hasAttribute('disabled')).toBe(false);
  });
});

describe('Import and export: the bundle download', () => {
  let realFetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  function stubFetch(responses) {
    realFetch = globalThis.fetch;
    const seen = [];
    globalThis.fetch = (url, init) => {
      seen.push({ url, init });
      return Promise.resolve(responses.shift());
    };
    return seen;
  }

  // A plain object, because the Response of Node does not take the Blob of jsdom.
  const fakeResponse = (status, { headers = {}, body = {} } = {}) => ({
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(headers),
    blob: () => Promise.resolve(new Blob(['PK'])),
    json: () => Promise.resolve(body),
  });
  const zipResponse = () =>
    fakeResponse(200, {
      headers: { 'Content-Disposition': 'inline; filename="home-keeper-2026-10-11.zip"' },
    });

  it('downloads the bundle with the token and the checked rows', async () => {
    const { hass } = makeCompanionHass();
    hass.auth = { data: { access_token: 'tok' } };
    const panel = await mount(hass);
    await waitFor(() => sourceBoxes(panel.shadowRoot).pawsistant);
    await toggle(panel, 'settings');
    const seen = stubFetch([zipResponse()]);
    const saved = [];
    panel._downloadBlob = (name, blob) => saved.push({ name, blob });
    await panel._exportBundle();
    expect(seen).toHaveLength(1);
    expect(seen[0].url).toBe(
      '/api/home_keeper/export_bundle?include=appliances%2Ctasks%2Cpawsistant%2Csettings',
    );
    expect(seen[0].init.headers.Authorization).toBe('Bearer tok');
    expect(saved.map((s) => s.name)).toEqual(['home-keeper-2026-10-11.zip']);
    expect(panel._transfer.exported).toBe(
      'Exported: Tasks and appliances, Pawsistant, Files, and Settings.',
    );
  });

  it('leaves the settings out of a bundle when the row is off', async () => {
    const { hass } = makeCompanionHass();
    const panel = await mount(hass);
    await waitFor(() => sourceBoxes(panel.shadowRoot).pawsistant);
    const seen = stubFetch([zipResponse()]);
    panel._downloadBlob = () => {};
    await panel._exportBundle();
    expect(seen[0].url).toBe('/api/home_keeper/export_bundle?include=appliances%2Ctasks%2Cpawsistant');
  });

  it('tries once more with a fresh token after a 401', async () => {
    const { hass } = makeCompanionHass();
    let token = 'old';
    hass.auth = {
      get accessToken() {
        return token;
      },
      refreshAccessToken: () => {
        token = 'new';
        return Promise.resolve();
      },
    };
    const panel = await mount(hass);
    const seen = stubFetch([fakeResponse(401), zipResponse()]);
    panel._downloadBlob = () => {};
    await panel._exportBundle();
    expect(seen.map((s) => s.init.headers.Authorization)).toEqual(['Bearer old', 'Bearer new']);
  });

  it('shows no result line when the download fails', async () => {
    const { hass } = makeCompanionHass();
    const panel = await mount(hass);
    stubFetch([fakeResponse(400, { body: { message: 'No' } })]);
    const saved = [];
    panel._downloadBlob = (name) => saved.push(name);
    await panel._exportBundle();
    expect(saved).toEqual([]);
    expect(panel._transfer.exported).toBe('');
    expect(panel._transfer.exporting).toBe(false);
  });
});

describe('Import and export: a chosen bundle', () => {
  let RealXHR;
  afterEach(() => {
    globalThis.XMLHttpRequest = RealXHR;
  });

  /** A stand-in for XMLHttpRequest that answers each send with the next report. */
  function stubXHR(reports) {
    RealXHR = globalThis.XMLHttpRequest;
    const sent = [];
    class FakeXHR {
      constructor() {
        this.upload = { addEventListener() {} };
        this.listeners = {};
        this.headers = {};
      }
      open(method, url) {
        this.method = method;
        this.url = url;
      }
      setRequestHeader(k, v) {
        this.headers[k] = v;
      }
      addEventListener(type, fn) {
        this.listeners[type] = fn;
      }
      send(body) {
        sent.push({ url: this.url, method: this.method, body, headers: this.headers });
        const next = reports.shift();
        this.status = next.status ?? 200;
        this.responseText = JSON.stringify(next.body ?? next);
        setTimeout(() => this.listeners.load?.(), 0);
      }
    }
    globalThis.XMLHttpRequest = FakeXHR;
    return sent;
  }

  async function pickFile(panel, file) {
    const picker = panel.shadowRoot.querySelector('#hk-transfer input[type="file"]');
    Object.defineProperty(picker, 'files', { value: [file], configurable: true });
    picker.dispatchEvent(new Event('change'));
    await new Promise((r) => setTimeout(r, 0));
  }

  const zip = () => new File(['PK\u0003\u0004'], 'home-keeper.zip', { type: 'application/zip' });

  const BUNDLE_REPORT = {
    ...OK_REPORT,
    counts: { ...OK_REPORT.counts, files: { created: 3, unchanged: 1 } },
    sections: {
      pawsistant: {
        ok: true,
        counts: { events: { created: 40, updated: 0, unchanged: 2 }, dogs: { created: 1, updated: 1 } },
      },
    },
    problems: [
      { section: 'profiles', index: null, path: 'profiles', message: '"profiles" was skipped, because include_settings is off', severity: 'warning' },
      { section: 'pawsistant', index: null, path: 'pawsistant.dogs[0].name', message: 'Biscuit <b>is</b> new', severity: 'warning' },
    ],
  };

  it('sends a bundle to the upload view, and the preview shows each section', async () => {
    const sent = stubXHR([BUNDLE_REPORT]);
    const { hass, calls } = makeCompanionHass();
    const panel = await mount(hass);
    await waitFor(() => sourceBoxes(panel.shadowRoot).pawsistant);
    await pickFile(panel, zip());
    await panel._previewImport();
    expect(calls.some((c) => c.type === 'home_keeper/import_data')).toBe(false);
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toBe('/api/home_keeper/import_upload');
    expect(sent[0].body.get('dry_run')).toBe('true');
    expect(sent[0].body.get('include_settings')).toBe('false');
    expect(sent[0].body.get('match')).toBe('auto');
    expect(sent[0].body.get('file').name).toBe('home-keeper.zip');

    const root = panel.shadowRoot;
    const row = (part) => root.querySelector(`tr[data-part="${part}"]`);
    expect([...row('pawsistant').querySelectorAll('td')].map((td) => td.textContent).slice(0, 2)).toEqual([
      '41',
      '1',
    ]);
    expect(row('pawsistant').querySelector('th').textContent).toContain('Pawsistant');
    // The note of a companion is in its own row, as text.
    expect(row('pawsistant').querySelector('td.hk-transfer-notes').textContent).toContain(
      'Biscuit <b>is</b> new',
    );
    expect(row('pawsistant').querySelector('b')).toBe(null);
    expect(row('files').querySelector('td').textContent).toBe('3');
    expect(row('files').textContent).toContain('Unchanged: 1');
    // A clean preview of this file licenses Import.
    expect(buttons(root).run.hasAttribute('disabled')).toBe(false);
  });

  it('offers the settings of a bundle, and a change asks for a new preview', async () => {
    const sent = stubXHR([BUNDLE_REPORT, BUNDLE_REPORT, { ...BUNDLE_REPORT, dry_run: false }]);
    const { hass } = makeCompanionHass();
    const panel = await mount(hass);
    await pickFile(panel, zip());
    const root = panel.shadowRoot;
    expect(root.querySelector('#transfer-settings')).toBe(null);
    await panel._previewImport();
    const box = root.querySelector('#transfer-settings');
    expect(box).toBeTruthy();
    expect(box.checked).toBe(false);
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    await Promise.resolve();
    // The preview was of an import without the settings.
    expect(panel._transfer.report).toBe(null);
    expect(buttons(root).run.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('#transfer-settings').checked).toBe(true);
    await panel._previewImport();
    expect(sent[1].body.get('include_settings')).toBe('true');
    await panel._runImport();
    expect(sent[2].body.get('dry_run')).toBe('false');
    expect(sent[2].body.get('include_settings')).toBe('true');
  });

  it('does not offer settings for a bundle that has none', async () => {
    stubXHR([OK_REPORT]);
    const { hass } = makeCompanionHass();
    const panel = await mount(hass);
    await pickFile(panel, zip());
    await panel._previewImport();
    expect(panel.shadowRoot.querySelector('#transfer-settings')).toBe(null);
  });

  it('shows the message of the upload view when it refuses the file', async () => {
    stubXHR([{ status: 413, body: { message: 'The file is over the 500 MB limit.' } }]);
    const { hass } = makeCompanionHass();
    const panel = await mount(hass);
    await pickFile(panel, zip());
    await panel._previewImport();
    expect(panel._transfer.report).toBe(null);
    expect(panel._transfer.error).toBe('The file is over the 500 MB limit.');
  });

  it('drops a chosen file when a small text file is picked next', async () => {
    const { hass } = makeCompanionHass();
    const panel = await mount(hass);
    await pickFile(panel, zip());
    expect(panel._transfer.file).toBeTruthy();
    await pickFile(panel, new File(['tasks: []\n'], 'small.yaml'));
    await waitFor(() => panel._transfer.text);
    expect(panel._transfer.file).toBe(null);
    expect(panel._transfer.text).toBe('tasks: []\n');
  });
});
