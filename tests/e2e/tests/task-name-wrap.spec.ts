import { expect, test } from '@playwright/test';
import { openPanel } from './helpers';

/**
 * A task row's name keeps a readable column when the drawer takes half the panel.
 *
 * Above 1151px the row is a grid, and its tracks used to be a zero-floor name track
 * beside a fixed chip track. That holds while the panel has the window. Open the
 * drawer and the panel is ~515px against ~728px of tracks, and every pixel of the
 * shortfall came off the one track that could give: the name fell to 17px, and
 * because the text also carried overflow-wrap:anywhere it followed the track down to
 * one letter per line. "Wear rain jacket" rendered as a 17px wide, 128px tall column
 * of single letters.
 *
 * It shipped that way, and it is in the committed documentation:
 * docs/images/30b-panel-sensor-backstop.png and its neighbours on main show the
 * stack, because the capture opens the drawer. Nothing failed, because no test
 * measured a rendered box and a screenshot is not an assertion (AGENTS.md says
 * exactly this about #221).
 *
 * So this measures boxes, with the drawer open. Nothing below a browser can: the
 * collapse is the grid algorithm resolving track sizes against content, which jsdom
 * does not implement and no schema-level test can see.
 */
test.describe('Home Keeper panel — a task name keeps its column', () => {
  test('the name survives the drawer taking half the panel @responsive', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('#hk-list')).toBeVisible();

    // The drawer is the trigger. Below 1151px it is a full-width sheet and the row is
    // a flex line, so this is a no-op there rather than a different test.
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-form')).toBeVisible();
    await page.waitForTimeout(400);

    const measured = await panel.locator('.hk-name-text').evaluateAll((els) =>
      els
        // Rows inside a collapsed group are laid out at zero width. They are not on
        // screen, so they are not what this measures.
        .filter((el) => el.getBoundingClientRect().width > 0)
        .map((el) => {
          const r = el.getBoundingClientRect();
          return {
            text: (el.textContent ?? '').trim(),
            width: Math.round(r.width),
            height: Math.round(r.height),
          };
        }),
    );

    expect(measured.length, 'the seeded list should have visible rows to measure').toBeGreaterThan(
      0,
    );

    for (const row of measured) {
      if (!row.text) continue;
      // A collapsed column is one character wide (17px at this font size). 40px sits
      // clear of that and well under any real name's column.
      expect(
        row.width,
        `"${row.text}" collapsed to a ${row.width}px column`,
      ).toBeGreaterThan(40);

      // The shape check is the one that names the bug: a letter-per-line stack is far
      // taller than it is wide. A name that honestly wraps to 2 or 3 lines stays well
      // inside this, and a 1-line name is 16px tall.
      expect(
        row.height,
        `"${row.text}" is ${row.height}px tall in a ${row.width}px column, which is a letter-per-line stack`,
      ).toBeLessThan(row.width);
    }
  });
});
