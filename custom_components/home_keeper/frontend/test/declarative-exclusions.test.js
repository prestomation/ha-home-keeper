import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, emitChange, waitFor } from './panel-harness.js';

/**
 * The recipe dialog's More filters block and the preview's Exclude and Include
 * buttons (#373).
 *
 * The backend already applied a recipe's exclusion lists; the dialog had no field
 * for them, so the only way to leave an entity out was the entity id regex. These
 * tests mount the real panel and check that each new control writes the list the
 * backend reads, and that the preview and the pickers stay in step.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const BASE = {
  id: 'spec-1',
  name: 'Low battery',
  description: '',
  enabled: true,
  preset_id: null,
  trigger: { mode: 'threshold', comparison: '<=', value: 20, clear_on_recover: true },
  task_template: { name_template: 'Replace {{ friendly_name }}', notes_template: '' },
  per_entity_overrides: {},
};

const MATCHES = [
  { entity_id: 'sensor.lock_battery', rendered_name: 'Replace Lock' },
  { entity_id: 'sensor.phone_battery', rendered_name: 'Replace Phone' },
  { entity_id: 'sensor.smoke_battery', rendered_name: 'Replace Smoke' },
];

/** A fake backend whose preview drops the excluded entities, as the real one does. */
function makeHass(spec) {
  const previews = [];
  const saves = [];
  return {
    previews,
    saves,
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
            return Promise.resolve({ companions: [spec] });
          case 'home_keeper/update_declarative_companion':
            saves.push(msg);
            return Promise.resolve({});
          case 'home_keeper/preview_declarative_companion': {
            previews.push(msg);
            const out = msg.companion.selection.exclude_entity_ids ?? [];
            const matched = MATCHES.filter((m) => !out.includes(m.entity_id));
            return Promise.resolve({ count: matched.length, over_cap: false, matched });
          }
          case 'frontend/get_user_data':
            return Promise.resolve({ value: msg.key === 'home_keeper_intro_dismissed' });
          default:
            return Promise.resolve({});
        }
      },
    },
  };
}

async function openEditDialog(selection) {
  const fake = makeHass({ ...BASE, selection });
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = fake.hass;
  const edit = await waitFor(() => panel.shadowRoot?.querySelector('.hk-decl-edit'), 5000);
  expect(edit, 'the seeded recipe should render a row with an Edit button').toBeTruthy();
  edit.click();
  await waitFor(() => panel.shadowRoot?.querySelector('ha-dialog.hk-decl-dialog'));
  await waitFor(() => panel.shadowRoot.querySelector('.hk-decl-preview-header'), 5000);
  return { panel, ...fake };
}

const $ = (panel, sel) => panel.shadowRoot.querySelector(sel);
const sectionForm = (panel, key) => $(panel, `[data-decl-section="${key}"]`);
const lastPreview = (previews) => previews[previews.length - 1].companion.selection;
const previewText = (panel) => $(panel, '.hk-decl-preview').textContent;

/** Wait until the preview has been asked again, then until its header is back. */
async function nextPreview(panel, previews, before) {
  await waitFor(() => previews.length > before, 5000);
  return waitFor(() => $(panel, '.hk-decl-preview-header'), 5000);
}

describe('the More filters row', () => {
  it('is closed for a recipe with nothing in it, and says so', async () => {
    const { panel } = await openEditDialog({ domain: 'sensor' });
    const more = $(panel, '.hk-decl-more');
    expect(more.getAttribute('aria-expanded')).toBe('false');
    expect($(panel, '.hk-decl-more-body').hidden).toBe(true);
    expect($(panel, '.hk-decl-more-summary').textContent).toBe('No other filters set');
  });

  it('is open for a recipe that uses a filter in it, and counts what is set', async () => {
    const { panel } = await openEditDialog({
      domain: 'sensor',
      device_class: 'battery',
      exclude_area_ids: ['garage'],
      exclude_label_ids: ['rechargeable'],
    });
    expect($(panel, '.hk-decl-more').getAttribute('aria-expanded')).toBe('true');
    expect($(panel, '.hk-decl-more-body').hidden).toBe(false);
    expect($(panel, '.hk-decl-more-summary').textContent).toBe('1 filter · 2 exclusions');
  });

  it('opens and closes on a click', async () => {
    const { panel } = await openEditDialog({ domain: 'sensor' });
    const more = $(panel, '.hk-decl-more');
    more.click();
    expect(more.getAttribute('aria-expanded')).toBe('true');
    expect($(panel, '.hk-decl-more-body').hidden).toBe(false);
    more.click();
    expect(more.getAttribute('aria-expanded')).toBe('false');
    expect($(panel, '.hk-decl-more-body').hidden).toBe(true);
  });

  it('stays open when a trigger-mode change rebuilds the dialog', async () => {
    const { panel } = await openEditDialog({ domain: 'sensor' });
    $(panel, '.hk-decl-more').click();
    emitChange(sectionForm(panel, 'trigger'), { mode: 'state' });
    const more = await waitFor(() => $(panel, '.hk-decl-more'));
    expect(more.getAttribute('aria-expanded')).toBe('true');
    expect($(panel, '.hk-decl-more-body').hidden).toBe(false);
  });

  it('holds the filter and exclusion forms, the exclusions under their own head', async () => {
    const { panel } = await openEditDialog({ domain: 'sensor' });
    const body = $(panel, '.hk-decl-more-body');
    expect(body.contains(sectionForm(panel, 'filters'))).toBe(true);
    const indent = body.querySelector('.hk-indent');
    expect(indent.contains(sectionForm(panel, 'exclusions'))).toBe(true);
    expect(indent.querySelector('.hk-eyebrow').textContent).toBe('Exclusions');
    // The selection section keeps only the two common fields.
    expect(sectionForm(panel, 'selection').schema.map((f) => f.name)).toEqual([
      'integration',
      'domain',
    ]);
  });
});

describe('the filter and exclusion forms', () => {
  it('send what is picked to the preview, and update the summary', async () => {
    const { panel, previews } = await openEditDialog({ domain: 'sensor' });
    let before = previews.length;
    emitChange(sectionForm(panel, 'filters'), { area_ids: ['hall'], label_ids: ['battery'] });
    await nextPreview(panel, previews, before);
    expect(lastPreview(previews).area_ids).toEqual(['hall']);
    expect(lastPreview(previews).label_ids).toEqual(['battery']);

    before = previews.length;
    emitChange(sectionForm(panel, 'exclusions'), {
      exclude_device_ids: ['dev1'],
      exclude_area_ids: ['garage'],
    });
    await nextPreview(panel, previews, before);
    expect(lastPreview(previews).exclude_device_ids).toEqual(['dev1']);
    expect(lastPreview(previews).exclude_area_ids).toEqual(['garage']);
    expect($(panel, '.hk-decl-more-summary').textContent).toBe('2 filters · 2 exclusions');
  });

  it('writes each filter pick back to its form, so a second pick keeps the first', async () => {
    // ha-form does not keep its own value. Without the write-back the area picker
    // builds the next pick from the seed, and the first area is lost. So fire the
    // event as ha-form does, without setting `data` as emitChange does.
    const { panel } = await openEditDialog({ domain: 'sensor' });
    const form = sectionForm(panel, 'filters');
    const pick = (patch) =>
      form.dispatchEvent(
        new CustomEvent('value-changed', { detail: { value: { ...form.data, ...patch } } }),
      );
    pick({ area_ids: ['hall'] });
    expect(form.data.area_ids).toEqual(['hall']);
    pick({ label_ids: ['battery'] });
    expect(form.data).toMatchObject({ area_ids: ['hall'], label_ids: ['battery'] });
  });
});

describe('Exclude and Include on the preview', () => {
  it('puts an Exclude button on each matched row', async () => {
    const { panel } = await openEditDialog({ domain: 'sensor' });
    const buttons = [...panel.shadowRoot.querySelectorAll('.hk-decl-exclude')];
    expect(buttons.map((b) => b.dataset.toggleEntity)).toEqual(MATCHES.map((m) => m.entity_id));
    expect(buttons[0].getAttribute('aria-label')).toBe('Exclude');
    expect($(panel, '.hk-decl-excluded')).toBeNull();
  });

  it('Exclude writes the entity into the exclusion list and the picker', async () => {
    const { panel, previews } = await openEditDialog({ domain: 'sensor' });
    const before = previews.length;
    $(panel, '[data-toggle-entity="sensor.phone_battery"]').click();

    // The picker and the summary change at once, before the preview returns.
    expect(sectionForm(panel, 'exclusions').data.exclude_entity_ids).toEqual([
      'sensor.phone_battery',
    ]);
    expect($(panel, '.hk-decl-more-summary').textContent).toBe('1 exclusion');

    await nextPreview(panel, previews, before);
    await waitFor(() => $(panel, '.hk-decl-excluded'), 5000);
    expect(lastPreview(previews).exclude_entity_ids).toEqual(['sensor.phone_battery']);
    // The row left the matches and is listed under them, with Include.
    expect($(panel, '.hk-decl-preview-header').textContent).toContain('2 of 2');
    expect($(panel, '.hk-decl-excluded-head').textContent).toBe('1 entity excluded');
    const include = $(panel, '.hk-decl-include');
    expect(include.dataset.toggleEntity).toBe('sensor.phone_battery');
    expect(include.getAttribute('aria-label')).toBe('Include');
    expect(panel.shadowRoot.querySelectorAll('.hk-decl-exclude')).toHaveLength(2);
  });

  it('Include takes the entity out of the list again', async () => {
    const { panel, previews } = await openEditDialog({
      domain: 'sensor',
      exclude_entity_ids: ['sensor.phone_battery'],
    });
    await waitFor(() => $(panel, '.hk-decl-include'), 5000);
    const before = previews.length;
    $(panel, '.hk-decl-include').click();
    expect(sectionForm(panel, 'exclusions').data.exclude_entity_ids).toEqual([]);
    await nextPreview(panel, previews, before);
    await waitFor(() => !$(panel, '.hk-decl-excluded'), 5000);
    expect(lastPreview(previews).exclude_entity_ids).toEqual([]);
    expect(previewText(panel)).toContain('Replace Phone');
  });

  it('keeps an entity picked in the picker when a row is excluded after it', async () => {
    const { panel, previews } = await openEditDialog({ domain: 'sensor' });
    emitChange(sectionForm(panel, 'exclusions'), { exclude_entity_ids: ['sensor.lock_battery'] });
    await nextPreview(panel, previews, previews.length - 1);
    await waitFor(() => $(panel, '[data-toggle-entity="sensor.smoke_battery"]'), 5000);
    $(panel, '.hk-decl-exclude[data-toggle-entity="sensor.smoke_battery"]').click();
    expect(sectionForm(panel, 'exclusions').data.exclude_entity_ids).toEqual([
      'sensor.lock_battery',
      'sensor.smoke_battery',
    ]);
  });

  it('Save sends every list', async () => {
    const { panel, saves } = await openEditDialog({ domain: 'sensor' });
    emitChange(sectionForm(panel, 'exclusions'), { exclude_label_ids: ['rechargeable'] });
    $(panel, '[data-toggle-entity="sensor.phone_battery"]').click();
    $(panel, '.hk-decl-save').click();
    await waitFor(() => saves.length, 5000);
    const sel = saves[0].updates.selection;
    expect(sel.exclude_entity_ids).toEqual(['sensor.phone_battery']);
    expect(sel.exclude_label_ids).toEqual(['rechargeable']);
  });
});
