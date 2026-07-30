import { expect, test } from '@playwright/test';
import { openPanel } from './helpers';

/**
 * Uploads in the appliance editor (issue #159).
 *
 * The bug wasn't a missing error — it was an error the user never saw, rendered in
 * the form-level alert far below the button that produced it. The assertion that
 * matters here is therefore `toBeInViewport()`: the failure must be on screen,
 * next to the control, without scrolling.
 */

/** Open the seeded water heater's edit form. */
async function openApplianceEditor(page) {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await panel.locator('#tab-appliances').click();
  await panel.locator('.detail-open[data-detail-id="asset_water_heater"]').click();
  await expect(panel.locator('.d-edit')).toBeVisible();
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-asset-form')).toBeVisible();
  return panel;
}

/**
 * Put a file on the documents picker without shipping its bytes through CDP.
 * `setInputFiles` with 100+ MB is slow and pointless — the pre-check only reads
 * `file.size`, and a real oversized upload would take minutes to be refused.
 */
async function pickFile(panel, sizeBytes: number, filename: string) {
  // The picker is inside the panel's shadow root, which Playwright locators pierce
  // but `document.querySelector` does not — so hand the element to evaluate().
  await panel
    .locator('.hk-doc-add input[type="file"]')
    .evaluate((picker: HTMLInputElement, { size, name }) => {
      const file = new File([new Uint8Array(8)], name, { type: 'application/pdf' });
      Object.defineProperty(file, 'size', { value: size });
      const dt = new DataTransfer();
      dt.items.add(file);
      Object.defineProperty(picker, 'files', { value: dt.files, configurable: true });
      picker.dispatchEvent(new Event('change'));
    }, { size: sizeBytes, name: filename });
}

test('an oversized file fails visibly, next to the upload button', async ({ page }) => {
  const panel = await openApplianceEditor(page);
  await pickFile(panel, 101 * 1024 * 1024, 'huge-manual.pdf');

  const alert = panel.locator('.hk-doc-add ha-alert[alert-type="error"]');
  await expect(alert).toBeVisible();
  // The regression assertion for #159: visible *without scrolling*.
  await expect(alert).toBeInViewport();
  await expect(alert).toContainText('100 MB');

  // ...and it sits next to the control that caused it, not hundreds of px away.
  const button = panel.locator('.hk-doc-add ha-button', { hasText: 'Upload file' });
  const [alertBox, buttonBox] = [await alert.boundingBox(), await button.boundingBox()];
  expect(alertBox && buttonBox).toBeTruthy();
  expect(Math.abs(alertBox!.y - buttonBox!.y)).toBeLessThan(200);
});

test('a valid upload shows progress and adds the document', async ({ page }) => {
  const panel = await openApplianceEditor(page);

  // Hold the response open so the in-flight UI is observable; a LAN upload of a
  // small file would otherwise be over before the bar renders.
  let release: () => void = () => {};
  const held = new Promise<void>((r) => (release = r));
  await page.route('**/api/home_keeper/document/**', async (route) => {
    await held;
    await route.continue();
  });

  // A unique name per run: this uploads to the *seeded* appliance, so a fixed name
  // would collide with a leftover from an earlier local run and match two cards.
  const filename = `e2e-upload-${process.pid}-${Date.now()}.pdf`;
  const chooser = page.waitForEvent('filechooser');
  await panel.locator('.hk-doc-add ha-button', { hasText: 'Upload file' }).click();
  await (await chooser).setFiles({
    name: filename,
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'),
  });

  // In-flight: the bar renders and the buttons lock so nothing can race the upload.
  await expect(panel.locator('#hk-upload-bar')).toBeVisible();
  const box = await panel.locator('#hk-upload-bar').boundingBox();
  expect(box!.width).toBeGreaterThan(0);
  // The upload button relabels itself and locks; Save locks too so it can't PUT the
  // draft over the asset the upload response is about to rewrite.
  await expect(
    panel.locator('.hk-doc-add ha-button', { hasText: 'Uploading' }),
  ).toHaveAttribute('disabled', '');
  await expect(panel.locator('#a-save')).toHaveAttribute('disabled', '');

  release();
  // Done: progress torn down, the document is listed, and no error is left behind.
  await expect(panel.locator('#hk-upload')).toHaveCount(0);
  const card = panel.locator('.hk-doc-card', { hasText: filename });
  await expect(card).toBeVisible();
  await expect(panel.locator('ha-alert[alert-type="error"]')).toHaveCount(0);

  // Put the seeded appliance back: this test uploads to shared fixture data, and a
  // document left behind changes what the other appliance specs see.
  await card.locator('ha-icon-button[label="Remove document"]').click();
  await expect(card).toHaveCount(0);
});
