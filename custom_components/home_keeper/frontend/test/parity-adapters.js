// The adapters of the parity registry (`tests/fixtures/parity.json`): 1 call of the
// shipped TypeScript function per rule id. `shared-cases.test.js` and
// `parity-corpus.test.js` both use them. An adapter only turns a case input into the
// function's arguments and its result into the form that the case file states. It
// holds no rule of its own.
import { readFileSync } from 'node:fs';
import { companionKeys, profileMatches } from '../src/card-filter.ts';
import { isLowPart, isUncountedPart } from '../src/parts-overview.ts';
import {
  decimalMark,
  formatQuantity,
  isBuyTask,
  isMonitoredDormant,
  normalizeIcon,
  taskSnoozeHours,
  usageIntervalStats,
  usesSinceReplacement,
} from '../src/utils.ts';

// vitest runs from the repository root (see vitest.config.js).
export const read = (path) => JSON.parse(readFileSync(path, 'utf8'));
export const REGISTRY = read('tests/fixtures/parity.json');

const usage = (completions) => {
  const stats = usageIntervalStats(completions);
  const out = {};
  for (const key of ['last', 'average', 'shortest', 'longest']) {
    if (stats[key] !== undefined) out[key] = stats[key];
  }
  return out;
};

export const ADAPTERS = {
  // Empty registries: a case task carries its effective ids, as the backend enriches
  // a task before it calls the pure matcher.
  profile_filter: (c, data) =>
    profileMatches(c.task, c.filter, {}, {}, new Date(c.now ?? data.now).getTime()),
  companion_keys: (c) => [...companionKeys(c.input)].sort(),
  quantity_format: (c) => formatQuantity(c.value, c.unit, c.lang ?? 'en'),
  decimal_mark: (c) => decimalMark(c.input ?? undefined),
  part_low: (c) => isLowPart(c.input),
  part_tracks_stock: (c) => !isUncountedPart(c.input),
  icon: (c) => normalizeIcon(c.input),
  snooze_hours: (c) => taskSnoozeHours(c.input),
  buy_task: (c) => isBuyTask(c.input),
  use_count: (c) => usesSinceReplacement(c.input.use, c.input.replace ?? undefined),
  usage_intervals: (c) => usage(c.input),
  // The list is a constant; isMonitoredDormant is where the panel reads it.
  edge_sensor_modes: (c) =>
    isMonitoredDormant({
      id: 't',
      recurrence_type: 'sensor',
      next_due: null,
      sensor: c.input === null ? {} : { mode: c.input },
    }),
};
