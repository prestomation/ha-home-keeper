/**
 * The deferral rules the panel and the card now share.
 *
 * `deferVerbs` is the gate every surface asks before drawing a caret, and
 * `snoozeTarget` is what turns a preset or a typed date into the instant the service
 * is actually called with — so both decide user-visible behaviour rather than
 * arranging pixels, and both are on the mutation surface.
 */

import { describe, expect, it } from 'vitest';
import {
  deferMenuItems,
  deferRowActions,
  deferSplit,
  deferVerbs,
  emptySkipState,
  emptySnoozeState,
  snoozeHintText,
  snoozeTarget,
} from '../src/defer.ts';
import { t } from '../src/i18n.ts';

const task = (over = {}) => ({
  id: 't1',
  name: 'Replace filter',
  next_due: '2026-09-30T09:00:00-04:00',
  ...over,
});

describe('deferVerbs', () => {
  it('offers both verbs when nothing is configured', () => {
    // The switches default *on*, so an install that predates them — every existing
    // one — must read as "offer both" rather than as "both off".
    expect(deferVerbs(task(), {})).toEqual({ snooze: true, skip: true });
  });

  it('withdraws each verb independently when its switch is off', () => {
    expect(deferVerbs(task(), { allow_snooze: false })).toEqual({
      snooze: false,
      skip: true,
    });
    expect(deferVerbs(task(), { allow_skip: false })).toEqual({
      snooze: true,
      skip: false,
    });
  });

  it('offers neither verb on a dormant task', () => {
    // No due date is nothing to defer: snooze raises in the store and skip has no
    // occurrence to move past.
    expect(deferVerbs(task({ next_due: null }), {})).toEqual({
      snooze: false,
      skip: false,
    });
  });

  it('offers snooze but not skip on a completion-blocked task', () => {
    // The store rejects skipping a synced problem task, but a notification walk
    // still has to be able to get past it — so snooze deliberately survives.
    const blocked = task({ managed_by: { completion_blocked: true } });
    expect(deferVerbs(blocked, {})).toEqual({ snooze: true, skip: false });
  });
});

describe('deferSplit', () => {
  it('returns Done untouched when no verb is on offer', () => {
    const done = '<ha-button class="done-btn">Done</ha-button>';
    expect(deferSplit(task(), done, { snooze: false, skip: false })).toBe(done);
  });

  it('returns nothing at all when there is no Done to wrap', () => {
    // A task with no Done button has no split to hang a caret off.
    expect(deferSplit(task(), '', { snooze: true, skip: true })).toBe('');
  });

  it('wraps Done and carries only the verbs on offer', () => {
    const html = deferSplit(task(), '<b>Done</b>', { snooze: true, skip: false });
    expect(html).toContain('class="hk-split"');
    expect(html).toContain('<b>Done</b>');
    expect(html).toContain('hk-defer-snooze');
    expect(html).not.toContain('hk-defer-skip');
  });

  it('takes the caret class the host asks for', () => {
    const html = deferSplit(task(), '<b>Done</b>', { snooze: true, skip: true }, 'row-caret');
    expect(html).toContain('class="row-caret"');
  });

  it('escapes the task id it puts in the dataset', () => {
    const html = deferSplit(
      task({ id: 'a"><script>x</script>' }),
      '<b>Done</b>',
      { snooze: true, skip: true },
    );
    expect(html).not.toContain('<script>');
    expect(html).toContain('&quot;');
  });
});

describe('snoozeTarget', () => {
  const from = new Date('2026-03-10T09:00:00Z');

  it('resolves a preset relative to the given instant', () => {
    const until = snoozeTarget({ open: true, task: task(), preset: '1d' }, from);
    expect(until?.toISOString()).toBe('2026-03-11T09:00:00.000Z');
  });

  it('returns null for a custom snooze with no date typed yet', () => {
    // The dialog's primary button leans on this: no target, no call.
    expect(snoozeTarget({ open: true, task: task(), preset: 'custom' }, from)).toBeNull();
  });

  it('returns null for a custom date that will not parse', () => {
    const s = { open: true, task: task(), preset: 'custom', customAt: 'not a date' };
    expect(snoozeTarget(s, from)).toBeNull();
  });

  it('uses the typed date when the custom preset has one', () => {
    const s = { open: true, task: task(), preset: 'custom', customAt: '2026-04-01 08:30:00' };
    const until = snoozeTarget(s, from);
    expect(until).not.toBeNull();
    expect(until.getFullYear()).toBe(2026);
    expect(until.getMonth()).toBe(3);
    expect(until.getDate()).toBe(1);
  });
});

describe('deferMenuItems', () => {
  it('labels each entry and says what it does to the schedule', () => {
    // The verbs are not self-explanatory — the whole of #268 — so the sub-line is
    // load-bearing rather than decoration, and both come from the string table.
    const html = deferMenuItems({ snooze: true, skip: true });
    expect(html).toContain(t('btn.snooze'));
    expect(html).toContain(t('defer.snoozeHint'));
    expect(html).toContain(t('btn.skip'));
    expect(html).toContain(t('defer.skipHint'));
  });

  it('marks each entry as a menu item', () => {
    expect(deferMenuItems({ snooze: true, skip: true })).toContain('role="menuitem"');
  });

  it('is empty when neither verb is on offer', () => {
    expect(deferMenuItems({ snooze: false, skip: false })).toBe('');
  });
});

describe('deferSplit chrome', () => {
  it('marks the caret as a closed menu button and names it', () => {
    // aria-expanded is what the controller flips, and what the e2e specs read.
    const html = deferSplit(task(), '<b>Done</b>', { snooze: true, skip: true });
    expect(html).toContain('aria-haspopup="menu"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain(`aria-label="${t('defer.more')}"`);
  });

  it('renders the menu hidden, so it is closed until the caret opens it', () => {
    const html = deferSplit(task(), '<b>Done</b>', { snooze: true, skip: true });
    expect(html).toMatch(/<div class="hk-defer-menu" role="menu" hidden>/);
  });
});

describe('empty state factories', () => {
  it('start closed, with no task, on the default preset', () => {
    const s = emptySnoozeState();
    expect(s.open).toBe(false);
    expect(s.task).toBeNull();
    // A fresh dialog must offer a usable default rather than an empty picker.
    expect(snoozeTarget(s)).not.toBeNull();
  });

  it('hand back a fresh object each time, not a shared one', () => {
    // These seed live dialog state; a shared object would leak one task's typed
    // note into the next task's dialog.
    const a = emptySkipState();
    a.data.note = 'typed';
    expect(emptySkipState().data.note).toBeUndefined();
  });
});

describe('snoozeHintText', () => {
  it('prompts for a date when the custom preset has none', () => {
    const s = { open: true, task: task(), preset: 'custom' };
    expect(snoozeHintText(s, 'en')).toBe(t('defer.snoozePickDate'));
  });

  it('states the resolved date once there is one', () => {
    const s = { open: true, task: task(), preset: '1d' };
    const text = snoozeHintText(s, 'en');
    expect(text).not.toBe(t('defer.snoozePickDate'));
    expect(text).not.toContain('defer.snoozeResolves');
    expect(text.length).toBeGreaterThan(0);
  });
});

describe('deferRowActions', () => {
  it('renders both verbs, snooze before skip', () => {
    // Order is the design: the two exceptions sit ahead of Done, so the rightmost
    // target on the row stays the one people actually mean.
    const html = deferRowActions(task(), { snooze: true, skip: true });
    expect(html.indexOf('hk-defer-snooze')).toBeGreaterThanOrEqual(0);
    expect(html.indexOf('hk-defer-snooze')).toBeLessThan(html.indexOf('hk-defer-skip'));
  });

  it('renders only the verb on offer', () => {
    const blocked = deferRowActions(task(), { snooze: true, skip: false });
    expect(blocked).toContain('hk-defer-snooze');
    expect(blocked).not.toContain('hk-defer-skip');
  });

  it('renders nothing when neither verb is on offer', () => {
    expect(deferRowActions(task(), { snooze: false, skip: false })).toBe('');
  });

  it('labels each button, since an icon alone does not say which verb it is', () => {
    const html = deferRowActions(task(), { snooze: true, skip: true });
    expect(html).toContain(`label="${t('btn.snooze')}"`);
    expect(html).toContain(`title="${t('btn.skip')}"`);
  });

  it('carries the task id so a click knows which row it came from', () => {
    expect(deferRowActions(task({ id: 'abc' }), { snooze: true, skip: true })).toContain(
      'data-id="abc"',
    );
  });

  it('escapes the task id', () => {
    const html = deferRowActions(task({ id: 'a"><script>x</script>' }), {
      snooze: true,
      skip: true,
    });
    expect(html).not.toContain('<script>');
  });
});
