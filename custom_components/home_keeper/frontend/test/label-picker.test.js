/**
 * The QR label picker lists the tasks that the task list shows: the status pill or
 * the active Profile, then the search box.
 */
import { describe, expect, it } from 'vitest';
import { openLabelPicker } from '../src/panel-labels.ts';

const DAY_MS = 86_400_000;
const at = (offsetDays) => new Date(Date.now() + offsetDays * DAY_MS).toISOString();

const TASKS = [
  { id: 'late', name: 'B late filter', enabled: true, next_due: at(-2), labels: ['kitchen'] },
  { id: 'later', name: 'A later filter', enabled: true, next_due: at(60), labels: [] },
  { id: 'late2', name: 'C late gutter', enabled: true, next_due: at(-1), labels: [] },
];

function host(over = {}) {
  return {
    _view: 'tasks',
    _tasks: TASKS,
    _assets: [],
    _filter: 'all',
    _query: '',
    _profile: '',
    _options: { profiles: [] },
    _hass: { devices: {}, areas: {} },
    _render() {},
    ...over,
  };
}

const picked = (p) => {
  openLabelPicker(p);
  return p._labelDialog.ids;
};

describe('openLabelPicker', () => {
  it('lists every task by name with no filter', () => {
    expect(picked(host())).toEqual(['later', 'late', 'late2']);
  });

  it('applies the status pill of the list', () => {
    expect(picked(host({ _filter: 'overdue' }))).toEqual(['late', 'late2']);
  });

  it('applies the search after the pill', () => {
    expect(picked(host({ _filter: 'overdue', _query: 'filter' }))).toEqual(['late']);
  });

  it('applies the active Profile in place of the pill', () => {
    const profile = { id: 'p1', name: 'Kitchen', filter: { status: 'all', labels: ['kitchen'] } };
    const p = host({ _filter: 'soon', _profile: 'p1', _options: { profiles: [profile] } });
    expect(picked(p)).toEqual(['late']);
  });
});
