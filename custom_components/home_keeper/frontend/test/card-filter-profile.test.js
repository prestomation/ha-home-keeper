import { describe, expect, it } from 'vitest';
import { DUE_SOON_DAYS, profileHasAnyTask, profileMatches } from '../src/card-filter.ts';

// `profileMatches` decides which tasks a notification profile sends. It has to
// agree with the backend's windows exactly, or a digest reports a different set
// than the panel previews. `card-filter.test.js` covers the card's own filters;
// this covers the profile predicate, which nothing exercised directly.

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
});

describe('profileMatches area and device filters', () => {
  const devices = { d1: { area_id: 'kitchen' }, d2: { area_id: 'garage' } };

  it('an empty list means "no constraint", not "match nothing"', () => {
    const t = task({ area_id: 'kitchen', device_id: 'd1' });
    expect(profileMatches(t, { areas: [], devices: [], labels: [] }, devices, {}, NOW)).toBe(true);
    // Absent behaves the same as empty.
    expect(profileMatches(t, {}, devices, {}, NOW)).toBe(true);
  });

  it('filters by the task area', () => {
    const t = task({ area_id: 'kitchen' });
    expect(profileMatches(t, { areas: ['kitchen'] }, devices, {}, NOW)).toBe(true);
    expect(profileMatches(t, { areas: ['garage'] }, devices, {}, NOW)).toBe(false);
    expect(profileMatches(t, { areas: ['garage', 'kitchen'] }, devices, {}, NOW)).toBe(true);
  });

  it('falls back to the device area when the task has none', () => {
    const t = task({ device_id: 'd2' });
    expect(profileMatches(t, { areas: ['garage'] }, devices, {}, NOW)).toBe(true);
    expect(profileMatches(t, { areas: ['kitchen'] }, devices, {}, NOW)).toBe(false);
  });

  it('an area-less task matches no area filter', () => {
    // It must not slip through by comparing against a placeholder that happens
    // to be absent from the wanted list.
    const t = task();
    expect(profileMatches(t, { areas: ['kitchen'] }, devices, {}, NOW)).toBe(false);
  });

  it('filters by device', () => {
    expect(profileMatches(task({ device_id: 'd1' }), { devices: ['d1'] }, devices, {}, NOW)).toBe(
      true,
    );
    expect(profileMatches(task({ device_id: 'd1' }), { devices: ['d2'] }, devices, {}, NOW)).toBe(
      false,
    );
    // A device-less task matches no device filter.
    expect(profileMatches(task(), { devices: ['d1'] }, devices, {}, NOW)).toBe(false);
  });

  it('applies area and device filters together', () => {
    const t = task({ area_id: 'kitchen', device_id: 'd1' });
    expect(profileMatches(t, { areas: ['kitchen'], devices: ['d1'] }, devices, {}, NOW)).toBe(true);
    expect(profileMatches(t, { areas: ['kitchen'], devices: ['d2'] }, devices, {}, NOW)).toBe(false);
    expect(profileMatches(t, { areas: ['garage'], devices: ['d1'] }, devices, {}, NOW)).toBe(false);
  });
});

describe('profileMatches exclusions', () => {
  const devices = { d1: { area_id: 'kitchen', labels: ['pro'] }, d2: { area_id: 'garage' } };
  const areas = { kitchen: { labels: ['indoors'] }, garage: { labels: [] } };

  it('drops a task carrying an excluded label', () => {
    const t = task({ labels: ['pro'] });
    expect(profileMatches(t, { exclude_labels: ['pro'] }, {}, {}, NOW)).toBe(false);
    expect(profileMatches(t, { exclude_labels: ['mechanic'] }, {}, {}, NOW)).toBe(true);
  });

  it('excludes on ANY hit across several excluded labels', () => {
    const t = task({ labels: ['dog', 'pro'] });
    expect(profileMatches(t, { exclude_labels: ['mechanic', 'pro'] }, {}, {}, NOW)).toBe(false);
  });

  it('lets an exclusion beat a satisfied include', () => {
    // This is the whole point of #214: "everything on my list except the call-outs".
    const t = task({ labels: ['dog', 'pro'] });
    expect(profileMatches(t, { labels: ['dog'] }, {}, {}, NOW)).toBe(true);
    expect(profileMatches(t, { labels: ['dog'], exclude_labels: ['pro'] }, {}, {}, NOW)).toBe(
      false,
    );
  });

  it('treats an empty or absent exclude list as "exclude nothing"', () => {
    // An inverted check here would empty every profile at once, so pin both spellings.
    const t = task({ labels: ['dog'], area_id: 'kitchen', device_id: 'd2' });
    expect(
      profileMatches(
        t,
        { exclude_labels: [], exclude_areas: [], exclude_devices: [] },
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
      profileMatches(task({ device_id: 'd1' }), { exclude_labels: ['pro'] }, devices, areas, NOW),
    ).toBe(false);
    expect(
      profileMatches(
        task({ area_id: 'kitchen' }),
        { exclude_labels: ['indoors'] },
        devices,
        areas,
        NOW,
      ),
    ).toBe(false);
  });

  it('drops a task in an excluded area, including one inherited from its device', () => {
    expect(
      profileMatches(task({ area_id: 'garage' }), { exclude_areas: ['garage'] }, devices, {}, NOW),
    ).toBe(false);
    expect(
      profileMatches(task({ device_id: 'd2' }), { exclude_areas: ['garage'] }, devices, {}, NOW),
    ).toBe(false);
    expect(
      profileMatches(task({ area_id: 'kitchen' }), { exclude_areas: ['garage'] }, devices, {}, NOW),
    ).toBe(true);
  });

  it('drops a task on an excluded device', () => {
    expect(
      profileMatches(task({ device_id: 'd1' }), { exclude_devices: ['d1'] }, devices, {}, NOW),
    ).toBe(false);
    expect(
      profileMatches(task({ device_id: 'd2' }), { exclude_devices: ['d1'] }, devices, {}, NOW),
    ).toBe(true);
  });

  it('does not sweep up an area-less or device-less task', () => {
    // The placeholder '' must not collide with a real id, or every unattached task
    // would vanish the moment any exclusion was set.
    const bare = task();
    expect(profileMatches(bare, { exclude_areas: ['garage'] }, {}, {}, NOW)).toBe(true);
    expect(profileMatches(bare, { exclude_devices: ['d1'] }, {}, {}, NOW)).toBe(true);
  });
});

describe('profileMatches companions', () => {
  const owned = (integration) =>
    task({ managed_by: { integration, display_name: 'Battery Notes' } });

  it('selects only tasks owned by a named integration', () => {
    const filter = { companions: ['battery_notes'] };
    expect(profileMatches(owned('battery_notes'), filter, {}, {}, NOW)).toBe(true);
    expect(profileMatches(owned('printer_glue'), filter, {}, {}, NOW)).toBe(false);
  });

  it('matches any of several named integrations', () => {
    const filter = { companions: ['battery_notes', 'dog_glue'] };
    expect(profileMatches(owned('dog_glue'), filter, {}, {}, NOW)).toBe(true);
    expect(profileMatches(owned('printer_glue'), filter, {}, {}, NOW)).toBe(false);
  });

  it('never selects a task no integration owns', () => {
    // A task made in the panel has no managed_by, so "just the battery tasks" must
    // not quietly include the user's own chores.
    expect(profileMatches(task(), { companions: ['battery_notes'] }, {}, {}, NOW)).toBe(false);
    const nameless = task({ managed_by: { display_name: 'Nameless' } });
    expect(profileMatches(nameless, { companions: ['battery_notes'] }, {}, {}, NOW)).toBe(false);
  });

  it('treats an explicitly null managed_by like an absent one', () => {
    const nulled = task({ managed_by: null });
    expect(profileMatches(nulled, { companions: ['battery_notes'] }, {}, {}, NOW)).toBe(false);
    expect(
      profileMatches(nulled, { exclude_companions: ['battery_notes'] }, {}, {}, NOW),
    ).toBe(true);
  });

  it('drops a task owned by an excluded integration', () => {
    const filter = { exclude_companions: ['battery_notes'] };
    expect(profileMatches(owned('battery_notes'), filter, {}, {}, NOW)).toBe(false);
    expect(profileMatches(owned('dog_glue'), filter, {}, {}, NOW)).toBe(true);
  });

  it('does not sweep up an unowned task with a non-empty exclude list', () => {
    expect(
      profileMatches(task(), { exclude_companions: ['battery_notes'] }, {}, {}, NOW),
    ).toBe(true);
  });

  it('lets the exclude list win over a matching include', () => {
    expect(
      profileMatches(
        owned('battery_notes'),
        { companions: ['battery_notes'], exclude_companions: ['battery_notes'] },
        {},
        {},
        NOW,
      ),
    ).toBe(false);
  });

  it('treats an empty or absent companions list as every owner', () => {
    expect(profileMatches(owned('battery_notes'), { companions: [] }, {}, {}, NOW)).toBe(true);
    expect(profileMatches(owned('battery_notes'), {}, {}, {}, NOW)).toBe(true);
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
    expect(profileHasAnyTask([other, mine], { labels: ['dog'] }, {}, {}, NOW)).toBe(true);
  });

  it('keeps the rest of the filter, so a label nobody carries matches nothing', () => {
    expect(profileHasAnyTask([task()], { labels: ['dog'] }, {}, {}, NOW)).toBe(false);
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
