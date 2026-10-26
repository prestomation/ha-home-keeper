/**
 * One-off screenshot capture of the Home Assistant logbook views for task events
 * (#467). Not part of the e2e suite (the filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images SHOT_PREFIX=after npx playwright test \
 *     --config=screenshots-logbook.config.ts
 *
 * SHOT_PREFIX names the set: "before" for a run on the code without logbook.py, and
 * "after" for a run on the code with it. The capture completes, skips and snoozes
 * tasks, and adds a task that is overdue. Then it photographs 4 views at desktop and
 * phone width:
 *  - the Logbook panel, filtered to the Home Keeper to-do list
 *  - the more-info dialog of the to-do list
 *  - the device page of the water heater, which has the anode task
 *  - the more-info dialog of the next-due sensor of the anode task
 *
 * Run it against a fresh container (`docker compose down -v`, then
 * `git checkout -- tests/integration/ha_config/`). The capture changes the task store.
 */
import { test, expect, Page } from '@playwright/test';
import { callService, createTask, deleteTask, TODO_ENTITY } from './tests/helpers';
import { TASK } from './fixture-ids';
import { DESKTOP, PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const PREFIX = process.env.SHOT_PREFIX || 'after';

let overdueTask: string | undefined;

test.afterAll(async () => {
  await deleteTask(overdueTask);
});

async function ws<T>(page: Page, msg: Record<string, unknown>): Promise<T> {
  return page.evaluate(async (m) => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass: { callWS: <R>(x: Record<string, unknown>) => Promise<R> };
    };
    return ha.hass.callWS(m);
  }, msg) as Promise<T>;
}

async function openMoreInfo(page: Page, entityId: string): Promise<void> {
  await page.evaluate((id) => {
    const ha = document.querySelector('home-assistant');
    ha?.dispatchEvent(
      new CustomEvent('hass-more-info', {
        detail: { entityId: id },
        bubbles: true,
        composed: true,
      }),
    );
  }, entityId);
}

/**
 * Take the desktop shot, then the phone shot of the same view. A dialog view takes a
 * viewport shot, because a full-page shot of the panel behind it is mostly the task
 * list.
 */
async function shoot(
  page: Page,
  name: string,
  open: () => Promise<void>,
  fullPage = true,
): Promise<void> {
  for (const [size, suffix] of [
    [DESKTOP, ''],
    [PHONE, '-mobile'],
  ] as const) {
    await page.setViewportSize(size);
    await open();
    await page.waitForTimeout(4000);
    await page.screenshot({
      path: `${OUT}/logbook-${PREFIX}${suffix}-${name}.png`,
      fullPage,
    });
  }
}

test('capture the logbook views of task events', async ({ page }) => {
  test.setTimeout(240000);
  await page.setViewportSize(DESKTOP);
  await page.goto('/home-keeper', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass?: { services?: Record<string, Record<string, unknown>> };
    };
    return Boolean(ha?.hass?.services?.home_keeper?.complete_task);
  }, undefined, { timeout: 60000 });

  // The activity that the logbook shows.
  await callService('home_keeper', 'complete_task', {
    task_id: TASK.anode,
    who: 'Ann',
    cost: 12,
    note: 'Replaced the anode rod',
  });
  await callService('home_keeper', 'skip_task', { task_id: TASK.furnaceFilter });
  await callService('home_keeper', 'snooze_task', { task_id: TASK.rexVet, hours: 48 });
  await callService('home_keeper', 'complete_task', { task_id: TASK.furnaceFilter, who: 'Ben' });
  // A new task that is already overdue. The next refresh fires the overdue event.
  overdueTask = await createTask({
    name: 'Clean the gutters',
    recurrence_type: 'floating',
    interval: 90,
    unit: 'days',
    last_completed: '2026-01-01T09:00:00+00:00',
  });
  await page.waitForTimeout(5000);

  const registry = await ws<{ entity_id: string; unique_id: string; device_id: string | null }[]>(
    page,
    { type: 'config/entity_registry/list' },
  );
  const nextDue = registry.find((e) => e.unique_id === `home_keeper_${TASK.anode}_next_due`);
  expect(nextDue, 'the anode task must have a next-due sensor').toBeTruthy();
  const deviceId = nextDue!.device_id;
  expect(deviceId, 'the anode task must be on a device').toBeTruthy();

  await shoot(page, 'panel', async () => {
    await page.goto(`/logbook?entity_id=${TODO_ENTITY}`, { waitUntil: 'domcontentloaded' });
  });
  await shoot(page, 'todo-more-info', async () => {
    await page.goto('/home-keeper', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    await openMoreInfo(page, TODO_ENTITY);
  }, false);
  await shoot(page, 'device', async () => {
    await page.goto(`/config/devices/device/${deviceId}`, { waitUntil: 'domcontentloaded' });
    // On a phone the page scrolls in an inner element, so a full-page shot stops
    // before the activity card. Scroll the card into view.
    const card = page.locator('ha-card').filter({ hasText: /^\s*Activity/ }).first();
    await card.waitFor({ timeout: 30000 });
    await page.waitForTimeout(2000);
    await card.scrollIntoViewIfNeeded();
  });
  await shoot(page, 'sensor-more-info', async () => {
    await page.goto('/home-keeper', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    await openMoreInfo(page, nextDue!.entity_id);
  }, false);
});
