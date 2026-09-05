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
//
// The second option is what makes the interception survivable. Chrome classifies a
// response synthesized by `route.fulfill` as coming from a *public* address space, so
// its Local Network Access checks then block this page's own
// `ws://localhost:8123/api/websocket` as a local-network request
// (`net::ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS`). With no websocket the frontend
// never fetches the resource list, so the card cannot load by the very path this test
// exists to prove — a false failure that looks exactly like a real one. It is scoped to
// this spec rather than the whole project: every other spec leaves the document alone
// and keeps the check, so a future test of network or CORS behaviour still gets it.
// (Re-plumbing `CHROMIUM_EXEC` here is the cost — `launchOptions` replaces the config's
// copy wholesale rather than merging with it.)
test.use({
  serviceWorkers: 'block',
  launchOptions: {
    args: ['--disable-features=LocalNetworkAccessChecks'],
    ...(process.env.CHROMIUM_EXEC ? { executablePath: process.env.CHROMIUM_EXEC } : {}),
  },
});

const CARD_BUNDLE = 'home-keeper-card.js';
// `index.html.template` renders each entry in `extra_modules` as an inline import.
// Home Assistant 2026.9 wrapped that import in a rejection handler:
//
//   import("{{ extra_module }}").catch(function (err) {
//     console.error("Failed to load extra module {{ extra_module }}", err);
//   });
//
// The handler repeats the URL in its message, so stripping the `import(...)` call
// alone leaves the bundle named in the shell and the strip's own guard below fails.
// The optional group therefore takes the chained `.catch(...)` with it. It stays
// optional so the bare `import("<url>");` older releases render is still stripped.
const CARD_IMPORT =
  /import\(\s*(["'])[^"']*home-keeper-card\.js[^"']*\1\s*\)(?:\s*\.catch\(\s*function\s*\([^)]*\)\s*\{[^{}]*\}\s*\))?\s*;?/g;

test.describe('Home Keeper card — delivery (#228)', () => {
  test('renders from an app shell that never imported its bundle', async ({ page }) => {
    // The card can only load once the websocket is up and the resource list has been
    // fetched, which is later than the shell import the other card specs rely on.
    test.setTimeout(120_000);

    // Diagnosing this test from a CI log is otherwise guesswork: the first version
    // failed on CI and passed locally, and the cause (the websocket never connecting)
    // was invisible until the console was captured.
    const problems: string[] = [];
    const bundleTraffic: string[] = [];
    page.on('console', (m) => {
      if (m.type() === 'error') problems.push(`console: ${m.text().slice(0, 300)}`);
    });
    page.on('pageerror', (e) => problems.push(`pageerror: ${String(e).slice(0, 300)}`));
    page.on('request', (r) => {
      if (r.url().includes(CARD_BUNDLE)) bundleTraffic.push(`request ${r.url()}`);
    });
    page.on('response', (r) => {
      if (r.url().includes(CARD_BUNDLE)) bundleTraffic.push(`response ${r.status()}`);
    });
    page.on('requestfailed', (r) => {
      if (r.url().includes(CARD_BUNDLE))
        problems.push(`bundle request failed: ${r.failure()?.errorText}`);
    });

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
    try {
      await card.waitFor({ state: 'attached', timeout: 60_000 });
    } catch (err) {
      throw new Error(
        'the card never loaded from the Lovelace resource after its app-shell import ' +
          `was removed — issue #228.\nbundle traffic: ${
            bundleTraffic.length ? bundleTraffic.join(', ') : '(the bundle was never requested)'
          }\nbrowser problems:\n${problems.join('\n') || '(none)'}`,
        { cause: err },
      );
    }
    await expect(card.locator('.hk-row, .hk-empty').first()).toBeVisible({ timeout: 30_000 });
    await expect(card.locator('.hk-title').first()).toContainText('Home maintenance');

    // The element being defined is not on its own proof the *resource* delivered it —
    // some future shell-side fallback could define it without a fetch. The bundle
    // crossing the wire after the shell's import was removed is what pins the path.
    expect(
      bundleTraffic.filter((t) => t.startsWith('response')),
      `the card upgraded without the bundle being fetched: ${bundleTraffic.join(', ')}`,
    ).not.toHaveLength(0);

    // What the reporter saw: HA substitutes an error card for an undefined custom
    // element, one per card instance. The seeded dashboard's other cards are native,
    // so a single one of these is the bug.
    await expect(page.locator('hui-error-card')).toHaveCount(0);
  });
});
