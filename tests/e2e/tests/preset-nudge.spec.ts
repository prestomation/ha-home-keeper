import { test, expect, Locator, Page } from '@playwright/test';
import {
  authToken,
  callService,
  gotoTab,
  listTasks,
  openPanel,
  openSettingsSection,
  trackPanelErrors,
} from './helpers';
import {
  FIRMWARE_PRESET,
  INTRO_KEY,
  PRESET_NUDGE_KEY,
  getUserData,
  markAllPresetsSeen,
  setUserData,
  suggestOnly,
} from '../user-data';

/**
 * The preset suggestions on the Tasks tab, end to end.
 *
 * The e2e container has one `update.*` entity, so Firmware update available matches
 * 1 entity. global-setup marks every preset seen and hidden, so no other spec meets
 * the dialog. Each test here hides every preset but that one (`suggestOnly`), which
 * keeps the spec about one preset whatever else the container matches, and
 * `afterEach` puts back the intro answer, the companions and the hidden state.
 */

const FIRMWARE = FIRMWARE_PRESET;

async function listSpecs(): Promise<Array<Record<string, any>>> {
  return (await callService('home_keeper', 'list_declarative_companions', {}, true)).companions;
}

/** The suggestion dialog. Its host never reports visible, so wait on a row in it. */
function presetDialog(panel: Locator): Locator {
  return panel.locator('ha-dialog.hk-preset-dialog');
}

async function openFresh(page: Page): Promise<Locator> {
  await openPanel(page);
  return page.locator('home-keeper-panel').first();
}

test.describe('Home Keeper panel — preset suggestions', { tag: '@responsive' }, () => {
  let intro: unknown;
  let seeded: Set<string>;

  test.beforeEach(async () => {
    intro = await getUserData(authToken(), INTRO_KEY);
    seeded = new Set((await listSpecs()).map((s) => s.id as string));
    await setUserData(authToken(), INTRO_KEY, true);
    await suggestOnly(authToken(), FIRMWARE);
  });

  test.afterEach(async () => {
    for (const spec of await listSpecs()) {
      if (seeded.has(spec.id as string)) continue;
      await callService('home_keeper', 'delete_declarative_companion', { id: spec.id }).catch(
        () => undefined,
      );
    }
    await setUserData(authToken(), INTRO_KEY, intro);
    await markAllPresetsSeen(authToken());
  });

  test('the dialog opens once, then Not now leaves the card', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await openFresh(page);
    const dialog = presetDialog(panel);
    const row = dialog.locator('label.hk-preset-pick');
    await expect(row).toHaveCount(1, { timeout: 20_000 });
    await expect(row).toBeVisible();
    await expect(row).toContainText('Firmware update available');
    await expect(row).toContainText('1 entity matches');
    await expect(row.getByRole('checkbox')).toBeChecked();
    const add = dialog.locator('ha-button.hk-preset-dialog-add');
    const later = dialog.locator('ha-button.hk-preset-dialog-later');
    await expect(add).toHaveText('Add 1 preset');
    await expect(add).toBeInViewport();
    await expect(later).toBeInViewport();

    await later.click();
    await expect(dialog).toHaveCount(0);
    const card = panel.locator('.hk-preset-nudge');
    await expect(card).toBeVisible();
    const cardRow = card.locator('.hk-preset-nudge-row');
    await expect(cardRow).toHaveCount(1);
    await expect(cardRow).toContainText('1 entity matches');
    // The row sits inside its card: no clipped Set up at any width.
    const cardBox = await card.boundingBox();
    const setupBox = await cardRow.locator('.hk-preset-nudge-setup').boundingBox();
    expect(cardBox && setupBox).toBeTruthy();
    expect(setupBox!.x + setupBox!.width).toBeLessThanOrEqual(cardBox!.x + cardBox!.width + 1);

    // The dialog was a one-time offer; the card stays.
    const again = await openFresh(page);
    await expect(again.locator('.hk-preset-nudge')).toBeVisible();
    await expect(presetDialog(again)).toHaveCount(0);
    const stored = (await getUserData(authToken(), PRESET_NUDGE_KEY)) as {
      shown: string[];
      dismissed: string[];
    };
    expect(stored.shown).toContain(FIRMWARE);
    expect(stored.dismissed).not.toContain(FIRMWARE);
    expect(errors).toEqual([]);
  });

  test('Add makes the companion and its task', async ({ page }) => {
    const panel = await openFresh(page);
    const dialog = presetDialog(panel);
    await expect(dialog.locator('label.hk-preset-pick')).toHaveCount(1, { timeout: 20_000 });
    await dialog.locator('ha-button.hk-preset-dialog-add').click();
    await expect(dialog).toHaveCount(0, { timeout: 30_000 });

    await expect
      .poll(async () => (await listSpecs()).filter((s) => s.preset_id === FIRMWARE).length, {
        timeout: 30_000,
      })
      .toBe(1);
    await expect(panel.locator('.hk-preset-nudge')).toHaveCount(0);
    await expect
      .poll(async () => (await listTasks()).some((t) => /HK demo router firmware/.test(t.name)), {
        timeout: 45_000,
      })
      .toBe(true);

    // The stored companion reads as the preset: what the backend saved is the same
    // spec, so its dialog shows no change.
    await openSettingsSection(panel, 'companions');
    const row = panel.locator('.hk-decl-row', { hasText: 'Firmware update available' });
    await row.locator('.hk-decl-edit').click();
    const form = panel.locator('ha-dialog.hk-decl-dialog');
    await expect(form.locator('.hk-preset-summary')).toBeVisible({ timeout: 20_000 });
    await expect(form.locator('.hk-preset-summary-changed')).toBeHidden();
    await form.locator('.hk-decl-cancel').first().click();
  });

  test('Set up on the card opens the Add dialog on the preset', async ({ page }) => {
    await suggestOnly(authToken(), FIRMWARE, true);
    const panel = await openFresh(page);
    const setup = panel.locator('.hk-preset-nudge-setup');
    await expect(setup).toBeVisible({ timeout: 20_000 });
    await setup.click();
    const form = panel.locator('ha-dialog.hk-decl-dialog');
    await expect(form).toHaveCount(1, { timeout: 20_000 });
    await expect(form.locator('.hk-decl-preview').first()).toBeVisible({ timeout: 20_000 });
    await form.locator('.hk-decl-cancel').first().click();
    await expect(form).toHaveCount(0);
    expect((await listSpecs()).filter((s) => s.preset_id === FIRMWARE)).toEqual([]);
  });

  test('the Add dialog says what the preset does, and Reset puts a change back', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await suggestOnly(authToken(), FIRMWARE, true);
    const panel = await openFresh(page);
    const setup = panel.locator('.hk-preset-nudge-setup');
    await expect(setup).toBeVisible({ timeout: 20_000 });
    await setup.click();
    const form = panel.locator('ha-dialog.hk-decl-dialog');
    const box = form.locator('.hk-preset-summary');
    await expect(box).toBeVisible({ timeout: 20_000 });
    await expect(box.locator('.hk-preset-summary-kicker')).toHaveText('From preset');
    await expect(box.locator('.hk-preset-summary-name')).toHaveText('Firmware update available');
    await expect(box.locator('.hk-preset-summary-desc')).toContainText('update entity');
    await expect(box.locator('.hk-preset-summary-changed')).toBeHidden();
    // Each preview row says what its entity reads now.
    await expect(form.locator('.hk-decl-reading').first()).toContainText('Now:', {
      timeout: 20_000,
    });

    // The state box is the trigger section's first text box.
    const state = form
      .locator('[data-decl-section="trigger"] ha-selector-text')
      .first()
      .locator('input');
    await state.fill('off');
    await state.blur();
    await expect(box.locator('.hk-preset-summary-chip')).toHaveText('Changed: Trigger');
    await expect(box.locator('.hk-preset-summary-changed')).toBeVisible();

    await box.locator('.hk-preset-summary-reset').click();
    // The dialog is drawn again from the preset, so read the new nodes.
    await expect(form.locator('.hk-preset-summary-changed')).toBeHidden();
    await expect(
      form.locator('[data-decl-section="trigger"] ha-selector-text').first().locator('input'),
    ).toHaveValue('on');

    await form.locator('.hk-decl-cancel').first().click();
    await expect(form).toHaveCount(0);
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('Not now on the card hides it for good', async ({ page }) => {
    await suggestOnly(authToken(), FIRMWARE, true);
    const panel = await openFresh(page);
    const card = panel.locator('.hk-preset-nudge');
    await expect(card).toBeVisible({ timeout: 20_000 });
    await card.locator('ha-button.hk-preset-nudge-hide').click();
    await expect(card).toHaveCount(0);
    await expect
      .poll(async () => ((await getUserData(authToken(), PRESET_NUDGE_KEY)) as any)?.dismissed)
      .toContain(FIRMWARE);

    const again = await openFresh(page);
    await expect(again.locator('#hk-list')).toBeVisible();
    await expect(again.locator('.hk-preset-nudge')).toHaveCount(0);
    await expect(presetDialog(again)).toHaveCount(0);
  });

  test('the dialog waits for the task list', async ({ page }) => {
    await page.goto('/home-keeper/settings', { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel).toBeVisible({ timeout: 45_000 });
    await expect(panel.locator('#hk-list')).toHaveCount(0);
    await expect(presetDialog(panel)).toHaveCount(0);
    await gotoTab(panel, 'tasks');
    await expect(presetDialog(panel).locator('label.hk-preset-pick')).toHaveCount(1, {
      timeout: 20_000,
    });
  });
});
