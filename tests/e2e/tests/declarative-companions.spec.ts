import { test, expect, Locator, Page } from '@playwright/test';
import {
  callService,
  listTasks,
  openPanel,
  openSettingsSection,
  trackPanelErrors,
} from './helpers';

/**
 * Settings → Companions → Declarative companions, end to end.
 *
 * A declarative companion is a recipe rather than an integration: it matches entities
 * by integration/domain/device-class/regex and materializes one managed sensor task
 * per match. The e2e container seeds `binary_sensor.hk_demo_remote_battery`
 * (device_class battery, always `on`), so the bundled **Low battery** preset matches
 * exactly one entity and the preview and the task count are both knowable. Device
 * Pulse is *not* installed there, so its preset card is the disabled case.
 *
 * The last test is the regression for issues #230 / #231: a trigger carries different
 * keys per mode and the backend **rejects** the ones that belong to another mode, so
 * switching the Trigger mode dropdown has to drop them. A recipe seeded from Device
 * Pulse kept its `comparison` and `value` when switched to *state*, and the save came
 * back "sensor.comparison is not valid for a state-mode sensor task".
 */

/** The one entity the Low battery preset matches in the e2e container. */
const DEMO_BATTERY = 'binary_sensor.hk_demo_remote_battery';

/** Every stored spec, over the service API. */
async function listSpecs(): Promise<Array<Record<string, any>>> {
  return (await callService('home_keeper', 'list_declarative_companions', {}, true)).companions;
}

/** The declarative subsection of the Companions card, with Settings already open. */
async function openDeclarativeSection(page: Page): Promise<Locator> {
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await openSettingsSection(panel, 'companions');
  const companions = panel.locator('#hk-companions');
  await expect(companions).toBeVisible();
  await expect(companions.locator('.hk-companion-group-decl')).toBeVisible();
  return panel;
}

/** Pick an option from an `ha-form` dropdown (`ha-select` on `ha-dropdown`). */
async function chooseHaSelect(select: Locator, optionLabel: string | RegExp): Promise<void> {
  await select.click();
  await select.page().getByRole('menuitem', { name: optionLabel }).first().click();
}

/**
 * Fill the nth `ha-selector-text` of one dialog section.
 *
 * Sections are addressed by `data-decl-section` rather than by counting forms: the
 * trigger section's schema changes with the mode, so a dialog-wide index would move
 * under the test the moment a mode is switched.
 */
async function fillSection(
  dialog: Locator,
  section: string,
  nth: number,
  value: string,
): Promise<void> {
  await dialog
    .locator(`[data-decl-section="${section}"] ha-selector-text`)
    .nth(nth)
    .locator('input, textarea')
    .fill(value);
}

test.describe('Home Keeper panel — declarative companions', () => {
  /** Spec ids present before the test, so only what a test created is torn down. */
  let seeded: Set<string>;

  test.beforeEach(async () => {
    seeded = new Set((await listSpecs()).map((s) => s.id as string));
  });

  test.afterEach(async () => {
    // Deleting a spec also deletes every task it materialized, so this is the whole
    // teardown — the e2e store is the committed seed fixture and must come back clean.
    for (const spec of await listSpecs()) {
      if (seeded.has(spec.id as string)) continue;
      await callService('home_keeper', 'delete_declarative_companion', { id: spec.id }).catch(
        () => undefined,
      );
    }
  });

  test('the subsection renders its heading, help and both Add buttons', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await openDeclarativeSection(page);
    const companions = panel.locator('#hk-companions');

    await expect(companions.locator('.hk-companion-group-decl')).toHaveText(
      'Declarative companions',
    );
    await expect(companions).toContainText('one managed sensor task per match');
    await expect(companions.locator('.hk-decl-add')).toBeVisible();
    await expect(companions.locator('.hk-decl-preset')).toBeVisible();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('the preset picker offers three recipes and gates the one that needs an integration', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    const panel = await openDeclarativeSection(page);

    await panel.locator('.hk-decl-preset').click();
    const picker = panel.locator('ha-dialog.hk-decl-picker');
    await expect(picker).toBeVisible();
    await expect(picker.locator('.hk-decl-preset-card')).toHaveCount(3);

    // Low battery needs nothing installed, so it is pickable.
    const lowBattery = picker.locator('.hk-decl-preset-card', { hasText: 'Low battery' });
    await expect(lowBattery).toBeEnabled();
    await expect(lowBattery).not.toHaveClass(/hk-decl-preset-disabled/);

    // Device Pulse needs its upstream integration, which this container does not have.
    const devicePulse = picker.locator('.hk-decl-preset-card', { hasText: 'Device Pulse' });
    await expect(devicePulse).toHaveClass(/hk-decl-preset-disabled/);
    await expect(devicePulse).toBeDisabled();
    await expect(devicePulse.locator('.hk-decl-preset-req')).toHaveText(
      'Requires the device_pulse integration',
    );

    await picker.locator('.hk-decl-cancel').click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0);
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('the Low battery preset previews one match and materializes one task', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await openDeclarativeSection(page);

    await panel.locator('.hk-decl-preset').click();
    const picker = panel.locator('ha-dialog.hk-decl-picker');
    await picker.locator('.hk-decl-preset-card', { hasText: 'Low battery' }).click();

    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expect(dialog).toBeVisible();
    // The preview is debounced and then round-trips to the backend, so it lands a
    // moment after the dialog. One battery binary sensor is seeded, and only one.
    await expect(dialog.locator('.hk-decl-preview-header')).toHaveText(
      'Showing 1 of 1 matches',
      { timeout: 20_000 },
    );
    await expect(dialog.locator('.hk-decl-preview')).toContainText(DEMO_BATTERY);

    await dialog.locator('.hk-decl-save').click();
    await expect(dialog).toHaveCount(0, { timeout: 20_000 });

    const row = panel.locator('.hk-decl-row', { hasText: 'Low battery' });
    await expect(row).toHaveCount(1, { timeout: 20_000 });
    const specId = await row.getAttribute('data-spec-id');
    expect(specId).toBeTruthy();

    // The reconciler runs off a dispatched signal, so the task appears shortly after
    // the save rather than as part of it.
    await expect
      .poll(
        async () =>
          (await listTasks()).filter(
            (t) => t.source?.declarative_companion?.spec_id === specId,
          ).length,
        { timeout: 30_000 },
      )
      .toBe(1);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('deleting a recipe asks first, then takes its tasks with it', async ({ page }) => {
    const errors = trackPanelErrors(page);
    // Seeded over the service so the test starts at the row rather than re-walking
    // the create flow the test above already covers.
    const created = await callService(
      'home_keeper',
      'add_declarative_companion',
      {
        name: 'E2E delete probe',
        selection: { domain: 'binary_sensor', device_class: 'battery' },
        trigger: { mode: 'state', state: 'on', clear_on_recover: true },
        task_template: { name_template: 'E2E delete probe: {{ friendly_name }}' },
      },
      true,
    );
    const specId = created.companion.id as string;
    await expect
      .poll(
        async () =>
          (await listTasks()).filter((t) => t.source?.declarative_companion?.spec_id === specId)
            .length,
        { timeout: 30_000 },
      )
      .toBe(1);

    const panel = await openDeclarativeSection(page);
    const row = panel.locator(`.hk-decl-row[data-spec-id="${specId}"]`);
    await expect(row).toBeVisible();
    await row.locator('.hk-decl-delete').click();

    // The confirmation is a body-level scrim, not an `ha-dialog`: its destructive
    // variant has to resolve against HA's document-level theme.
    const scrim = page.locator('.hk-confirm-scrim');
    await expect(scrim).toBeVisible();
    await expect(scrim).toContainText('E2E delete probe');
    // Cancel then Delete, in that order — Delete is the one that carries the fill.
    await scrim.locator('ha-button').last().click();

    await expect(scrim).toHaveCount(0);
    await expect(row).toHaveCount(0, { timeout: 20_000 });
    await expect
      .poll(
        async () =>
          (await listTasks()).filter((t) => t.source?.declarative_companion?.spec_id === specId)
            .length,
        { timeout: 30_000 },
      )
      .toBe(0);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('switching the trigger mode drops the keys the new mode rejects', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await openDeclarativeSection(page);

    await panel.locator('.hk-decl-add').click();
    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expect(dialog).toBeVisible();

    // Name it, and narrow the selection to the one seeded battery sensor — a blank
    // recipe matches every entity in the registry, which is a lot of tasks to make
    // and unmake for one assertion. Selection schema: integration, domain (both
    // dropdowns), then device_class and entity_regex as the two text fields.
    await fillSection(dialog, 'identity', 0, 'E2E mode switch probe');
    await fillSection(dialog, 'selection', 1, DEMO_BATTERY.replace('.', '\\.'));

    // State → Threshold: the threshold's own fields appear. A field label is drawn
    // inside the HA component's own shadow root, so it is reachable through
    // `getByText` (which pierces) rather than through the section's `textContent`.
    const trigger = dialog.locator('[data-decl-section="trigger"]');
    await chooseHaSelect(trigger.locator('ha-select').first(), 'Threshold');
    await expect(trigger.getByText('Comparison').first()).toBeVisible();

    // Threshold → State: the comparison and value go with it. Left behind, the save
    // fails with "sensor.comparison is not valid for a state-mode sensor task".
    await chooseHaSelect(
      dialog.locator('[data-decl-section="trigger"] ha-select').first(),
      'State',
    );
    await expect(trigger.getByText('State to watch for').first()).toBeVisible();
    await expect(trigger.getByText('Comparison')).toHaveCount(0);

    await dialog.locator('.hk-decl-save').click();
    // A rejected save keeps the dialog up with the backend's message in an alert.
    await expect(dialog.locator('ha-alert[alert-type="error"]')).toHaveCount(0);
    await expect(dialog, 'the save was rejected — the dialog is still open').toHaveCount(0, {
      timeout: 20_000,
    });

    const saved = (await listSpecs()).find((s) => s.name === 'E2E mode switch probe');
    expect(saved, 'the recipe was not stored').toBeTruthy();
    expect(saved!.trigger.mode).toBe('state');
    expect(saved!.trigger).not.toHaveProperty('comparison');
    expect(saved!.trigger).not.toHaveProperty('value');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
