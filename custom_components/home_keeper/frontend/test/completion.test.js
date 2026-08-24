import { describe, expect, it, vi } from 'vitest';
import * as api from '../src/api.ts';
import { buildTaskPayload, taskFormData, taskSchema } from '../src/forms.ts';

describe('task form — completion capture mode', () => {
  it('exposes the completion_detail selector for scheduled tasks', () => {
    const names = taskSchema({ recurrence_type: 'floating' }).map((f) => f.name);
    expect(names).toContain('completion_detail');
  });

  it('omits completion_detail when the field is locked', () => {
    const names = taskSchema({
      recurrence_type: 'floating',
      managed_by: {
        integration: 'x',
        display_name: 'X',
        locked_fields: ['completion_detail'],
      },
    }).map((f) => f.name);
    expect(names).not.toContain('completion_detail');
  });

  it('defaults the form value to none', () => {
    expect(taskFormData({}).completion_detail).toBe('none');
    expect(taskFormData({ completion_detail: 'required' }).completion_detail).toBe('required');
  });

  it('sends completion_detail in the payload for scheduled tasks', () => {
    const payload = buildTaskPayload({
      name: 'Filter',
      recurrence_type: 'floating',
      interval: 1,
      unit: 'months',
      completion_detail: 'optional',
    });
    expect(payload.completion_detail).toBe('optional');
  });

  it('defaults completion_detail to none in the payload', () => {
    const payload = buildTaskPayload({ name: 'X', recurrence_type: 'floating' });
    expect(payload.completion_detail).toBe('none');
  });
});

describe('api completion metadata', () => {
  const fakeHass = () => {
    const calls = [];
    return {
      calls,
      callWS: vi.fn((msg) => {
        calls.push(msg);
        return Promise.resolve({ task: { id: msg.task_id } });
      }),
    };
  };

  it('completeTask drops empty metadata keys', async () => {
    const hass = fakeHass();
    await api.completeTask(hass, 't1', { note: '', cost: 5, who: 'person.al', photo: '' });
    expect(hass.calls[0]).toEqual({
      type: 'home_keeper/complete_task',
      task_id: 't1',
      cost: 5,
      who: 'person.al',
    });
  });

  it('completeTask with no metadata sends only the task id', async () => {
    const hass = fakeHass();
    await api.completeTask(hass, 't1');
    expect(hass.calls[0]).toEqual({ type: 'home_keeper/complete_task', task_id: 't1' });
  });

  it('updateCompletion sends ts plus the filled metadata', async () => {
    const hass = fakeHass();
    await api.updateCompletion(hass, 't1', '2026-01-01T00:00:00+00:00', { note: 'fixed' });
    expect(hass.calls[0]).toEqual({
      type: 'home_keeper/update_completion',
      task_id: 't1',
      ts: '2026-01-01T00:00:00+00:00',
      note: 'fixed',
    });
  });

  it('ignores NaN cost', async () => {
    const hass = fakeHass();
    await api.completeTask(hass, 't1', { cost: Number.NaN });
    expect(hass.calls[0]).toEqual({ type: 'home_keeper/complete_task', task_id: 't1' });
  });

  it('completeTask sends completed_at when set', async () => {
    const hass = fakeHass();
    await api.completeTask(hass, 't1', { note: 'done' }, '2026-01-05T09:00:00-04:00');
    expect(hass.calls[0]).toEqual({
      type: 'home_keeper/complete_task',
      task_id: 't1',
      completed_at: '2026-01-05T09:00:00-04:00',
      note: 'done',
    });
  });

  it('completeTask omits completed_at when unset', async () => {
    const hass = fakeHass();
    await api.completeTask(hass, 't1', { note: 'done' });
    expect(hass.calls[0]).toEqual({
      type: 'home_keeper/complete_task',
      task_id: 't1',
      note: 'done',
    });
  });


  it('completeTask carries a meter reading', async () => {
    const hass = fakeHass();
    await api.completeTask(hass, 't1', { reading: 45000 });
    expect(hass.calls[0]).toEqual({
      type: 'home_keeper/complete_task',
      task_id: 't1',
      reading: 45000,
    });
  });

  it('keeps a reading of 0 rather than dropping it as falsy', async () => {
    // A brand-new hour meter reads 0. `if (metadata.reading)` would silently drop
    // it and let the backend re-read the live sensor instead — the same trap `cost`
    // already guards against with an explicit != null check.
    const hass = fakeHass();
    await api.completeTask(hass, 't1', { reading: 0 });
    expect(hass.calls[0].reading).toBe(0);
  });

  it('keeps a negative reading', async () => {
    const hass = fakeHass();
    await api.completeTask(hass, 't1', { reading: -12.5 });
    expect(hass.calls[0].reading).toBe(-12.5);
  });

  it('drops an absent or NaN reading', async () => {
    const hass = fakeHass();
    await api.completeTask(hass, 't1', { reading: undefined });
    expect(hass.calls[0]).not.toHaveProperty('reading');
    await api.completeTask(hass, 't2', { reading: Number.NaN });
    expect(hass.calls[1]).not.toHaveProperty('reading');
  });

  it('updateCompletion carries the reading through an edit', async () => {
    const hass = fakeHass();
    await api.updateCompletion(hass, 't1', '2026-01-01T00:00:00+00:00', {
      note: 'oil',
      reading: 45000,
    });
    expect(hass.calls[0]).toEqual({
      type: 'home_keeper/update_completion',
      task_id: 't1',
      ts: '2026-01-01T00:00:00+00:00',
      note: 'oil',
      reading: 45000,
    });
  });

  it('updateCompletion omitting the reading clears it server-side', async () => {
    // Documented backend behaviour, and the reason the panel's edit dialog seeds
    // `reading` from the completion: editing only a note must not wipe the meter.
    const hass = fakeHass();
    await api.updateCompletion(hass, 't1', '2026-01-01T00:00:00+00:00', { note: 'oil' });
    expect(hass.calls[0]).not.toHaveProperty('reading');
  });

  it('moveCompletion sends old_ts and new_ts', async () => {
    const hass = fakeHass();
    await api.moveCompletion(
      hass,
      't1',
      '2026-01-01T00:00:00+00:00',
      '2026-01-05T00:00:00+00:00',
    );
    expect(hass.calls[0]).toEqual({
      type: 'home_keeper/move_completion',
      task_id: 't1',
      old_ts: '2026-01-01T00:00:00+00:00',
      new_ts: '2026-01-05T00:00:00+00:00',
    });
  });
});
