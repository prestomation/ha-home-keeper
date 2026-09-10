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
    'ha-textarea',
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
    const text = panel.shadowRoot.querySelector('#hk-transfer').textContent;
    expect(text).toContain('Tasks: 2 new, 1 updated');
    expect(text).toContain('History entries: 5');
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
    const items = [...panel.shadowRoot.querySelectorAll('.hk-transfer-problems li')];
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
