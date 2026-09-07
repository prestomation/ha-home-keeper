import { describe, expect, it } from 'vitest';
import {
  DUE_SOON_DAYS,
  emptyGroup,
  groupActive,
  groupMatches,
  profileHasAnyTask,
  profileMatches,
} from '../src/card-filter.ts';

// `profileMatches` decides which tasks a notification profile sends. It has to
// agree with the backend's windows exactly, or a digest reports a different set
// than the panel previews. `card-filter.test.js` covers the card's own filters;
// this covers the profile predicate, which nothing exercised directly.
//
// A filter is a status window plus an OR of groups, so this asks three questions and
// not one: what the gates drop, what one group means (`groupMatches`), and how several
// groups combine (`profileMatches groups`).

const DAY_MS = 86_400_000;
const NOW = Date.parse('2026-06-13T10:00:00Z');
const at = (offsetDays) => new Date(NOW + offsetDays * DAY_MS).toISOString();

const task = (over = {}) => ({
  id: 't1',
  name: 'Filter',
  enabled: true,
  next_due: at(-1),
  ...over,
});

/** A filter of one group, spelled the way a stored profile spells it. */
const one = (group = {}, over = {}) => ({ groups: [{ ...group }], ...over });

/** An auto-created "Buy {part}" reminder — excluded by kind, not by id. */
const buyTask = (over = {}) =>
  task({ source: { buy: { asset_id: 'a1', part_id: 'p1' } }, ...over });

describe('profileMatches gating', () => {
  it('excludes disabled tasks', () => {
    expect(profileMatches(task(), {}, {}, {}, NOW)).toBe(true);
    expect(profileMatches(task({ enabled: false }), {}, {}, {}, NOW)).toBe(false);
  });

  it('treats an absent `enabled` as enabled', () => {
    // Only an explicit `false` disables; `undefined` is an older record.
    const t = task();
    delete t.enabled;
    expect(profileMatches(t, {}, {}, {}, NOW)).toBe(true);
  });

  it('excludes undated tasks', () => {
    expect(profileMatches(task({ next_due: null }), {}, {}, {}, NOW)).toBe(false);
    expect(profileMatches(task({ next_due: '' }), {}, {}, {}, NOW)).toBe(false);
  });

  it('includes an armed problem-sensor task (#248)', () => {
    // These used to be dropped outright, so a synced problem never showed under any
    // Profile — in the panel or on the card. An armed one is dated (next_due = when
    // the sensor went bad) and overdue, so it belongs like any other overdue task.
    expect(profileMatches(task({ source: { problem_sensor: 'binary_sensor.x' } }), {}, {}, {}, NOW)).toBe(
      true,
    );
    // A dormant one (sensor back to OK) is undated, so the rule above still drops it.
    expect(
      profileMatches(
        task({ next_due: null, source: { problem_sensor: 'binary_sensor.x' } }),
        {},
        {},
        {},
        NOW,
      ),
    ).toBe(false);
    // Sources of other shapes keep behaving as before.
    expect(profileMatches(task({ source: { part: { asset_id: 'a1' } } }), {}, {}, {}, NOW)).toBe(
      true,
    );
    expect(profileMatches(task({ source: null }), {}, {}, {}, NOW)).toBe(true);
  });
});

describe('profileMatches status windows', () => {
  it('defaults to overdue when no status is set', () => {
    // The default has to be `overdue`, not "everything": an empty profile that
    // matched every dated task would notify on the whole list.
    expect(profileMatches(task({ next_due: at(-1) }), {}, {}, {}, NOW)).toBe(true);
    expect(profileMatches(task({ next_due: at(1) }), {}, {}, {}, NOW)).toBe(false);
    expect(profileMatches(task({ next_due: at(1) }), { status: '' }, {}, {}, NOW)).toBe(false);
  });

  it('overdue means due at or before now, inclusive', () => {
    const f = { status: 'overdue' };
    expect(profileMatches(task({ next_due: at(-1) }), f, {}, {}, NOW)).toBe(true);
    expect(profileMatches(task({ next_due: new Date(NOW).toISOString() }), f, {}, {}, NOW)).toBe(
      true,
    );
    expect(profileMatches(task({ next_due: at(0.001) }), f, {}, {}, NOW)).toBe(false);
  });

  it('due_soon spans overdue through the window edge, inclusive', () => {
    const f = { status: 'due_soon' };
    expect(profileMatches(task({ next_due: at(-5) }), f, {}, {}, NOW)).toBe(true);
    expect(profileMatches(task({ next_due: at(DUE_SOON_DAYS) }), f, {}, {}, NOW)).toBe(true);
    // One millisecond past the window is out — this is what pins the boundary
    // as `>` rather than `>=`.
    const justPast = new Date(NOW + DUE_SOON_DAYS * DAY_MS + 1).toISOString();
    expect(profileMatches(task({ next_due: justPast }), f, {}, {}, NOW)).toBe(false);
  });

  it('all accepts any dated, enabled task', () => {
    const f = { status: 'all' };
    expect(profileMatches(task({ next_due: at(-30) }), f, {}, {}, NOW)).toBe(true);
    expect(profileMatches(task({ next_due: at(365) }), f, {}, {}, NOW)).toBe(true);
    expect(profileMatches(task({ next_due: null }), f, {}, {}, NOW)).toBe(false);
  });

  it('applies one status window to every group', () => {
    // The window belongs to the profile, not to a rule inside it: a group that names
    // the task cannot drag it past a status the profile excluded.
    const later = task({ next_due: at(30), labels: ['dog'] });
    expect(profileMatches(later, one({ labels: ['dog'] }, { status: 'overdue' }), {}, {}, NOW)).toBe(
      false,
    );
    expect(profileMatches(later, one({ labels: ['dog'] }, { status: 'all' }), {}, {}, NOW)).toBe(
      true,
    );
  });
});

describe('profileMatches area and device filters', () => {
  const devices = { d1: { area_id: 'kitchen' }, d2: { area_id: 'garage' } };

  it('an empty list means "no constraint", not "match nothing"', () => {
    const t = task({ area_id: 'kitchen', device_id: 'd1' });
    expect(profileMatches(t, one({ areas: [], devices: [], labels: [] }), devices, {}, NOW)).toBe(
      true,
    );
    // Absent behaves the same as empty.
    expect(profileMatches(t, {}, devices, {}, NOW)).toBe(true);
  });

  it('filters by the task area', () => {
    const t = task({ area_id: 'kitchen' });
    expect(profileMatches(t, one({ areas: ['kitchen'] }), devices, {}, NOW)).toBe(true);
    expect(profileMatches(t, one({ areas: ['garage'] }), devices, {}, NOW)).toBe(false);
    expect(profileMatches(t, one({ areas: ['garage', 'kitchen'] }), devices, {}, NOW)).toBe(true);
  });

  it('falls back to the device area when the task has none', () => {
    const t = task({ device_id: 'd2' });
    expect(profileMatches(t, one({ areas: ['garage'] }), devices, {}, NOW)).toBe(true);
    expect(profileMatches(t, one({ areas: ['kitchen'] }), devices, {}, NOW)).toBe(false);
  });

  it('an area-less task matches no area filter', () => {
    // It must not slip through by comparing against a placeholder that happens
    // to be absent from the wanted list.
    expect(profileMatches(task(), one({ areas: ['kitchen'] }), devices, {}, NOW)).toBe(false);
  });

  it('filters by device', () => {
    expect(
      profileMatches(task({ device_id: 'd1' }), one({ devices: ['d1'] }), devices, {}, NOW),
    ).toBe(true);
    expect(
      profileMatches(task({ device_id: 'd1' }), one({ devices: ['d2'] }), devices, {}, NOW),
    ).toBe(false);
    // A device-less task matches no device filter.
    expect(profileMatches(task(), one({ devices: ['d1'] }), devices, {}, NOW)).toBe(false);
  });

  it('applies area and device filters together', () => {
    const t = task({ area_id: 'kitchen', device_id: 'd1' });
    expect(profileMatches(t, one({ areas: ['kitchen'], devices: ['d1'] }), devices, {}, NOW)).toBe(
      true,
    );
    expect(profileMatches(t, one({ areas: ['kitchen'], devices: ['d2'] }), devices, {}, NOW)).toBe(
      false,
    );
    expect(profileMatches(t, one({ areas: ['garage'], devices: ['d1'] }), devices, {}, NOW)).toBe(
      false,
    );
  });
});

describe('profileMatches exclusions', () => {
  const devices = { d1: { area_id: 'kitchen', labels: ['pro'] }, d2: { area_id: 'garage' } };
  const areas = { kitchen: { labels: ['indoors'] }, garage: { labels: [] } };

  it('drops a task carrying an excluded label', () => {
    const t = task({ labels: ['pro'] });
    expect(profileMatches(t, one({ exclude_labels: ['pro'] }), {}, {}, NOW)).toBe(false);
    expect(profileMatches(t, one({ exclude_labels: ['mechanic'] }), {}, {}, NOW)).toBe(true);
  });

  it('excludes on ANY hit across several excluded labels', () => {
    const t = task({ labels: ['dog', 'pro'] });
    expect(profileMatches(t, one({ exclude_labels: ['mechanic', 'pro'] }), {}, {}, NOW)).toBe(false);
  });

  it('lets an exclusion beat a satisfied include', () => {
    // This is the whole point of #214: "everything on my list except the call-outs".
    const t = task({ labels: ['dog', 'pro'] });
    expect(profileMatches(t, one({ labels: ['dog'] }), {}, {}, NOW)).toBe(true);
    expect(profileMatches(t, one({ labels: ['dog'], exclude_labels: ['pro'] }), {}, {}, NOW)).toBe(
      false,
    );
  });

  it('treats an empty or absent exclude list as "exclude nothing"', () => {
    // An inverted check here would empty every profile at once, so pin both spellings.
    const t = task({ labels: ['dog'], area_id: 'kitchen', device_id: 'd2' });
    expect(
      profileMatches(
        t,
        one({ exclude_labels: [], exclude_areas: [], exclude_devices: [] }),
        devices,
        areas,
        NOW,
      ),
    ).toBe(true);
    expect(profileMatches(t, {}, devices, areas, NOW)).toBe(true);
  });

  it('excludes on the effective label, inherited from the device or the area', () => {
    // Parity with the backend, which enriches tasks before matching: excluding `pro`
    // also drops a task that only carries it via the device it hangs off.
    expect(
      profileMatches(
        task({ device_id: 'd1' }),
        one({ exclude_labels: ['pro'] }),
        devices,
        areas,
        NOW,
      ),
    ).toBe(false);
    expect(
      profileMatches(
        task({ area_id: 'kitchen' }),
        one({ exclude_labels: ['indoors'] }),
        devices,
        areas,
        NOW,
      ),
    ).toBe(false);
  });

  it('drops a task in an excluded area, including one inherited from its device', () => {
    expect(
      profileMatches(
        task({ area_id: 'garage' }),
        one({ exclude_areas: ['garage'] }),
        devices,
        {},
        NOW,
      ),
    ).toBe(false);
    expect(
      profileMatches(task({ device_id: 'd2' }), one({ exclude_areas: ['garage'] }), devices, {}, NOW),
    ).toBe(false);
    expect(
      profileMatches(
        task({ area_id: 'kitchen' }),
        one({ exclude_areas: ['garage'] }),
        devices,
        {},
        NOW,
      ),
    ).toBe(true);
  });

  it('drops a task on an excluded device', () => {
    expect(
      profileMatches(task({ device_id: 'd1' }), one({ exclude_devices: ['d1'] }), devices, {}, NOW),
    ).toBe(false);
    expect(
      profileMatches(task({ device_id: 'd2' }), one({ exclude_devices: ['d1'] }), devices, {}, NOW),
    ).toBe(true);
  });

  it('does not sweep up an area-less or device-less task', () => {
    // The placeholder '' must not collide with a real id, or every unattached task
    // would vanish the moment any exclusion was set.
    const bare = task();
    expect(profileMatches(bare, one({ exclude_areas: ['garage'] }), {}, {}, NOW)).toBe(true);
    expect(profileMatches(bare, one({ exclude_devices: ['d1'] }), {}, {}, NOW)).toBe(true);
  });

  it('drops the buy reminders when a group excludes shopping', () => {
    expect(profileMatches(buyTask(), one({ exclude_shopping: true }), {}, {}, NOW)).toBe(false);
    expect(profileMatches(buyTask(), one({ exclude_shopping: false }), {}, {}, NOW)).toBe(true);
    // By kind, not by id: an ordinary task is untouched by the switch.
    expect(profileMatches(task(), one({ exclude_shopping: true }), {}, {}, NOW)).toBe(true);
  });
});

describe('profileMatches companions', () => {
  const owned = (integration) =>
    task({ managed_by: { integration, display_name: 'Battery Notes' } });

  it('selects only tasks owned by a named integration', () => {
    const filter = one({ companions: ['battery_notes'] });
    expect(profileMatches(owned('battery_notes'), filter, {}, {}, NOW)).toBe(true);
    expect(profileMatches(owned('printer_glue'), filter, {}, {}, NOW)).toBe(false);
  });

  it('matches any of several named integrations', () => {
    const filter = one({ companions: ['battery_notes', 'dog_glue'] });
    expect(profileMatches(owned('dog_glue'), filter, {}, {}, NOW)).toBe(true);
    expect(profileMatches(owned('printer_glue'), filter, {}, {}, NOW)).toBe(false);
  });

  it('never selects a task no integration owns', () => {
    // A task made in the panel has no managed_by, so "just the battery tasks" must
    // not quietly include the user's own chores.
    expect(profileMatches(task(), one({ companions: ['battery_notes'] }), {}, {}, NOW)).toBe(false);
    const nameless = task({ managed_by: { display_name: 'Nameless' } });
    expect(profileMatches(nameless, one({ companions: ['battery_notes'] }), {}, {}, NOW)).toBe(
      false,
    );
  });

  it('treats an explicitly null managed_by like an absent one', () => {
    const nulled = task({ managed_by: null });
    expect(profileMatches(nulled, one({ companions: ['battery_notes'] }), {}, {}, NOW)).toBe(false);
    expect(profileMatches(nulled, one({ exclude_companions: ['battery_notes'] }), {}, {}, NOW)).toBe(
      true,
    );
  });

  it('drops a task owned by an excluded integration', () => {
    const filter = one({ exclude_companions: ['battery_notes'] });
    expect(profileMatches(owned('battery_notes'), filter, {}, {}, NOW)).toBe(false);
    expect(profileMatches(owned('dog_glue'), filter, {}, {}, NOW)).toBe(true);
  });

  it('does not sweep up an unowned task with a non-empty exclude list', () => {
    expect(profileMatches(task(), one({ exclude_companions: ['battery_notes'] }), {}, {}, NOW)).toBe(
      true,
    );
  });

  it('lets the exclude list win over a matching include', () => {
    expect(
      profileMatches(
        owned('battery_notes'),
        one({ companions: ['battery_notes'], exclude_companions: ['battery_notes'] }),
        {},
        {},
        NOW,
      ),
    ).toBe(false);
  });

  it('treats an empty or absent companions list as every owner', () => {
    expect(profileMatches(owned('battery_notes'), one({ companions: [] }), {}, {}, NOW)).toBe(true);
    expect(profileMatches(owned('battery_notes'), {}, {}, {}, NOW)).toBe(true);
  });
});

// ── the group primitives (#291) ─────────────────────────────────────────────

describe('emptyGroup', () => {
  it('constrains nothing, so seeding one never narrows a profile', () => {
    const g = emptyGroup();
    expect(g).toEqual({
      labels: [],
      labels_match: 'any',
      areas: [],
      devices: [],
      companions: [],
      exclude_labels: [],
      exclude_areas: [],
      exclude_devices: [],
      exclude_companions: [],
      exclude_shopping: false,
    });
    expect(groupActive(g)).toBe(false);
    expect(groupMatches(g, task(), {}, {})).toBe(true);
  });

  it('hands out a fresh group each time', () => {
    // A shared array would make editing one group edit its siblings.
    const first = emptyGroup();
    first.labels.push('dog');
    expect(emptyGroup().labels).toEqual([]);
  });
});

describe('groupActive', () => {
  it('is false for a group with nothing set at all', () => {
    expect(groupActive({})).toBe(false);
    expect(groupActive({ labels: [], areas: [], exclude_devices: [] })).toBe(false);
    // The label mode says how to read `labels`; on its own it constrains nothing.
    expect(groupActive({ labels_match: 'all' })).toBe(false);
    expect(groupActive({ exclude_shopping: false })).toBe(false);
  });

  it('is true for any one non-empty list', () => {
    for (const key of [
      'labels',
      'areas',
      'devices',
      'companions',
      'exclude_labels',
      'exclude_areas',
      'exclude_devices',
      'exclude_companions',
    ]) {
      expect(groupActive({ [key]: ['x'] })).toBe(true);
    }
  });

  it('is true for an exclude-only shopping group', () => {
    // A group that only drops the buy reminders is a real rule, so it must not be
    // dropped as "empty" — that would silently re-admit them.
    expect(groupActive({ exclude_shopping: true })).toBe(true);
  });
});

describe('groupMatches', () => {
  const devices = { d1: { area_id: 'kitchen', labels: ['pro'] } };
  const areas = { kitchen: { labels: ['indoors'] } };

  it('needs every include list that carries a value', () => {
    const t = task({ labels: ['dog'], area_id: 'kitchen', device_id: 'd1' });
    expect(groupMatches({ labels: ['dog'], areas: ['kitchen'] }, t, devices, areas)).toBe(true);
    // One list unsatisfied is enough to fail the group.
    expect(groupMatches({ labels: ['dog'], areas: ['garage'] }, t, devices, areas)).toBe(false);
    expect(groupMatches({ labels: ['cat'], areas: ['kitchen'] }, t, devices, areas)).toBe(false);
  });

  it('reads the effective labels — own, device and area', () => {
    expect(groupMatches({ labels: ['pro'] }, task({ device_id: 'd1' }), devices, areas)).toBe(true);
    expect(groupMatches({ labels: ['indoors'] }, task({ area_id: 'kitchen' }), devices, areas)).toBe(
      true,
    );
  });

  it('matches ANY label by default and ALL only when asked', () => {
    const t = task({ labels: ['dog'] });
    const both = task({ labels: ['dog', 'outdoor'] });
    const wanted = ['dog', 'outdoor'];
    expect(groupMatches({ labels: wanted }, t, {}, {})).toBe(true);
    expect(groupMatches({ labels: wanted, labels_match: 'any' }, t, {}, {})).toBe(true);
    expect(groupMatches({ labels: wanted, labels_match: 'all' }, t, {}, {})).toBe(false);
    expect(groupMatches({ labels: wanted, labels_match: 'all' }, both, {}, {})).toBe(true);
    // Anything that is not exactly 'all' reads as `any` — a stored group that never
    // had the key must not tighten into ALL behind the user.
    expect(groupMatches({ labels: wanted, labels_match: 'ANY' }, t, {}, {})).toBe(true);
    expect(groupMatches({ labels: wanted, labels_match: undefined }, t, {}, {})).toBe(true);
  });

  it('is true for a group that constrains nothing', () => {
    expect(groupMatches({}, task(), {}, {})).toBe(true);
    expect(
      groupMatches({ labels: [], areas: [], devices: [], companions: [] }, task(), {}, {}),
    ).toBe(true);
  });

  it('drops a buy reminder only when this group excludes shopping', () => {
    expect(groupMatches({ exclude_shopping: true }, buyTask(), {}, {})).toBe(false);
    expect(groupMatches({}, buyTask(), {}, {})).toBe(true);
    expect(groupMatches({ exclude_shopping: true }, task(), {}, {})).toBe(true);
  });

  it('ignores the status window, which belongs to the profile', () => {
    // A group says nothing about when a task is due; `profileMatches` gates that.
    expect(groupMatches({}, task({ next_due: at(365) }), {}, {})).toBe(true);
  });
});

describe('profileMatches groups', () => {
  const devices = { d1: { area_id: 'kitchen' }, d2: { area_id: 'garage' } };

  it('reads a single group exactly as the old flat filter did', () => {
    const dog = task({ labels: ['dog'] });
    expect(profileMatches(dog, one({ labels: ['dog'] }), {}, {}, NOW)).toBe(true);
    expect(profileMatches(dog, one({ labels: ['cat'] }), {}, {}, NOW)).toBe(false);
  });

  it('takes a task either group matches', () => {
    // The reason groups exist: "the dog's jobs OR anything in the garage" is one
    // profile, and neither rule can be written as a longer flat list.
    const filter = { groups: [{ labels: ['dog'] }, { areas: ['garage'] }] };
    expect(profileMatches(task({ labels: ['dog'] }), filter, devices, {}, NOW)).toBe(true);
    expect(profileMatches(task({ area_id: 'garage' }), filter, devices, {}, NOW)).toBe(true);
    // Matching both is still one match.
    expect(
      profileMatches(task({ labels: ['dog'], area_id: 'garage' }), filter, devices, {}, NOW),
    ).toBe(true);
    // A task neither group names is out.
    expect(
      profileMatches(task({ labels: ['cat'], area_id: 'kitchen' }), filter, devices, {}, NOW),
    ).toBe(false);
  });

  it('needs every include list inside the group that takes the task', () => {
    // Within a group the lists are ANDed, so half a group is not a match.
    const filter = { groups: [{ labels: ['dog'], areas: ['kitchen'] }] };
    expect(
      profileMatches(task({ labels: ['dog'], area_id: 'kitchen' }), filter, devices, {}, NOW),
    ).toBe(true);
    expect(
      profileMatches(task({ labels: ['dog'], area_id: 'garage' }), filter, devices, {}, NOW),
    ).toBe(false);
    expect(
      profileMatches(task({ labels: ['cat'], area_id: 'kitchen' }), filter, devices, {}, NOW),
    ).toBe(false);
  });

  it('lets each axis decide a group on its own', () => {
    const owner = { integration: 'battery_notes', display_name: 'Battery Notes' };
    const cases = [
      [{ labels: ['dog'] }, task({ labels: ['dog'] }), task({ labels: ['cat'] })],
      [{ areas: ['kitchen'] }, task({ area_id: 'kitchen' }), task({ area_id: 'garage' })],
      [{ devices: ['d1'] }, task({ device_id: 'd1' }), task({ device_id: 'd2' })],
      [
        { companions: ['battery_notes'] },
        task({ managed_by: owner }),
        task({ managed_by: { integration: 'other', display_name: 'Other' } }),
      ],
    ];
    for (const [group, hit, miss] of cases) {
      expect(profileMatches(hit, one(group), devices, {}, NOW)).toBe(true);
      expect(profileMatches(miss, one(group), devices, {}, NOW)).toBe(false);
    }
  });

  it('honours labels_match per group', () => {
    // Two groups, two modes: the ALL group is strict while the ANY group beside it
    // is not, which is only expressible per group.
    const filter = {
      groups: [
        { labels: ['dog', 'outdoor'], labels_match: 'all' },
        { labels: ['car'], labels_match: 'any' },
      ],
    };
    expect(profileMatches(task({ labels: ['dog'] }), filter, {}, {}, NOW)).toBe(false);
    expect(profileMatches(task({ labels: ['dog', 'outdoor'] }), filter, {}, {}, NOW)).toBe(true);
    expect(profileMatches(task({ labels: ['car'] }), filter, {}, {}, NOW)).toBe(true);
  });

  it('scopes an exclusion to the group that carries it', () => {
    // The exclusion is part of one rule, not of the profile: "the dog's jobs except
    // the call-outs, OR anything in the garage" keeps a garage call-out.
    const filter = {
      groups: [{ labels: ['dog'], exclude_labels: ['pro'] }, { areas: ['garage'] }],
    };
    expect(profileMatches(task({ labels: ['dog', 'pro'] }), filter, devices, {}, NOW)).toBe(false);
    expect(
      profileMatches(task({ labels: ['pro'], area_id: 'garage' }), filter, devices, {}, NOW),
    ).toBe(true);
  });

  it('counts an exclude-only group as a rule of its own', () => {
    // It constrains, so it is active — and being active, it decides on its own.
    const filter = { groups: [{ exclude_areas: ['garage'] }] };
    expect(profileMatches(task({ area_id: 'kitchen' }), filter, devices, {}, NOW)).toBe(true);
    expect(profileMatches(task({ area_id: 'garage' }), filter, devices, {}, NOW)).toBe(false);
  });

  it('ignores an empty group beside an active one', () => {
    // The editor always shows a spare group. If that empty row counted, adding it
    // would silently widen the profile back to every task.
    const filter = { groups: [{ labels: ['dog'] }, {}] };
    expect(profileMatches(task({ labels: ['dog'] }), filter, {}, {}, NOW)).toBe(true);
    expect(profileMatches(task({ labels: ['cat'] }), filter, {}, {}, NOW)).toBe(false);
    // Order does not matter — the empty one is dropped either way.
    const reversed = { groups: [{}, { labels: ['dog'] }] };
    expect(profileMatches(task({ labels: ['cat'] }), reversed, {}, {}, NOW)).toBe(false);
  });

  it('matches every live task when no group constrains anything', () => {
    for (const filter of [{}, { groups: [] }, { groups: [{}] }, { groups: [{}, {}] }]) {
      expect(profileMatches(task({ labels: ['anything'] }), filter, {}, {}, NOW)).toBe(true);
      // The gates still apply — "no active group" is not "no rules".
      expect(profileMatches(task({ enabled: false }), filter, {}, {}, NOW)).toBe(false);
      expect(profileMatches(task({ next_due: null }), filter, {}, {}, NOW)).toBe(false);
    }
  });

  it('reads no legacy top-level list', () => {
    // The flat keys are gone. A filter that still carries them selects on its groups
    // alone, so a stale key can never quietly narrow (or widen) a profile.
    const legacy = { labels: ['cat'], areas: ['garage'], groups: [{ labels: ['dog'] }] };
    expect(profileMatches(task({ labels: ['dog'] }), legacy, devices, {}, NOW)).toBe(true);
    expect(profileMatches(task({ labels: ['cat'] }), legacy, devices, {}, NOW)).toBe(false);
    // With no groups at all, the top-level keys gate nothing.
    expect(profileMatches(task({ labels: ['cat'] }), { labels: ['dog'] }, {}, {}, NOW)).toBe(true);
  });

  it('excludes shopping inside the group that says so', () => {
    const filter = { groups: [{ exclude_shopping: true }, { areas: ['garage'] }] };
    // The first group drops it; the second still takes it on its area.
    expect(profileMatches(buyTask({ area_id: 'garage' }), filter, devices, {}, NOW)).toBe(true);
    expect(profileMatches(buyTask({ area_id: 'kitchen' }), filter, devices, {}, NOW)).toBe(false);
    expect(profileMatches(task({ area_id: 'kitchen' }), filter, devices, {}, NOW)).toBe(true);
  });
});

describe('profileHasAnyTask', () => {
  // The Settings → Notifications footer asks "is there anything here to send a real
  // card about?". That is not the same question as "what does this profile deliver
  // today", and the difference is the whole reason the helper exists.

  it('ignores the profile status, so an overdue profile still has a task', () => {
    const later = task({ next_due: at(30) });
    // The profile itself would send nothing today...
    expect(profileMatches(later, { status: 'overdue' }, {}, {}, NOW)).toBe(false);
    // ...but Test sends `status: all`, so there is a card to reach.
    expect(profileHasAnyTask([later], { status: 'overdue' }, {}, {}, NOW)).toBe(true);
  });

  it('is true when any one task clears the filter', () => {
    const mine = task({ id: 'mine', labels: ['dog'] });
    const other = task({ id: 'other', labels: ['car'] });
    expect(profileHasAnyTask([other, mine], one({ labels: ['dog'] }), {}, {}, NOW)).toBe(true);
  });

  it('is true when a task clears any one of several groups', () => {
    const filter = { groups: [{ labels: ['dog'] }, { labels: ['car'] }] };
    expect(profileHasAnyTask([task({ labels: ['car'] })], filter, {}, {}, NOW)).toBe(true);
    expect(profileHasAnyTask([task({ labels: ['dog'] })], filter, {}, {}, NOW)).toBe(true);
    expect(profileHasAnyTask([task({ labels: ['boat'] })], filter, {}, {}, NOW)).toBe(false);
  });

  it('keeps the rest of the filter, so a label nobody carries matches nothing', () => {
    expect(profileHasAnyTask([task()], one({ labels: ['dog'] }), {}, {}, NOW)).toBe(false);
  });

  it('is false for no tasks at all', () => {
    expect(profileHasAnyTask([], {}, {}, {}, NOW)).toBe(false);
  });

  it('still drops a task the filter disqualifies outright', () => {
    // Disabled and undated tasks are out under every status, `all` included.
    expect(profileHasAnyTask([task({ enabled: false })], {}, {}, {}, NOW)).toBe(false);
    expect(profileHasAnyTask([task({ next_due: null })], {}, {}, {}, NOW)).toBe(false);
  });
});
