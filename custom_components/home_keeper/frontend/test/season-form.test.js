import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, emitChange, makeHass, mountPanel, waitFor } from './panel-harness.js';
import { buildTaskPayload } from '../src/forms.ts';

/**
 * Editing the active season in the drawer.
 *
 * The windows are a list the user grows and shrinks, so the controls that change its
 * length (Add another season, Remove) live outside `ha-form` — which means only a test
 * that drives the real panel covers them. That is the gap issue #242's reporter fell
 * into: a task saved with two windows reopened with the second one switched on and no
 * pickers under it, and saving from that form dropped the window entirely.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
});

/** Every season window form on screen, in order. */
const windows = (panel) => [
  ...(panel.shadowRoot?.querySelectorAll('#hk-task-form ha-form[id^="hk-task-form-season-"]') ??
    []),
];

const sectionWith = (panel, name) =>
  [...(panel.shadowRoot?.querySelectorAll('#hk-task-form ha-form') ?? [])].find((f) =>
    (f.schema ?? []).some(
      (s) => s.name === name || (s.schema ?? []).some((child) => child.name === name),
    ),
  ) ?? null;

const twoWindowTask = () => ({
  id: 't1',
  name: 'Fertilize the yard',
  recurrence_type: 'floating',
  interval: 2,
  unit: 'months',
  enabled: true,
  active_season: [
    { start: '04-01', end: '05-31' },
    { start: '09-01', end: '10-31' },
  ],
});

describe('the active-season windows in the task drawer', () => {
  it('reveals a window when the season is switched on', async () => {
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();

    const cadence = await waitFor(() => sectionWith(panel, 'season_on'));
    expect(windows(panel), 'no window before the season is switched on').toHaveLength(0);

    emitChange(cadence, { season_on: true });

    const shown = await waitFor(() => (windows(panel).length ? windows(panel) : null));
    expect(shown).toHaveLength(1);
    expect(shown[0].schema.flatMap((f) => f.schema.map((s) => s.name))).toEqual([
      'season_1_start_month',
      'season_1_start_day',
      'season_1_end_month',
      'season_1_end_day',
    ]);
  });

  it('opens a stored two-window task with both windows filled in', async () => {
    // The reported bug: the second window came back switched on with its month
    // pickers gone, so the only way to correct it was to delete the task.
    const task = twoWindowTask();
    const { panel } = await mountPanel('/tasks', makeHass({ tasks: [task] }));
    panel._openEdit(task);

    const shown = await waitFor(() => (windows(panel).length ? windows(panel) : null));
    expect(shown).toHaveLength(2);
    expect(shown[1].data).toMatchObject({
      season_2_start_month: '9',
      season_2_start_day: 1,
      season_2_end_month: '10',
      season_2_end_day: 31,
    });
    // Every window is the same control repeated, so they read one set of labels.
    expect(shown[0].computeLabel({ name: 'season_1_start_month' })).toBe(
      shown[1].computeLabel({ name: 'season_2_start_month' }),
    );
  });

  it('adds a window, and saving writes every window the form showed', async () => {
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();
    const cadence = await waitFor(() => sectionWith(panel, 'season_on'));
    emitChange(cadence, { season_on: true });
    await waitFor(() => (windows(panel).length ? windows(panel) : null));

    panel.shadowRoot.querySelector('#hk-season-add').click();

    const both = await waitFor(() => {
      const w = windows(panel);
      return w.length === 2 ? w : null;
    });
    emitChange(both[1], { season_2_start_month: '11', season_2_end_month: '12' });

    const payload = buildTaskPayload({ ...panel._edit.task, name: 'Fertilize' });
    // The end day was the last of September, so it follows the month to the last of
    // December rather than staying on the 30th.
    expect(payload.active_season).toEqual([
      { start: '04-01', end: '09-30' },
      { start: '11-01', end: '12-31' },
    ]);
  });

  it('leaves a mid-month end day where the user put it when the month changes', async () => {
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();
    const cadence = await waitFor(() => sectionWith(panel, 'season_on'));
    emitChange(cadence, { season_on: true });
    const [window1] = await waitFor(() => (windows(panel).length ? windows(panel) : null));

    emitChange(window1, { season_1_end_day: 12 });
    emitChange(sectionWith(panel, 'season_1_end_month'), { season_1_end_month: '11' });

    const payload = buildTaskPayload({ ...panel._edit.task, name: 'Fertilize' });
    expect(payload.active_season).toEqual([{ start: '04-01', end: '11-12' }]);
  });

  it('removes the window it names, leaving the others where the user put them', async () => {
    const task = twoWindowTask();
    const { panel } = await mountPanel('/tasks', makeHass({ tasks: [task] }));
    panel._openEdit(task);
    await waitFor(() => (windows(panel).length === 2 ? windows(panel) : null));

    // Remove the *first* window: the survivor has to shift down into slot 1 rather
    // than the last one being dropped.
    panel.shadowRoot.querySelector('#hk-season-remove-1').click();

    const left = await waitFor(() => {
      const w = windows(panel);
      return w.length === 1 ? w : null;
    });
    expect(left[0].data).toMatchObject({
      season_1_start_month: '9',
      season_1_start_day: 1,
      season_1_end_month: '10',
      season_1_end_day: 31,
    });
    const payload = buildTaskPayload(panel._edit.task);
    expect(payload.active_season).toEqual([{ start: '09-01', end: '10-31' }]);
  });

  it('offers Remove only once there is more than one window', async () => {
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();
    const cadence = await waitFor(() => sectionWith(panel, 'season_on'));
    emitChange(cadence, { season_on: true });
    await waitFor(() => (windows(panel).length ? windows(panel) : null));
    expect(panel.shadowRoot.querySelector('#hk-season-remove-1')).toBeNull();

    panel.shadowRoot.querySelector('#hk-season-add').click();
    await waitFor(() => (windows(panel).length === 2 ? windows(panel) : null));
    expect(panel.shadowRoot.querySelector('#hk-season-remove-1')).toBeTruthy();
    expect(panel.shadowRoot.querySelector('#hk-season-remove-2')).toBeTruthy();
  });

  it('stops offering Add at the panel cap', async () => {
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();
    const cadence = await waitFor(() => sectionWith(panel, 'season_on'));
    emitChange(cadence, { season_on: true });
    await waitFor(() => (windows(panel).length ? windows(panel) : null));

    for (let i = 1; i < 6; i++) {
      panel.shadowRoot.querySelector('#hk-season-add').click();
      await waitFor(() => (windows(panel).length === i + 1 ? windows(panel) : null));
    }
    expect(windows(panel)).toHaveLength(6);
    expect(panel.shadowRoot.querySelector('#hk-season-add')).toBeNull();
  });

  it('keeps the windows out of the way of a task that has no calendar date', async () => {
    const { panel, addBtn } = await mountPanel('/tasks', makeHass());
    addBtn.click();
    const kind = await waitFor(() => sectionWith(panel, 'recurrence_type'));
    emitChange(kind, { recurrence_type: 'sensor' });

    await waitFor(() => sectionWith(panel, 'sensor_entity_id'));
    expect(sectionWith(panel, 'season_on')).toBeNull();
    expect(windows(panel)).toHaveLength(0);
  });
});
