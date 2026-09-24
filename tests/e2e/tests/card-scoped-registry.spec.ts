import { test, expect } from '@playwright/test';
import { DASHBOARD } from './helpers';

/**
 * Regression test for #368 — "Custom element doesn't exist: home-keeper-card",
 * on some page loads only.
 *
 * Home Assistant 2026.9 replaces `window.customElements` with the
 * `@webcomponents/scoped-custom-element-registry` polyfill. The polyfill does not
 * see an element that was defined in the native registry before it was installed.
 * When the app shell imports the card bundle, and the bundle runs before the
 * frontend's own bundles, the card lands in the native registry. The Lovelace
 * resource then imports the same URL, the browser does not run the module again,
 * and the card factory gets `undefined` from the registry it asks.
 *
 * In the field the card bundle comes from the browser cache and wins the race by
 * chance. Here we make it win every time: the frontend's `core` and `app` bundles
 * are held back, and nothing else is. The card must still render.
 *
 * `tests/integration/test_card_resource.py` pins the cause without timing: in
 * storage resource mode the app shell does not import the card bundle at all.
 */

// A service worker answers requests before `page.route` sees them, so the delay
// would not apply to a bundle it serves.
test.use({ serviceWorkers: 'block' });

// Long enough that the card bundle, which is not held, always runs first.
const HOLD_MS = 3_000;
const FRONTEND_BOOT = /^\/frontend_latest\/(core|app)\.[0-9a-f]+\.js$/;

test.describe('Home Keeper card — scoped registry (#368)', () => {
  test('renders when its bundle runs before the frontend boots', async ({ page }) => {
    test.setTimeout(120_000);

    const held: string[] = [];
    await page.route(
      (url) => FRONTEND_BOOT.test(url.pathname),
      async (route) => {
        held.push(new URL(route.request().url()).pathname);
        await new Promise((r) => setTimeout(r, HOLD_MS));
        await route.continue();
      },
    );

    // Keep a reference to the native registry before any page script runs, so the
    // test can tell whether the frontend replaced it.
    await page.addInitScript(() => {
      (window as unknown as { __hkNativeRegistry: CustomElementRegistry }).__hkNativeRegistry =
        window.customElements;
    });

    await page.goto(DASHBOARD, { waitUntil: 'domcontentloaded' });

    // Guard the guard: without the hold, this test proves nothing.
    expect(held, 'the frontend boot bundles were never held back').not.toHaveLength(0);

    // Deliberately not `helpers.openCardDashboard`: its reload retry would hide
    // exactly this failure.
    await expect(page.locator('hui-error-card, home-keeper-card').first()).toBeAttached({
      timeout: 60_000,
    });
    // Let the frontend settle. A late definition would rebuild the card.
    await page.waitForTimeout(2_000);

    const state = await page.evaluate((tag) => {
      const w = window as unknown as { __hkNativeRegistry: CustomElementRegistry };
      return {
        polyfilled: window.customElements !== w.__hkNativeRegistry,
        inPageRegistry: !!window.customElements.get(tag),
        inNativeRegistry: !!w.__hkNativeRegistry.get(tag),
      };
    }, 'home-keeper-card');

    // Also guard the guard. If a future frontend drops the polyfill, the race is
    // gone and this spec needs a new reason to exist.
    expect(state.polyfilled, 'the frontend no longer replaces window.customElements').toBe(true);

    // What the card factory reads. On #368 this is false.
    expect(
      state.inPageRegistry,
      `home-keeper-card is not in the registry the card factory reads (${JSON.stringify(state)}) — issue #368`,
    ).toBe(true);
    await expect(page.locator('hui-error-card')).toHaveCount(0);
    const card = page.locator('home-keeper-card').first();
    await expect(card.locator('.hk-title').first()).toContainText('Home maintenance');
  });
});
