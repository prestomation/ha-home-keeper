/**
 * One-off screenshot capture for the Profile companion filter — not part of the e2e
 * suite (the filename is not *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-companion-filter.config.ts
 *
 * A profile filters by the integration that created a task, so the shot has to show a
 * real owner in the picker. The capture seeds owners the way a companion does — an
 * `add_task` carrying a `managed_by` block — rather than faking the registry, so the
 * picker is filled by exactly the path a real glue uses.
 */
import { expect, test } from '@playwright/test';
import { callService, createTask, deleteTask, openPanel } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/hk-shots';

/** Two owners, so the picker in the shot holds a real choice. */
const OWNERS = [
  {
    integration: 'battery_notes',
    display_name: 'Battery Notes',
    name: 'Replace battery: Front door sensor',
  },
  { integration: 'pawsistant', display_name: 'Pawsistant', name: 'Buddy: flea treatment' },
];

let taskIds: string[] = [];
let savedProfiles: unknown[] = [];

test.beforeAll(async () => {
  taskIds = [];
  for (const owner of OWNERS) {
    taskIds.push(
      await createTask({
        name: owner.name,
        recurrence_type: 'floating',
        interval: 3,
        unit: 'months',
        managed_by: { integration: owner.integration, display_name: owner.display_name },
      }),
    );
  }
  // The container's store and options are the committed seed fixture, so remember what
  // the profile list held and put it back afterwards.
  savedProfiles = (await callService('home_keeper', 'list_profiles', {}, true)).profiles ?? [];

  // Seed the profile with the filter already set. Driving HA's multi-select menu to
  // pick a value is fragile capture plumbing, and the shot only needs to show the
  // control holding a real owner.
  await callService('home_keeper', 'set_options', {
    profiles: [
      ...savedProfiles,
      {
        id: 'shot-battery-tasks',
        name: 'Battery tasks',
        filter: { status: 'all', companions: ['battery_notes'] },
      },
    ],
  });
});

test.afterAll(async () => {
  await callService('home_keeper', 'set_options', { profiles: savedProfiles });
  for (const id of taskIds) await deleteTask(id);
});

test('capture the profile companion filter', async ({ page }) => {
  await openPanel(page);
  await page.goto('/home-keeper/settings/profiles', { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();

  const card = panel.locator('#hk-profiles');
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.scrollIntoViewIfNeeded();

  // Open the seeded profile's editor, which is where the filter form lives.
  await card.getByText('Battery tasks', { exact: true }).first().click();
  const form = panel.locator('ha-form').filter({ hasText: /Companions/ }).first();
  await expect(form).toBeVisible({ timeout: 20_000 });
  await expect(form.getByText('Battery Notes').first()).toBeVisible();
  await page.waitForTimeout(1200);

  // The Profiles card only, not the whole Settings tab: a fullPage shot of this page
  // buries the feature and drags HA's position:fixed sidebar into the middle of it.
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({ path: `${OUT}/profile-companion-filter.png` });
});
