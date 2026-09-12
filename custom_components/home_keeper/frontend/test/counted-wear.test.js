import { afterEach, describe, expect, it } from 'vitest';
import { statusBucket } from '../src/card-filter.ts';
import { setLanguage } from '../src/i18n.ts';
import { mergePartForm, partCountsUses, partDependentSchema, partFormData } from '../src/forms.ts';
import {
  countedProgress,
  dueLabel,
  isUseTask,
  recurrenceSummary,
  statusChipHtml,
  useCountLabel,
  useProgress,
  usesSinceReplacement,
} from '../src/utils.ts';

afterEach(() => setLanguage('en'));

const NOW = new Date('2026-06-13T10:00:00Z').getTime();

/** A counted wear item's use task, as the reconciler builds it. */
function useTask(overrides = {}) {
  return {
    id: 'use1',
    name: 'Wear rain jacket',
    recurrence_type: 'use',
    next_due: null,
    completions: [],
    source: { part: { asset_id: 'a1', part_id: 'p1', role: 'use' } },
    ...overrides,
  };
}

/** Its replacement half — no role written, which is how the reconciler stores it. */
function replaceTask(overrides = {}) {
  return {
    id: 'rep1',
    name: 'Renew DWR (Rain jacket)',
    recurrence_type: 'triggered',
    next_due: null,
    completions: [],
    source: { part: { asset_id: 'a1', part_id: 'p1' } },
    ...overrides,
  };
}

function asset(part = {}) {
  return {
    id: 'a1',
    name: 'Rain jacket',
    parts: [
      {
        id: 'p1',
        name: 'DWR',
        type: 'wear',
        replace_interval: 25,
        replace_unit: 'uses',
        use_noun: 'wears',
        ...part,
      },
    ],
  };
}

function uses(n, endingAt = NOW - 3_600_000) {
  return Array.from({ length: n }, (_, i) => ({
    ts: new Date(endingAt - (n - i) * 60_000).toISOString(),
  }));
}

describe('isUseTask', () => {
  it('reads both the recurrence type and the role', () => {
    expect(isUseTask(useTask())).toBe(true);
    expect(isUseTask(replaceTask())).toBe(false);
  });

  it('refuses a task whose type says use but whose role does not', () => {
    // Either check alone is a worse test: a malformed source would otherwise turn an
    // ordinary replacement task into a silent no-op on stock.
    expect(isUseTask(useTask({ source: { part: { asset_id: 'a1', part_id: 'p1' } } }))).toBe(false);
    expect(isUseTask({ recurrence_type: 'use' })).toBe(false);
  });

  it('refuses a floating task carrying a use role', () => {
    expect(isUseTask(useTask({ recurrence_type: 'floating' }))).toBe(false);
  });
});

describe('statusBucket', () => {
  it('puts a use task in its own Counted section', () => {
    expect(statusBucket(useTask(), NOW)).toBe('counted');
  });

  it('reaches the check at all, despite having no due date', () => {
    // The regression this pins: `if (!task.next_due) return 'none'` sits above the
    // `shopping` line, so a bucket placed beside `shopping` would never be reached by
    // a task that is dateless for its whole life.
    expect(statusBucket(useTask(), NOW)).not.toBe('none');
  });

  it('stays Counted after a completion rather than reading as Completed', () => {
    const task = useTask({ completions: uses(3), last_completed: new Date(NOW).toISOString() });
    expect(statusBucket(task, NOW, { completed: true })).toBe('counted');
  });

  it('leaves the dormant replacement task Monitored', () => {
    expect(statusBucket(replaceTask(), NOW)).toBe('monitored');
  });

  it('puts the armed replacement task in Overdue like any other armed task', () => {
    const armed = replaceTask({ next_due: new Date(NOW - 1000).toISOString() });
    expect(statusBucket(armed, NOW)).toBe('overdue');
  });
});

describe('usesSinceReplacement', () => {
  it('counts everything before the first replacement', () => {
    expect(usesSinceReplacement(useTask({ completions: uses(7) }), replaceTask())).toBe(7);
  });

  it('restarts after a replacement', () => {
    const replacedAt = new Date(NOW - 5 * 86_400_000);
    const task = useTask({
      completions: [...uses(5, NOW - 10 * 86_400_000), ...uses(3, NOW - 86_400_000)],
    });
    const replaced = replaceTask({ last_completed: replacedAt.toISOString() });
    expect(usesSinceReplacement(task, replaced)).toBe(3);
  });

  it('agrees with the backend on a completion exactly at the replacement', () => {
    const when = new Date(NOW - 86_400_000).toISOString();
    const task = useTask({ completions: [{ ts: when }] });
    expect(usesSinceReplacement(task, replaceTask({ last_completed: when }))).toBe(0);
  });

  it('counts an unparseable entry rather than dropping the whole log', () => {
    const task = useTask({ completions: [{ ts: 'not-a-date' }, ...uses(2)] });
    expect(usesSinceReplacement(task, replaceTask())).toBe(3);
  });

  it('counts everything when there is no replacement task at all', () => {
    expect(usesSinceReplacement(useTask({ completions: uses(4) }), undefined)).toBe(4);
  });
});

describe('countedProgress', () => {
  it('walks from the use task to its part and its sibling', () => {
    const task = useTask({ completions: uses(17) });
    expect(countedProgress(task, [asset()], [task, replaceTask()])).toEqual({
      count: 17,
      target: 25,
      noun: 'wears',
    });
  });

  it('is null for a task that is not a use task', () => {
    expect(countedProgress(replaceTask(), [asset()], [])).toBeNull();
  });

  it('is null rather than zeroed when the part is gone', () => {
    // A zeroed shape would render "0 of 0"; null lets the caller fall back.
    expect(countedProgress(useTask(), [], [])).toBeNull();
  });

  it('is null when the part carries no target', () => {
    expect(countedProgress(useTask(), [asset({ replace_interval: null })], [])).toBeNull();
  });

  it('finds a sibling whose role is absent, which is how it is stored', () => {
    const task = useTask({ completions: uses(4) });
    const sibling = replaceTask({ last_completed: new Date(NOW - 60_000).toISOString() });
    expect(countedProgress(task, [asset()], [task, sibling]).count).toBe(0);
  });

  it('never mistakes the use task for its own sibling', () => {
    const task = useTask({ completions: uses(4), last_completed: new Date(NOW).toISOString() });
    expect(countedProgress(task, [asset()], [task]).count).toBe(4);
  });
});

describe('useCountLabel', () => {
  it('renders the part own plural noun verbatim', () => {
    expect(useCountLabel(17, 25, 'wears')).toBe('17 of 25 wears');
  });

  it('renders an irregular plural exactly as it was typed', () => {
    // Appending an "s" would give "loafs". The form asks for the plural precisely so
    // the panel never has to guess.
    expect(useCountLabel(3, 12, 'loaves')).toBe('3 of 12 loaves');
  });

  it('falls back to a localized plural when the part names no noun', () => {
    expect(useCountLabel(17, 25, '')).toBe('17 of 25 uses');
    expect(useCountLabel(1, 1, '')).toBe('1 of 1 use');
  });

  it('does not clamp a count past its target', () => {
    // The reminder is already in Overdue; freezing the number at 25 would hide how
    // far past it the household is.
    expect(useCountLabel(31, 25, 'wears')).toBe('31 of 25 wears');
  });
});

describe('useProgress', () => {
  it('is a plain fraction below the target', () => {
    expect(useProgress(5, 20)).toBe(0.25);
  });

  it('clamps the bar at full even though the label is not clamped', () => {
    expect(useProgress(31, 25)).toBe(1);
  });

  it('is zero for a target of zero rather than dividing by it', () => {
    expect(useProgress(3, 0)).toBe(0);
  });
});

describe('statusChipHtml', () => {
  it('draws the count when the caller supplies it', () => {
    const html = statusChipHtml(useTask(), undefined, {
      counted: { count: 17, target: 25, noun: 'wears' },
    });
    expect(html).toContain('17 of 25 wears');
    expect(html).toContain('hk-counted');
    expect(html).not.toContain('hk-counted-full');
  });

  it('goes full at the target, where the replacement task actually arms', () => {
    const html = statusChipHtml(useTask(), undefined, {
      counted: { count: 25, target: 25, noun: 'wears' },
    });
    expect(html).toContain('hk-counted-full');
  });

  it('falls back to Counting rather than inventing a figure', () => {
    expect(statusChipHtml(useTask(), undefined, {})).toContain('Counting');
  });
});

describe('recurrenceSummary', () => {
  it('describes a use task as counting, not as a schedule', () => {
    expect(recurrenceSummary(useTask())).toBe('Counts uses');
  });

  it('leaves the replacement half described as monitored', () => {
    expect(recurrenceSummary(replaceTask())).toBe('Monitored');
  });
});

describe('dueLabel', () => {
  it('reads Counting for a use task, not "no due date"', () => {
    // "-" is true and completely wrong to read: it suggests something unscheduled
    // that ought to be scheduled.
    expect(dueLabel(useTask(), new Date(NOW))).toBe('Counting');
  });
});

describe('useCountLabel — the noun', () => {
  it('falls back on a blank noun, not just an absent one', () => {
    expect(useCountLabel(3, 25, '   ')).toBe('3 of 25 uses');
  });

  it('picks the plural category from the target, not the count', () => {
    // `tn` is keyed on the target: "1 of 1 use", never "1 of 1 uses".
    expect(useCountLabel(0, 1, '')).toBe('0 of 1 use');
    expect(useCountLabel(1, 2, '')).toBe('1 of 2 uses');
  });

  it('trims a noun that was typed with spaces', () => {
    expect(useCountLabel(3, 25, '  wears  ')).toBe('3 of 25 wears');
  });
});

describe('usesSinceReplacement — the guards', () => {
  it('counts everything when the replacement task has no completion field', () => {
    expect(usesSinceReplacement(useTask({ completions: uses(3) }), {})).toBe(3);
  });

  it('counts everything when last_completed is unparseable', () => {
    const replaced = replaceTask({ last_completed: 'not-a-date' });
    expect(usesSinceReplacement(useTask({ completions: uses(3) }), replaced)).toBe(3);
  });

  it('treats an absent completions list as zero', () => {
    expect(usesSinceReplacement(useTask({ completions: undefined }), replaceTask())).toBe(0);
  });

  it('counts nothing when every use predates the replacement', () => {
    const replaced = replaceTask({ last_completed: new Date(NOW).toISOString() });
    const task = useTask({ completions: uses(4, NOW - 86_400_000) });
    expect(usesSinceReplacement(task, replaced)).toBe(0);
  });
});

describe('countedProgress — the guards', () => {
  it('is null when the task carries no part source', () => {
    expect(countedProgress(useTask({ source: undefined }), [asset()], [])).toBeNull();
  });

  it('is null when the assets list is absent', () => {
    expect(countedProgress(useTask(), undefined, [])).toBeNull();
  });

  it('is null when the asset holds no parts', () => {
    expect(countedProgress(useTask(), [{ id: 'a1', name: 'x' }], [])).toBeNull();
  });

  it('is null for a target of zero rather than dividing by it', () => {
    expect(countedProgress(useTask(), [asset({ replace_interval: 0 })], [])).toBeNull();
  });

  it('is null for a negative target', () => {
    expect(countedProgress(useTask(), [asset({ replace_interval: -5 })], [])).toBeNull();
  });

  it('is null when the target is not a number', () => {
    expect(countedProgress(useTask(), [asset({ replace_interval: '25' })], [])).toBeNull();
  });

  it('does not match a part on another appliance with the same part id', () => {
    const other = { ...asset(), id: 'a2' };
    expect(countedProgress(useTask(), [other], [])).toBeNull();
  });

  it('reports an empty noun when the part names none', () => {
    const task = useTask({ completions: uses(2) });
    expect(countedProgress(task, [asset({ use_noun: undefined })], [task])).toEqual({
      count: 2,
      target: 25,
      noun: '',
    });
  });
});

describe('partCountsUses', () => {
  it('is true only for a wear part measured in uses', () => {
    expect(partCountsUses({ type: 'wear', replace_unit: 'uses' })).toBe(true);
    expect(partCountsUses({ type: 'wear', replace_unit: 'months' })).toBe(false);
    expect(partCountsUses({ type: 'consumable', replace_unit: 'uses' })).toBe(false);
  });
});

describe('mergePartForm', () => {
  const counted = {
    id: 'p1',
    name: 'DWR',
    type: 'wear',
    replace_interval: 25,
    replace_unit: 'uses',
    use_noun: 'wears',
    use_task_name: 'Wear rain jacket',
    replace_also_every: { interval: 12, unit: 'months' },
  };

  it('turns the backstop on with its defaults', () => {
    const next = mergePartForm({ ...counted, replace_also_every: null }, { also_every_on: true });
    expect(next.replace_also_every).toEqual({ interval: 1, unit: 'months' });
  });

  it('turns the backstop off without losing the rest', () => {
    const next = mergePartForm(counted, { also_every_on: false });
    expect(next.replace_also_every).toBeNull();
    expect(next.use_noun).toBe('wears');
  });

  it('edits the backstop interval in place', () => {
    const next = mergePartForm(counted, { also_every_interval: 6, also_every_unit: 'weeks' });
    expect(next.replace_also_every).toEqual({ interval: 6, unit: 'weeks' });
  });

  it('clears the counting fields when the unit goes back to time', () => {
    const next = mergePartForm(counted, { replace_unit: 'months' });
    expect(next.use_noun).toBe('');
    expect(next.use_task_name).toBe('');
    expect(next.replace_also_every).toBeNull();
  });

  it('introduces no counting keys on a part that never had them', () => {
    // A merge whose contract is "one form, its own fields" must not grow a part it
    // was not asked to touch.
    const plain = { id: 'p2', name: 'Filter', type: 'consumable' };
    const next = mergePartForm(plain, { part_name: 'Filter cartridge' });
    expect('use_noun' in next).toBe(false);
    expect('replace_also_every' in next).toBe(false);
    expect('action' in next).toBe(false);
  });

  it('caps a counted target at the ceiling the backend enforces', () => {
    expect(mergePartForm(counted, { replace_interval: 900 }).replace_interval).toBe(250);
  });

  it('leaves a time-measured interval uncapped', () => {
    const timed = { ...counted, replace_unit: 'months' };
    expect(mergePartForm(timed, { replace_interval: 900 }).replace_interval).toBe(900);
  });

  it('keeps a chosen unit on a wear item that has no interval yet', () => {
    // The reveal reads the unit, so clearing it here made picking "uses" before
    // typing a target a dead control: the counting fields never appeared.
    const fresh = { id: 'p3', name: 'Coating', type: 'wear' };
    const next = mergePartForm(fresh, { replace_unit: 'uses' });
    expect(next.replace_unit).toBe('uses');
    expect(partCountsUses(next)).toBe(true);
  });

  it('still drops the unit when the part stops being a wear item', () => {
    const next = mergePartForm({ ...counted }, { type: 'consumable' });
    expect(next.replace_unit).toBeNull();
    expect(next.replace_interval).toBeNull();
  });

  it('keeps the action', () => {
    expect(mergePartForm(counted, { action: 'renew' }).action).toBe('renew');
  });

  it('resets the action when the part stops being a wear item', () => {
    const next = mergePartForm({ ...counted, action: 'renew' }, { type: 'consumable' });
    expect(next.action).toBe('replace');
  });

  it('defaults an emptied action back to replace rather than clearing it', () => {
    expect(mergePartForm(counted, { action: '' }).action).toBe('replace');
  });

  it('trims a use noun and a use task name', () => {
    const next = mergePartForm(counted, {
      use_noun: '  hikes  ',
      use_task_name: '  Hike in them  ',
    });
    expect(next.use_noun).toBe('hikes');
    expect(next.use_task_name).toBe('Hike in them');
  });

  it('reads the backstop switch from the stored object when only a field is sent', () => {
    // The 2 interval fields can arrive without the switch (they are in their own
    // grid), so the switch state falls back to whether the object is already there.
    const next = mergePartForm(counted, { also_every_interval: 3 });
    expect(next.replace_also_every).toEqual({ interval: 3, unit: 'months' });
    const off = mergePartForm(
      { ...counted, replace_also_every: null },
      { also_every_interval: 3 },
    );
    expect(off.replace_also_every).toBeNull();
  });

  it('caps the target at the ceiling only for a counted part', () => {
    expect(mergePartForm(counted, { replace_interval: 250 }).replace_interval).toBe(250);
    expect(mergePartForm(counted, { replace_interval: 251 }).replace_interval).toBe(250);
  });

  it('leaves a null target alone rather than capping it', () => {
    expect(mergePartForm(counted, { replace_interval: '' }).replace_interval).toBeNull();
  });
});

describe('partDependentSchema — the counting fields', () => {
  const wear = (extra) => ({ id: 'p1', name: 'DWR', type: 'wear', ...extra });
  const names = (fields) =>
    fields.flatMap((f) => (f.type === 'grid' ? f.schema.map((x) => x.name) : [f.name]));

  it('offers the action for every wear item, counted or not', () => {
    expect(names(partDependentSchema(wear({ replace_unit: 'months' })))).toContain('action');
    expect(names(partDependentSchema(wear({ replace_unit: 'uses' })))).toContain('action');
  });

  it('offers no action for a consumable', () => {
    expect(names(partDependentSchema({ id: 'p2', name: 'F', type: 'consumable' }))).not.toContain(
      'action',
    );
  });

  it('pairs the noun and the task name in one grid', () => {
    const fields = partDependentSchema(wear({ replace_unit: 'uses' }));
    const grid = fields.find(
      (f) => f.type === 'grid' && f.schema.some((x) => x.name === 'use_noun'),
    );
    expect(grid.schema.map((x) => x.name)).toEqual(['use_noun', 'use_task_name']);
  });

  it('pairs the backstop interval and unit in one grid, only when it is on', () => {
    const off = partDependentSchema(wear({ replace_unit: 'uses' }));
    expect(names(off)).not.toContain('also_every_interval');
    const on = partDependentSchema(
      wear({ replace_unit: 'uses', replace_also_every: { interval: 12, unit: 'months' } }),
    );
    const grid = on.find(
      (f) => f.type === 'grid' && f.schema.some((x) => x.name === 'also_every_interval'),
    );
    expect(grid.schema.map((x) => x.name)).toEqual(['also_every_interval', 'also_every_unit']);
  });
});

describe('partFormData — the counting seeds', () => {
  it('seeds the backstop switch off and its fields defaulted when there is none', () => {
    const data = partFormData({ name: 'DWR', type: 'wear', replace_unit: 'uses' });
    expect(data.also_every_on).toBe(false);
    expect(data.also_every_interval).toBe(1);
    expect(data.also_every_unit).toBe('months');
  });

  it('seeds the action from the part, defaulting to replace', () => {
    expect(partFormData({ name: 'x', type: 'wear' }).action).toBe('replace');
    expect(partFormData({ name: 'x', type: 'wear', action: 'sharpen' }).action).toBe('sharpen');
  });
});
