import { test, expect } from '@playwright/test';
import { openPanel } from './helpers';

/**
 * A list row keeps the left side of its outline (#554). The left edge is a 3px status
 * rail. It was transparent when idle, so the rounded corners looked cut off.
 */
test('a plain list row keeps its left border (#554)', async ({ page }) => {
  await page.setViewportSize({ width: 1015, height: 904 });
  await page.goto('/home-keeper/appliances');
  await openPanel(page);
  const card = page
    .locator('home-keeper-panel')
    .first()
    .locator('ha-card.hk-card:not(.overdue):not(.soon):not(.hk-selected)')
    .first();
  await expect(card).toBeVisible();
  const b = await card.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { left: cs.borderLeftColor, top: cs.borderTopColor };
  });
  expect(b.left, 'left border is drawn').not.toBe('rgba(0, 0, 0, 0)');
  expect(b.left).toBe(b.top);
});
