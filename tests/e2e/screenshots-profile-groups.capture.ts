/**
 * One-off screenshot capture for a Profile's **filter groups** — not part of the e2e
 * suite (the filename is not *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     --config=screenshots-profile-groups.config.ts
 *
 * A profile selects a task that matches *any one* of its groups, and inside a group
 * every filter that has a value must match. That rule is invisible on a profile with
 * one group: no OR divider, no per-group heading, no Delete beside a group. So the
 * shot needs a profile with two, and both of them holding real values — the README
 * section this illustrates is exactly the two-group example.
 *
 * The profile is seeded over the public `set_options` service rather than built on
 * camera, for the same reason the companion-filter capture does it: driving Home
 * Assistant's label and area pickers is fragile capture plumbing, and the shot is
 * about the layout the groups render in, not about the pickers' own behaviour.
 *
 * Desktop *and* phone, in one run. Below 700px the panel answers a settings URL with
 * the section as a page of its own, so a desktop-only shot documents none of what a
 * phone user sees of a control this tall.
 */
import { expect, test, type Locator, type Page } from '@playwright/test';
import { callService, openPanel } from './tests/helpers';
import { PHONE } from './viewports';

const OUT = process.env.SHOT_DIR || '/tmp/hk-shots';

const PROFILE_ID = 'shot-groups';
const PROFILE_NAME = 'Household jobs or the dog';
/** What each group calls itself. A folded group is read from its name, so the seed
 *  names both rather than leaving the editor's "Group 1" / "Group 2" fallback in a shot
 *  whose subject is the named row. */
const GROUP_ONE_NAME = 'Home jobs';
const GROUP_TWO_NAME = 'Dog in the living room';

/** The container's own profile list, put back when the capture is done. */
let savedProfiles: unknown[] = [];

test.beforeAll(async () => {
  // The container's store and options are the committed seed fixture, so remember what
  // the profile list held and put it back afterwards.
  savedProfiles = (await callService('home_keeper', 'list_profiles', {}, true)).profiles ?? [];
});

test.afterAll(async () => {
  await callService('home_keeper', 'set_options', { profiles: savedProfiles });
});

/** The seeded profile's row, opened, with its first group expanded. Guarded rather than
 *  a bare click: Home Assistant replaces the custom-panel element a few seconds after a
 *  page settles, and a fresh panel starts with every row folded.
 *
 *  A group is a `details` row now, and a profile with two of them starts with *both*
 *  folded — so the shot has to open one. One expanded group beside one folded one is
 *  the state worth documenting: the open row shows the form the filters are set in, and
 *  the folded row shows what the accordion reduces a group to, its name and its summary
 *  line. Two open rows would show neither. */
async function openRow(panel: Locator): Promise<Locator> {
  const card = panel.locator('#hk-profiles');
  await expect(card).toBeVisible({ timeout: 30_000 });
  const row = card.locator('.hk-item-card').filter({ hasText: PROFILE_NAME }).first();
  const header = row.locator('> .hk-item-header');
  if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
  // Both groups, the operator between them, and the button that adds a third. Waited
  // for rather than assumed: the group forms render after the row opens, and a
  // shutter that fires first photographs a half-built editor.
  await expect(row.locator('.hk-filter-group')).toHaveCount(2);
  await expect(row.locator('.hk-filter-or')).toHaveCount(1);
  await expect(row.locator('.hk-filter-group-add')).toBeVisible();
  // The names carry the feature on a folded row, so they are waited for before the
  // shutter rather than left to arrive with the next paint.
  await expect(row.locator('.hk-filter-group[data-group="0"] .hk-filter-group-name')).toHaveText(
    GROUP_ONE_NAME,
  );
  await expect(row.locator('.hk-filter-group[data-group="1"] .hk-filter-group-name')).toHaveText(
    GROUP_TWO_NAME,
  );
  const first = row.locator('.hk-filter-group[data-group="0"]');
  if ((await first.getAttribute('open')) === null) await first.locator('> summary').click();
  // The open row's form, not just the open attribute: `details` shows its body one
  // frame after the toggle, and a shutter between the two catches a row mid-open.
  await expect(row.locator('.hk-filter-group[open] ha-form')).toBeVisible();
  // …and the *other* row still folded, which is the half of the shot the accordion is
  // for. Both open would be the layout this change replaced.
  await expect(row.locator('.hk-filter-group[open]')).toHaveCount(1);
  return row;
}

/** Navigate to Settings → Profiles and open the seeded row. */
async function openProfiles(page: Page): Promise<{ panel: Locator; row: Locator }> {
  await page.goto('/home-keeper/settings/profiles', { waitUntil: 'domcontentloaded' });
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel).toBeVisible({ timeout: 45_000 });
  const row = await openRow(panel);
  return { panel, row };
}

test('capture a profile with two filter groups', async ({ page }) => {
  await openPanel(page);

  // Seeded from inside the page so the areas are resolved out of the *live* registry
  // rather than hard-coded: Home Assistant's onboarding creates them, and a filter
  // naming an area that does not exist draws the picker's "unknown area" error and
  // documents the editor as misconfigured.
  //
  // Only this profile is written, not the container's list plus this one: a second
  // row above it would push the groups down the shot without adding anything the
  // README section is about. `afterAll` puts the real list back.
  await page.evaluate(
    async ({ id, name, groupOne, groupTwo }) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const hass = (document.querySelector('home-assistant') as any)?.hass;
      if (!hass) return;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const areas: any[] = await hass.callWS({ type: 'config/area_registry/list' });
      const pick = (areaId: string, fallback: number): string | undefined =>
        (areas.find((a) => a.area_id === areaId) ?? areas[fallback])?.area_id;
      const kitchen = pick('kitchen', 1);
      const livingRoom = pick('living_room', 0);
      await hass.callService('home_keeper', 'set_options', {
        profiles: [
          {
            id,
            name,
            filter: {
              status: 'all',
              groups: [
                // "The household's own jobs, but not the ones in the kitchen" — an
                // include and an exclude in one group, which is the AND half of the
                // rule. The name is what its row is headed with, open or folded.
                {
                  name: groupOne,
                  labels: ['home'],
                  labels_match: 'any',
                  exclude_areas: kitchen ? [kitchen] : [],
                },
                // "…or anything for the dog in the living room" — a second group,
                // OR-ed with the first, which is what the divider between them says.
                // This is the one left folded in the shot, so its name and its summary
                // line are the whole of what the reader gets: a named group has to be
                // legible without being opened.
                {
                  name: groupTwo,
                  labels: ['dog'],
                  labels_match: 'any',
                  areas: livingRoom ? [livingRoom] : [],
                },
              ],
            },
          },
        ],
      });
    },
    {
      id: PROFILE_ID,
      name: PROFILE_NAME,
      groupOne: GROUP_ONE_NAME,
      groupTwo: GROUP_TWO_NAME,
    },
  );

  // Saving options reloads the config entry, which re-registers the sidebar panel —
  // so land on the panel again before asking for a route inside it.
  await openPanel(page);
  const { panel, row } = await openProfiles(page);
  await page.waitForTimeout(1200);
  // Re-guarded after the settle, not just before it: the panel element Home Assistant
  // swaps in during that wait folds the row *and* every group in it.
  await openRow(panel);

  // The profile's row, not the whole Settings page: the groups are *inside* one
  // profile, and a full-page shot of this route renders the fields too small to read
  // while dragging Home Assistant's position:fixed sidebar into the middle of it.
  await row.scrollIntoViewIfNeeded();
  await row.screenshot({ path: `${OUT}/profile-filter-groups.png` });

  // The phone layout. Below 700px the same route is a page of its own with a back
  // bar, and every field in a group takes the full width — which is the width at
  // which a two-group editor is longest, and the one a review cannot see from the
  // desktop shot.
  //
  // Phone *width*, but not the phone height: the layout is chosen by the width
  // alone, while an element screenshot taller than the viewport paints Home
  // Assistant's position:fixed chrome wherever the viewport put it. At 844px the
  // bottom tab bar landed straight across the middle of this row, over the first
  // group's exclude fields. A viewport taller than the row leaves the bar below it.
  await page.setViewportSize({ width: PHONE.width, height: 3200 });
  const { panel: phonePanel, row: phoneRow } = await openProfiles(page);
  await page.waitForTimeout(1200);
  await openRow(phonePanel);
  await phoneRow.scrollIntoViewIfNeeded();
  await phoneRow.screenshot({ path: `${OUT}/profile-mobile-filter-groups.png` });
});
