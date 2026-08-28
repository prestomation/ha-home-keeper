import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import {
  definePanelStubs,
  emitChange,
  focusField,
  makeHass,
  mountPanel,
  stubLazyMarkdown,
  waitFor,
} from './panel-harness.js';

/**
 * Typing in a form field must never rebuild the form.
 *
 * `_render()` replaces the panel's whole shadow tree, so a re-render triggered mid-edit
 * destroys the field being typed in and focus falls back to `<body>`. Home Assistant
 * then owns those keystrokes: its global shortcuts are registered on `window`
 * (tinykeys) and only stand down when the keydown target is a text input, so the rest
 * of the word gets eaten as hotkeys — `d` opens the device quick bar, `e` entities,
 * `c` commands, `a` Assist, `m` a my-link.
 *
 * The reported symptom (typing a task name popped up the device search, once Assist)
 * came from the *first* keystroke: the form seeds defaults the edit state doesn't carry
 * (an unset `sensor_mode` shows as 'usage'), so the "did the visible schema change?"
 * check compared 'usage' against `undefined` and re-rendered on the first unrelated
 * character. These tests pin the invariant from both directions — an unrelated edit
 * keeps the form node (and its focus), a real schema change still rebuilds it.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
});

/**
 * The `ha-form` inside `#hk-task-form` that offers *name*.
 *
 * The task form is rendered as one `ha-form` per section (Basics, Schedule, the
 * fields the schedule reveals, Placement, Completion) so a heading can sit between
 * two runs of fields. `#hk-task-form` is therefore the wrapper around them, not a
 * form: a `value-changed` dispatched at the wrapper reaches no listener, so these
 * tests must address the section that actually owns the field they are editing —
 * otherwise they pass without exercising anything.
 *
 * Cadence fields sit inside an unnamed `grid` container, so look one level down too.
 */
const sectionWith = (panel, name) =>
  [...(panel.shadowRoot?.querySelectorAll('#hk-task-form ha-form') ?? [])].find((f) =>
    (f.schema ?? []).some(
      (s) => s.name === name || (s.schema ?? []).some((child) => child.name === name),
    ),
  ) ?? null;

/** Wait until a section form offering *name* is on screen. */
const waitForSection = (panel, name) => waitFor(() => sectionWith(panel, name));

describe('typing in the task form must not rebuild it (HA hotkeys eat the keystrokes)', () => {
  it('keeps the form and its focused field alive through the first character of a new task name', async () => {
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();

    const form = await waitForSection(panel, 'name');
    expect(form, 'the new-task form should render').toBeTruthy();
    const input = focusField(form);

    // The very first character typed into the name field.
    emitChange(form, { name: 'D' });

    expect(
      sectionWith(panel, 'name'),
      'typing a name must not rebuild the form',
    ).toBe(form);
    expect(
      panel.shadowRoot.activeElement,
      'the field being typed in must keep focus — once it is gone, HA claims the keys',
    ).toBe(input);

    // And it stays put for the rest of the word ("Dishwasher" spells out `d`, `a`, `e`
    // — device quick bar, Assist, entity quick bar).
    for (const name of ['Di', 'Dis', 'Dish', 'Dishw', 'Dishwa', 'Dishwas']) {
      emitChange(form, { name });
    }
    expect(sectionWith(panel, 'name')).toBe(form);
    expect(panel.shadowRoot.activeElement).toBe(input);
    expect(form.data.name).toBe('Dishwas');
  });

  it('keeps the form alive while editing an existing task', async () => {
    const task = {
      id: 't1',
      name: 'Change filter',
      recurrence_type: 'floating',
      interval: 3,
      unit: 'months',
      enabled: true,
    };
    const { panel } = await mountPanel('/tasks', makeHass({ tasks: [task] }));

    // The same entry point the list/detail "Edit" button uses.
    panel._openEdit(task);

    const form = await waitForSection(panel, 'name');
    expect(form, 'the edit form should render').toBeTruthy();
    const input = focusField(form);

    emitChange(form, { name: 'Change filters' });

    expect(
      sectionWith(panel, 'name'),
      'renaming an existing task must not rebuild the form',
    ).toBe(form);
    expect(panel.shadowRoot.activeElement).toBe(input);
  });

  // Splitting the form into sections means an event carries only the section that
  // changed, so any handler that reads a field unconditionally sees `undefined` for
  // the fields in every *other* section. The cadence interval is the one that bites:
  // it is coerced with `Number(...) || 1`, so an unguarded read would silently reset
  // "every 3 months" to "every 1 month" on the first character typed into the name.
  it('leaves fields in other sections alone when one section changes', async () => {
    const task = {
      id: 't1',
      name: 'Change filter',
      recurrence_type: 'floating',
      interval: 3,
      unit: 'months',
      enabled: true,
    };
    const { panel } = await mountPanel('/tasks', makeHass({ tasks: [task] }));
    panel._openEdit(task);

    const basics = await waitForSection(panel, 'name');
    const cadence = sectionWith(panel, 'interval');
    expect(cadence, 'the cadence fields should be on screen').toBeTruthy();
    expect(cadence.data.interval).toBe(3);

    emitChange(basics, { name: 'Change filters' });

    expect(panel._edit.task.interval, 'typing a name must not reset the cadence').toBe(3);
    expect(panel._edit.task.unit).toBe('months');
    expect(panel._edit.task.name).toBe('Change filters');
  });

  it('still rebuilds the form when the recurrence type changes the visible fields', async () => {
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();

    const form = await waitForSection(panel, 'recurrence_type');
    expect(form.schema.map((f) => f.name)).toContain('recurrence_type');

    emitChange(form, { recurrence_type: 'sensor' });

    const rebuilt = await waitFor(() => {
      const f = sectionWith(panel, 'recurrence_type');
      return f && f !== form ? f : null;
    });
    expect(
      rebuilt,
      'switching recurrence type must rebuild the form (its fields change)',
    ).toBeTruthy();
    // The sensor binding is revealed *by* that choice, so it lands in the dependent
    // section below it rather than alongside the recurrence picker.
    expect(sectionWith(panel, 'sensor_entity_id')).toBeTruthy();
  });

  it('still rebuilds the form when the sensor mode changes the visible fields', async () => {
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();

    const kind = await waitForSection(panel, 'recurrence_type');
    emitChange(kind, { recurrence_type: 'sensor' });
    const form = await waitForSection(panel, 'sensor_mode');
    expect(form, 'sensor fields should be on screen').toBeTruthy();

    emitChange(form, { sensor_mode: 'threshold' });

    const rebuilt = await waitFor(() => {
      const f = sectionWith(panel, 'sensor_mode');
      return f && f !== form ? f : null;
    });
    expect(rebuilt, 'switching sensor mode must rebuild the form').toBeTruthy();
    expect(rebuilt.schema.map((f) => f.name)).toContain('sensor_value');
  });

  it('still rebuilds the form when a state binding swaps to a binary sensor', async () => {
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();

    const kind = await waitForSection(panel, 'recurrence_type');
    emitChange(kind, { recurrence_type: 'sensor' });
    let form = await waitForSection(panel, 'sensor_mode');
    emitChange(form, { sensor_mode: 'state' });
    form = await waitForSection(panel, 'sensor_state');
    expect(form, 'the state-mode fields should be on screen').toBeTruthy();
    // Free text until the bound entity is known to be a binary sensor.
    const stateField = (f) => f.schema.find((s) => s.name === 'sensor_state');
    expect(stateField(form).selector).toEqual({ text: {} });

    // Picking a binary sensor swaps that control for an on/off picker, which is a
    // schema change like any other and must still rebuild the form.
    emitChange(form, { sensor_entity_id: 'binary_sensor.leak' });

    const rebuilt = await waitFor(() => {
      const f = sectionWith(panel, 'sensor_state');
      return f && f !== form ? f : null;
    });
    expect(rebuilt, 'binding a binary sensor must rebuild the form').toBeTruthy();
    expect(stateField(rebuilt).selector.select.options.map((o) => o.value)).toEqual(['on', 'off']);
  });
});

describe('typing in the appliance form must not rebuild it', () => {
  it('keeps the identity form and its focused field alive through the first character', async () => {
    const { panel, addBtn } = await mountPanel('/appliances', makeHass());
    addBtn.click();

    const form = await waitFor(() => panel.shadowRoot?.querySelector('#hk-asset-form ha-form'));
    expect(form, 'the new-appliance form should render').toBeTruthy();
    const input = focusField(form);

    emitChange(form, { name: 'D' });

    expect(
      panel.shadowRoot.querySelector('#hk-asset-form ha-form'),
      'typing a name must not rebuild the appliance form',
    ).toBe(form);
    expect(panel.shadowRoot.activeElement).toBe(input);
  });
});

describe('a late ha-markdown upgrade must not rebuild an open form', () => {
  /**
   * `ha-markdown` is one of HA's lazily-registered elements: the panel asks for it on
   * every render until it arrives, then re-renders so notes upgrade from the escaped
   * text fallback to real Markdown. That resolution is asynchronous, so it can land
   * while a form is open — the intermittent version of the same bug (a couple of
   * characters into a task name, the panel rebuilds and the next letter opens Assist).
   *
   * The positive control — that the upgrade *does* repaint when nothing is being edited
   * — lives in `markdown-upgrade.test.js`: a custom element cannot be un-registered, so
   * it needs a file whose registry has never seen `ha-markdown`.
   */
  it('holds the upgrade while a task form is open', async () => {
    const registerMarkdown = stubLazyMarkdown();
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();

    const form = await waitForSection(panel, 'name');
    const input = focusField(form);
    emitChange(form, { name: 'Da' });

    // HA's Lovelace chunk lands now, mid-word.
    registerMarkdown();
    await waitFor(() => customElements.get('ha-markdown'));
    // Give the pending ensureMarkdown() callbacks a turn.
    await new Promise((r) => setTimeout(r, 50));

    expect(
      sectionWith(panel, 'name'),
      'a background Markdown upgrade must not rebuild the form being typed in',
    ).toBe(form);
    expect(panel.shadowRoot.activeElement).toBe(input);
  });
});
