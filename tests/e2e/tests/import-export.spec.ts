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
  return JSON.stringify(
    {
      home_keeper: { format: 1 },
      appliances: [
        { external_id: `e2e-boiler-${tag}`, name: `E2E boiler ${tag}`, manufacturer: 'Acme' },
      ],
      tasks: [
        {
          external_id: `e2e-flush-${tag}`,
          name: `E2E flush the boiler ${tag}`,
          appliance: `e2e-boiler-${tag}`,
          interval: 6,
          unit: 'months',
          history: [{ completed_at: '2025-04-01', note: 'Imported from a spreadsheet' }],
        },
      ],
    },
    null,
    2,
  );
}

async function typeDocument(panel: import('@playwright/test').Locator, text: string) {
  // `ha-textarea` wraps a real textarea in its own shadow root; drive the inner one
  // and dispatch the event the card listens for, exactly as a paste would.
  await panel.locator('#transfer-text').evaluate((el: HTMLElement, value: string) => {
    (el as HTMLTextAreaElement & { value: string }).value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }, text);
}

test.describe('Home Keeper panel — Import and export', { tag: '@responsive' }, () => {
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
    await expect(panel.locator('.hk-transfer-counts')).toContainText('Tasks: 1 new');
    await expect(panel.locator('.hk-transfer-counts')).toContainText(
      'Appliances: 1 new',
    );
    await expect(panel.locator('.hk-transfer-counts')).toContainText('History entries: 1');
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
    await typeDocument(
      panel,
      JSON.stringify({ home_keeper: { format: 1 }, tasks: [{ name: '' }] }),
    );
    await panel.locator('#transfer-preview').click();

    await expect(panel.locator('.hk-transfer-problems')).toBeVisible();
    await expect(panel.locator('.hk-transfer-problems')).toContainText('tasks[0]');
    // Import stays shut, so a document with an error cannot be applied by mistake.
    await expect(panel.locator('#transfer-import')).toHaveAttribute('disabled', '');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
