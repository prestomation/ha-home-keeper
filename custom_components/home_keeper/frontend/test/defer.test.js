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
  snoozeStateFor,
  snoozeTarget,
} from '../src/defer.ts';
import { isoToHaDateTime } from '../src/forms.ts';
import { DEFAULT_SNOOZE_PRESET } from '../src/utils.ts';
import { t } from '../src/i18n.ts';

// The clock is pinned so a fixture's due date cannot quietly drift past it and
// flip what `deferVerbs` answers. `NOW` is what every call below passes.
const NOW = new Date('2026-09-15T12:00:00Z');

const task = (over = {}) => ({
  id: 't1',
  name: 'Replace filter',
  next_due: '2026-09-30T09:00:00-04:00',
  ...over,
});

describe('deferVerbs', () => {
  it('offers every verb when nothing is configured', () => {
    // The switches default *on*, so an install that predates them — every existing
    // one — must read as "offer everything" rather than as "all off".
    expect(deferVerbs(task(), {}, NOW)).toEqual({
      snooze: true,
      skip: true,
      dueToday: true,
      details: true,
    });
  });

  it('withdraws each verb independently when its switch is off', () => {
    expect(deferVerbs(task(), { allow_snooze: false }, NOW)).toEqual({
      snooze: false,
      skip: true,
      dueToday: true,
      details: true,
    });
    expect(deferVerbs(task(), { allow_skip: false }, NOW)).toEqual({
      snooze: true,
      skip: false,
      dueToday: true,
      details: true,
    });
    expect(deferVerbs(task(), { allow_due_today: false }, NOW)).toEqual({
      snooze: true,
      skip: true,
      dueToday: false,
      details: true,
    });
  });

  it('offers no verb on a dormant task', () => {
    // No due date is nothing to defer: snooze and due today raise in the store,
    // and skip has no occurrence to move past.
    expect(deferVerbs(task({ next_due: null }), {}, NOW)).toEqual({
      snooze: false,
      skip: false,
      dueToday: false,
      details: false,
    });
  });

  it('offers snooze and due today but not skip on a completion-blocked task', () => {
    // The store rejects skipping a synced problem task, but a notification walk
    // still has to be able to get past it — so snooze (and, alongside it, due
    // today, which asserts nothing about the problem either) deliberately
    // survive.
    const blocked = task({ managed_by: { completion_blocked: true } });
    expect(deferVerbs(blocked, {}, NOW)).toEqual({
      snooze: true,
      skip: false,
      dueToday: true,
      details: false,
    });
  });

  it('withholds due today on a task that is already due, and only that verb', () => {
    // Moving an overdue task's date to now pushes it *later* and drops the overdue
    // state, which is the opposite of what the button says. Snooze and skip still
    // apply — asserting they stay true is what pins the `&&` here, since flipping
    // it to `||` would offer due today on everything.
    const overdue = task({ next_due: '2026-09-01T09:00:00Z' });
    expect(deferVerbs(overdue, {}, NOW)).toEqual({
      snooze: true,
      skip: true,
      dueToday: false,
      details: true,
    });
  });

  it('withholds due today at the instant the task falls due', () => {
    // `isOverdue` is `<=`, so the boundary belongs to "already due". A mutant that
    // relaxes it to `<` survives every other case in this file.
    const exactly = task({ next_due: NOW.toISOString() });
    expect(deferVerbs(exactly, {}, NOW).dueToday).toBe(false);
  });

  it('offers due today on a task due later', () => {
    expect(deferVerbs(task({ next_due: '2026-12-01T09:00:00Z' }), {}, NOW).dueToday).toBe(
      true,
    );
  });

  it('offers details only on a one-tap task (#399)', () => {
    // A task that asks for details opens the dialog from Done already, so the entry
    // would repeat it. A missing mode is one-tap, as everywhere else.
    expect(deferVerbs(task({ completion_detail: 'none' }), {}, NOW).details).toBe(true);
    expect(deferVerbs(task({ completion_detail: 'optional' }), {}, NOW).details).toBe(false);
    expect(deferVerbs(task({ completion_detail: 'required' }), {}, NOW).details).toBe(false);
  });

  it('withholds details on a task locked to its tag (#399)', () => {
    // Done refuses a tag-locked task, so a second way to complete it must refuse too.
    // Both halves of the lock are needed: the flag alone locks nothing.
    expect(deferVerbs(task({ tag_id: 'tag1', require_tag_scan: true }), {}, NOW).details).toBe(
      false,
    );
    expect(deferVerbs(task({ require_tag_scan: true }), {}, NOW).details).toBe(true);
  });

  it('keeps details when every deferral switch is off (#399)', () => {
    // The entry is not a deferral, so the deferral switches do not govern it.
    const off = { allow_snooze: false, allow_skip: false, allow_due_today: false };
    expect(deferVerbs(task(), off, NOW)).toEqual({
      snooze: false,
      skip: false,
      dueToday: false,
      details: true,
    });
  });

  it('reads the wall clock when no now is given', () => {
    // The default parameter is the production path: every caller omits it.
    const longPast = task({ next_due: '2000-01-01T00:00:00Z' });
    expect(deferVerbs(longPast, {}).dueToday).toBe(false);
    const longFuture = task({ next_due: '2099-01-01T00:00:00Z' });
    expect(deferVerbs(longFuture, {}).dueToday).toBe(true);
  });
});

describe('deferSplit', () => {
  it('returns Done untouched when no verb is on offer', () => {
    const done = '<ha-button class="done-btn">Done</ha-button>';
    expect(deferSplit(task(), done, { snooze: false, skip: false })).toBe(done);
  });

  it('wraps Done when only the details entry is on offer (#399)', () => {
    // Every deferral switch off still leaves a one-tap task the details entry, and
    // it needs the caret to be reached.
    const html = deferSplit(task(), '<b>Done</b>', {
      snooze: false,
      skip: false,
      dueToday: false,
      details: true,
    });
    expect(html).toContain('hk-split-caret');
    expect(html).toContain('hk-defer-details');
    expect(html).not.toContain('hk-defer-snooze');
  });

  it('lists the details entry first, with its label and hint (#399)', () => {
    const html = deferMenuItems({ snooze: true, skip: false, dueToday: false, details: true });
    expect(html.indexOf('hk-defer-details')).toBeLessThan(html.indexOf('hk-defer-snooze'));
    expect(html).toContain(t('defer.details'));
    expect(html).toContain(t('defer.detailsHint'));
    expect(html).toContain('mdi:camera-outline');
    expect(deferMenuItems({ snooze: true, skip: false, dueToday: false, details: false })).not.toContain(
      'hk-defer-details',
    );
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

  it('gives the caret the same weight as the Done it joins', () => {
    // This is what keeps the two halves the same colour. Home Assistant fills a
    // button from its appearance, and the weights differ by surface, so a caret on a
    // different weight paints a different fill and the pill reads as two buttons.
    const primary = deferSplit(task(), '<b>Done</b>', { snooze: true, skip: true }, 'primary');
    const secondary = deferSplit(task(), '<b>Done</b>', { snooze: true, skip: true }, 'secondary');
    expect(primary).toContain('data-hk-weight="primary"');
    expect(secondary).toContain('data-hk-weight="secondary"');
    expect(secondary).toContain('appearance="filled"');
  });

  it('clips the pair to one pill, with the menu outside the clip', () => {
    // The menu hangs below the button, so it has to be a sibling of the element
    // whose overflow rounds the corners rather than a child of it.
    const html = deferSplit(task(), '<b>Done</b>', { snooze: true, skip: true });
    const pillEnd = html.indexOf('</span>');
    expect(html.indexOf('hk-split-pill')).toBeLessThan(pillEnd);
    expect(html.indexOf('hk-defer-menu')).toBeGreaterThan(pillEnd);
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

  // An overdue task: the length counts from the given instant.
  const overdue = task({ next_due: '2026-03-01T09:00:00Z' });

  it('resolves a preset relative to the given instant', () => {
    const until = snoozeTarget({ open: true, task: overdue, preset: '1d' }, from);
    expect(until?.toISOString()).toBe('2026-03-11T09:00:00.000Z');
  });

  // F10-2: presets counted from now moved a task that is not yet due earlier.
  it('F10-2: resolves a preset from a due date later than now', () => {
    const later = task({ next_due: '2026-04-09T09:00:00Z' });
    const until = snoozeTarget({ open: true, task: later, preset: '1d' }, from);
    expect(until?.toISOString()).toBe('2026-04-10T09:00:00.000Z');
  });

  it('F10-2: resolves a preset from now for a task with no due date', () => {
    const until = snoozeTarget({ open: true, task: null, preset: '1d' }, from);
    expect(until?.toISOString()).toBe('2026-03-11T09:00:00.000Z');
  });

  it('F10-2: refuses a custom date that is not later than the due date', () => {
    const later = task({ next_due: '2026-04-09T09:00:00Z' });
    const s = (customAt) => ({ open: true, task: later, preset: 'custom', customAt });
    expect(snoozeTarget(s(isoToHaDateTime('2026-04-01T09:00:00Z')), from)).toBeNull();
    expect(snoozeTarget(s(isoToHaDateTime('2026-04-09T09:00:00Z')), from)).toBeNull();
    expect(snoozeTarget(s(isoToHaDateTime('2026-04-09T09:01:00Z')), from)?.toISOString()).toBe(
      '2026-04-09T09:01:00.000Z',
    );
  });

  it('F10-2: refuses a custom date in the past for an overdue task', () => {
    const s = (customAt) => ({ open: true, task: overdue, preset: 'custom', customAt });
    expect(snoozeTarget(s(isoToHaDateTime('2026-03-05T09:00:00Z')), from)).toBeNull();
    expect(snoozeTarget(s(isoToHaDateTime('2026-03-10T09:01:00Z')), from)?.toISOString()).toBe(
      '2026-03-10T09:01:00.000Z',
    );
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
    const s = { open: true, task: overdue, preset: 'custom', customAt: '2026-04-01 08:30:00' };
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

  it('gives due today its own entry, class and icon', () => {
    // The class is what `DeferMenus` binds the click to and what the e2e specs
    // select on, and the icon is the only thing distinguishing the entry at a
    // glance — so both are behaviour here, not decoration.
    const html = deferMenuItems({ snooze: false, skip: false, dueToday: true });
    expect(html).toContain('hk-defer-due-today');
    expect(html).toContain('mdi:calendar-arrow-left');
    expect(html).toContain(t('btn.dueToday'));
    expect(html).toContain(t('defer.dueTodayHint'));
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

  it('F10-2: says why a custom date before the due date does not work', () => {
    const s = {
      open: true,
      task: task(),
      preset: 'custom',
      customAt: isoToHaDateTime('2026-09-20T09:00:00Z'),
    };
    const text = snoozeHintText(s, 'en', NOW);
    expect(text).toMatch(/^Pick a date and time after .+\.$/);
    expect(text).toContain('2026');
    expect(text).not.toBe(t('defer.snoozePickDate'));
  });

  it('F10-2: says "pick a date" for a preset with no date, whatever was typed before', () => {
    const s = {
      open: true,
      task: task(),
      preset: 'no-such-preset',
      customAt: isoToHaDateTime('2026-09-20T09:00:00Z'),
    };
    expect(snoozeHintText(s, 'en', NOW)).toBe(t('defer.snoozePickDate'));
  });

  it('F10-2: states the date a preset gives from a later due date', () => {
    const s = { open: true, task: task(), preset: '1d' };
    expect(snoozeHintText(s, 'en', NOW)).toMatch(/^Due date moves to .*Oct.*1.*2026/);
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

  it('puts due today last, after skip and still ahead of Done', () => {
    // Done is appended by the caller, so "last here" is "next to Done". The class
    // is what the card's long-press wiring and the e2e specs select on.
    const html = deferRowActions(task(), { snooze: true, skip: true, dueToday: true });
    expect(html).toContain('hk-defer-due-today');
    expect(html).toContain(t('btn.dueToday'));
    expect(html.indexOf('hk-defer-skip')).toBeLessThan(html.indexOf('hk-defer-due-today'));
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

describe('snoozeStateFor', () => {
  it('opens on the usual preset for a task with no length of its own', () => {
    const tk = task();
    expect(snoozeStateFor(tk, NOW)).toEqual({ open: true, task: tk, preset: DEFAULT_SNOOZE_PRESET });
    expect(snoozeStateFor(task({ snooze_hours: null }), NOW).preset).toBe(DEFAULT_SNOOZE_PRESET);
  });

  it('opens on the preset of the task length', () => {
    const tk = task({ snooze_hours: 1 });
    expect(snoozeStateFor(tk, NOW)).toEqual({ open: true, task: tk, preset: '1h' });
    expect(snoozeStateFor(task({ snooze_hours: 4 }), NOW).preset).toBe('4h');
    expect(snoozeStateFor(task({ snooze_hours: 24 }), NOW).preset).toBe('1d');
    expect(snoozeStateFor(task({ snooze_hours: 720 }), NOW).preset).toBe('1mo');
  });

  it('opens on custom, filled in, for a length no preset has', () => {
    const tk = task({ snooze_hours: 3, next_due: '2026-09-01T09:00:00Z' });
    const s = snoozeStateFor(tk, NOW);
    expect(s).toEqual({
      open: true,
      task: tk,
      preset: 'custom',
      customAt: isoToHaDateTime('2026-09-15T15:00:00Z'),
    });
    // The date field resolves to exactly the task length from now.
    expect(snoozeTarget(s, NOW)).toEqual(new Date('2026-09-15T15:00:00Z'));
  });

  it('F10-2: fills in the length from a due date later than now', () => {
    const tk = task({ snooze_hours: 3 });
    const s = snoozeStateFor(tk, NOW);
    expect(s.customAt).toBe(isoToHaDateTime('2026-09-30T16:00:00Z'));
    expect(snoozeTarget(s, NOW)).toEqual(new Date('2026-09-30T16:00:00Z'));
  });
});
