import { test, expect } from '@playwright/test';
import {
  callService,
  createTask,
  deleteTask,
  familyChoresCard,
  listTasks,
  openDashboard,
  openPanel,
} from './helpers';

/**
 * Task mirrors, from the household's side.
 *
 * The integration suite proves the loop over the service API. What only a browser
 * shows is the payoff: the chore appearing as an ordinary line on the family's own
 * to-do list card — with the due date that makes it actionable — and a tick on that
 * card's checkbox landing back in Home Keeper's completion history. A captured
 * surface with nothing asserting on it is how #221 hid in plain sight for months,
 * so this spec reads the card's *contents*, not its count.
 *
 * A mirror is a **profile**: the sync lives in the profile's own `sync` block, so
 * configuring one here means saving `profiles`, and the panel half of this spec
 * checks the profile editor's **Sync to a to-do list** group rather than a card of
 * its own.
 *
 * `todo.family_chores` is a seeded `local_todo` list (see
 * `tests/integration/ha_config/.storage/core.config_entries`) standing in for the
 * Todoist project or kitchen-tablet list a real household already checks. It reports
 * its completed items rather than dropping them, so the profile below syncs with
 * `vanish_as_completed` off — what the README tells a `local_todo` user to do, and
 * what keeps a swept line from reading as somebody ticking a chore off.
 */

const FAMILY_LIST = 'todo.family_chores';
const CHORE = 'E2E mirror chore';
const PROFILE_ID = 'e2e_mirror_profile';
const PROFILE_NAME = 'Household chores';

/** The items on the household list, optionally filtered by status. */
async function familyItems(status?: string[]): Promise<any[]> {
  const data: Record<string, unknown> = { entity_id: FAMILY_LIST };
  if (status) data.status = status;
  const resp = await callService('todo', 'get_items', data, true);
  return resp[FAMILY_LIST]?.items ?? [];
}

async function familySummaries(status?: string[]): Promise<string[]> {
  return (await familyItems(status)).map((i) => i.summary);
}

/** Retry a Home Keeper service call through the entry-reload window a save opens. */
async function callWhenReady(service: string, data: Record<string, unknown>): Promise<void> {
  await expect
    .poll(
      async () => {
        try {
          await callService('home_keeper', service, data);
          return true;
        } catch {
          return false;
        }
      },
      { timeout: 40_000 },
    )
    .toBe(true);
}

/**
 * Point one profile's sync at the household list — the save the panel's Settings tab
 * makes when you pick a list in a profile's **Sync to a to-do list** group.
 *
 * The filter is *overdue*, which is also the mirror's timing: a task goes on the list
 * the moment it falls due. Saving `[]` drops the profile again, which is what clears
 * the lines it wrote (the planner reads a tracked entry whose profile is gone exactly
 * as it reads a cleared picker). Profiles are saved as a whole list and nothing else
 * in this suite depends on the container's seeded ones, so replacing them is safe —
 * `problem-sensor.spec.ts` does the same.
 */
async function setSync(on: boolean): Promise<void> {
  await callWhenReady('set_options', {
    profiles: on
      ? [
          {
            id: PROFILE_ID,
            name: PROFILE_NAME,
            filter: { status: 'overdue', labels: [], areas: [], devices: [] },
            sync: { entity_id: FAMILY_LIST, two_way: true, vanish_as_completed: false },
          },
        ]
      : [],
  });
}

test.describe('Home Keeper — tasks mirrored onto a household to-do list', () => {
  let taskId: string | undefined;

  test.beforeEach(async () => {
    await setSync(true);
  });

  test.afterEach(async () => {
    // The container's store and the seeded list are shared state, so this spec has
    // to leave nothing behind — the profile, the task, and both the open and
    // ticked-off lines. Dropping the profile is what clears the open ones, so it
    // goes first, and the sweep waits for that pass to land: removing a line the
    // mirror still believes it owns is exactly the "the household deleted it" input
    // it is built to react to. The sweep takes the whole list because an overdue
    // profile puts every seeded overdue chore on it too, and nothing else here
    // writes to that list.
    await setSync(false);
    await expect
      .poll(async () => (await familySummaries(['needs_action'])).length, { timeout: 30_000 })
      .toBe(0);
    await deleteTask(taskId);
    taskId = undefined;
    const leftovers = (await familyItems()).map((i) => i.uid);
    if (leftovers.length) {
      await callService('todo', 'remove_item', { entity_id: FAMILY_LIST, item: leftovers });
    }
  });

  test('an overdue chore lands on the household list, carrying its due date', async ({
    page,
  }) => {
    // Before: the family's list has no line for this chore.
    expect(await familySummaries()).not.toContain(CHORE);

    // A floating task with no "last done" is due immediately, so an overdue profile
    // wants it the moment it exists.
    taskId = await createTask({
      name: CHORE,
      recurrence_type: 'floating',
      interval: 1,
      unit: 'days',
    });

    await expect
      .poll(async () => await familySummaries(['needs_action']), { timeout: 40_000 })
      .toContain(CHORE);

    // The payoff, in the browser: the chore is a line on the family's own card.
    await openDashboard(page);
    const card = familyChoresCard(page);
    await expect(card).toBeVisible({ timeout: 30_000 });
    await expect(card).toContainText(CHORE);

    // And it is not just a summary — the line carries the task's due date, which is
    // what makes it actionable on somebody's phone. `next_due` is stored in Home
    // Assistant's own timezone, so its leading `YYYY-MM-DD` is the day a to-do list
    // works in (and dropping the time is what stops the line drifting a day either
    // way for whoever reads it).
    const task = (await listTasks()).find((t) => t.id === taskId);
    const item = (await familyItems(['needs_action'])).find((i) => i.summary === CHORE);
    expect(item.due, 'the mirrored line should carry a due date').toBeTruthy();
    expect(item.due).toBe(String(task!.next_due).slice(0, 10));
  });

  test("the profile's Sync group names the list it keeps in step", async ({ page }) => {
    // The surface `docs/images/47-panel-profile-sync.png` documents. A capture is not
    // coverage: without this, the group could render with an empty picker and the
    // only thing that would notice is a reader of the README.
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-settings').click();
    const profiles = panel.locator('#hk-profiles');
    await expect(profiles).toBeVisible();

    const row = profiles.locator('.hk-item-card').filter({ hasText: PROFILE_NAME }).first();
    const header = row.locator('> .hk-item-header');
    await expect(header.locator('.hk-item-name')).toHaveText(PROFILE_NAME);
    // The collapsed row already says where it syncs — that chip is the whole point of
    // folding the sync into the profile instead of listing it somewhere else.
    await expect(header.locator('.hk-sync-chip')).toHaveText('Family chores');

    // Opening the row reveals the filter form and, below it, the collapsible Sync
    // group. A configured list makes the group start open, so the list is one click
    // from the Settings tab rather than two.
    //
    // Re-opened on every attempt rather than opened once: Home Assistant's frontend
    // replaces the custom-panel element a few seconds after a page settles, and a
    // fresh panel starts with every profile row folded again. Asserting against a
    // single click is a race this spec would lose intermittently.
    const group = row.locator('.hk-sync-group');
    const openRow = async (): Promise<void> => {
      if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
    };
    const openThen = async (probe: () => Promise<boolean>): Promise<boolean> => {
      try {
        await openRow();
        return await probe();
      } catch {
        return false; // the panel was swapped mid-check; the next poll re-resolves
      }
    };

    await expect
      .poll(() => openThen(() => group.locator('.hk-item-body ha-form').isVisible()), {
        timeout: 30_000,
      })
      .toBe(true);
    await expect(group.locator('.hk-item-name')).toHaveText('Sync to a to-do list');
    await expect(group.locator('.hk-item-header')).toHaveAttribute('aria-expanded', 'true');

    // …and the picker inside it is holding the list, not sitting empty. HA's
    // `ha-entity-picker` renders the chosen list inside its own shadow root and keeps
    // no <input> carrying the value, so the list's name is read through Playwright's
    // shadow-piercing text engine rather than off a form field.
    await expect
      .poll(() => openThen(() => group.getByText('Family chores').isVisible()), {
        timeout: 30_000,
      })
      .toBe(true);
  });

  test('ticking the line off on the card completes the task in Home Keeper', async ({
    page,
  }) => {
    taskId = await createTask({
      name: CHORE,
      recurrence_type: 'floating',
      interval: 1,
      unit: 'days',
    });
    await expect
      .poll(async () => await familySummaries(['needs_action']), { timeout: 40_000 })
      .toContain(CHORE);

    // Tick it off in the browser, the way the household would — the card's own
    // checkbox, not a service call.
    await openDashboard(page);
    const card = familyChoresCard(page);
    await expect(card).toBeVisible({ timeout: 30_000 });
    const row = card
      .locator('ha-check-list-item, ha-md-list-item')
      .filter({ hasText: CHORE })
      .first();
    await row.locator('ha-checkbox, input[type="checkbox"]').first().click();

    // Home Keeper records it as a completion like any other Done.
    await expect
      .poll(
        async () => (await listTasks()).find((t) => t.id === taskId)?.completions?.length,
        { timeout: 60_000 },
      )
      .toBe(1);

    // The line they ticked is theirs — it stays on the list as their record rather
    // than vanishing out from under them.
    expect(await familySummaries(['completed'])).toContain(CHORE);

    // …and the panel agrees: the task's detail page lists the completion.
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator(`.detail-open[data-detail-id="${taskId}"]`).click();
    await expect(panel.locator('.hk-hist-list li')).toHaveCount(1);
  });
});
