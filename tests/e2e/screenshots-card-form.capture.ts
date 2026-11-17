/**
 * One-off screenshot capture for the button weights of the card's New task form. Not
 * part of the e2e suite (the filename is not *.spec.ts). Run:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-card-form.capture.ts \
 *     --config=screenshots-card-form.config.ts
 *
 * Create is the primary button and Cancel is tertiary. Desktop and phone.
 */
import { expect, test, type Locator, type Page } from '@playwright/test';
import { openCardDashboard } from './tests/helpers';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

async function shoot(page: Page, card: Locator, name: string): Promise<void> {
  await card.locator('#hk-add').click();
  const create = card.locator('#hk-create');
  await expect(create).toBeVisible();
  await expect(create).toHaveAttribute('data-hk-weight', 'primary');
  await expect(card.locator('.hk-form-actions ha-button[data-hk-weight="tertiary"]')).toBeVisible();
  // The form is taller than the window: the shot is the window with the buttons in
  // its middle, so Create and Cancel show beside the fields above them.
  await create.evaluate((el) => el.scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/${name}` });
}

test('capture the buttons of the card form', async ({ page }) => {
  test.setTimeout(180_000);
  const card = await openCardDashboard(page);
  await shoot(page, card, 'card-form-buttons.png');

  await page.setViewportSize(PHONE);
  const phone = await openCardDashboard(page);
  await shoot(page, phone, 'card-form-mobile-buttons.png');
});
