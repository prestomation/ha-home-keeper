import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';

/**
 * Moving between Settings sections patches the page; it does not rebuild it.
 *
 * The rail asks for a smooth scroll to the section it names. While a rail click went
 * through `_render`, that scroll started from the wrong place: the swap leaves the
 * page a fraction of its height for a frame (every `ha-form` on it re-renders after),
 * the browser clamps the scroll to the shorter page, and the smooth scroll then
 * crawls back down from the top — read as a jump to the top followed by a slow ride
 * to the destination.
 *
 * A jsdom test cannot see a scroll (nothing here has a height), so what is pinned is
 * the mechanism underneath it: the section change leaves the rendered page standing.
 * Node identity is the assertion — a full render replaces `shadowRoot.innerHTML`, so
 * every node held from before it would be detached.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

/** Stand in for HA's router, which answers `location-changed` with a new `route`. */
function routeTo(panel, path) {
  panel.route = { prefix: '/home-keeper', path };
}

/** Boot a panel straight onto the Settings page. Not `mountPanel`, which waits for
 *  the list view's Add button — Settings has no list and no Add. */
async function mountSettings() {
  const panel = document.createElement('home-keeper-panel');
  routeTo(panel, '/settings');
  document.body.appendChild(panel);
  panel.hass = makeHass();
  const layout = await waitFor(() => panel.shadowRoot?.querySelector('.hk-settings-layout'));
  expect(layout, 'settings layout should render').toBeTruthy();
  return { panel, layout };
}

describe('Settings — moving between sections', () => {
  it('keeps the rendered page and re-marks it in place', async () => {
    const { panel, layout } = await mountSettings();
    const root = panel.shadowRoot;
    const general = root.querySelector('#hk-settings-general');
    const companions = root.querySelector('#hk-companions');
    expect(general, 'the General card should render').toBeTruthy();
    expect(companions, 'the Companions card should render').toBeTruthy();

    root.querySelector('.hk-rail-link[data-section="companions"]').click();
    routeTo(panel, '/settings/companions');

    // The same page, not a new one: the layout and both cards held from before the
    // navigation are still the ones on screen.
    expect(root.querySelector('.hk-settings-layout')).toBe(layout);
    expect(root.querySelector('#hk-settings-general')).toBe(general);
    expect(root.querySelector('#hk-companions')).toBe(companions);

    // …and it says which section is open, in all three places that decide what shows.
    expect(layout.dataset.section).toBe('companions');
    expect(companions.classList.contains('hk-sec-current')).toBe(true);
    expect(general.classList.contains('hk-sec-current')).toBe(false);
    expect(
      root.querySelector('.hk-rail-link[data-section="companions"]').getAttribute('aria-current'),
    ).toBe('page');
    expect(
      root.querySelector('.hk-rail-link[data-section="general"]').hasAttribute('aria-current'),
    ).toBe(false);
  });

  it('moves the mark again on a second section, and clears it on the index', async () => {
    const { panel, layout } = await mountSettings();
    const root = panel.shadowRoot;

    routeTo(panel, '/settings/profiles');
    expect(layout.dataset.section).toBe('profiles');
    routeTo(panel, '/settings/notifications');
    expect(layout.dataset.section).toBe('notifications');
    expect(root.querySelector('#hk-profiles').classList.contains('hk-sec-current')).toBe(false);
    expect(root.querySelector('#hk-notifications').classList.contains('hk-sec-current')).toBe(true);

    // Back out to the whole page: no section is named, so nothing is marked and the
    // narrow rules have nothing to hide behind.
    routeTo(panel, '/settings');
    expect(root.querySelector('.hk-settings-layout')).toBe(layout);
    expect(layout.dataset.section).toBeUndefined();
    expect(root.querySelectorAll('.hk-settings-col ha-card.hk-sec-current')).toHaveLength(0);
    expect(root.querySelectorAll('.hk-rail-link[aria-current]')).toHaveLength(0);
  });

  it('carries the back bar with the section it belongs to, still wired', async () => {
    // The narrow layout's back bar names the open section, so it is rebuilt on every
    // move — and its button is a new element each time, which is the part a patch can
    // silently leave dead.
    const { panel } = await mountSettings();
    const root = panel.shadowRoot;
    expect(root.querySelector('.hk-settings-backbar')).toBeNull();

    routeTo(panel, '/settings/profiles');
    const bar = root.querySelector('.hk-settings-backbar');
    expect(bar, 'an open section should carry a back bar').toBeTruthy();
    expect(bar.textContent).toContain('Profiles');
    // One bar, not one per section visited.
    routeTo(panel, '/settings/companions');
    expect(root.querySelectorAll('.hk-settings-backbar')).toHaveLength(1);
    expect(root.querySelector('.hk-settings-backbar').textContent).toContain('Companions');

    root.getElementById('settings-back').click();
    expect(location.pathname).toBe('/home-keeper/settings');
    routeTo(panel, '/settings');
    expect(root.querySelector('.hk-settings-backbar')).toBeNull();
  });

  it('still renders from scratch when the destination is another view', async () => {
    // The patch is for a lateral move along the Settings page. Anything else is a
    // different page and has to be built, or the panel would show Settings forever.
    const { panel, layout } = await mountSettings();
    const root = panel.shadowRoot;

    routeTo(panel, '/settings/companions');
    routeTo(panel, '/tasks');

    expect(root.querySelector('.hk-settings-layout')).toBeNull();
    expect(layout.isConnected).toBe(false);
    expect(await waitFor(() => root.querySelector('#add-btn'))).toBeTruthy();
  });
});
