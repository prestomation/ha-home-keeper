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
 * A declarative companion is a spec rather than an integration: it matches entities
 * by integration/domain/device-class/regex and materializes one managed sensor task
 * per match. The e2e container seeds exactly one `update.*` entity
 * (`update.hk_demo_router_firmware`, always `on`), so the bundled **Firmware update
 * available** preset matches one entity and the preview and the task count are both
 * knowable. Device Pulse is *not* installed there, so its preset card is the disabled
 * case, and it is the only one of the three shipped presets that is gated.
 *
 * Two companions can also select the same entity, and each one makes its own task for
 * it. The overlap test seeds one companion, then opens the Add dialog on the same
 * entity. The preview must say which companion already covers that entity.
 *
 * The last test is the regression for issues #230 / #231: a trigger carries different
 * keys per mode and the backend **rejects** the ones that belong to another mode, so
 * switching the Trigger mode dropdown has to drop them. A companion seeded from Device
 * Pulse kept its `comparison` and `value` when switched to *state*, and the save came
 * back "sensor.comparison is not valid for a state-mode sensor task".
 */

/** The one entity the Firmware update available preset matches in the e2e container. */
const DEMO_UPDATE = 'update.hk_demo_router_firmware';
/** A battery flag the container also seeds; the mode-switch test narrows onto it. */
const DEMO_BATTERY = 'binary_sensor.hk_demo_remote_battery';

/**
 * The entity the overlap test points both of its companions at.
 *
 * A moisture sensor, deliberately: the container is a working store that can hold
 * companions somebody added by hand, and those watch the usual maintenance entities
 * (batteries, firmware updates, consumables). The warning names the companion with the
 * most overlap, so a second companion over the same entity would make which name
 * appears a question of order.
 */
const DEMO_MOISTURE = 'binary_sensor.hk_demo_water_tank_low';
/** `entity_regex` is a fullmatch, so the escaped entity id selects that entity alone. */
const MOISTURE_REGEX = DEMO_MOISTURE.replace('.', '\\.');

/** Every stored spec, over the service API. */
async function listSpecs(): Promise<Array<Record<string, any>>> {
  return (await callService('home_keeper', 'list_declarative_companions', {}, true)).companions;
}

/**
 * Wait for an `ha-dialog` to be on screen.
 *
 * The host element itself never reports visible — `ha-dialog` portals its surface,
 * so Playwright measures a zero-size host — which is why every dialog assertion in
 * this suite waits on a node *inside* the dialog instead. `within` names one the
 * dialog cannot be usable without.
 */
async function expectDialogOpen(dialog: Locator, within: string): Promise<void> {
  await expect(dialog).toHaveCount(1, { timeout: 20_000 });
  await expect(dialog.locator(within).first()).toBeVisible({ timeout: 20_000 });
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

/**
 * Type a regex into the companion's entity id filter.
 *
 * The regex lives under **More filters** (#373), which is closed on a new companion, so
 * open it first. Device class is the first text box there and the regex the second.
 */
async function fillRegex(dialog: Locator, value: string): Promise<void> {
  const more = dialog.locator('.hk-decl-more');
  if ((await more.getAttribute('aria-expanded')) !== 'true') await more.click();
  await expect(dialog.locator('[data-decl-section="filters"]')).toBeVisible();
  await fillSection(dialog, 'filters', 1, value);
}

/** Every demo binary sensor the container seeds: a companion with several matches. */
const DEMO_BINARY_REGEX = 'binary_sensor\\.hk_demo_.*';

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

  test('the preset picker offers every preset and gates the one that needs an integration', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    const panel = await openDeclarativeSection(page);

    await panel.locator('.hk-decl-preset').click();
    const picker = panel.locator('ha-dialog.hk-decl-picker');
    await expectDialogOpen(picker, '.hk-decl-preset-card');
    await expect(picker.locator('.hk-decl-preset-card')).toHaveCount(3);

    // Firmware update available needs nothing installed, so it is pickable.
    const firmware = picker.locator('.hk-decl-preset-card', {
      hasText: 'Firmware update available',
    });
    await expect(firmware).toBeEnabled();
    await expect(firmware).not.toHaveClass(/hk-decl-preset-disabled/);

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

  test('the Firmware update preset previews one match and materializes one task', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    const panel = await openDeclarativeSection(page);

    await panel.locator('.hk-decl-preset').click();
    const picker = panel.locator('ha-dialog.hk-decl-picker');
    await expectDialogOpen(picker, '.hk-decl-preset-card');
    await picker.locator('.hk-decl-preset-card', { hasText: 'Firmware update available' }).click();

    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expectDialogOpen(dialog, '[data-decl-section="identity"]');
    // The preview is debounced and then round-trips to the backend, so it lands a
    // moment after the dialog. One update entity is seeded, and only one.
    await expect(dialog.locator('.hk-decl-preview-header')).toHaveText(
      'Showing 1 of 1 matches',
      { timeout: 20_000 },
    );
    await expect(dialog.locator('.hk-decl-preview')).toContainText(DEMO_UPDATE);

    await dialog.locator('.hk-decl-save').click();
    await expect(dialog).toHaveCount(0, { timeout: 20_000 });

    const row = panel.locator('.hk-decl-row', { hasText: 'Firmware update available' });
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

  test('deleting a companion asks first, then takes its tasks with it', async ({ page }) => {
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
    // The store first, then the panel. Confirming Delete re-renders the panel
    // immediately, and a re-render rebuilds the section's innerHTML — so a row that
    // is merely *between renders* satisfies `toHaveCount(0)` while the companion is
    // still stored. That is how a delete the backend rejected outright read as a
    // successful one, all the way to the task assertion below.
    await expect
      .poll(async () => (await listSpecs()).some((s) => s.id === specId), { timeout: 20_000 })
      .toBe(false);
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

  test('the preview warns when another companion already covers the matches', async ({ page }) => {
    const errors = trackPanelErrors(page);
    // The companion that gets there first, seeded over the service. Every entity it
    // covers already has one of its tasks, so a second companion over the same entity
    // makes a second, identical task.
    const created = await callService(
      'home_keeper',
      'add_declarative_companion',
      {
        name: 'E2E overlap probe',
        selection: { domain: 'binary_sensor', entity_regex: MOISTURE_REGEX },
        trigger: { mode: 'state', state: 'on', clear_on_recover: true },
        task_template: { name_template: 'E2E overlap probe: {{ device_name or friendly_name }}' },
      },
      true,
    );
    const specId = created.companion.id as string;
    const probeTasks = async (): Promise<number> =>
      (await listTasks()).filter((t) => t.source?.declarative_companion?.spec_id === specId).length;
    await expect.poll(probeTasks, { timeout: 30_000 }).toBe(1);

    const panel = await openDeclarativeSection(page);
    await panel.locator('.hk-decl-add').click();
    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expectDialogOpen(dialog, '[data-decl-section="identity"]');
    await fillSection(dialog, 'identity', 0, 'E2E overlap duplicate');
    await fillRegex(dialog, MOISTURE_REGEX);

    // The warning is computed in the panel from the tasks and the companions it already
    // holds, so it lands with the preview rather than after a second round trip.
    const overlap = dialog.locator('.hk-decl-preview-overlap');
    await expect(overlap).toHaveCount(1, { timeout: 20_000 });
    await expect(overlap).toHaveText(
      '“E2E overlap probe” already covers 1 of these entities, so narrow the selection ' +
        'to prevent duplicate tasks.',
    );

    // A companion does not overlap itself: the tasks it already made are the tasks the
    // save rebuilds. Editing the probe therefore previews without the warning.
    await dialog.locator('.hk-decl-cancel').click();
    await expect(dialog).toHaveCount(0);
    await panel.locator(`.hk-decl-row[data-spec-id="${specId}"] .hk-decl-edit`).click();
    await expectDialogOpen(dialog, '[data-decl-section="identity"]');
    await expect(dialog.locator('.hk-decl-preview-header')).toHaveText('Showing 1 of 1 matches', {
      timeout: 20_000,
    });
    await expect(dialog.locator('.hk-decl-preview-overlap')).toHaveCount(0);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('switching the trigger mode drops the keys the new mode rejects', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await openDeclarativeSection(page);

    await panel.locator('.hk-decl-add').click();
    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expectDialogOpen(dialog, '[data-decl-section="identity"]');

    // Name it, and narrow the selection to the one seeded battery sensor — a blank
    // companion matches every entity in the registry, which is a lot of tasks to make
    // and unmake for one assertion. Selection schema: integration, domain (both
    // dropdowns), then device_class and entity_regex as the two text fields.
    await fillSection(dialog, 'identity', 0, 'E2E mode switch probe');
    await fillRegex(dialog, DEMO_BATTERY.replace('.', '\\.'));

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
    expect(saved, 'the companion was not stored').toBeTruthy();
    expect(saved!.trigger.mode).toBe('state');
    expect(saved!.trigger).not.toHaveProperty('comparison');
    expect(saved!.trigger).not.toHaveProperty('value');

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  /**
   * The `template` trigger mode, end to end (issue #346).
   *
   * A template is the one condition a user cannot check by reading it, so what this
   * pins is the **verdict**: the preview renders the template against each matched
   * entity, and the chip says what it got. The seeded pair lands on opposite sides of
   * the same template, so one row each way proves the render really ran rather than
   * that a chip is drawn unconditionally.
   *
   * The error half matters just as much. A template that cannot render is
   * indeterminate — it opens nothing and closes nothing — and a preview that quietly
   * showed "Monitored" for it would read as "this is fine" while the companion did
   * nothing for a week.
   */
  test('a template trigger previews its verdict per entity', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const panel = await openDeclarativeSection(page);

    await panel.locator('.hk-decl-add').click();
    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expectDialogOpen(dialog, '[data-decl-section="identity"]');

    await fillSection(dialog, 'identity', 0, 'E2E template probe');
    // Two seeded sensors that straddle the template below: the printer reads 780 and
    // the battery reads 42.
    await fillRegex(dialog, 'sensor\\.(demo_printer_hours|e2e_battery_device_battery)');

    const trigger = dialog.locator('[data-decl-section="trigger"]');
    await chooseHaSelect(trigger.locator('ha-select').first(), 'Template');

    // Straight after the mode change the box is empty, which is a form mid-typing and
    // not a mistake. The preview used to fail the whole command there and paint one
    // raw `sensor.template is required`, taking the match list with it — at the moment
    // the user most wants to see which entities the companion covers.
    await expect(dialog.locator('.hk-decl-template-hint')).toBeVisible({ timeout: 20_000 });
    await expect(dialog.locator('.hk-decl-template-error')).toHaveCount(0);
    await expect(dialog.locator('.hk-decl-preview-row')).toHaveCount(2);
    await expect(dialog.locator('.hk-decl-chip')).toHaveCount(0);

    // The mode change re-renders the dialog, so re-read the section before typing.
    const box = dialog.locator('[data-decl-section="trigger"] textarea').first();
    await box.fill('{{ state | float(0) >= 500 }}');
    await box.blur();

    // The verdict summary replaces the plain one only when the backend rendered a
    // template, so this line is itself the proof that it did.
    await expect(dialog.locator('.hk-decl-preview-header')).toHaveText(
      'Showing 2 of 2 matches. 1 of these are due now.',
      { timeout: 20_000 },
    );
    await expect(dialog.locator('.hk-decl-chip.due')).toHaveCount(1);
    await expect(dialog.locator('.hk-decl-chip.quiet')).toHaveCount(1);
    await expect(dialog.locator('.hk-decl-template-error')).toHaveCount(0);

    // A template that cannot render: one alert carrying the Jinja message, and an
    // Error chip on every row rather than a quiet one.
    await box.fill('{{ stat | float(0) >= 500 }}');
    await box.blur();
    await expect(dialog.locator('.hk-decl-template-error')).toContainText(
      "'stat' is undefined",
      { timeout: 20_000 },
    );
    await expect(dialog.locator('.hk-decl-chip.bad')).toHaveCount(2);
    await expect(dialog.locator('.hk-decl-chip.due')).toHaveCount(0);
    await expect(dialog.locator('.hk-decl-chip.quiet')).toHaveCount(0);
    // And the header claims no count: "Due now: 0" beside a red Jinja error reads as
    // "nothing is due", which is the one thing a failed render did not say.
    await expect(dialog.locator('.hk-decl-preview-header')).not.toContainText('due now');

    // A template that renders a *number* is answering some other question. It used to
    // read as "due" for every row, because the verdict went through `cv.boolean` and
    // any non-zero number is truthy there.
    await box.fill('{{ state }}');
    await box.blur();
    await expect(dialog.locator('.hk-decl-chip.bad')).toHaveCount(2, { timeout: 20_000 });
    await expect(dialog.locator('.hk-decl-chip.due')).toHaveCount(0);

    // Saved with the working template, to prove the mode survives the round trip
    // through `normalize_sensor` rather than only rendering in the dialog.
    await box.fill('{{ state | float(0) >= 500 }}');
    await box.blur();
    await expect(dialog.locator('.hk-decl-chip.due')).toHaveCount(1, { timeout: 20_000 });
    await dialog.locator('.hk-decl-save').click();
    await expect(dialog, 'the save was rejected — the dialog is still open').toHaveCount(0, {
      timeout: 20_000,
    });

    const saved = (await listSpecs()).find((s) => s.name === 'E2E template probe');
    expect(saved, 'the companion was not stored').toBeTruthy();
    expect(saved!.trigger.mode).toBe('template');
    expect(saved!.trigger.template).toBe('{{ state | float(0) >= 500 }}');
    // An attribute is rejected in this mode, so the rewrite must not have carried one.
    expect(saved!.trigger).not.toHaveProperty('attribute');

    try {
      // The companion opens one task per match, and only the printer's is due: the
      // battery's stays dormant because its template renders false. This is the half a
      // preview cannot prove — that the watcher reads the same answer the dialog did.
      const mine = async (): Promise<Array<Record<string, any>>> =>
        (await listTasks()).filter(
          (t) => t.source?.declarative_companion?.spec_id === saved!.id,
        );
      await expect.poll(async () => (await mine()).length, { timeout: 30_000 }).toBe(2);
      await expect
        .poll(async () => (await mine()).filter((t) => t.next_due !== null).length, {
          timeout: 30_000,
        })
        .toBe(1);
      const due = (await mine()).find((t) => t.next_due !== null);
      expect(due!.sensor.entity_id).toBe('sensor.demo_printer_hours');
    } finally {
      await callService('home_keeper', 'delete_declarative_companion', { id: saved!.id });
    }

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('Exclude on a preview row leaves that entity out of the companion (#373)', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const created = await callService(
      'home_keeper',
      'add_declarative_companion',
      {
        name: 'E2E exclusion probe',
        selection: { domain: 'binary_sensor', entity_regex: DEMO_BINARY_REGEX },
        trigger: { mode: 'state', state: 'on', clear_on_recover: true },
        task_template: { name_template: 'E2E exclusion probe: {{ friendly_name }}' },
      },
      true,
    );
    const specId = created.companion.id as string;
    const probeEntities = async (): Promise<string[]> =>
      (await listTasks())
        .filter((t) => t.source?.declarative_companion?.spec_id === specId)
        .map((t) => t.source.declarative_companion.entity_id as string)
        .sort();
    await expect.poll(async () => (await probeEntities()).length, { timeout: 30_000 }).toBeGreaterThan(1);
    const before = await probeEntities();

    const panel = await openDeclarativeSection(page);
    await panel.locator(`.hk-decl-row[data-spec-id="${specId}"] .hk-decl-edit`).click();
    const dialog = panel.locator('ha-dialog.hk-decl-dialog');
    await expectDialogOpen(dialog, '[data-decl-section="identity"]');
    const header = dialog.locator('.hk-decl-preview-header');
    await expect(header).toHaveText(`Showing ${before.length} of ${before.length} matches`, {
      timeout: 20_000,
    });

    // The regex is one of the filters under More filters, so the row opens by
    // default on this companion and counts it.
    const more = dialog.locator('.hk-decl-more');
    await expect(more).toHaveAttribute('aria-expanded', 'true');
    await expect(more.locator('.hk-decl-more-summary')).toHaveText('1 filter');

    const excluded = before[0];
    await dialog.locator(`.hk-decl-exclude[data-toggle-entity="${excluded}"]`).click();
    const left = before.length - 1;
    await expect(header).toHaveText(`Showing ${left} of ${left} matches`, { timeout: 20_000 });
    await expect(dialog.locator('.hk-decl-excluded-head')).toHaveText('1 entity excluded');
    await expect(dialog.locator(`.hk-decl-include[data-toggle-entity="${excluded}"]`)).toBeVisible();
    await expect(more.locator('.hk-decl-more-summary')).toHaveText('1 filter · 1 exclusion');

    // The four exclusion pickers are under More filters, below the other filters.
    const exclusions = dialog.locator('[data-decl-section="exclusions"]');
    await expect(exclusions).toBeVisible();
    await expect(dialog.locator('.hk-decl-more-body .hk-indent-head')).toContainText('Exclusions');

    await dialog.locator('.hk-decl-save').click();
    await expect(dialog).toHaveCount(0, { timeout: 20_000 });
    const stored = (await listSpecs()).find((s) => s.id === specId);
    expect(stored?.selection.exclude_entity_ids).toEqual([excluded]);
    await expect.poll(probeEntities, { timeout: 30_000 }).toEqual(before.slice(1));

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
