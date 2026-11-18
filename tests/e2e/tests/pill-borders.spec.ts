import { test, expect } from '@playwright/test';
import { openListFilters, openPanel } from './helpers';

/**
 * A pill keeps its whole outline (#554).
 *
 * A group of choices (`.hk-seg`) is 1 pill: the group clips its buttons with
 * `overflow: hidden` and rounded ends. The selected button is a square box with an
 * inset ring. Where its square corner sits under the rounded end of the group, the
 * clip cuts the ring, and the end of the pill looks flat and open. So each button at
 * an end of a clipping group must carry the same round end, and each button of a group
 * that does not clip must be a pill on its own.
 */
test.describe('Home Keeper — pill outlines (#554)', () => {
  const PAGES: Array<[string, string]> = [
    ['the Appliances page', '/home-keeper/appliances'],
    ['the Parts page', '/home-keeper/appliances/parts'],
    ['the Tasks page', '/home-keeper'],
  ];

  for (const [name, url] of PAGES) {
    test(`every choice pill on ${name} has round ends @responsive`, async ({ page }) => {
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      const panel = page.locator('home-keeper-panel').first();
      await expect(panel.locator('.hk-wrap')).toBeVisible();
      if ((await panel.locator('#hk-filters-btn').count()) > 0) await openListFilters(panel);
      expect(await panel.locator('.hk-seg:visible').count(), 'a page with pills').toBeGreaterThan(0);

      const bad = await panel.evaluate((host) => {
        const out: string[] = [];
        const px = (v: string): number => parseFloat(v) || 0;
        host.shadowRoot!.querySelectorAll<HTMLElement>('.hk-seg').forEach((seg) => {
          const sr = seg.getBoundingClientRect();
          if (sr.width === 0 || sr.height === 0) return;
          const sc = getComputedStyle(seg);
          const clips = sc.overflowX !== 'visible' && px(sc.borderTopLeftRadius) > 0;
          const ring = px(sc.borderTopWidth);
          const buttons = Array.from(seg.querySelectorAll<HTMLElement>(':scope > .hk-seg-btn'));
          buttons.forEach((btn, i) => {
            const c = getComputedStyle(btn);
            const r = btn.getBoundingClientRect();
            if (r.width === 0) return;
            const high = clips ? sr.height / 2 - ring : r.height / 2;
            const need = high - 1.5;
            const corners = {
              tl: px(c.borderTopLeftRadius),
              tr: px(c.borderTopRightRadius),
              br: px(c.borderBottomRightRadius),
              bl: px(c.borderBottomLeftRadius),
            };
            const first = i === 0;
            const last = i === buttons.length - 1;
            const want: Array<keyof typeof corners> = clips
              ? [...(first ? (['tl', 'bl'] as const) : []), ...(last ? (['tr', 'br'] as const) : [])]
              : ['tl', 'tr', 'br', 'bl'];
            for (const k of want) {
              if (corners[k] < need) {
                out.push(`${(btn.textContent || '').trim().slice(0, 12)} ${k}=${corners[k]} < ${need}`);
              }
            }
          });
        });
        return out;
      });
      expect(bad, 'each outer corner of a choice pill is round').toEqual([]);
    });
  }
});
