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
import { PHONE } from './viewports';

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
// A declarative companion, so the picker also shows Home Keeper's own entries (#378).
let specId = '';

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
  const created = await callService(
    'home_keeper',
    'add_declarative_companion',
    {
      name: 'Leak sensors',
      selection: { domain: 'binary_sensor', device_class: 'moisture' },
      trigger: { mode: 'state', state: 'on', clear_on_recover: true },
      task_template: { name_template: 'Check {{ friendly_name }}', notes_template: '' },
    },
    true,
  );
  specId = created.companion.id as string;
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
        id: 'shot-leak-tasks',
        name: 'Active leaks',
        filter: { status: 'all', companions: [`home_keeper:declarative:${specId}`] },
      },
    ],
  });
});

test.afterAll(async () => {
  await callService('home_keeper', 'set_options', { profiles: savedProfiles });
  if (specId) await callService('home_keeper', 'delete_declarative_companion', { id: specId });
  for (const id of taskIds) await deleteTask(id);
});

test('capture the profile companion filter', async ({ page }) => {
  const open = async (): Promise<ReturnType<typeof page.locator>> => {
    await openPanel(page);
    await page.goto('/home-keeper/settings/profiles', { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    const card = panel.locator('#hk-profiles');
    await expect(card).toBeVisible({ timeout: 30_000 });
    await card.scrollIntoViewIfNeeded();
    // Open the seeded profile's editor, which is where the filter form lives.
    await card.getByText('Active leaks', { exact: true }).first().click();
    const form = panel.locator('ha-form').filter({ hasText: /Companions/ }).first();
    await expect(form).toBeVisible({ timeout: 20_000 });
    // The declarative companion is named in the picker, not as a raw key.
    await expect(form.getByText('Leak sensors (declarative companion)').first()).toBeVisible();
    await page.waitForTimeout(1200);
    return card;
  };

  // The Profiles card only, not the whole Settings tab: a fullPage shot of this page
  // buries the feature and drags HA's position:fixed sidebar into the middle of it.
  const card = await open();
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({ path: `${OUT}/profile-companion-filter.png` });

  // On a phone the bottom tab bar is fixed over the page, so an element shot of the
  // tall card draws it across the middle. Open the picker instead and photograph the
  // screen: the menu is what shows Home Keeper's own entries.
  await page.setViewportSize(PHONE);
  const phoneCard = await open();
  const add = phoneCard.getByText('Companions', { exact: true }).first();
  await add.scrollIntoViewIfNeeded();
  await add.click();
  await expect(page.getByText('All Home Keeper tasks').first()).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/profile-mobile-companion-filter.png` });
});
