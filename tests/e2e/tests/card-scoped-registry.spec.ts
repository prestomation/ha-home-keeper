import { test, expect, type Page } from '@playwright/test';
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
 *
 * The second test is the upgrade case. For up to a day after an upgrade, the service
 * worker can replay a shell that an older Home Keeper rendered, and that shell still
 * imports the card, under the old `?v=` token. With the race forced, the old import
 * defines the card in the native registry. The resource then imports the new token,
 * which is a different module, so the module runs again and defines the card in the
 * frontend's registry.
 */

// A service worker answers requests before `page.route` sees them, so the delay
// would not apply to a bundle it serves.
//
// The flag is for the upgrade test. Chrome classifies a response synthesized by
// `route.fulfill` as coming from a *public* address space, and its Local Network
// Access checks then block the page's own `ws://localhost:8123/api/websocket`. With
// no websocket the resource list never loads. See `card-registration.spec.ts` in
// git history (#228) for how that looked. `launchOptions` replaces the config's copy
// wholesale, so `CHROMIUM_EXEC` is plumbed again here.
test.use({
  serviceWorkers: 'block',
  launchOptions: {
    args: ['--disable-features=LocalNetworkAccessChecks'],
    ...(process.env.CHROMIUM_EXEC ? { executablePath: process.env.CHROMIUM_EXEC } : {}),
  },
});

const TAG = 'home-keeper-card';
// Long enough that the card bundle, which is not held, always runs first.
const HOLD_MS = 3_000;
const FRONTEND_BOOT = /^\/frontend_latest\/(core|app)\.[0-9a-f]+\.js$/;
// What `IndexView` rendered for the card before #368, under a token no build has.
const STALE_IMPORT =
  '<script>import("/home_keeper_panel/home-keeper-card.js?v=000000000000")' +
  '.catch(function (err) { console.error(err); });</script>';
// The shell script that starts the frontend. The stale import goes right after it,
// which is where `IndexView` put extra modules.
const BOOT_SCRIPT_END = 'window.latestJS=!0)</script>';

/** Hold the frontend's boot bundles, and keep a handle on the native registry. */
async function forceTheRace(page: Page): Promise<string[]> {
  const held: string[] = [];
  await page.route(
    (url) => FRONTEND_BOOT.test(url.pathname),
    async (route) => {
      held.push(new URL(route.request().url()).pathname);
      await new Promise((r) => setTimeout(r, HOLD_MS));
      await route.continue();
    },
  );
  // Before any page script runs, so the test can tell whether the frontend
  // replaced the registry.
  await page.addInitScript(() => {
    (window as unknown as { __hkNativeRegistry: CustomElementRegistry }).__hkNativeRegistry =
      window.customElements;
  });
  return held;
}

/** Wait for the dashboard to settle, then assert the card is where HA looks. */
async function expectCardInPageRegistry(page: Page, held: string[]): Promise<void> {
  // Guard the guard: without the hold, this test proves nothing.
  expect(held, 'the frontend boot bundles were never held back').not.toHaveLength(0);

  // Deliberately not `helpers.openCardDashboard`: its reload retry would hide
  // exactly this failure.
  await expect(page.locator(`hui-error-card, ${TAG}`).first()).toBeAttached({
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
  }, TAG);

  // Also guard the guard. If a future frontend drops the polyfill, the race is
  // gone and this spec needs a new reason to exist.
  expect(state.polyfilled, 'the frontend no longer replaces window.customElements').toBe(true);

  // What the card factory reads. On #368 this is false.
  expect(
    state.inPageRegistry,
    `${TAG} is not in the registry the card factory reads (${JSON.stringify(state)}) — issue #368`,
  ).toBe(true);
  await expect(page.locator('hui-error-card')).toHaveCount(0);
  const card = page.locator(TAG).first();
  await expect(card.locator('.hk-title').first()).toContainText('Home maintenance');
}

test.describe('Home Keeper card — scoped registry (#368)', () => {
  test('renders when its bundle runs before the frontend boots', async ({ page }) => {
    test.setTimeout(120_000);
    const held = await forceTheRace(page);
    await page.goto(DASHBOARD, { waitUntil: 'domcontentloaded' });
    await expectCardInPageRegistry(page, held);
  });

  test('renders from a shell an older version cached', async ({ page }) => {
    test.setTimeout(120_000);
    const held = await forceTheRace(page);

    // Captured in the handler and asserted after navigating: throwing inside a route
    // handler leaves the request unfulfilled and surfaces as an opaque goto timeout.
    let injected = false;
    await page.route(
      (url) => url.pathname === DASHBOARD,
      async (route) => {
        if (route.request().resourceType() !== 'document') return route.continue();
        const response = await route.fetch();
        const shell = await response.text();
        injected = shell.includes(BOOT_SCRIPT_END);
        const headers = { ...response.headers() };
        // The body we hand back is decoded text; reusing the original encoding and
        // length headers would leave the browser unable to parse it.
        delete headers['content-encoding'];
        delete headers['content-length'];
        await route.fulfill({
          status: response.status(),
          headers,
          contentType: 'text/html',
          body: shell.replace(BOOT_SCRIPT_END, BOOT_SCRIPT_END + STALE_IMPORT),
        });
      },
    );

    await page.goto(DASHBOARD, { waitUntil: 'domcontentloaded' });
    expect(
      injected,
      'the shell no longer has the boot script this test puts the stale import after',
    ).toBe(true);
    await expectCardInPageRegistry(page, held);
  });
});
