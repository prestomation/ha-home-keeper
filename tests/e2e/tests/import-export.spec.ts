import { test, expect } from '@playwright/test';
import {
  callService,
  gotoTab,
  openPanel,
  openSettingsSection,
  trackPanelErrors,
} from './helpers';

/**
 * The import flow end to end, in a real browser against a real Home Assistant.
 *
 * The unit tests prove the panel's two-step gate and the backend's decisions. What
 * only a browser can show is that the whole chain holds: text typed into a box
 * becomes a websocket call, the preview's verdict is drawn where the user is
 * looking, and pressing Import actually puts a task on the list.
 */
/**
 * A fresh document per run.
 *
 * The three viewport projects share one Home Assistant, so a fixed document would
 * have the first project create the records and the rest correctly report an
 * *update* — which is the upsert working exactly as designed, and a test asserting
 * "1 new" failing for a reason that is not a bug. Unique keys keep each run a
 * create, and the re-import-updates property has its own integration test.
 */
function makeDocument(tag: string): string {
  // Written as YAML, which is what an export now writes and what somebody editing one
  // by hand types. JSON still imports — YAML is a superset — and the JSON path has its
  // own case below.
  return [
    'home_keeper:',
    '  format: 1',
    'appliances:',
    `  - external_id: e2e-boiler-${tag}`,
    `    name: E2E boiler ${tag}`,
    '    manufacturer: Acme',
    'tasks:',
    `  - external_id: e2e-flush-${tag}`,
    `    name: E2E flush the boiler ${tag}`,
    `    appliance: e2e-boiler-${tag}`,
    '    interval: 6',
    '    unit: months',
    '    history:',
    // Unquoted on purpose: the loader drops YAML's implicit timestamp resolver, so
    // this has to stay text rather than arrive as a date the store cannot write.
    '      - completed_at: 2025-04-01',
    "        note: Imported from a spreadsheet",
    '',
  ].join('\n');
}

async function typeDocument(panel: import('@playwright/test').Locator, text: string) {
  // Set the value of the native textarea and send the event that the card listens
  // for, as a paste does.
  await panel.locator('#transfer-text').evaluate((el: HTMLElement, value: string) => {
    (el as HTMLTextAreaElement & { value: string }).value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, text);
}

test.describe('Home Keeper panel — Import and export', { tag: '@responsive' }, () => {
  test('shows the paste box on a fresh load', async ({ page }) => {
    // A fresh page has loaded no other Home Assistant page, so a lazy HA element that
    // the panel does not load stays an empty box with no size.
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await openSettingsSection(panel, 'transfer');
    const box = panel.locator('#transfer-text');
    await expect(box).toBeVisible();
    await expect(box).toBeEditable();
    await expect(panel.locator('label[for="transfer-text"]')).toBeVisible();
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('previews a document, then imports it', async ({ page }, testInfo) => {
    const tag = `${testInfo.project.name}-${Date.now().toString(36)}`;
    const taskName = `E2E flush the boiler ${tag}`;
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await openSettingsSection(panel, 'transfer');
    await expect(panel.locator('#hk-transfer')).toBeVisible();
    await expect(panel.locator('#transfer-export')).toBeVisible();

    // Nothing typed yet, so neither import button is offered.
    await expect(panel.locator('#transfer-preview')).toHaveAttribute('disabled', '');
    await expect(panel.locator('#transfer-import')).toHaveAttribute('disabled', '');

    await typeDocument(panel, makeDocument(tag));
    await expect(panel.locator('#transfer-preview')).not.toHaveAttribute('disabled', '');
    // Still shut: nothing has told the user what the import would do.
    await expect(panel.locator('#transfer-import')).toHaveAttribute('disabled', '');

    await panel.locator('#transfer-preview').click();
    await expect(panel.locator('.hk-transfer-report')).toBeVisible();
    // 1 row per section: New, then Updated, then the notes.
    await expect(panel.locator('tr[data-part="tasks"] td').first()).toHaveText('1');
    await expect(panel.locator('tr[data-part="appliances"] td').first()).toHaveText('1');
    await expect(panel.locator('tr[data-part="tasks"]')).toContainText('History entries: 1');
    await expect(panel.locator('#transfer-import')).not.toHaveAttribute('disabled', '');

    await panel.locator('#transfer-import').click();
    // The import reloads the config entry, so the panel re-reads on the far side of
    // it — the task appearing on the list is what proves the whole chain ran.
    await expect(panel.locator('.hk-transfer-report')).toContainText('imported');

    await gotoTab(panel, 'tasks');
    await expect(panel.locator('#hk-list')).toContainText(taskName, { timeout: 15000 });

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);

    // The imported records are this test's own, so take them back out rather than
    // leaving them for the next project's run to trip over.
    await callService('home_keeper', 'delete_task', { task_id: taskName });
    await callService('home_keeper', 'delete_asset', {
      asset_id: `E2E boiler ${tag}`,
    });
  });

  test('a bad document is refused with the path to the problem', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await openSettingsSection(panel, 'transfer');
    // JSON, because YAML is a superset of it: this is also the case proving a file
    // exported before the format was YAML still imports.
    await typeDocument(
      panel,
      JSON.stringify({ home_keeper: { format: 1 }, tasks: [{ name: '' }] }),
    );
    await panel.locator('#transfer-preview').click();

    await expect(panel.locator('tr[data-part="tasks"] .hk-transfer-problems')).toBeVisible();
    await expect(panel.locator('.hk-transfer-report')).toContainText('tasks[0]');
    // Import stays shut, so a document with an error cannot be applied by mistake.
    await expect(panel.locator('#transfer-import')).toHaveAttribute('disabled', '');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a file that is not YAML at all is refused with a line and a column', async ({
    page,
  }) => {
    // The panel carries no parser, so this message comes back from the backend. That
    // is the whole point of sending the text rather than a parsed object: a syntax
    // error arrives with somewhere to look.
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await openSettingsSection(panel, 'transfer');
    await typeDocument(panel, 'tasks:\n  - name: A\n   bad: B\n');
    await panel.locator('#transfer-preview').click();

    await expect(panel.locator('.hk-transfer-report')).toContainText('line 3');
    await expect(panel.locator('#transfer-import')).toHaveAttribute('disabled', '');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a dropped history field is named in the preview, and the import still runs', async ({
    page,
  }, testInfo) => {
    // A warning has to be *visible*, not merely returned. The card sorts errors above
    // warnings and draws both, and a field nobody read is data that did not arrive —
    // so a spreadsheet migration writing `notes` for `note` must say so here rather
    // than losing the column in silence.
    const tag = `${testInfo.project.name}-${Date.now().toString(36)}`;
    const taskName = `E2E warned ${tag}`;
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await openSettingsSection(panel, 'transfer');
    await typeDocument(
      panel,
      [
        'home_keeper:',
        '  format: 1',
        'tasks:',
        `  - name: ${taskName}`,
        '    interval: 6',
        '    unit: months',
        '    history:',
        '      - completed_at: 2025-04-01',
        '        notes: Imported from a spreadsheet',
        '',
      ].join('\n'),
    );
    await panel.locator('#transfer-preview').click();

    const problems = panel.locator('.hk-transfer-report');
    await expect(problems.locator('.hk-transfer-problems')).toBeVisible();
    await expect(problems).toContainText('tasks[0].history[0].notes');
    await expect(problems.locator('li.warning')).toHaveCount(1);
    await expect(problems.locator('li.error')).toHaveCount(0);
    // A warning is not a refusal: the preview is clean enough to import.
    await expect(panel.locator('#transfer-import')).not.toHaveAttribute('disabled', '');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a document too large for the websocket is refused in the browser', async ({
    page,
  }) => {
    // Home Assistant does not answer a frame past aiohttp's 4 MiB default — it closes
    // the connection ("Decompressed message exceeds size limit 4194304"). So this is
    // the one case the panel has to decide by itself, and the assertion that matters
    // is that no call goes out: a send here costs the user their link to Home
    // Assistant and tells them only to try again, which cannot work.
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const sent: string[] = [];
    page.on('websocket', (ws) =>
      ws.on('framesent', (f) => {
        const body = typeof f.payload === 'string' ? f.payload : f.payload.toString();
        if (body.includes('home_keeper/import_data')) sent.push(body.slice(0, 80));
      }),
    );

    await openSettingsSection(panel, 'transfer');
    await typeDocument(
      panel,
      ['home_keeper:', '  format: 1', 'tasks:', '  - name: E2E oversized',
        '    interval: 1', '    unit: days',
        `    notes: "${'y'.repeat(5 * 1024 * 1024)}"`].join('\n'),
    );
    await panel.locator('#transfer-preview').click();

    const alert = panel.locator('#hk-transfer ha-alert[alert-type="error"]').first();
    await expect(alert).toBeVisible();
    await expect(alert).toContainText('4');
    await expect(panel.locator('#transfer-import')).toHaveAttribute('disabled', '');
    expect(sent, 'the oversized document must never reach the socket').toEqual([]);
    // The connection is still up, which is the whole point of not sending it.
    await expect(panel.locator('#hk-transfer')).toBeVisible();

    // And a document that fits still goes through on the same card.
    await typeDocument(
      panel,
      ['home_keeper:', '  format: 1', 'tasks:', '  - name: E2E fits',
        '    interval: 1', '    unit: days', ''].join('\n'),
    );
    await panel.locator('#transfer-preview').click();
    await expect(panel.locator('.hk-transfer-counts')).toBeVisible();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('two records claiming one external_id are refused, naming both', async ({
    page,
  }) => {
    // The collision that used to import cleanly and break every later run of the same
    // document. It is an error, so Import stays shut.
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await openSettingsSection(panel, 'transfer');
    await typeDocument(
      panel,
      [
        'home_keeper:',
        '  format: 1',
        'tasks:',
        '  - name: E2E clash one',
        '    external_id: e2e-clash',
        '    interval: 1',
        '    unit: months',
        '  - name: E2E clash two',
        '    external_id: e2e-clash',
        '    interval: 1',
        '    unit: months',
        '',
      ].join('\n'),
    );
    await panel.locator('#transfer-preview').click();

    const problems = panel.locator('.hk-transfer-report');
    await expect(problems).toContainText('tasks[0], tasks[1]');
    await expect(problems.locator('li.error')).toHaveCount(2);
    await expect(panel.locator('#transfer-import')).toHaveAttribute('disabled', '');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('exports a bundle with the companion, then previews it as an upload', async ({
    page,
  }, testInfo) => {
    // The stub Pawsistant registers `import_export`, so it is a row of the export
    // list and a section of the bundle. The chosen zip goes to the upload view, and
    // the preview has a row for the companion with its note.
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await openSettingsSection(panel, 'transfer');

    const box = (key: string) => panel.locator(`input[data-transfer-source="${key}"]`);
    await expect(box('home_keeper')).toBeChecked();
    await expect(box('pawsistant')).toBeChecked();
    await expect(box('files')).toBeChecked();
    await expect(box('files')).toBeDisabled();
    await expect(box('settings')).not.toBeChecked();

    // The YAML file holds the data rows.
    const [yaml] = await Promise.all([
      page.waitForEvent('download'),
      panel.locator('#transfer-export').click(),
    ]);
    expect(yaml.suggestedFilename()).toMatch(/^home-keeper-\d{4}-\d{2}-\d{2}\.yaml$/);
    await expect(panel.locator('.hk-transfer-exported')).toContainText('Pawsistant');

    // The bundle holds the settings too, when the row is on.
    await box('settings').check();
    const [zip] = await Promise.all([
      page.waitForEvent('download'),
      panel.locator('#transfer-export-bundle').click(),
    ]);
    expect(zip.suggestedFilename()).toMatch(/^home-keeper-\d{4}-\d{2}-\d{2}\.zip$/);
    const zipPath = testInfo.outputPath('bundle.zip');
    await zip.saveAs(zipPath);
    await expect(panel.locator('.hk-transfer-exported')).toContainText('Settings');

    const [chooser] = await Promise.all([
      page.waitForEvent('filechooser'),
      panel.locator('#transfer-pick').click(),
    ]);
    await chooser.setFiles(zipPath);
    await expect(panel.locator('#transfer-text')).toHaveCount(0);
    await expect(panel.locator('.hk-transfer-file')).toHaveText('bundle.zip');
    await panel.locator('#transfer-preview').click();

    const row = panel.locator('tr[data-part="pawsistant"]');
    await expect(row).toContainText('Pawsistant');
    await expect(row).toContainText('Care tasks are made again after the import.');
    await expect(panel.locator('tr[data-part="files"]')).toBeVisible();
    // The bundle has settings, so the card offers them. A change asks for a new preview.
    const settings = panel.locator('#transfer-settings');
    await expect(settings).not.toBeChecked();
    await expect(panel.locator('#transfer-import')).not.toHaveAttribute('disabled', '');
    await settings.check();
    await expect(panel.locator('#transfer-import')).toHaveAttribute('disabled', '');
    await panel.locator('#transfer-preview').click();
    await expect(panel.locator('tr[data-part="settings"]')).toBeVisible();
    await expect(panel.locator('#transfer-import')).not.toHaveAttribute('disabled', '');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
