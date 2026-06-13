import { describe, it, expect } from 'vitest';
import {
  escapeHTML,
  recurrenceSummary,
  isOverdue,
  dueLabel,
  deviceName,
} from '../src/utils.ts';

describe('escapeHTML', () => {
  it('escapes HTML-significant characters', () => {
    expect(escapeHTML('<b>"x" & \'y\'</b>')).toBe(
      '&lt;b&gt;&quot;x&quot; &amp; &#39;y&#39;&lt;/b&gt;',
    );
  });
  it('handles null/undefined', () => {
    expect(escapeHTML(null)).toBe('');
    expect(escapeHTML(undefined)).toBe('');
  });
});

describe('recurrenceSummary', () => {
  it('describes floating tasks relative to completion', () => {
    expect(
      recurrenceSummary({ recurrence_type: 'floating', interval: 1, unit: 'months' }),
    ).toBe('every month after completion');
    expect(
      recurrenceSummary({ recurrence_type: 'floating', interval: 3, unit: 'months' }),
    ).toBe('every 3 months after completion');
  });
  it('describes fixed tasks by frequency', () => {
    expect(recurrenceSummary({ recurrence_type: 'fixed', interval: 1, freq: 'DAILY' })).toBe(
      'every day',
    );
    expect(recurrenceSummary({ recurrence_type: 'fixed', interval: 2, freq: 'WEEKLY' })).toBe(
      'every 2 weeks',
    );
  });
});

describe('isOverdue', () => {
  const now = new Date('2026-06-13T12:00:00Z');
  it('is true when next_due is in the past', () => {
    expect(isOverdue({ next_due: '2026-06-01T00:00:00Z' }, now)).toBe(true);
  });
  it('is false when next_due is in the future', () => {
    expect(isOverdue({ next_due: '2026-07-01T00:00:00Z' }, now)).toBe(false);
  });
  it('is false when next_due missing', () => {
    expect(isOverdue({}, now)).toBe(false);
  });
});

describe('dueLabel', () => {
  const now = new Date('2026-06-13T12:00:00Z');
  it('renders relative day labels', () => {
    expect(dueLabel({ next_due: '2026-06-13T18:00:00Z' }, now)).toBe('today');
    expect(dueLabel({ next_due: '2026-06-14T12:00:00Z' }, now)).toBe('tomorrow');
    expect(dueLabel({ next_due: '2026-06-16T12:00:00Z' }, now)).toBe('in 3 days');
    expect(dueLabel({ next_due: '2026-06-12T12:00:00Z' }, now)).toBe('yesterday');
  });
});

describe('deviceName', () => {
  const devices = {
    abc: { id: 'abc', name: 'Fridge', name_by_user: 'Kitchen fridge' },
    def: { id: 'def', name: 'Furnace', name_by_user: null },
  };
  it('prefers name_by_user', () => {
    expect(deviceName(devices, 'abc')).toBe('Kitchen fridge');
  });
  it('falls back to name', () => {
    expect(deviceName(devices, 'def')).toBe('Furnace');
  });
  it('returns id for unknown device, empty for none', () => {
    expect(deviceName(devices, 'zzz')).toBe('zzz');
    expect(deviceName(devices, null)).toBe('');
  });
});
