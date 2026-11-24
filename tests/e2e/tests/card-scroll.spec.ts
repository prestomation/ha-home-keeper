import { test, expect, type Page } from '@playwright/test';
import { openCardDashboard } from './helpers';

/**
 * The card scrolls on a touchscreen, with the add button on and off (#605).
 *
 * A card in a fixed-height slot (a sections-view row count) keeps its
 * header and scrolls the rest. Opening the add form put the whole form above the list, in
 * a block that could not scroll. In a short card it pushed the list out and cut off the
 * Save button, and a touch screen has no Tab key to reach it.
 */

const SLOT = 'hk-scroll-slot';

test.use({ hasTouch: true });

type Config = Record<string, unknown>;

/** Mount a fresh card in a fixed-height slot, as a sections-view row count does. */
async function mountCard(page: Page, height: number, config: Config) {
  await openCardDashboard(page);
  await page.evaluate(
    ({ height, config, SLOT }) => {
      document.getElementById(SLOT)?.remove();
      const slot = document.createElement('div');
      slot.id = SLOT;
      slot.style.cssText = `position:fixed;top:0;left:0;width:100%;height:${height}px;z-index:99999;background:#fff`;
      const card = document.createElement('home-keeper-card') as HTMLElement & {
        setConfig: (c: Config) => void;
        hass: unknown;
      };
      card.setConfig({ type: 'custom:home-keeper-card', ...config });
      card.hass = (document.querySelector('home-assistant') as any).hass;
      slot.appendChild(card);
      document.body.appendChild(slot);
    },
    { height, config, SLOT },
  );
  const card = page.locator(`#${SLOT} home-keeper-card`);
  await expect(card.locator('.hk-row').first()).toBeVisible({ timeout: 20_000 });
  return card;
}

/** One finger swipe up at the middle of the card, sent as real touch events. */
async function swipeUp(page: Page, card: ReturnType<Page['locator']>): Promise<void> {
  const box = (await card.boundingBox())!;
  const x = Math.round(box.x + box.width / 2);
  const top = Math.round(box.y + box.height * 0.8);
  const cdp = await page.context().newCDPSession(page);
  const send = (type: string, y?: number) =>
    cdp.send('Input.dispatchTouchEvent', {
      type,
      touchPoints: y === undefined ? [] : [{ x, y }],
    });
  for (let swipe = 0; swipe < 6; swipe++) {
    await send('touchStart', top);
    for (let i = 1; i <= 12; i++) {
      await send('touchMove', top - i * 15);
      await page.waitForTimeout(16);
    }
    await send('touchEnd');
    await page.waitForTimeout(400);
  }
}

/** One turn of the mouse wheel at the middle of the card. */
async function wheelDown(page: Page, card: ReturnType<Page['locator']>): Promise<void> {
  const box = (await card.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  for (let i = 0; i < 6; i++) await page.mouse.wheel(0, 600);
  await page.waitForTimeout(300);
}

/** The largest scrollTop of any element inside the card, shadow roots included. */
const scrolled = (card: ReturnType<Page['locator']>) =>
  card.evaluate((host) => {
    let max = 0;
    const walk = (root: ParentNode) => {
      for (const el of Array.from(root.querySelectorAll('*'))) {
        max = Math.max(max, (el as HTMLElement).scrollTop);
        if (el.shadowRoot) walk(el.shadowRoot);
      }
    };
    walk(host.shadowRoot!);
    return max;
  });

for (const showAdd of [false, true]) {
  test(`a short card scrolls its list by wheel, show_add ${showAdd} (#605)`, async ({ page }) => {
    const card = await mountCard(page, 260, { show_add: showAdd, grid_options: { rows: 4 } });
    await wheelDown(page, card);
    expect(await scrolled(card), 'the list scrolled').toBeGreaterThan(0);
  });

  test(`a short card scrolls its list by touch, show_add ${showAdd} (#605) @phone`, async ({
    page,
  }) => {
    const card = await mountCard(page, 260, { show_add: showAdd, grid_options: { rows: 4 } });
    await swipeUp(page, card);
    expect(await scrolled(card), 'the list scrolled').toBeGreaterThan(0);
  });
}

test('the open add form stays reachable in a short card (#605) @phone', async ({ page }) => {
  const card = await mountCard(page, 300, { show_add: true, grid_options: { rows: 4 } });
  await card.locator('#hk-add').click();
  const save = card.locator('.hk-form-actions ha-button, .hk-form-actions button').first();
  await expect(save).toBeAttached();
  await swipeUp(page, card);
  const cardBox = (await card.locator('ha-card').boundingBox())!;
  const saveBox = (await save.boundingBox())!;
  expect(saveBox.y + saveBox.height, 'the form actions end inside the card').toBeLessThanOrEqual(
    cardBox.y + cardBox.height + 1,
  );
  expect(saveBox.y, 'the form actions start inside the card').toBeGreaterThanOrEqual(cardBox.y);
});

test('the open add form stays reachable by wheel in a short card (#605)', async ({ page }) => {
  const card = await mountCard(page, 300, { show_add: true, grid_options: { rows: 4 } });
  await card.locator('#hk-add').click();
  const save = card.locator('.hk-form-actions ha-button, .hk-form-actions button').first();
  await expect(save).toBeAttached();
  await wheelDown(page, card);
  const cardBox = (await card.locator('ha-card').boundingBox())!;
  const saveBox = (await save.boundingBox())!;
  expect(saveBox.y + saveBox.height, 'the form actions end inside the card').toBeLessThanOrEqual(
    cardBox.y + cardBox.height + 1,
  );
  expect(saveBox.y, 'the form actions start inside the card').toBeGreaterThanOrEqual(cardBox.y);
});
