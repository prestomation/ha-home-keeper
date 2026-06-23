/**
 * One-off screenshot capture for PR documentation — not part of the e2e suite
 * (filename does not match *.spec.ts). Run with:
 *   SHOT_DIR=../../docs/images npx playwright test screenshots.capture.ts \
 *     --config=screenshots.config.ts
 *
 * The panel is built from Home Assistant components, so forms are `ha-form`s:
 * text fields live inside `ha-selector-text` (fill the inner input) and dropdowns
 * are `ha-select` built on `ha-dropdown` (open, then click the role="menuitem").
 */
import { test, expect, Locator } from '@playwright/test';
import { openPanel, openDashboard } from './tests/helpers';

const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

/** Fill the input of the nth ha-form text selector within a scope. */
async function fillText(scope: Locator, nth: number, value: string): Promise<void> {
  await scope.locator('ha-selector-text').nth(nth).locator('input, textarea').fill(value);
}

/** Pick an option label from an HA ha-select (ha-dropdown) dropdown. */
async function chooseHaSelect(select: Locator, optionLabel: string | RegExp): Promise<void> {
  await select.click();
  await select.page().getByRole('menuitem', { name: optionLabel }).first().click();
}

test('capture Home Keeper panel + usage screenshots', async ({ page }) => {
  // 1. The admin sidebar panel — task list with floating + fixed + overdue tasks.
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.waitForTimeout(1200); // let the HA sidebar/layout settle (avoid ghosting)
  await page.screenshot({ path: `${OUT}/1-panel-task-list.png`, fullPage: true });

  // 1a2. Completion-details dialog — a task whose capture mode is "optional" or
  // "required" opens this dialog on Done so you can record a note, cost, who and a
  // photo. The seeded "Replace fridge filter" task is set to optional capture.
  await panel.locator('.done-btn[data-id="task_fridge_filter"]').click();
  // ha-dialog portals its surface, so wait on an inner field rather than the host.
  const noteField = panel
    .locator('ha-dialog[open] ha-selector-text textarea, ha-dialog[open] ha-selector-text input')
    .first();
  await noteField.waitFor({ state: 'visible', timeout: 15_000 });
  await noteField.fill('Replaced cartridge; rinsed housing');
  await panel.locator('ha-dialog[open] ha-selector-number input').first().fill('42.50');
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/11-panel-completion-dialog.png`, fullPage: true });
  // Dismiss via Escape (closes ha-dialog) so the capture records no extra completion.
  await page.keyboard.press('Escape');
  await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

  // 1b. Task detail page — click a task to see its full schedule, notes and the
  // completion history of every time it was done (now annotated with the per-
  // completion note and cost recorded at Done time).
  await panel.locator('.detail-open[data-detail-id="task_fridge_filter"]').click();
  await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/7-panel-task-detail.png`, fullPage: true });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1c. Managed-task detail page — a task owned by another integration
  // (Pawsistant). Shows the "Managed by Pawsistant" chip, the completion prompt,
  // and deletion guidance in place of a Delete button.
  await panel.locator('.detail-open[data-detail-id="task_buddy_medicine"]').click();
  await expect(panel.locator('ha-assist-chip.hk-managed').first()).toBeVisible();
  await expect(panel.locator('.hk-managed-prompt')).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/9-panel-managed-detail.png`, fullPage: true });

  // 1d. Edit form of a managed task — the integration-locked fields (name and
  // attach-to-device) are omitted; only the unlocked fields are editable.
  await panel.locator('.d-edit').click();
  await expect(panel.locator('#hk-task-form')).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/10-panel-managed-edit-locked.png`, fullPage: true });
  await panel.locator('#f-cancel').click();
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1e. Tasks grouped by managing integration — managed tasks bucket under their
  // integration; everything else falls under "Your tasks".
  await panel.locator('.hk-seg[data-seg="group"] .hk-seg-btn', { hasText: 'Integration' }).click();
  await expect(panel.locator('details.hk-group').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/11-panel-grouped-by-integration.png`, fullPage: true });
  // Reset grouping so later list shots are unaffected.
  await panel.locator('.hk-seg[data-seg="group"] .hk-seg-btn', { hasText: 'Status' }).click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1f. Orphan cleanup — when a managing integration is uninstalled, its tasks are
  // no longer protected: a warning banner offers a one-click "Remove orphaned tasks",
  // and each orphaned task shows the "Integration offline" chip.
  await expect(panel.locator('.hk-orphan-banner')).toBeVisible();
  await expect(panel.locator('ha-assist-chip.hk-orphaned').first()).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/12-panel-orphan-cleanup.png`, fullPage: true });

  // 1g. Orphaned task detail — the Delete button returns (protection lifts) with an
  // explanation that the owning integration is gone.
  await panel.locator('.detail-open[data-detail-id="task_rex_vet"]').click();
  await expect(panel.locator('ha-assist-chip.hk-orphaned').first()).toBeVisible();
  await expect(panel.locator('.d-del')).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/13-panel-orphan-detail.png`, fullPage: true });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1h. Condition-driven (triggered) battery task detail. An active one (battery
  // low) reads as due-now with the "Managed by Battery Notes" chip and shows the
  // full replacement cadence — every time the battery was changed.
  await panel.locator('.detail-open[data-detail-id="task_door_battery"]').click();
  await expect(panel.locator('ha-assist-chip.hk-managed').first()).toBeVisible();
  await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/14-panel-battery-detail.png`, fullPage: true });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 1h2. A synced "problem" binary-sensor task. Home Keeper mirrors every
  // device_class: problem sensor as a task that's armed while the problem is active
  // (created at runtime by the sync, so locate it by name rather than a fixed id).
  // It can't be completed here — the originating integration clears it — so the Done
  // action is shown *disabled*; clicking it pops up the reason. The completion prompt
  // also explains how it resolves.
  await panel.locator('.hk-card', { hasText: 'Sump pump problem' }).locator('.detail-open').first().click();
  await expect(panel.locator('.hk-managed-prompt')).toBeVisible();
  await expect(panel.locator('.d-done-blocked-wrap')).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/16-panel-problem-sensor-detail.png`, fullPage: true });
  // Tapping the disabled Done surfaces a toast explaining why it can't be completed
  // here (best-effort capture — the toast is transient).
  await panel.locator('.d-done-blocked-wrap').click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/16b-panel-problem-sensor-blocked-toast.png`, fullPage: true });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 18. The same blocked Done on a Tasks-*list* card row — greyed/disabled (not a
  // working complete action); clicking it pops the same reason as the detail page.
  const sumpCard = panel.locator('.hk-card', { hasText: 'Sump pump problem' });
  await expect(sumpCard.locator('.done-blocked-wrap ha-button[disabled]')).toHaveCount(1);
  await sumpCard.locator('.done-blocked-wrap').click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/18-panel-tasks-blocked-done.png`, fullPage: true });
  // (healthy batteries) — collapsed by default to stay out of the way, one click
  // to browse. Expand it for the shot.
  const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
  await monitored.locator('summary').click();
  await expect(monitored.locator('.hk-card').first()).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/15-panel-monitored-section.png`, fullPage: true });

  // 19. The Completed section — a one-off (do-once) task drops here once it's done,
  // leaving the active list but keeping its completion history. Collapsed by default
  // (like Monitored); expand it for the shot.
  const completed = panel.locator('details.hk-group[data-group-key="status:completed"]');
  await completed.locator('summary').click();
  await expect(completed.locator('.hk-card').first()).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/19-panel-completed-section.png`, fullPage: true });

  // 2. Create form — floating recurrence + device picker.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await fillText(panel.locator('#hk-task-form'), 0, 'Replace dishwasher filter');
  await page.screenshot({ path: `${OUT}/2-panel-create-floating.png`, fullPage: true });

  // 3. Create form switched to a fixed (anchored) schedule.
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /Fixed/);
  await expect(panel.locator('#hk-task-form ha-selector-datetime').first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/3-panel-create-fixed.png`, fullPage: true });

  // 20. Create form switched to a one-off (do-once) task — no cadence, just a single
  // Due date picker. Completing it later sends it to the Completed section.
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /One-off/);
  await expect(panel.locator('#hk-task-form ha-selector-datetime').first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/20-panel-create-one-off.png`, fullPage: true });

  // 30. Create form switched to a sensor-based task (usage / meter) — an entity
  // picker, a mode toggle, and a target replace the clock cadence. Home Keeper arms
  // the task once the bound meter advances by the target since the last completion.
  // Reopen the panel fresh first so no transient tooltip/toast from the blocked-done
  // steps above lingers over the form.
  await openPanel(page);
  await expect(panel.locator('#add-btn')).toBeVisible();
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-form')).toBeVisible();
  await fillText(panel.locator('#hk-task-form'), 0, 'Service generator (runtime hours)');
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').first(), /Sensor-based/);
  await expect(panel.locator('#hk-task-form ha-selector-entity').first()).toBeVisible();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/30-panel-create-sensor-task.png`, fullPage: true });

  // 31. The same form switched to threshold mode — a comparison + value, plus an
  // optional hold (seconds) to debounce. The task arms on the crossing. (The sensor
  // mode select is the 2nd ha-select in the form, after recurrence type.)
  await chooseHaSelect(panel.locator('#hk-task-form ha-select').nth(1), /Threshold/);
  await expect(panel.locator('#hk-task-form ha-selector-number').first()).toBeVisible();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/31-panel-create-sensor-threshold.png`, fullPage: true });

  // 5. Appliances tab — the asset list with the seeded virtual device.
  await panel.locator('#tab-appliances').click();
  await expect(panel.locator('.hk-name').first()).toBeVisible();
  await page.screenshot({ path: `${OUT}/5-panel-appliances-list.png`, fullPage: true });

  // 5b. Appliance detail page — its metadata, parts, related tasks and the
  // maintenance history (including the archived history of a task that was
  // deleted while still assigned to it).
  await panel.locator('.detail-open[data-detail-id="asset_water_heater"]').click();
  await expect(panel.locator('.hk-hist-group').first()).toBeVisible();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/8-panel-appliance-detail.png`, fullPage: true });
  await panel.locator('#back-btn').click();
  await expect(panel.locator('#add-btn')).toBeVisible();

  // 6. Appliance create form — virtual device, metadata, parts and relationships.
  await panel.locator('#add-btn').click();
  await expect(panel.locator('#hk-asset-form')).toBeVisible();
  const assetForm = panel.locator('#hk-asset-form');
  await fillText(assetForm, 0, 'Garage water heater'); // name
  await fillText(assetForm, 1, 'Rheem'); // manufacturer
  // Add a wear part to show the parts editor + replacement interval.
  await panel.locator('#a-add-part').click();
  const part = panel.locator('.hk-part').first();
  await fillText(part, 0, 'Anode rod'); // part name
  await fillText(part, 1, 'AR-1'); // part number
  await chooseHaSelect(part.locator('ha-select').first(), 'wear item');
  // Number selectors in part order: cost #0, stock #1, reorder-at #2, and (after
  // switching to wear) replace-interval #3. Fill spare-inventory + interval so the
  // shot shows stock tracking alongside the maintenance cadence.
  const partNums = panel.locator('.hk-part').first().locator('ha-selector-number');
  await partNums.nth(1).locator('input').fill('2'); // stock
  await partNums.nth(2).locator('input').fill('1'); // reorder at
  await partNums.nth(3).locator('input').fill('12'); // replace interval
  // The wear part now exposes a "Last replaced" date field so the maintenance
  // schedule can start from the real date rather than "now".
  await expect(panel.locator('.hk-part').first().locator('ha-selector-date')).toBeVisible();
  // Custom fields: quick-add a text and a (trackable) date metadata entry so the
  // shot shows the flexible metadata editor — label/type/value rows plus the
  // one-click seed buttons for the common fields.
  await assetForm.locator('ha-button', { hasText: 'Serial number' }).click();
  await assetForm.locator('ha-button', { hasText: 'Warranty expiry' }).click();
  await expect(assetForm.locator('.hk-meta-seeds')).toBeVisible();
  await page.screenshot({ path: `${OUT}/6-panel-appliance-create.png`, fullPage: true });

  // 17. The Settings tab — friendly forms mirroring the options flow: a
  // Problem sensor sync card (toggle + entity / device / area / label exclusions)
  // and a General card (one-off retention), each saved on change.
  await openPanel(page);
  await panel.locator('#tab-settings').click();
  await expect(panel.locator('#hk-settings')).toBeVisible();
  await expect(panel.locator('#hk-settings ha-form')).toBeVisible();
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/17-panel-settings.png`, fullPage: true });

  // 17a. Settings → Profiles + Notifications. A Profile is a standalone saved filter;
  // a Notification is a delivery binding that references one. Seed one of each via the
  // public set_options service so both editors render populated.
  await page.evaluate(async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    await hass.callService('home_keeper', 'set_options', {
      profiles: [
        {
          id: 'demo_me',
          name: 'My chores',
          filter: { status: 'overdue', labels: [], areas: [], devices: [] },
        },
        {
          id: 'demo_upstairs',
          name: 'Upstairs',
          filter: { status: 'due_soon', labels: [], areas: [], devices: [] },
        },
      ],
      notifications: [
        {
          id: 'demo_walk',
          name: 'Walk my chores',
          profile_id: 'demo_me',
          targets: [],
          actions: ['complete', 'snooze', 'open'],
          snooze_hours: 24,
          style: 'walk',
          auto: { overdue: true, due_soon: false },
        },
      ],
    });
  });
  await openPanel(page);
  await panel.locator('#tab-settings').click();
  // Settings → Profiles — the standalone saved-filter editor.
  await expect(panel.locator('#hk-profiles')).toBeVisible();
  await expect(panel.locator('#hk-profiles .hk-notify-profile ha-form').first()).toBeVisible();
  await page.waitForTimeout(700);
  await panel.locator('#hk-profiles').screenshot({ path: `${OUT}/profiles-card.png` });
  // Settings → Notifications — delivery bindings that each reference a Profile.
  await expect(panel.locator('#hk-notifications')).toBeVisible();
  await expect(panel.locator('#hk-notifications .hk-notify-profile ha-form').first()).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT}/22-panel-notifications.png`, fullPage: true });

  // 17a2. The Tasks tab Profile dropdown — pick a saved Profile to filter the admin list.
  await openPanel(page);
  await expect(panel.locator('select[data-profile-filter]')).toBeVisible();
  await panel.locator('select[data-profile-filter]').selectOption('demo_me');
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/23-panel-profile-filter.png`, fullPage: true });

  // 17b. Settings → Companions — integrations that work with Home Keeper. The e2e
  // container ships only Home Keeper, so seed a couple of connected companions via
  // the public register_companion service to capture the section populated. The
  // in-memory companion registry lives in `hass.data` and is rebuilt on a config-entry
  // reload, so register *after* the panel (and thus the entry) is settled, and retry a
  // couple of times in case an options reload from 17a is still landing.
  const seedCompanions = async (): Promise<void> => {
    await page.evaluate(async () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const hass = (document.querySelector('home-assistant') as any)?.hass;
      if (!hass) return;
      await hass.callService('home_keeper', 'register_companion', {
        domain: 'pawsistant',
        name: 'Pawsistant',
        icon: 'mdi:paw',
        description:
          'Pet care tracker — logs walks, meals, meds and weight, and can schedule recurring pet-care chores as Home Keeper tasks.',
        config_entry_id: 'demo_pawsistant',
        docs_url: 'https://github.com/prestomation/Pawsistant',
        capabilities: ['care_schedules'],
      });
      await hass.callService('home_keeper', 'register_companion', {
        domain: 'home_keeper_battery_notes',
        name: 'Battery Notes',
        icon: 'mdi:battery-alert-variant-outline',
        description:
          'Turns Battery Notes low-battery alerts into Home Keeper “replace battery” tasks, kept in sync both ways.',
        config_entry_id: 'demo_battery_notes',
        capabilities: ['battery_replacement'],
      });
    });
  };
  // A self-registered companion only surfaces while its *domain* has a config entry
  // (build_companion_list drops connected rows for uninstalled domains). The e2e
  // container ships no entry for these demo domains, so the section can read empty
  // here — best-effort: capture when it populates, otherwise warn and keep the
  // committed image rather than overwrite it with an empty card.
  await openPanel(page);
  await seedCompanions();
  await openPanel(page);
  await panel.locator('#tab-settings').click();
  await expect(panel.locator('#hk-companions')).toBeVisible();
  const companionsSeeded = await panel
    .locator('.hk-comp-configure')
    .first()
    .isVisible({ timeout: 5000 })
    .catch(() => false);
  if (companionsSeeded) {
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${OUT}/21-panel-companions.png`, fullPage: true });
  } else {
    // eslint-disable-next-line no-console
    console.warn(
      '[screenshots] companions did not populate (no config entry for the demo ' +
        'domains in this env) — keeping the committed 21-panel-companions.png',
    );
  }

  // 4. The usage surfaces — native to-do list + calendar on a dashboard.
  await openDashboard(page);
  await page.waitForTimeout(1500); // let cards settle
  await page.screenshot({ path: `${OUT}/4-usage-todo-and-calendar.png`, fullPage: true });
});
