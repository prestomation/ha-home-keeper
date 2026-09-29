import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, emitChange, waitFor } from './panel-harness.js';

/**
 * The companion dialog's More filters block and the preview's Exclude and Include
 * buttons (#373).
 *
 * The backend already applied a companion's exclusion lists; the dialog had no field
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
  const keyCalls = [];
  return {
    previews,
    saves,
    keyCalls,
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
          case 'home_keeper/list_entity_keys':
            keyCalls.push(msg);
            return Promise.resolve({
              keys: [
                {
                  key: 'filter_time_left',
                  count: 2,
                  example_entity_id: 'sensor.kitchen_filter',
                  example_name: 'Kitchen vacuum Filter time left',
                },
                {
                  key: 'side_brush_time_left',
                  count: 1,
                  example_entity_id: 'sensor.kitchen_side',
                  example_name: 'Kitchen vacuum Side brush time left',
                },
              ],
              without_key: 3,
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

async function openEditDialog(selection) {
  const fake = makeHass({ ...BASE, selection });
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: '/settings' };
  document.body.appendChild(panel);
  panel.hass = fake.hass;
  const edit = await waitFor(() => panel.shadowRoot?.querySelector('.hk-decl-edit'), 5000);
  expect(edit, 'the seeded companion should render a row with an Edit button').toBeTruthy();
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
  it('is closed for a companion with nothing in it, and says so', async () => {
    const { panel } = await openEditDialog({ domain: 'sensor' });
    const more = $(panel, '.hk-decl-more');
    expect(more.getAttribute('aria-expanded')).toBe('false');
    expect($(panel, '.hk-decl-more-body').hidden).toBe(true);
    expect($(panel, '.hk-decl-more-summary').textContent).toBe('No other filters set');
  });

  it('is open for a companion that uses a filter in it, and counts what is set', async () => {
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
    // Two indented groups: the entity keys, then the exclusions.
    const [keys, indent] = body.querySelectorAll('.hk-indent');
    expect(keys.querySelector('.hk-eyebrow').textContent).toBe('Entity keys');
    expect(keys.contains(body.querySelector('.hk-decl-keys'))).toBe(true);
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

describe('the entity key editor', () => {
  const type = (input, value) => {
    input.value = value;
    input.dispatchEvent(new Event('input'));
  };

  it('shows the stored keys with their task names, and counts them as one filter', async () => {
    const fake = makeHass({
      ...BASE,
      selection: { domain: 'sensor', translation_keys: ['filter_time_left', 'side_brush'] },
      task_template: { ...BASE.task_template, task_names: { filter_time_left: 'Replace filter' } },
    });
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/settings' };
    document.body.appendChild(panel);
    panel.hass = fake.hass;
    (await waitFor(() => panel.shadowRoot?.querySelector('.hk-decl-edit'), 5000)).click();
    await waitFor(() => $(panel, '.hk-decl-keys .hk-decl-key'), 5000);
    const keys = [...panel.shadowRoot.querySelectorAll('.hk-decl-keys .hk-decl-key')];
    const names = [...panel.shadowRoot.querySelectorAll('.hk-decl-keys .hk-decl-key-name')];
    expect(keys.map((k) => k.value)).toEqual(['filter_time_left', 'side_brush']);
    expect(names.map((n) => n.value)).toEqual(['Replace filter', '']);
    expect($(panel, '.hk-decl-more').getAttribute('aria-expanded')).toBe('true');
    expect($(panel, '.hk-decl-more-summary').textContent).toBe('1 filter');
  });

  it('adds, fills in and removes a key, and sends the result to the preview and Save', async () => {
    const { panel, previews, saves } = await openEditDialog({ domain: 'sensor' });
    $(panel, '.hk-decl-more').click();
    expect(panel.shadowRoot.querySelectorAll('.hk-decl-key').length).toBe(0);
    $(panel, '.hk-decl-key-add').click();
    $(panel, '.hk-decl-key-add').click();
    const [k1, k2] = panel.shadowRoot.querySelectorAll('.hk-decl-key');
    const [n1] = panel.shadowRoot.querySelectorAll('.hk-decl-key-name');
    let before = previews.length;
    type(k1, 'filter_time_left');
    type(n1, 'Replace filter');
    type(k2, 'side_brush');
    await nextPreview(panel, previews, before);
    expect(lastPreview(previews).translation_keys).toEqual(['filter_time_left', 'side_brush']);
    expect(previews[previews.length - 1].companion.task_template.task_names).toEqual({
      filter_time_left: 'Replace filter',
    });
    expect($(panel, '.hk-decl-more-summary').textContent).toBe('1 filter');

    before = previews.length;
    panel.shadowRoot.querySelectorAll('.hk-decl-key-remove')[0].click();
    await nextPreview(panel, previews, before);
    expect(lastPreview(previews).translation_keys).toEqual(['side_brush']);
    expect(panel.shadowRoot.querySelectorAll('.hk-decl-key').length).toBe(1);

    $(panel, '.hk-decl-save').click();
    await waitFor(() => saves.length, 5000);
    expect(saves[0].updates.selection.translation_keys).toEqual(['side_brush']);
    expect(saves[0].updates.task_template.task_names).toEqual({});
  });
});

describe('the key list', () => {
  it('lists the keys of the target integration, and a click adds or takes out a key', async () => {
    const { panel, previews, keyCalls } = await openEditDialog({
      domain: 'sensor',
      target_integration: 'roborock',
    });
    $(panel, '.hk-decl-more').click();
    const opts = await waitFor(() => {
      const found = panel.shadowRoot.querySelectorAll('.hk-decl-keyopt');
      return found.length ? [...found] : null;
    }, 5000);
    expect(keyCalls[0]).toMatchObject({ integration: 'roborock', domain: 'sensor' });
    expect(opts.map((o) => o.dataset.key)).toEqual(['filter_time_left', 'side_brush_time_left']);
    expect(opts[0].querySelector('.hk-decl-keyopt-count').textContent).toBe('2 entities');
    expect(opts[1].querySelector('.hk-decl-keyopt-count').textContent).toBe('1 entity');
    expect(opts[0].querySelector('.hk-decl-keyopt-ex').textContent).toBe(
      'Kitchen vacuum Filter time left',
    );
    expect($(panel, '.hk-decl-keylist-title').textContent).toBe('Keys of your roborock entities');
    expect($(panel, '.hk-decl-keylist-head').textContent).toContain('Entities with no key: 3');

    let before = previews.length;
    opts[0].click();
    await nextPreview(panel, previews, before);
    expect(lastPreview(previews).translation_keys).toEqual(['filter_time_left']);
    expect(panel.shadowRoot.querySelector('.hk-decl-key').value).toBe('filter_time_left');
    expect(
      panel.shadowRoot.querySelector('[data-key="filter_time_left"]').getAttribute('aria-pressed'),
    ).toBe('true');

    before = previews.length;
    panel.shadowRoot.querySelector('[data-key="filter_time_left"]').click();
    await nextPreview(panel, previews, before);
    expect(lastPreview(previews).translation_keys).toEqual([]);
    expect(panel.shadowRoot.querySelectorAll('.hk-decl-key').length).toBe(0);
  });

  it('searches the list and keeps the focus in the search box', async () => {
    const { panel } = await openEditDialog({ domain: 'sensor', target_integration: 'roborock' });
    $(panel, '.hk-decl-more').click();
    const q = await waitFor(() => $(panel, '.hk-decl-keylist-q'), 5000);
    q.focus();
    q.value = 'side';
    q.dispatchEvent(new Event('input'));
    const keys = [...panel.shadowRoot.querySelectorAll('.hk-decl-keyopt')].map((o) => o.dataset.key);
    expect(keys).toEqual(['side_brush_time_left']);
    expect(panel.shadowRoot.activeElement).toBe(q);
    q.value = 'nothing like it';
    q.dispatchEvent(new Event('input'));
    expect($(panel, '.hk-decl-keylist-options').textContent).toContain('No key matches your search.');
  });

  it('loads the list again only when the integration or the domain changes', async () => {
    const { panel, keyCalls } = await openEditDialog({
      domain: 'sensor',
      target_integration: 'roborock',
    });
    await waitFor(() => keyCalls.length, 5000);
    const form = sectionForm(panel, 'selection');
    const pick = (patch) =>
      form.dispatchEvent(
        new CustomEvent('value-changed', { detail: { value: { ...form.data, ...patch } } }),
      );
    pick({});
    expect(keyCalls.length).toBe(1);
    pick({ integration: 'ecovacs' });
    await waitFor(() => keyCalls.length > 1, 5000);
    expect(keyCalls[1]).toMatchObject({ integration: 'ecovacs', domain: 'sensor' });
    pick({ integration: 'ecovacs', domain: 'number' });
    await waitFor(() => keyCalls.length > 2, 5000);
    expect(keyCalls[2]).toMatchObject({ integration: 'ecovacs', domain: 'number' });
  });

  it('shows no list without a target integration', async () => {
    const { panel, keyCalls } = await openEditDialog({ domain: 'sensor' });
    $(panel, '.hk-decl-more').click();
    expect($(panel, '.hk-decl-keylist').hidden).toBe(true);
    expect(keyCalls).toEqual([]);
  });
});

describe('Task labels in the task template (#378)', () => {
  it('offers a Task labels picker, seeded from the stored labels', async () => {
    const fake = makeHass({
      ...BASE,
      selection: { domain: 'sensor' },
      task_template: { ...BASE.task_template, labels: ['leak'] },
    });
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: '/settings' };
    document.body.appendChild(panel);
    panel.hass = fake.hass;
    (await waitFor(() => panel.shadowRoot?.querySelector('.hk-decl-edit'), 5000)).click();
    const form = await waitFor(() => sectionForm(panel, 'template'), 5000);

    const field = form.schema.find((f) => f.name === 'labels');
    expect(field.selector).toEqual({ label: { multiple: true } });
    expect(form.computeLabel(field)).toBe('Task labels');
    expect(form.computeHelper(field)).toContain('tasks it already made');
    expect(form.data.labels).toEqual(['leak']);
  });

  it('writes each pick back to its form, so a second pick keeps the first', async () => {
    const { panel } = await openEditDialog({ domain: 'sensor' });
    const form = sectionForm(panel, 'template');
    const pick = (patch) =>
      form.dispatchEvent(
        new CustomEvent('value-changed', { detail: { value: { ...form.data, ...patch } } }),
      );
    pick({ labels: ['leak'] });
    expect(form.data.labels).toEqual(['leak']);
    pick({ name_template: 'Check {{ friendly_name }}' });
    expect(form.data).toMatchObject({
      labels: ['leak'],
      name_template: 'Check {{ friendly_name }}',
    });
  });

  it('Save sends the task labels', async () => {
    const { panel, saves } = await openEditDialog({ domain: 'sensor' });
    emitChange(sectionForm(panel, 'template'), { labels: ['leak', 'urgent'] });
    $(panel, '.hk-decl-save').click();
    await waitFor(() => saves.length, 5000);
    expect(saves[0].updates.task_template.labels).toEqual(['leak', 'urgent']);
    expect(saves[0].updates.task_template.name_template).toBe('Replace {{ friendly_name }}');
  });
});
