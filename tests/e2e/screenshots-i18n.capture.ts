/**
 * One-off screenshot capture for the i18n PR — shows the panel rendered in
 * several Home Assistant languages. Not part of the e2e suite (filename does not
 * match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots-i18n.capture.ts \
 *     --config=screenshots-i18n.config.ts
 *
 * The panel follows `hass.language`, which the HA frontend derives from the
 * `selectedLanguage` value in localStorage. We set it before navigating, reload,
 * and screenshot — so both HA's chrome and our panel render in that language.
 */
import { test, expect, Page } from '@playwright/test';
import { openPanel } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

// A representative spread of the 16 shipped locales.
const LANGS: { code: string; file: string }[] = [
  { code: 'en', file: '1-i18n-panel-en.png' },
  { code: 'de', file: '2-i18n-panel-de.png' },
  { code: 'fr', file: '3-i18n-panel-fr.png' },
  { code: 'zh-Hans', file: '4-i18n-panel-zh-Hans.png' },
];

async function setLanguage(page: Page, code: string): Promise<void> {
  // HA reads the selected language from this localStorage key (JSON-encoded).
  await page.addInitScript((lang) => {
    window.localStorage.setItem('selectedLanguage', JSON.stringify(lang));
  }, code);
}

test('capture Home Keeper panel localized in several languages', async ({ page }) => {
  for (const { code, file } of LANGS) {
    await setLanguage(page, code);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.hk-name').first()).toBeVisible();
    // Let the HA sidebar/layout and any lazy HA components settle.
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/${file}`, fullPage: true });
  }

  // One localized create form (German) so the localized ha-form field labels and
  // dropdown options are visible too.
  await setLanguage(page, 'de');
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${OUT}/5-i18n-task-form-de.png`, fullPage: true });
});
