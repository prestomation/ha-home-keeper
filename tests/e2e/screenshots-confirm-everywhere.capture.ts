/**
 * Focused screenshot capture for the delete confirmations of the panel and the card.
 *
 * Every action that loses data asks in the same dialog. The title names the item, the
 * red button says what it does, and the body says what is lost. This photographs each
 * kind at desktop and phone width. It makes the records it deletes, shows the dialog,
 * cancels, and removes them again.
 *
 * The scrim is `position: fixed` on `document.body`, so each shot is a viewport capture.
 *
 * Run:
 *   CHROMIUM_EXEC=$(ls /opt/pw-browsers/chromium-*\/chrome-linux/chrome | head -1) \
 *     SHOT_DIR=../../docs/images \
 *     npx playwright test --config=screenshots-confirm-everywhere.config.ts
 */
import { test, expect, type Locator, type Page } from '@playwright/test';
import {
  callService,
  createTask,
  deleteTask,
  openCardDashboard,
  openPanel,
  openSettingsSection,
} from './tests/helpers';
import { ASSET, TASK } from './fixture-ids';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const scrim = (page: Page) => page.locator('.hk-confirm-scrim');

/** Open a dialog at each width, photograph it, and cancel. */
async function shoot(
  page: Page,
  name: string,
  open: () => Promise<void>,
  check: (body: Locator) => Promise<void>,
): Promise<void> {
  for (const [size, file] of [
    [DESKTOP, `${name}.png`],
    [PHONE, `${name.replace(/^(\d+)-panel-/, '$1b-panel-mobile-')}.png`],
  ] as const) {
    await page.setViewportSize(size);
    await open();
    await expect(scrim(page)).toBeVisible();
    await check(scrim(page).locator('#hk-confirm-body'));
    await page.mouse.move(0, 0);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/${file}` });
    await page.keyboard.press('Escape');
    await expect(scrim(page)).toHaveCount(0);
  }
}

const panelOf = (page: Page) => page.locator('home-keeper-panel').first();

async function openPage(page: Page, url: string): Promise<Locator> {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  const panel = panelOf(page);
  await panel.waitFor({ state: 'attached', timeout: 45_000 });
  return panel;
}

test('capture the delete confirmations', async ({ page }) => {
  test.setTimeout(240_000);
  const made: { task?: string; asset?: string; companion?: string } = {};
  try {
    // A task with a completion and a skip, for the history rows and the task delete.
    made.task = await createTask({ name: 'Car oil change', interval: 180, unit: 'days' });
    await callService('home_keeper', 'complete_task', {
      task_id: made.task,
      note: 'Synthetic oil, new filter',
      cost: 64.5,
    });
    await callService('home_keeper', 'skip_task', { task_id: made.task, note: 'Away' });

    // 90. The history entry. 97. The skip.
    const history = async () => {
      const panel = await openPage(page, `/home-keeper/tasks/${made.task}/history`);
      await expect(panel.locator('.hk-hist-list li')).toHaveCount(2, { timeout: 45_000 });
      return panel;
    };
    await shoot(
      page,
      '90-panel-history-delete-confirm',
      async () => {
        const panel = await history();
        await panel.locator('.hk-hist-del').first().click();
      },
      (body) => expect(body).toContainText('Synthetic oil'),
    );
    await shoot(
      page,
      '97-panel-skip-delete-confirm',
      async () => {
        const panel = await history();
        await panel.locator('.hk-hist-skip-del').first().click();
      },
      (body) => expect(body).toContainText('Car oil change'),
    );

    // 98. The task delete: its history goes with it, and the dialog says so.
    await shoot(
      page,
      '98-panel-task-delete-confirm',
      async () => {
        const panel = await openPage(page, `/home-keeper/tasks/${made.task}`);
        await panel.locator('.d-del').click();
      },
      (body) => expect(body).toContainText('History entries deleted with it: 1.'),
    );

    // 99. The appliance delete: the history of a removed task is archived on it.
    await callService('home_keeper', 'add_asset', { name: 'Garage boiler' });
    const assets = (await callService('home_keeper', 'list_assets', {}, true)).assets;
    const asset = assets.find((a: any) => a.name === 'Garage boiler');
    made.asset = asset.id;
    const owned = await createTask({
      name: 'Flush the boiler',
      interval: 6,
      unit: 'months',
      device_id: asset.device_id,
    });
    await callService('home_keeper', 'complete_task', { task_id: owned });
    await callService('home_keeper', 'delete_task', { task_id: owned });
    await shoot(
      page,
      '99-panel-appliance-delete-confirm',
      async () => {
        const panel = await openPage(page, `/home-keeper/appliances/${asset.id}`);
        await panel.locator('.d-del').click();
      },
      (body) => expect(body).toContainText('History entries of removed tasks, deleted: 1.'),
    );

    // 100. The notification delete.
    const filter = { status: 'all', labels: [], areas: [], devices: [] };
    await callService('home_keeper', 'set_options', {
      profiles: [{ id: 'shot_profile', name: 'Chores', filter }],
      notifications: [
        {
          id: 'shot_notify',
          name: 'Bin day',
          profile_id: 'shot_profile',
          targets: [],
          actions: ['complete'],
          style: 'walk',
          snooze_hours: 24,
          channel: '',
          urgency: 'normal',
          auto: { overdue: false, due_soon: false },
        },
      ],
    });
    await shoot(
      page,
      '100-panel-notification-delete-confirm',
      async () => {
        await openPanel(page);
        const panel = panelOf(page);
        await openSettingsSection(panel, 'notifications');
        const row = panel.locator('#hk-notifications .hk-item-card').first();
        const header = row.locator('> .hk-item-header');
        if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
        await row.locator('> .hk-item-body .hk-notify-delete').click();
      },
      (body) => expect(body).toContainText('cannot be undone'),
    );

    // 101. The import: the counts of the preview, and the export as the backup.
    await shoot(
      page,
      '101-panel-import-confirm',
      async () => {
        await openPanel(page);
        const panel = panelOf(page);
        await openSettingsSection(panel, 'transfer');
        await panel.locator('#transfer-text').evaluate((el: HTMLElement) => {
          (el as HTMLTextAreaElement).value = [
            'home_keeper:',
            '  format: 1',
            'tasks:',
            '  - external_id: shot-import-task',
            '    name: Shot import task',
            '    interval: 3',
            '    unit: months',
            '',
          ].join('\n');
          el.dispatchEvent(new Event('input', { bubbles: true }));
        });
        await panel.locator('#transfer-preview').click();
        await expect(panel.locator('#transfer-import')).not.toHaveAttribute('disabled', '');
        await panel.locator('#transfer-import').click();
      },
      (body) => expect(body).toContainText('New records: 1'),
    );

    // 102. The seeded orphaned task: the bulk delete.
    await shoot(
      page,
      '102-panel-orphan-delete-confirm',
      async () => {
        await openPanel(page);
        await panelOf(page).locator('#cleanup-orphans-btn').click();
      },
      (body) => expect(body).toContainText('cannot be undone'),
    );

    // 103. A task photo (the seeded fridge filter has photos).
    await shoot(
      page,
      '103-panel-photo-remove-confirm',
      async () => {
        const panel = await openPage(page, `/home-keeper/tasks/${TASK.fridgeFilter}`);
        await panel.locator('.hk-photo-remove').first().click();
      },
      (body) => expect(body).toContainText('cannot be undone'),
    );

    // 105 to 107. Removing a stored document, a part file and a metadata field, in the
    // edit drawer of the seeded water heater.
    const drawer = async (): Promise<Locator> => {
      const panel = await openPage(page, `/home-keeper/appliances/${ASSET.waterHeater}`);
      await panel.locator('.d-edit').click();
      await expect(panel.locator('#hk-asset-form')).toBeVisible();
      // Fold sections open, so the controls inside them can be reached.
      await panel.locator('#hk-asset-form details:not([open]) > summary').evaluateAll((els) =>
        els.forEach((el) => (el as HTMLElement).click()),
      );
      return panel;
    };
    await shoot(
      page,
      '105-panel-remove-document-confirm',
      async () => {
        const panel = await drawer();
        await panel.locator('ha-icon-button[label="Remove document"]').first().click();
      },
      (body) => expect(body).toContainText('cannot be undone'),
    );
    await shoot(
      page,
      '106-panel-remove-part-file-confirm',
      async () => {
        const panel = await drawer();
        await panel.locator('.hk-part ha-icon-button[label="Remove file"]').first().click();
      },
      (body) => expect(body).toContainText('cannot be undone'),
    );
    await shoot(
      page,
      '107-panel-remove-field-confirm',
      async () => {
        const panel = await drawer();
        await panel.locator('.hk-entry ha-icon-button[label="Remove field"]').first().click();
      },
      (body) => expect(body).toContainText('cannot be undone'),
    );

    // 108. Deleting a companion rule, which takes the tasks it made.
    const companion = await callService(
      'home_keeper',
      'add_declarative_companion',
      {
        name: 'Battery low rule',
        selection: { domain: 'binary_sensor', device_class: 'battery' },
        trigger: { mode: 'state', state: 'on', clear_on_recover: true },
        task_template: { name_template: 'Battery low: {{ friendly_name }}' },
      },
      true,
    );
    made.companion = companion.companion.id as string;
    await shoot(
      page,
      '108-panel-companion-delete-confirm',
      async () => {
        await openPanel(page);
        const panel = panelOf(page);
        await openSettingsSection(panel, 'companions');
        await panel.locator(`.hk-decl-row[data-spec-id="${made.companion}"] .hk-decl-delete`).click();
      },
      (body) => expect(body).toContainText('cannot be undone'),
    );

    // 104. The card asks "mark done?" in the same dialog (the primary button).
    await shoot(
      page,
      '104-panel-card-mark-done-confirm',
      async () => {
        const card = await openCardDashboard(page);
        await card.evaluate((el: any) => el.setConfig({ ...el._config, confirm_complete: true }));
        await card.locator('.hk-done:not(.blocked)').first().click();
      },
      async (body) => expect(body).toBeEmpty(),
    );
  } finally {
    await callService('home_keeper', 'set_options', { profiles: [], notifications: [] });
    await deleteTask(made.task);
    if (made.companion) {
      await callService('home_keeper', 'delete_declarative_companion', {
        id: made.companion,
      }).catch(() => {});
    }
    if (made.asset) {
      await callService('home_keeper', 'delete_asset', { asset_id: made.asset }).catch(() => {});
    }
  }
});
