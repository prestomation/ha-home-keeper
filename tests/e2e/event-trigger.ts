/**
 * Opens the Home Assistant automation editor with an Event received trigger that
 * targets one device. The event entity capture and the walkthrough use it.
 *
 * The Add trigger dialog closes without adding the trigger when a test clicks its
 * row, so this fills the trigger in YAML mode and then switches back to the visual
 * editor. The result is the same trigger a user makes in the dialog.
 */
import type { Page } from '@playwright/test';

export const HEATER_EVENTS = 'event.garage_water_heater_home_keeper_events';

/** The registry device id of an entity, read through the frontend connection. */
export async function deviceIdOf(page: Page, entityId: string): Promise<string> {
  return page.evaluate(async (id) => {
    const ha = document.querySelector('home-assistant') as unknown as {
      hass?: { connection?: unknown; callWS: <T>(m: Record<string, unknown>) => Promise<T> };
    };
    for (let i = 0; i < 60 && !ha?.hass?.connection; i++) {
      await new Promise((r) => setTimeout(r, 500));
    }
    const entries = await ha.hass!.callWS<Array<{ entity_id: string; device_id: string }>>({
      type: 'config/entity_registry/list',
    });
    const entry = entries.find((e) => e.entity_id === id);
    if (!entry) throw new Error(`no registry entry for ${id}`);
    return entry.device_id;
  }, entityId);
}

/** Open a new automation with the trigger filled in, and open the trigger panel. */
export async function openEventReceivedTrigger(
  page: Page,
  deviceId: string,
  eventTypes: string[],
): Promise<void> {
  await page.goto('/config/automation/edit/new', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Menu' }).click();
  await page.getByRole('menuitem', { name: 'Edit in YAML' }).click();
  await page.locator('ha-yaml-editor .cm-content').first().click();
  await page.keyboard.press('Control+A');
  await page.keyboard.insertText(
    [
      'alias: Garage task done',
      'description: ""',
      'triggers:',
      '  - trigger: event.received',
      '    target:',
      `      device_id: ${deviceId}`,
      '    options:',
      '      event_type:',
      ...eventTypes.map((type) => `        - ${type}`),
      'conditions: []',
      'actions: []',
      'mode: single',
    ].join('\n'),
  );
  await page.getByRole('button', { name: 'Menu' }).click();
  await page.getByRole('menuitem', { name: 'Edit in visual editor' }).click();
  // Open the trigger. Its header text is not a stable target, so click the row.
  await page.locator('ha-automation-trigger-row').first().click({ position: { x: 120, y: 24 } });
  await page.getByText('Triggers when one or more event entities').first().waitFor();
}
