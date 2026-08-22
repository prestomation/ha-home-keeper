import { test, expect } from '@playwright/test';
import { DASHBOARD } from './helpers';

/**
 * Regression test for #228 — "Custom element doesn't exist: home-keeper-card".
 *
 * `frontend.add_extra_js_url` reaches a browser exactly one way: Home Assistant's
 * `IndexView` renders an inline `import("<url>")` for every extra module into the
 * app-shell HTML. That response carries no `Cache-Control` and no ETag, and HA's own
 * service worker serves navigations `StaleWhileRevalidate` from a 24h `file-cache` —
 * so a shell cached before Home Keeper was installed has no such import, and the card
 * element is never defined. The error sticks rather than flickering because HA already
 * recovers from a *late* definition (`customElements.whenDefined(tag)` -> `ll-rebuild`),
 * so a permanent error card proves the module never executed at all.
 *
 * Playwright cannot conjure a day-old cache entry, so this reproduces what that entry
 * *is*: the same shell with the card's import removed. The card must still render —
 * from the Lovelace resource list, which the frontend fetches over the websocket on
 * every dashboard load. That is the path every HACS card uses, which is why the
 * reporter's other cards worked on the very shell that broke ours.
 */

// Without this the test is a coin flip. HA registers its service worker on the first
// load, and a service worker answers navigations *before* `page.route` sees them — so
// the reload that follows would be served the original, unstripped shell and the card
// would load for the wrong reason. Blocking it is not dodging the bug: the service
// worker's caching is what we are simulating, not what we are exercising.
test.use({ serviceWorkers: 'block' });

const CARD_BUNDLE = 'home-keeper-card.js';
// `index.html.template` renders each entry in `extra_modules` as an inline
// `import("/home_keeper_panel/home-keeper-card.js?v=<hash>");`.
const CARD_IMPORT = /import\(\s*(["'])[^"']*home-keeper-card\.js[^"']*\1\s*\)\s*;?/g;

test.describe('Home Keeper card — delivery (#228)', () => {
  test('renders from an app shell that never imported its bundle', async ({ page }) => {
    // Captured in the handler and asserted after navigating: throwing inside a route
    // handler leaves the request unfulfilled and surfaces as an opaque goto timeout.
    let original: string | null = null;
    let stripped: string | null = null;

    await page.route(
      (url) => url.pathname === DASHBOARD,
      async (route) => {
        if (route.request().resourceType() !== 'document') return route.continue();
        const response = await route.fetch();
        original = await response.text();
        stripped = original.replace(CARD_IMPORT, '');
        const headers = { ...response.headers() };
        // The body we hand back is decoded text; reusing the original encoding and
        // length headers would leave the browser unable to parse it.
        delete headers['content-encoding'];
        delete headers['content-length'];
        await route.fulfill({
          status: response.status(),
          headers,
          contentType: 'text/html',
          body: stripped,
        });
      },
    );

    await page.goto(DASHBOARD, { waitUntil: 'domcontentloaded' });

    // Guard the guard. If HA ever stops rendering extra modules as an inline import,
    // this test would quietly start passing without simulating anything at all.
    expect(original, 'the dashboard navigation was never intercepted').not.toBeNull();
    expect(
      original!,
      'the app shell no longer carries the card import — re-derive what this simulates',
    ).toContain(CARD_BUNDLE);
    expect(stripped!, 'the strip left a reference behind').not.toContain(CARD_BUNDLE);

    // Deliberately not `helpers.openCardDashboard`: its 3x reload retry exists to
    // absorb exactly this class of failure and would mask the regression.
    const card = page.locator('home-keeper-card').first();
    await card.waitFor({ state: 'attached', timeout: 30_000 });
    await expect(card.locator('.hk-row, .hk-empty').first()).toBeVisible({ timeout: 30_000 });
    await expect(card.locator('.hk-title').first()).toContainText('Home maintenance');

    // What the reporter saw: HA substitutes an error card for an undefined custom
    // element, one per card instance. The seeded dashboard's other cards are native,
    // so a single one of these is the bug.
    await expect(page.locator('hui-error-card')).toHaveCount(0);
  });
});
