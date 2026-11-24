import { describe, expect, it } from 'vitest';
import {
  assetDeleteBody,
  assetDeleteImpact,
  historyDeleteText,
  taskDeleteBody,
  taskHomeName,
} from '../src/utils.ts';
import { importTotals } from '../src/transfer-view.ts';

const UNDO = 'This cannot be undone.';

describe('historyDeleteText', () => {
  it('names the entry, the task, the detail and the person', () => {
    const out = historyDeleteText(
      'completion',
      { ts: '2026-03-01T10:00:00Z', task: 'Car oil', detail: 'at 45,000 km', who: 'Sam' },
      'en',
    );
    expect(out.title).toMatch(/^Delete the entry of .*2026.*\?$/);
    expect(out.confirmLabel).toBe('Delete entry');
    expect(out.body).toBe(`Car oil\nat 45,000 km · by Sam\n${UNDO}`);
  });

  it('leaves out what the entry does not have', () => {
    const out = historyDeleteText('skip', { ts: '2026-03-01T10:00:00Z' }, 'en');
    expect(out.title).toContain('the skip of');
    expect(out.confirmLabel).toBe('Delete skip');
    expect(out.body).toBe(UNDO);
  });
});

describe('taskDeleteBody', () => {
  it('says nothing special for a task with no history', () => {
    expect(taskDeleteBody({ completions: [] }, 'Boiler')).toBeUndefined();
    expect(taskDeleteBody({})).toBeUndefined();
  });

  it('says that the history goes with a task that no appliance owns', () => {
    expect(taskDeleteBody({ completions: [{}, {}, {}] })).toBe(
      `History entries deleted with it: 3.\n${UNDO}`,
    );
  });

  it('says that the history stays on the appliance that owns the task', () => {
    expect(taskDeleteBody({ completions: [{}] }, 'Boiler')).toBe(
      `History entries kept on Boiler: 1.\n${UNDO}`,
    );
  });
});

describe('taskHomeName', () => {
  it('is the appliance that the task belongs to, by its title', () => {
    const asset = { id: 'a1', name: 'Boiler', device_id: 'd1' };
    expect(taskHomeName({ id: 't', device_id: 'd1' }, [asset], {})).toBe('Boiler');
    expect(taskHomeName({ id: 't', device_id: 'other' }, [asset], {})).toBeUndefined();
  });
});

describe('assetDeleteImpact', () => {
  const asset = {
    id: 'a1',
    task_history: [{ completions: [{}, {}] }, { completions: [{}] }, {}],
  };
  const part = (extra = {}) => ({ source: { part: { asset_id: 'a1', part_id: 'p', ...extra } } });

  it('counts the tasks that go, the tasks that stay, and the kept history', () => {
    const tasks = [
      part(), // made from a wear part: deleted
      part({ manual: true }), // an old manual link: the backend moves it to `parts`, so nothing here
      { source: { parts: [{ asset_id: 'a1', part_id: 'p' }] } }, // consumable link: stays
      { source: { buy: { asset_id: 'a1', part_id: 'p' } } }, // auto-buy task: deleted
      { source: { part: { asset_id: 'other', part_id: 'p' } } }, // another appliance
      {}, // no source
    ];
    expect(assetDeleteImpact(asset, tasks)).toEqual({ dropped: 2, kept: 1, history: 3 });
  });

  it('counts a task with a consumable link as kept, even if it also has a wear source', () => {
    const task = {
      source: {
        part: { asset_id: 'a1', part_id: 'p' },
        parts: [{ asset_id: 'a1', part_id: 'q' }],
      },
    };
    expect(assetDeleteImpact(asset, [task])).toEqual({ dropped: 0, kept: 1, history: 3 });
  });
});

describe('assetDeleteBody', () => {
  it('lists only the lines that are true', () => {
    expect(assetDeleteBody({ id: 'a1' }, [])).toBe(
      `Its parts, documents and notes are deleted too.\n${UNDO}`,
    );
  });

  it('adds a line for each count above 0', () => {
    const asset = { id: 'a1', task_history: [{ completions: [{}] }] };
    const tasks = [
      { source: { part: { asset_id: 'a1', part_id: 'p' } } },
      { source: { parts: [{ asset_id: 'a1', part_id: 'q' }] } },
    ];
    expect(assetDeleteBody(asset, tasks).split('\n')).toEqual([
      'Its parts, documents and notes are deleted too.',
      'Tasks made from its parts, deleted: 1.',
      'Tasks kept, without the link to it: 1.',
      'History entries of removed tasks, deleted: 1.',
      UNDO,
    ]);
  });
});

describe('importTotals', () => {
  it('adds the new and the updated records of every row', () => {
    const rows = [
      { created: 2, updated: 1 },
      { created: 0, updated: 4 },
      { created: 3, updated: 0 },
    ];
    expect(importTotals(rows)).toEqual({ created: 5, updated: 5 });
    expect(importTotals([])).toEqual({ created: 0, updated: 0 });
  });
});
