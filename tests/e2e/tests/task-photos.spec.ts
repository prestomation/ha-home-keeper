import { expect, test, type Page } from '@playwright/test';
import { authToken, openPanel, trackPanelErrors } from './helpers';
import { PHOTO, TASK } from '../fixture-ids';

/**
 * Task photos (#399). The seeded "Replace fridge filter" task carries 2 photos; the
 * filter housing is the cover.
 *
 * Every image here is served only through a signed URL, so the assertions read the
 * `src`/`href` the panel filled in and then fetch it, rather than trusting the picture.
 */

const BASE = process.env.HA_URL || 'http://localhost:8123';

async function openTask(page: Page) {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();
  await expect(panel.locator('.hk-subtab[data-tab="schedule"].active')).toBeVisible();
  return panel;
}

/** Fetch a signed, site-relative URL with no auth header, as an <img> does. */
async function fetchSigned(page: Page, url: string) {
  return page.request.get(`${BASE}${url}`);
}

test.describe('Task photos (#399)', { tag: '@responsive' }, () => {
  test('the task page shows the cover and a strip of signed photos', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await openTask(page);

    const cover = panel.locator('a.hk-task-cover img.hk-task-cover-img');
    await expect(cover).toHaveAttribute(
      'src',
      new RegExp(
        `^/api/home_keeper/task_photo/${TASK.fridgeFilter}/${PHOTO.filterHousing}\\?size=thumb&authSig=`,
      ),
      { timeout: 15_000 },
    );
    await expect(panel.locator('a.hk-task-cover')).toHaveAttribute(
      'href',
      new RegExp(`/${PHOTO.filterHousing}\\?authSig=`),
    );

    const tiles = panel.locator('.hk-photo');
    await expect(tiles).toHaveCount(2);
    await expect(tiles.first()).toHaveAttribute('data-photo-tile', PHOTO.filterHousing);
    await expect(tiles.first().locator('.hk-photo-badge')).toHaveText('Cover');
    // The cover has no "make cover" button; the second photo does.
    await expect(tiles.first().locator('.hk-photo-cover-btn')).toHaveCount(0);
    await expect(tiles.nth(1).locator('.hk-photo-cover-btn')).toHaveCount(1);
    await expect(panel.locator('.hk-section-count').first()).toHaveText('2 of 6');

    // The signed URLs really serve the thumbnail and the original.
    const thumb = await cover.getAttribute('src');
    const thumbRes = await fetchSigned(page, thumb!);
    expect(thumbRes.status()).toBe(200);
    expect(thumbRes.headers()['content-type']).toContain('image/jpeg');
    const full = await panel.locator('a.hk-task-cover').getAttribute('href');
    const fullRes = await fetchSigned(page, full!);
    expect(fullRes.status()).toBe(200);
    expect((await fullRes.body()).length).toBeGreaterThan((await thumbRes.body()).length);

    expect(errors, 'no panel errors').toEqual([]);
  });

  test('the task list row shows the cover thumbnail', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const row = panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`);
    await expect(row.locator('img.hk-row-cover')).toHaveAttribute('src', /size=thumb&authSig=/, {
      timeout: 15_000,
    });
    // A task with no photos has no thumbnail.
    await expect(
      panel.locator(`.detail-open[data-detail-id="${TASK.furnaceFilter}"] img.hk-row-cover`),
    ).toHaveCount(0);
  });

  test('the completion dialog shows the cover', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator(`.done-btn[data-id="${TASK.fridgeFilter}"]`).click();
    const cover = panel.locator('ha-dialog[open] .hk-completion-cover img');
    await expect(cover).toHaveAttribute('src', /size=thumb&authSig=/, { timeout: 15_000 });
    await page.keyboard.press('Escape');
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });
  });

  test('a photo can be added, made the cover and removed', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await openTask(page);
    const tiles = panel.locator('.hk-photo');
    await expect(tiles).toHaveCount(2);

    // A real PNG: the backend decodes it to make the thumbnail.
    const png = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
      'base64',
    );
    await panel
      .locator('.hk-photo-add + input[type="file"]')
      .setInputFiles({ name: 'new-gap.png', mimeType: 'image/png', buffer: png });
    await expect(tiles).toHaveCount(3, { timeout: 20_000 });
    const added = tiles.nth(2);
    const addedId = await added.getAttribute('data-photo-tile');
    expect(addedId).toBeTruthy();

    await added.locator('.hk-photo-cover-btn').click();
    await expect(tiles.first()).toHaveAttribute('data-photo-tile', addedId!, { timeout: 15_000 });

    // Put the seed back: remove the new photo, which leaves the original order.
    await tiles.first().locator('.hk-photo-remove').click();
    const scrim = page.locator('.hk-confirm-scrim');
    await expect(scrim).toBeVisible();
    await scrim.locator('ha-button').filter({ hasText: /Delete|Remove/i }).click();
    await expect(tiles).toHaveCount(2, { timeout: 15_000 });
    await expect(tiles.first()).toHaveAttribute('data-photo-tile', PHOTO.filterHousing);

    expect(errors, 'no panel errors').toEqual([]);
  });

  test('the photo upload refuses a PDF', async ({ page }) => {
    const res = await page.request.post(
      `${BASE}/api/home_keeper/task_photo/${TASK.fridgeFilter}/3f2c8a1e-5b6d-4c7e-8f90-a1b2c3d4e5f6`,
      {
        headers: { Authorization: `Bearer ${authToken()}` },
        multipart: {
          file: { name: 'manual.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nxx') },
        },
      },
    );
    expect(res.status()).toBe(400);
    expect((await res.json()).message).toContain('unsupported photo type');
  });
});
