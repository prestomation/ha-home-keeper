/**
 * One-off exploration capturing how Home Assistant's built-in `date` selector
 * behaves in the appliance create form — does it offer any faster way to enter a
 * date that's years in the past than stepping back one month at a time?
 *
 * Not part of the e2e suite (filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=/tmp/date-shots npx playwright test date-control-explore.capture.ts \
 *     --config=date-control-explore.config.ts
 *
 * Context: the panel's purchase/install/warranty fields are `{ date: {} }`
 * selectors -> `ha-selector-date` -> `ha-date-input` -> (on open) an
 * `ha-dialog-date-picker` modal. On HA 2026.6 that dialog is built on the Cally
 * calendar web component (`<calendar-date>` / `<calendar-month>`).
 */
import { test, expect, Locator } from '@playwright/test';
import { openPanel } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/date-shots';

async function fillText(scope: Locator, nth: number, value: string): Promise<void> {
  await scope.locator('ha-selector-text').nth(nth).locator('input, textarea').fill(value);
}

test('explore the HA date selector for years-ago dates', async ({ page }) => {
  test.setTimeout(120_000); // the ~96 month-back clicks are deliberately slow
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();

  await panel.locator('#tab-appliances').click();
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-asset-form')).toBeVisible();
  const assetForm = panel.locator('#hk-asset-form');
  await fillText(assetForm, 0, 'Garage water heater');

  const purchase = assetForm.locator('ha-selector-date').first();
  await purchase.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);

  // (1) The three date fields as they sit in the form. The native input is
  //     readOnly + type=text, so you cannot type a date into it.
  const ro = await purchase
    .locator('input')
    .first()
    .evaluate((el: HTMLInputElement) => ({ readOnly: el.readOnly, type: el.type }));
  console.log(`Closed field input -> readOnly=${ro.readOnly}, type=${ro.type}`);
  await page.screenshot({ path: `${OUT}/date-01-closed-fields.png`, fullPage: true });

  // (2) Open the picker: the default month-grid calendar with only < / > month
  //     navigation arrows (and a "Today" jump), titled "Select date".
  await purchase.click();
  const dialog = page.locator('ha-dialog-date-picker');
  await expect(dialog.getByRole('button', { name: /^OK$/i }).first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/date-02-picker-month-view.png`, fullPage: true });

  // (3) Selecting a day morphs the header into "<year> / <full date>". The year
  //     ("2026") looks like it might be a clickable shortcut to a year list — it
  //     is NOT (role=button count is 0, and clicking the text does nothing).
  await dialog.getByRole('button', { name: /^June 16$/ }).first().click().catch(() => {});
  await page.waitForTimeout(300);
  await dialog.getByText(/^(19|20)\d{2}$/).first().click().catch(() => {});
  await page.waitForTimeout(300);
  const yearBtns = await dialog.getByRole('button', { name: /^(19|20)\d{2}$/ }).count();
  console.log(`Year-as-button count after clicking the header year: ${yearBtns} (0 = inert label)`);
  await page.screenshot({ path: `${OUT}/date-03-header-year-inert.png`, fullPage: true });

  // (4) The only way to reach a years-ago date is the "<" arrow, one month per
  //     click. From June 2026, reaching ~2018 takes ~96 clicks. Demonstrate it.
  // Drive the 96 month-back clicks inside the page (piercing shadow roots to find
  // the "Back" arrow each time) — far faster than 96 Playwright round-trips, and
  // resilient to Cally re-rendering the month grid between clicks.
  await page.evaluate(async (n: number) => {
    const findBack = (): HTMLElement | null => {
      const roots: (Document | ShadowRoot)[] = [document];
      while (roots.length) {
        const root = roots.shift()!;
        const hit = root.querySelector('button[aria-label="Back"]') as HTMLElement | null;
        if (hit) return hit;
        root.querySelectorAll('*').forEach((el) => {
          const sr = (el as HTMLElement & { shadowRoot?: ShadowRoot }).shadowRoot;
          if (sr) roots.push(sr);
        });
      }
      return null;
    };
    for (let i = 0; i < n; i++) {
      findBack()?.click();
      await new Promise((r) => setTimeout(r, 15));
    }
  }, 96);
  await page.waitForTimeout(400);
  const header = (await dialog.getByText(/\b(19|20)\d{2}\b/).first().textContent().catch(() => '')) || '';
  console.log(`Header after 96 "<" clicks: "${header.trim()}"`);
  await page.screenshot({ path: `${OUT}/date-04-stepped-back-old-year.png`, fullPage: true });

  // (5) Pick a day + confirm to show an old date does land in the field.
  await dialog.getByRole('button', { name: /\b15\b/ }).first().click().catch(() => {});
  await page.waitForTimeout(200);
  await dialog.getByRole('button', { name: /^OK$/i }).first().click().catch(() => {});
  await page.waitForTimeout(400);
  await purchase.scrollIntoViewIfNeeded();
  const finalVal = await purchase.locator('input').first().evaluate((el: HTMLInputElement) => el.value);
  console.log(`Field value after confirming the old date: "${finalVal}"`);
  await page.screenshot({ path: `${OUT}/date-05-old-date-filled.png`, fullPage: true });

  console.log(
    `\nSUMMARY (HA 2026.6 date selector): input is readOnly (no typing); picker navigates ` +
      `month-by-month only via < / >; the header year is an inert label (year-button count=${yearBtns}); ` +
      `reaching ~2018 required 96 clicks; final field value="${finalVal}".`,
  );
});
