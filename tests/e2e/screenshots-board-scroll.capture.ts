import { test, expect, Page } from '@playwright/test';
import { openPanel, setTaskLayout } from './tests/helpers';
import { DESKTOP, PHONE } from './viewports';

/**
 * Capture the Tasks board after a press on a card in the last column. The board must
 * stay at the column that it was scrolled to. Run via:
 *   SHOT_DIR=../../docs/images npx playwright test --config=screenshots-board-scroll.config.ts
 */
const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

async function shoot(page: Page, file: string): Promise<void> {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-board-col .hk-bcard').first()).toBeVisible();
  // Wide columns, so that the board scrolls on a desktop too.
  await panel.evaluate((el) => {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync('.hk-board { grid-auto-columns: 480px !important; }');
    el.shadowRoot!.adoptedStyleSheets = [...el.shadowRoot!.adoptedStyleSheets, sheet];
    const b = el.shadowRoot!.querySelector('.hk-board') as HTMLElement;
    b.style.scrollSnapType = 'none';
    b.scrollLeft = b.scrollWidth;
  });
  await panel.locator('.hk-board-col:last-child .hk-bcard').first().click();
  await expect(panel.locator('ha-adaptive-dialog[open]')).toHaveCount(1);
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/${file}` });
  await page.keyboard.press('Escape');
}

test('board keeps its scroll after a press on a card', async ({ page }) => {
  await page.setViewportSize(DESKTOP);
  await openPanel(page);
  await setTaskLayout(page, 'board');
  try {
    await shoot(page, '534-panel-board-scroll.png');
    await page.setViewportSize(PHONE);
    await shoot(page, '534b-panel-mobile-board-scroll.png');
  } finally {
    await setTaskLayout(page, 'rows');
  }
});
