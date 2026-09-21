import { afterEach, describe, expect, it } from 'vitest';
import { partFirstDue, partPreview, partTaskName, partUseTaskName } from '../src/forms.ts';
import { setLanguage } from '../src/i18n.ts';

afterEach(() => setLanguage('en'));

/** A wear part, as `partFormData`/`mergePartForm` leave one. */
function wear(overrides = {}) {
  return {
    id: 'p1',
    name: 'HEPA filter',
    type: 'wear',
    replace_interval: 6,
    replace_unit: 'months',
    action: 'replace',
    ...overrides,
  };
}

/** The lines as plain text, which is what a reader sees. */
const texts = (part, asset = 'Air purifier') =>
  partPreview(part, asset).lines.map((l) => l.text);
const kinds = (part, asset = 'Air purifier') =>
  partPreview(part, asset).lines.map((l) => l.kind);

describe('partPreview — a part that creates nothing', () => {
  it('says nothing at all for a consumable', () => {
    // The box belongs to the wear half of the editor. A consumable generates no
    // task, so an empty `lines` is what hides the box.
    const preview = partPreview({ id: 'p1', name: 'Bulb', type: 'consumable' }, 'Lamp');
    expect(preview.lines).toEqual([]);
    expect(preview.detail).toEqual([]);
  });

  it('says nothing for a consumable that tracks stock', () => {
    // Stock alone must not summon the box: the detail block elaborates a task, and
    // a consumable has none.
    const preview = partPreview(
      { id: 'p1', name: 'Bulb', type: 'consumable', stock: 4, reorder_at: 1 },
      'Lamp',
    );
    expect(preview.lines).toEqual([]);
    expect(preview.detail).toEqual([]);
  });

  it('asks for an interval when the wear item has none', () => {
    expect(texts(wear({ replace_interval: null }))).toEqual([
      'Set an interval to create a task.',
    ]);
  });

  it('marks the no-interval line as a fact, not as a task name', () => {
    // Nothing is created yet, so nothing may render in the bold task weight.
    expect(kinds(wear({ replace_interval: null }))).toEqual(['fact']);
  });

  it('asks for an interval when the interval is zero', () => {
    // `reconcile.py` gates on a truthy `replace_interval`, so 0 creates no task
    // either. The preview has to agree with the gate, not with the field.
    expect(texts(wear({ replace_interval: 0 }))).toEqual([
      'Set an interval to create a task.',
    ]);
  });
});

describe('partPreview — a time-measured wear item', () => {
  it('names the task and its schedule', () => {
    expect(texts(wear())).toEqual([
      'Replace HEPA filter (Air purifier)',
      'Due every 6 months.',
    ]);
  });

  it('marks the name as a task line and the schedule as a fact', () => {
    expect(kinds(wear())).toEqual(['task', 'fact']);
  });

  it('takes the name from the action', () => {
    expect(texts(wear({ action: 'clean' }))[0]).toBe('Clean HEPA filter (Air purifier)');
    expect(texts(wear({ action: 'sharpen' }))[0]).toBe('Sharpen HEPA filter (Air purifier)');
  });

  it('falls back to replace for a part with no action', () => {
    // Every wear part written before actions existed carries no action at all.
    expect(texts(wear({ action: null }))[0]).toBe('Replace HEPA filter (Air purifier)');
  });

  it('adds the first due date once the part has a last-replaced date', () => {
    expect(texts(wear({ last_replaced: '2026-03-03' }))).toEqual([
      'Replace HEPA filter (Air purifier)',
      'Due every 6 months.',
      // `formatDate` is the panel's one date format, so the preview reads the same
      // way as every other date in it.
      'First one due Sep 3, 2026.',
    ]);
  });

  it('treats an absent part name as an empty one', () => {
    // `partFormData` seeds '' but a part straight from storage can omit the key.
    expect(texts(wear({ name: undefined }))[0]).toBe('Replace  (Air purifier)');
  });

  it('marks the first-due line as a fact', () => {
    expect(kinds(wear({ last_replaced: '2026-03-03' }))).toEqual(['task', 'fact', 'fact']);
  });

  it('reads a last-replaced date that carries spaces', () => {
    // The field is a date picker, but an imported document is free text.
    expect(texts(wear({ last_replaced: '  2026-03-03  ' }))).toContain(
      'First one due Sep 3, 2026.',
    );
  });

  it('uses the localized appliance fallback for an unnamed appliance', () => {
    // `reconcile.py` substitutes the same word, so the preview names the task the
    // backend will really create.
    expect(texts(wear(), '')[0]).toBe('Replace HEPA filter (Appliance)');
    expect(texts(wear(), '   ')[0]).toBe('Replace HEPA filter (Appliance)');
  });

  it('never says the count reads anything', () => {
    // The box previews what a part creates, and a part that is already counting
    // reads "17 of 25". A hardcoded "0 of 25" line stated a falsehood on every part
    // that had been used, which the capture of the seeded rain jacket showed
    // plainly. The noun the line carried is already in the due line.
    expect(texts(wear()).join(' ')).not.toContain('Count reads');
    const counted = texts(
      wear({ replace_interval: 20, replace_unit: 'uses', use_noun: 'wears' }),
      'Rain jacket',
    );
    expect(counted.join(' ')).not.toContain('Count reads');
    expect(counted.join(' ')).not.toContain('0 of 20');
  });
});

describe('partPreview — a counted wear item', () => {
  const counted = (overrides = {}) =>
    wear({
      name: 'Waterproof coating',
      replace_interval: 20,
      replace_unit: 'uses',
      action: 'renew',
      use_noun: 'wears',
      use_task_name: 'Wear rain jacket',
      ...overrides,
    });

  it('names both tasks, in the order the household meets them', () => {
    expect(texts(counted(), 'Rain jacket')).toEqual([
      'Wear rain jacket',
      'Each completion adds 1 to the count.',
      'Renew Waterproof coating (Rain jacket)',
      'Due after 20 wears.',
    ]);
  });

  it('marks each generated name as a task line', () => {
    expect(kinds(counted(), 'Rain jacket')).toEqual(['task', 'fact', 'task', 'fact']);
  });

  it('falls back to the localized use task name', () => {
    expect(texts(counted({ use_task_name: '' }), 'Rain jacket')[0]).toBe('Use Rain jacket');
    expect(texts(counted({ use_task_name: null }), 'Rain jacket')[0]).toBe('Use Rain jacket');
  });

  it('trims a use task name that is only spaces', () => {
    expect(texts(counted({ use_task_name: '   ' }), 'Rain jacket')[0]).toBe('Use Rain jacket');
  });

  it('falls back to the localized plural for a part with no noun', () => {
    const lines = texts(counted({ use_noun: '' }), 'Rain jacket');
    expect(lines).toContain('Due after 20 uses.');
  });

  it('uses the singular noun for a target of one', () => {
    const lines = texts(counted({ use_noun: '', replace_interval: 1 }), 'Rain jacket');
    expect(lines).toContain('Due after 1 use.');
  });

  it('names the backstop and which half wins', () => {
    const lines = texts(
      counted({ replace_also_every: { interval: 12, unit: 'months' } }),
      'Rain jacket',
    );
    expect(lines).toContain('Due after 20 wears, or after 12 months.');
    expect(lines).toContain('The earlier one wins.');
  });

  it('marks both backstop lines as facts', () => {
    // Neither is a task name, so neither may render in the bold task weight.
    expect(
      kinds(counted({ replace_also_every: { interval: 12, unit: 'months' } }), 'Rain jacket'),
    ).toEqual(['task', 'fact', 'task', 'fact', 'fact']);
  });

  it('falls back to the localized plural when the noun key is absent', () => {
    // `partFormData` seeds '', but a part straight from storage can omit the key
    // entirely, and the fallback has to survive an undefined as well as an empty
    // string.
    expect(texts(counted({ use_noun: undefined }), 'Rain jacket')).toContain(
      'Due after 20 uses.',
    );
  });

  it('trims a noun that carries spaces', () => {
    // Stored verbatim from a text box, so it arrives however it was typed.
    expect(texts(counted({ use_noun: '  wears  ' }), 'Rain jacket')).toContain(
      'Due after 20 wears.',
    );
  });

  it('falls back to the appliance name fallback in the use task too', () => {
    expect(texts(counted({ use_task_name: '' }), '')[0]).toBe('Use Appliance');
    expect(texts(counted({ use_task_name: '' }), '   ')[0]).toBe('Use Appliance');
  });

  it('says nothing about a backstop when the part has none', () => {
    expect(texts(counted(), 'Rain jacket').join(' ')).not.toContain('or after');
  });

  it('never dates the first one, because the count arms it', () => {
    // A counted part's replacement task is `triggered`: the count arms it, so a
    // last-replaced date gives it no due date at all.
    const lines = texts(counted({ last_replaced: '2026-03-03' }), 'Rain jacket');
    expect(lines.join(' ')).not.toContain('First one due');
  });
});

describe('partPreview — the stock block', () => {
  it('stays empty for a part that tracks no stock', () => {
    expect(partPreview(wear(), 'Air purifier').detail).toEqual([]);
  });

  it('says what one completion takes', () => {
    expect(partPreview(wear({ stock: 2 }), 'Air purifier').detail).toEqual([
      'Takes 1 from stock.',
    ]);
  });

  it('uses the part per-completion amount and its unit', () => {
    expect(
      partPreview(wear({ stock: 500, consume_quantity: 30, stock_unit: 'ml' }), 'Air purifier')
        .detail,
    ).toEqual(['Takes 30 ml from stock.']);
  });

  it('adds the buy reminder only when auto-buy is on', () => {
    const off = partPreview(wear({ stock: 2, reorder_at: 1 }), 'Air purifier').detail;
    expect(off).toEqual(['Takes 1 from stock.']);
    const on = partPreview(
      wear({ stock: 2, reorder_at: 1, create_buy_task: true }),
      'Air purifier',
    ).detail;
    expect(on).toEqual(['Takes 1 from stock.', 'Buy reminder at 1.']);
  });

  it('does not offer a buy reminder with no reorder point', () => {
    // Auto-buy without a threshold has nothing to fire on, and the form hides the
    // switch in that state.
    expect(
      partPreview(wear({ stock: 2, create_buy_task: true }), 'Air purifier').detail,
    ).toEqual(['Takes 1 from stock.']);
  });
});

describe('partTaskName and partUseTaskName', () => {
  it('uses the part name exactly as stored', () => {
    // `reconcile.py` does no tidying either, so a part with no name really does
    // generate a name with a gap in it. Inventing a placeholder here would preview
    // a name the task will not have.
    expect(partTaskName(wear({ name: '' }), 'Air purifier')).toBe('Replace  (Air purifier)');
  });

  it('never names the part in the use task', () => {
    // The household taps this to record using the appliance, not the component.
    expect(partUseTaskName(wear({ use_task_name: '' }), 'Rain jacket')).toBe('Use Rain jacket');
  });
});

describe('partFirstDue', () => {
  it('adds months', () => {
    expect(partFirstDue(wear({ last_replaced: '2026-03-03' }))).toEqual(
      new Date('2026-09-03T00:00:00'),
    );
  });

  it('clamps a day the target month does not have', () => {
    // Jan 31 plus 1 month is Feb 28, which is what `recurrence.add_months` does. A
    // naive `setMonth` rolls forward to Mar 3 instead.
    expect(
      partFirstDue(wear({ replace_interval: 1, last_replaced: '2026-01-31' })),
    ).toEqual(new Date('2026-02-28T00:00:00'));
  });

  it('adds days and weeks', () => {
    expect(
      partFirstDue(wear({ replace_interval: 10, replace_unit: 'days', last_replaced: '2026-03-03' })),
    ).toEqual(new Date('2026-03-13T00:00:00'));
    expect(
      partFirstDue(wear({ replace_interval: 2, replace_unit: 'weeks', last_replaced: '2026-03-03' })),
    ).toEqual(new Date('2026-03-17T00:00:00'));
  });

  it('returns null without a last-replaced date', () => {
    expect(partFirstDue(wear())).toBeNull();
    expect(partFirstDue(wear({ last_replaced: '' }))).toBeNull();
    expect(partFirstDue(wear({ last_replaced: '   ' }))).toBeNull();
  });

  it('returns null for a counted part', () => {
    expect(
      partFirstDue(wear({ replace_unit: 'uses', last_replaced: '2026-03-03' })),
    ).toBeNull();
  });

  it('returns null without an interval', () => {
    expect(partFirstDue(wear({ replace_interval: null, last_replaced: '2026-03-03' }))).toBeNull();
  });

  it('returns null for a date it cannot read', () => {
    expect(partFirstDue(wear({ last_replaced: 'not a date' }))).toBeNull();
  });
});

describe('partPreview — other languages', () => {
  it('names the task in the viewer language', () => {
    setLanguage('de');
    expect(texts(wear())).toEqual([
      'HEPA filter ersetzen (Air purifier)',
      'Fällig alle 6 Monate.',
    ]);
  });

  it('keeps the count noun verbatim, because it is the household word', () => {
    setLanguage('de');
    const lines = texts(
      wear({ replace_interval: 20, replace_unit: 'uses', use_noun: 'wears' }),
      'Rain jacket',
    );
    expect(lines).toContain('Fällig nach 20 wears.');
  });
});
