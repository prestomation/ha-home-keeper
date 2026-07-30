import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';

/**
 * The appliance detail page's "Manuals & documents" section, and a part's attached
 * file — the surfaces issue #164 reported as untappable on mobile.
 *
 * Every openable file must be a **real anchor carrying an href before the click**: a
 * `window.open` issued after the async signing round-trip is silently swallowed by the
 * iOS companion app's WKWebView, so a "sign on click" handler does nothing there. These
 * assertions are the regression guard — if a file link ever loses its href, it's broken
 * on mobile again.
 */
test.describe('Appliance documents open by a native tap (issue #164)', () => {
  test('every document and part file is an href-bearing anchor', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-appliances').click();
    await panel.locator('.detail-open[data-detail-id="asset_water_heater"]').click();

    // The seeded water heater carries one of each: an external link document
    // ("Owner's manual") and an uploaded file document ("Installation guide (PDF)").
    const docs = panel.locator('.hk-doc-row a.hk-doc-file');
    await expect(docs).toHaveCount(2, { timeout: 30_000 });

    const link = docs.filter({ hasText: "Owner's manual" });
    await expect(link).toHaveAttribute('href', 'https://example.com/water-heater-manual');
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', /noopener/);

    // The uploaded file's href is a pre-signed, site-relative URL minted at render —
    // not resolved on click. `toHaveAttribute` fails if the attribute is absent, which
    // is exactly the broken state (an href-less <a role="button">).
    const file = docs.filter({ hasText: 'Installation guide (PDF)' });
    await expect(file).toHaveAttribute(
      'href',
      /^\/api\/home_keeper\/document\/asset_water_heater\/asset_water_heater_doc_manual_pdf\?authSig=/,
      { timeout: 15_000 },
    );
    await expect(file).toHaveAttribute('target', '_blank');
    // A link, not a button wearing a link's clothes.
    await expect(file).not.toHaveAttribute('role', 'button');

    // The anode rod's attached receipt gets the same treatment.
    const clip = panel.locator('a.hk-part-file[data-part="part_anode"]');
    await expect(clip).toHaveAttribute(
      'href',
      /^\/api\/home_keeper\/part_document\/asset_water_heater\/part_anode\?authSig=/,
      { timeout: 15_000 },
    );

    expect(errors, 'no panel errors').toEqual([]);
  });

  test("the edit form's Open action is a native link too", async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-appliances').click();
    await panel.locator('.detail-open[data-detail-id="asset_water_heater"]').click();
    await panel.locator('.d-edit').click();

    // The uploaded document's card in the documents editor — its Open action must be an
    // anchor carrying the signed URL, not an icon-button that signs on click.
    const card = panel.locator('.hk-doc-card', { hasText: 'Installation guide (PDF)' });
    const open = card.locator('a.hk-doc-open');
    await expect(open).toHaveAttribute('href', /authSig=/, { timeout: 30_000 });
    const [opened] = await Promise.all([page.waitForEvent('popup'), open.click()]);
    await opened.close();
  });

  test('tapping an uploaded document actually opens it', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-appliances').click();
    await panel.locator('.detail-open[data-detail-id="asset_water_heater"]').click();

    const file = panel
      .locator('.hk-doc-row a.hk-doc-file')
      .filter({ hasText: 'Installation guide (PDF)' });
    await expect(file).toHaveAttribute('href', /authSig=/, { timeout: 30_000 });
    const href = await file.getAttribute('href');

    // The click must open a tab — the bug was a tap that produced nothing at all,
    // because the JS handler's window.open never fired. (We don't assert the popup's
    // URL: headless Chromium hands a PDF to its download path, leaving the tab's URL
    // empty, so the href itself is verified separately below.)
    const [opened] = await Promise.all([page.waitForEvent('popup'), file.click()]);
    await opened.close();

    // And the pre-minted signature is one the backend actually honours — a URL that
    // 401s would be just as dead an end for the user as no href at all.
    const response = await page.request.get(href!);
    expect(response.status()).toBe(200);
    expect(response.headers()['content-type']).toContain('application/pdf');
  });
});
