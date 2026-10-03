/**
 * One-off screenshot capture for the event entities (#415).
 * Not part of the e2e suite (the filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-event-entities.config.ts
 *
 * It marks the seeded anode task done, so the water heater's event entity has a
 * last event, then shoots at desktop and phone width:
 *  - the water heater device page with its Home Keeper events entity;
 *  - the more-info dialog of that entity;
 *  - the automation editor with an Event received trigger on that device;
 *  - the same trigger with the event type list open;
 *  - the Home Keeper service device with the entity that gets all events.
 * At the end it removes the completion again.
 */
import { test, expect, type Page } from '@playwright/test';
import { callService, listTasks } from './tests/helpers';
import { DESKTOP, PHONE, type Viewport } from './viewports';
import { HEATER_EVENTS, deviceIdOf, openEventReceivedTrigger } from './event-trigger';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';
const GLOBAL_EVENTS = 'event.home_keeper_events';

/** Open a device page and bring the event entity row into view. */
async function devicePage(page: Page, deviceId: string, entityName: string): Promise<void> {
  await page.goto(`/config/devices/device/${deviceId}`, { waitUntil: 'domcontentloaded' });
  const row = page.getByText(entityName, { exact: true }).first();
  await expect(row).toBeVisible({ timeout: 30000 });
  await page.waitForTimeout(2000);
  // A desktop shot takes the full page. On a phone, the Events card is the last
  // card, and the page scrolls inside a shadow root, not the window, so scroll
  // each scrollable element to its end.
  if (page.viewportSize()!.width >= 600) return;
  await page.evaluate(() => {
    const walk = (root: Document | ShadowRoot): void => {
      for (const el of Array.from(root.querySelectorAll('*'))) {
        if (el.scrollHeight > el.clientHeight + 10) {
          const style = getComputedStyle(el);
          if (/(auto|scroll)/.test(style.overflowY)) el.scrollTop = el.scrollHeight;
        }
        if (el.shadowRoot) walk(el.shadowRoot);
      }
    };
    walk(document);
    window.scrollTo(0, document.body.scrollHeight);
  });
  await page.waitForTimeout(1500);
}

/** Open the more-info dialog from the entity row, the way a user does. */
async function moreInfo(page: Page, entityName: string): Promise<void> {
  await page.getByText(entityName, { exact: true }).first().click();
  const dialog = page.locator('ha-more-info-dialog');
  await expect(dialog.getByText('Task completed').first()).toBeVisible({ timeout: 15000 });
  await page.waitForTimeout(1500);
}

async function eventTypeList(page: Page): Promise<void> {
  // The last "Event type" label belongs to the empty field that adds a type.
  await page.getByText('Event type', { exact: true }).last().click();
  await expect(page.getByText('Spare part low on stock').first()).toBeVisible({ timeout: 10000 });
  await page.waitForTimeout(800);
}

async function shootAll(
  page: Page,
  size: Viewport,
  tag: string,
  ids: { heater: string; service: string },
): Promise<void> {
  await page.setViewportSize(size);
  await devicePage(page, ids.heater, 'Home Keeper events');
  await page.screenshot({ path: `${OUT}/79-device${tag}-event-entity.png`, fullPage: !tag });

  await moreInfo(page, 'Home Keeper events');
  await page.screenshot({ path: `${OUT}/79b-device${tag}-event-more-info.png` });
  await page.keyboard.press('Escape');

  await openEventReceivedTrigger(page, ids.heater, ['task_completed', 'task_overdue']);
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${OUT}/79c-automation${tag}-event-received.png` });

  await eventTypeList(page);
  await page.screenshot({ path: `${OUT}/79d-automation${tag}-event-types.png` });
  await page.keyboard.press('Escape');

  await devicePage(page, ids.service, 'Events');
  await page.screenshot({ path: `${OUT}/79e-device${tag}-service-events.png`, fullPage: !tag });
}

test('capture the event entities and the Event received trigger', async ({ page }) => {
  test.setTimeout(300000);
  await page.setViewportSize(DESKTOP);
  await page.goto('/home-keeper', { waitUntil: 'domcontentloaded' });
  // On a fresh container, wait for the "Home Assistant has started!" toast to go.
  await page
    .getByText('Home Assistant has started!')
    .waitFor({ state: 'hidden', timeout: 20000 })
    .catch(() => undefined);

  const anode = (await listTasks()).find((t) => String(t.name).startsWith('Replace Anode rod'));
  expect(anode).toBeTruthy();
  // A completion of this task uses 1 anode rod spare. Note the stock to put it back.
  const spares = async (): Promise<{ asset: string; part: string; stock: number }> => {
    const assets = (await callService('home_keeper', 'list_assets', {}, true)).assets;
    const heater = assets.find((a: any) => a.name === 'Garage water heater');
    const part = heater.parts.find((p: any) => p.name === 'Anode rod');
    return { asset: heater.id, part: part.id, stock: Number(part.stock) };
  };
  const before = await spares();
  await callService('home_keeper', 'complete_task', {
    task_id: anode!.id,
    origin: 'screenshot',
  });

  const ids = {
    heater: await deviceIdOf(page, HEATER_EVENTS),
    service: await deviceIdOf(page, GLOBAL_EVENTS),
  };
  try {
    await shootAll(page, DESKTOP, '', ids);
    await shootAll(page, PHONE, '-mobile', ids);
  } finally {
    await page.setViewportSize(DESKTOP);
    const task = (await listTasks()).find((t) => t.id === anode!.id);
    const last = task?.completions?.at(-1);
    if (last?.origin === 'screenshot') {
      await callService('home_keeper', 'delete_completion', { task_id: anode!.id, ts: last.ts });
    }
    const after = await spares();
    if (after.stock !== before.stock) {
      await callService('home_keeper', 'adjust_part_stock', {
        asset_id: before.asset,
        part_id: before.part,
        delta: before.stock - after.stock,
      });
    }
  }
});
