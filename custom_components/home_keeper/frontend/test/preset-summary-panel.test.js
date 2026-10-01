import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, emitChange, waitFor } from './panel-harness.js';

/**
 * The preset summary in the real companion dialog: the box says what the preset does
 * and which tasks it makes, marks the sections the user changed, and Reset to preset
 * puts them back. Each preview row shows its reading, with a bar toward the preset's
 * limit while the trigger is still the preset's.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const DEFAULT_SPEC = {
  name: 'Zigbee (ZHA): wear counters',
  description: '',
  enabled: true,
  preset_id: 'zha_wear_high',
  selection: {
    target_integration: 'zha',
    domain: 'sensor',
    translation_keys: ['filter_run_time'],
    area_ids: [],
    label_ids: [],
    exclude_entity_ids: [],
    exclude_device_ids: [],
    exclude_area_ids: [],
    exclude_label_ids: [],
  },
  trigger: { mode: 'template', template: '{{ state | float > 4320 }}', clear_on_recover: true },
  task_template: {
    name_template: '{{ task_name }}: {{ device_name or friendly_name }}',
    notes_template: '',
    labels: [],
    task_names: { filter_run_time: 'Replace the filter' },
  },
  per_entity_overrides: {},
};

const PRESET = {
  id: 'zha_wear_high',
  name: 'Zigbee (ZHA): wear counters',
  description:
    'Opens a task when a wear counter of a Zigbee (ZHA) device passes its service limit. Limit: above 180 days.',
  icon: 'mdi:air-filter',
  requires_integration: 'zha',
  group: 'integration',
  matches: 1,
  limit: { kind: 'hours', value: 4320, above: true },
  default_spec: DEFAULT_SPEC,
};

function makeHass(companions) {
  const previews = [];
  return {
    previews,
    hass: {
      language: 'en',
      states: {},
      devices: {},
      callWS(msg) {
        switch (msg.type) {
          case 'home_keeper/get_tasks':
            return Promise.resolve({ tasks: [] });
          case 'home_keeper/get_assets':
            return Promise.resolve({ assets: [] });
          case 'home_keeper/get_options':
            return Promise.resolve({ options: {} });
          case 'home_keeper/list_declarative_companions':
            return Promise.resolve({ companions });
          case 'home_keeper/list_declarative_presets':
            return Promise.resolve({ presets: [PRESET] });
          case 'home_keeper/installed_integrations':
            return Promise.resolve({ integrations: ['zha'] });
          case 'home_keeper/preview_declarative_companion':
            previews.push(msg);
            return Promise.resolve({
              count: 1,
              over_cap: false,
              warnings: [],
              matched: [
                {
                  entity_id: 'sensor.bedroom_purifier_filter_run_time',
                  entity_registry_id: 'r1',
                  rendered_name: 'Replace the filter: Bedroom purifier',
                  rendered_notes: '',
                  trigger_now: false,
                  trigger_error: null,
                  state: '129600',
                  unit: 'min',
                },
              ],
            });
          case 'frontend/get_user_data':
            return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
          default:
            return Promise.resolve({});
        }
      },
    },
  };
}

async function openEdit(spec) {
  const { hass, previews } = makeHass([spec]);
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = hass;
  const edit = await waitFor(() => panel.shadowRoot?.querySelector('.hk-decl-edit'), 5000);
  edit.click();
  await waitFor(() => panel.shadowRoot?.querySelector('ha-dialog.hk-decl-dialog'));
  return { panel, previews };
}

const $ = (panel, sel) => panel.shadowRoot.querySelector(sel);
const stored = (over = {}) => ({ id: 'spec-1', ...JSON.parse(JSON.stringify(DEFAULT_SPEC)), ...over });

describe('the preset summary', () => {
  it('says what the preset does and which tasks it makes', async () => {
    const { panel } = await openEdit(stored());
    const box = $(panel, '.hk-preset-summary');
    expect(box).toBeTruthy();
    // It sits first in the form, above Identity.
    expect(box.parentElement.firstElementChild).toBe(box);
    expect($(panel, '.hk-preset-summary-kicker').textContent).toBe('From preset');
    expect($(panel, '.hk-preset-summary-name').textContent).toBe('Zigbee (ZHA): wear counters');
    expect($(panel, '.hk-preset-summary-desc').textContent).toBe(PRESET.description);
    const tasks = [...panel.shadowRoot.querySelectorAll('.hk-preset-summary-tasks .hk-decl-preset-task')];
    expect(tasks.map((t) => t.textContent)).toEqual(['Replace the filter']);
    expect($(panel, '.hk-preset-summary-changed').hidden).toBe(true);
  });

  it('shows no box for a companion that did not come from a preset', async () => {
    const { panel } = await openEdit(stored({ preset_id: null }));
    expect($(panel, '.hk-preset-summary')).toBeNull();
  });

  it('marks a changed section and puts it back on Reset', async () => {
    const { panel, previews } = await openEdit(stored({ name: 'My purifiers' }));
    emitChange($(panel, '[data-decl-section="trigger"]'), {
      mode: 'template',
      template: '{{ state | float > 2000 }}',
      for_seconds: 0,
      clear_on_recover: true,
    });
    const row = $(panel, '.hk-preset-summary-changed');
    expect(row.hidden).toBe(false);
    expect($(panel, '.hk-preset-summary-chip').textContent).toBe('Changed: Trigger');
    expect($(panel, '.hk-preset-summary-reset').textContent).toBe('Reset to preset');

    $(panel, '.hk-preset-summary-reset').click();
    // The dialog is drawn again from the reset draft.
    await waitFor(() => $(panel, '.hk-preset-summary-changed')?.hidden === true, 5000);
    await waitFor(() => previews.at(-1)?.companion.trigger.template === '{{ state | float > 4320 }}', 5000);
    const last = previews.at(-1).companion;
    expect(last.trigger).toEqual(DEFAULT_SPEC.trigger);
    // The user's own name stays.
    expect(last.name).toBe('My purifiers');
  });

  it('names every changed section by its heading', async () => {
    const { panel } = await openEdit(
      stored({
        selection: { ...DEFAULT_SPEC.selection, area_ids: ['bedroom'] },
        task_template: { ...DEFAULT_SPEC.task_template, labels: ['filters'] },
      }),
    );
    expect($(panel, '.hk-preset-summary-chip').textContent).toBe(
      'Changed: Which entities?, Task template',
    );
  });

  it('shows each reading with a bar toward the preset limit', async () => {
    const { panel } = await openEdit(stored());
    const reading = await waitFor(() => $(panel, '.hk-decl-reading'), 5000);
    // 129600 min is 2160 h, half of the 4320 h limit.
    expect(reading.textContent).toContain('Now: 129,600 min');
    expect($(panel, '.hk-decl-reading-pct').textContent).toBe('50% of the limit');
    expect($(panel, '.hk-decl-reading-bar').getAttribute('aria-hidden')).toBe('true');
    expect($(panel, '.hk-decl-reading-bar > span').style.width).toBe('50%');
  });

  it('drops the bar once the trigger is not the preset’s', async () => {
    const { panel } = await openEdit(
      stored({ trigger: { mode: 'template', template: '{{ state | float > 10 }}', clear_on_recover: true } }),
    );
    const reading = await waitFor(() => $(panel, '.hk-decl-reading'), 5000);
    expect(reading.textContent).toContain('Now: 129,600 min');
    expect($(panel, '.hk-decl-reading-bar')).toBeNull();
  });
});
