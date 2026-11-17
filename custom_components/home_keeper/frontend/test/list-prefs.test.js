import fc from 'fast-check';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';
import { switchView } from '../src/panel-settings.ts';
import { TASK_FILTERS } from '../src/panel-types.ts';
import { PARTS_FILTERS, PARTS_GROUPS, PARTS_SORTS } from '../src/parts-overview.ts';

/**
 * The list choices of this browser come back after a reload and after a tab change:
 * the filter, the group, the Profile, the appliance filter and view, the Parts filter,
 * group and sort, and the fold of the filter controls.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
  localStorage.clear();
});

const PROFILES = [
  {
    id: 'p1',
    name: 'Kitchen',
    filter: { status: 'all', labels: [], areas: [], devices: [], exclude_labels: [], exclude_areas: [], exclude_devices: [] },
  },
];

function hass() {
  const h = makeHass();
  const base = h.callWS;
  h.callWS = (msg) =>
    msg.type === 'home_keeper/get_options'
      ? Promise.resolve({ options: { profiles: PROFILES } })
      : base(msg);
  return h;
}

async function mount(path = '/tasks') {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  panel.addEventListener('location-changed', () => {
    panel.route = { prefix: '/home-keeper', path: location.pathname.slice('/home-keeper'.length) };
  });
  document.body.appendChild(panel);
  panel.hass = hass();
  await waitFor(() => panel._loaded && panel._options);
  return panel;
}

/** The choices, read from the panel. */
const choices = (panel) => ({
  filter: panel._filter,
  groupBy: panel._groupBy,
  profile: panel._profile,
  assetFilter: panel._assetFilter,
  assetView: panel._assetView,
  partsFilter: panel._partsFilter,
  partsGroup: panel._partsGroup,
  partsSort: panel._partsSort,
  controlsOpen: panel._controlsOpen,
});

/** The choices of the task list as its controls show them. */
function shownChoices(panel) {
  const root = panel.shadowRoot;
  const pressed = root.querySelector('.hk-seg[data-seg="filter"] .hk-seg-btn[aria-pressed="true"]');
  const group = root.querySelector('select[data-seg-select="group"]');
  const profile = root.querySelector('select[data-profile-filter]');
  return {
    filter: pressed?.dataset.segVal ?? null,
    groupBy: group?.value ?? null,
    profile: profile?.value ?? null,
  };
}

/** What the controls must show for the choices *c*. A Profile hides the filter pills. */
const shownOf = (c) => ({ filter: c.profile ? null : c.filter, groupBy: c.groupBy, profile: c.profile });

const pick = fc.record({
  filter: fc.constantFrom(...TASK_FILTERS),
  groupBy: fc.constantFrom('none', 'status', 'area', 'device', 'integration'),
  profile: fc.constantFrom('', 'p1'),
  assetFilter: fc.constantFrom('active', 'archived'),
  assetView: fc.constantFrom('flat', 'tree'),
  partsFilter: fc.constantFrom(...PARTS_FILTERS),
  partsGroup: fc.constantFrom(...PARTS_GROUPS),
  partsSort: fc.constantFrom(...PARTS_SORTS),
  controlsOpen: fc.boolean(),
});

/** Make the choices through the panel's own setters, as the controls do. */
function choose(panel, c) {
  panel._setFilter(c.filter);
  panel._setGroupBy(c.groupBy);
  panel._setProfile(c.profile);
  panel._setAssetFilter(c.assetFilter);
  panel._setAssetView(c.assetView);
  panel._setPartsFilter(c.partsFilter);
  panel._setPartsGroup(c.partsGroup);
  panel._setPartsSort(c.partsSort);
  if (panel._controlsOpen !== c.controlsOpen) panel._toggleControls();
}

describe('list choices', () => {
  it('come back after a reload and after a tab change', async () => {
    await fc.assert(
      fc.asyncProperty(pick, async (c) => {
        document.body.innerHTML = '';
        localStorage.clear();
        const panel = await mount();
        choose(panel, c);
        expect(choices(panel)).toEqual(c);
        // A tab change and back.
        switchView(panel, 'appliances');
        switchView(panel, 'settings');
        switchView(panel, 'tasks');
        expect(choices(panel), 'after a tab change').toEqual(c);
        // Home Assistant shows another page and then this one again: the same element.
        panel.remove();
        document.body.appendChild(panel);
        expect(choices(panel), 'after another page').toEqual(c);
        expect(shownChoices(panel), 'on screen after another page').toEqual(shownOf(c));
        // A reload: a new panel in the same browser.
        panel.remove();
        const again = await mount();
        expect(choices(again), 'after a reload').toEqual(c);
        await waitFor(() => again.shadowRoot.querySelector('.hk-seg[data-seg="filter"], select[data-profile-filter]'));
        expect(shownChoices(again), 'on screen after a reload').toEqual(shownOf(c));
      }),
      { numRuns: Math.max(10, Math.floor(fc.readConfigureGlobal().numRuns / 10)) },
    );
  }, 120_000);
});

describe('list choices in a browser that does not keep them', () => {
  it('stay for the visit when the browser refuses each write', async () => {
    // Some private windows read storage but refuse every write.
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError');
    });
    await fc.assert(
      fc.asyncProperty(pick, async (c) => {
        document.body.innerHTML = '';
        const panel = await mount();
        choose(panel, c);
        expect(choices(panel)).toEqual(c);
        // Home Assistant shows another page and then this one again.
        panel.remove();
        document.body.appendChild(panel);
        expect(choices(panel), 'after another page').toEqual(c);
      }),
      { numRuns: Math.max(10, Math.floor(fc.readConfigureGlobal().numRuns / 10)) },
    );
  }, 120_000);
});
