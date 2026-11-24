import { test, expect, Page } from '@playwright/test';
import { openCardDashboard } from './tests/helpers';
import { DESKTOP, PHONE } from './viewports';

/**
 * Capture the card with its add form open, in a card of fixed height, after a scroll to
 * the end of the form. The Save button must stay in reach (#605). Run via:
 *   SHOT_DIR=../../docs/images npx playwright test --config=screenshots-card-scroll.config.ts
 */
const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

async function shoot(page: Page, file: string): Promise<void> {
  await openCardDashboard(page);
  await page.evaluate(() => {
    document.getElementById('hk-scroll-slot')?.remove();
    const slot = document.createElement('div');
    slot.id = 'hk-scroll-slot';
    slot.style.cssText =
      'position:fixed;top:0;left:0;width:100%;height:340px;z-index:99999;padding:8px;box-sizing:border-box;background:var(--primary-background-color,#fff)';
    const card = document.createElement('home-keeper-card') as any;
    card.setConfig({ type: 'custom:home-keeper-card', show_add: true, grid_options: { rows: 4 } });
    card.hass = (document.querySelector('home-assistant') as any).hass;
    slot.appendChild(card);
    document.body.appendChild(slot);
  });
  const card = page.locator('#hk-scroll-slot home-keeper-card');
  await expect(card.locator('.hk-row').first()).toBeVisible();
  await card.locator('#hk-add').click();
  await expect(card.locator('.hk-form')).toBeVisible();
  const box = (await card.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  for (let i = 0; i < 6; i++) await page.mouse.wheel(0, 600);
  await page.waitForTimeout(500);
  await page.screenshot({
    path: `${OUT}/${file}`,
    clip: { x: 0, y: 0, width: page.viewportSize()!.width, height: 350 },
  });
}

test('the add form scrolls in a fixed-height card', async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await shoot(page, '605-card-add-form-scroll.png');
  await page.setViewportSize(PHONE);
  await shoot(page, '605b-card-mobile-add-form-scroll.png');
});
