import { test, expect, type Locator } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';
import { TASK } from '../fixture-ids';

/**
 * The weights, measured in rendered pixels (#262).
 *
 * These assert on colour, not on attributes, and that is the entire point. The panel
 * spent twelve buttons asking for `raised` and several more for `destructive`, both
 * of which Home Assistant's `ha-button` stopped reading when it moved to Web Awesome.
 * Every one of them silently rendered at the default accent fill, and no test noticed,
 * because the markup still said what it had always said. An attribute assertion would
 * have passed then and would pass again after the next rename; only the pixels can
 * tell you that Cancel is not drawn like Confirm.
 */

/** The background and label of a button's inner `part="base"`, as the browser paints it. */
async function paint(button: Locator): Promise<{ bg: string; fg: string }> {
  return button.evaluate((el) => {
    const base = (el as HTMLElement & { shadowRoot: ShadowRoot | null }).shadowRoot?.querySelector(
      '[part~="base"]',
    ) as HTMLElement | null;
    const cs = getComputedStyle(base ?? (el as HTMLElement));
    return { bg: cs.backgroundColor, fg: cs.color };
  });
}

const TRANSPARENT = 'rgba(0, 0, 0, 0)';

/** Parse an `rgb()`/`rgba()` string into channels. */
function channels(colour: string): [number, number, number] {
  const m = colour.match(/(\d+(?:\.\d+)?)/g);
  if (!m) throw new Error(`unparseable colour: ${colour}`);
  return [Number(m[0]), Number(m[1]), Number(m[2])];
}

/** True when the colour is visibly red-dominant — a destructive control. */
function readsAsDanger(colour: string): boolean {
  const [r, g, b] = channels(colour);
  return r > g + 40 && r > b + 40;
}

test.describe('Home Keeper panel — button weights are drawn, not just declared', () => {
  test('a task page draws Done, Edit and Delete at three different weights', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();
    await expect(panel.locator('.d-del')).toBeVisible();

    const done = await paint(panel.locator('.d-done'));
    const edit = await paint(panel.locator('.d-edit'));
    const del = await paint(panel.locator('.d-del'));

    // The bug: all three arrived at the same fill, the destructive one loudest.
    expect(done.bg, 'Done and Edit must not be the same weight').not.toBe(edit.bg);
    expect(done.bg, 'Done and Delete must not be the same weight').not.toBe(del.bg);

    // Done is the page's one primary: a solid, opaque fill.
    expect(done.bg).not.toBe(TRANSPARENT);
    // Delete recedes to text, and is red — the only destructive weight on this page.
    expect(del.bg, 'Delete must not carry a fill beside two other actions').toBe(TRANSPARENT);
    expect(readsAsDanger(del.fg), `Delete label should read red, got ${del.fg}`).toBe(true);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('the completion dialog does not draw Cancel at confirm weight', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await panel.locator(`.done-btn[data-id="${TASK.fridgeFilter}"]`).click();
    const dialog = panel.locator('ha-dialog[open]');
    await dialog
      .locator('ha-selector-text textarea, ha-selector-text input')
      .first()
      .waitFor({ state: 'visible', timeout: 15_000 });

    const markDone = await paint(dialog.getByRole('button', { name: 'Mark done' }));
    const skip = await paint(dialog.getByRole('button', { name: 'Skip details' }));
    const cancel = await paint(dialog.getByRole('button', { name: 'Cancel' }));

    // Three solid accent fills in a row was the reported state: the null action drawn
    // exactly as loudly as the two that commit.
    expect(cancel.bg, 'Cancel must not be filled').toBe(TRANSPARENT);
    expect(markDone.bg, 'Mark done is the primary and must be filled').not.toBe(TRANSPARENT);
    expect(skip.bg, 'Skip details is tonal, not the primary').not.toBe(markDone.bg);
    expect(skip.bg, 'Skip details is tonal, not tertiary').not.toBe(TRANSPARENT);

    await page.keyboard.press('Escape');
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('every tonal label clears the contrast a label needs', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.done-btn').first()).toBeVisible();

    // HA's own tonal label on its own tonal fill measures 2.85:1. The panel restates it
    // from `--hk-accent-ink` through `::part(base)`, keyed off the weight so a button
    // cannot opt out by being written somewhere new — this checks the rule reaches
    // every one of them, not just the one that was fixed by hand.
    const tonal = panel.locator('[data-hk-weight="secondary"]');
    const count = await tonal.count();
    expect(count, 'expected some tonal buttons on the task list').toBeGreaterThan(0);
    for (let i = 0; i < count; i += 1) {
      const { bg, fg } = await paint(tonal.nth(i));
      if (bg === TRANSPARENT) continue; // not painted yet / off-screen
      expect(contrast(fg, bg), `tonal button ${i}: ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});

/** WCAG relative luminance. */
function luminance(colour: string): number {
  const [r, g, b] = channels(colour).map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio between two opaque colours. */
function contrast(a: string, b: string): number {
  const [la, lb] = [luminance(a), luminance(b)];
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}
