import { test, expect, type Page } from '@playwright/test';
import { auditOutlines } from '../outline-audit';
import { ASSET } from '../fixture-ids';

/**
 * Every outline is whole (#554). See `outline-audit.ts` for the 2 faults it finds.
 * Each view is opened by URL, then audited at the width of the project.
 */
type View = { name: string; url: string; before?: (page: Page) => Promise<void> };

const VIEWS: View[] = [
  { name: 'Tasks', url: '/home-keeper' },
  { name: 'Appliances', url: '/home-keeper/appliances' },
  { name: 'Parts', url: '/home-keeper/appliances/parts' },
  { name: 'Appliance detail', url: `/home-keeper/appliances/${ASSET.waterHeater}` },
];

test.describe('Home Keeper — outlines are whole (#554)', () => {
  for (const view of VIEWS) {
    test(`${view.name} @responsive`, async ({ page }) => {
      await page.goto(view.url, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('home-keeper-panel').first().locator('.hk-wrap')).toBeVisible();
      if (view.before) await view.before(page);
      expect(await auditOutlines(page)).toEqual([]);
    });
  }
});
