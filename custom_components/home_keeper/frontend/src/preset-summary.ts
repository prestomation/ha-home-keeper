/**
 * The preset summary at the top of the companion form: which preset a draft came
 * from, which of its sections the user changed, and how far a preview row's reading
 * is from the preset's limit.
 *
 * Pure: no DOM, no Home Assistant. The form draws what these return.
 */

import type {
  DeclarativeCompanion,
  DeclarativeCompanionPreset,
  PresetLimit,
} from './types';
import { EXCLUSION_FIELDS } from './declarative-filters';

/** The form sections a preset decides. Name, description, enabled and the
 *  exclusions are the user's own, so a change there is not a change from the preset. */
export type PresetSection = 'selection' | 'trigger' | 'task_template';
export const PRESET_SECTIONS: readonly PresetSection[] = ['selection', 'trigger', 'task_template'];

type PresetSpec = DeclarativeCompanionPreset['default_spec'];

/** The preset *draft* came from, or `null` when it names none or an unknown one. */
export function presetFor(
  draft: Pick<DeclarativeCompanion, 'preset_id'>,
  presets: readonly DeclarativeCompanionPreset[] | null,
): DeclarativeCompanionPreset | null {
  if (!draft.preset_id || !presets) return null;
  return presets.find((p) => p.id === draft.preset_id) ?? null;
}

/**
 * *value* with every empty member removed and the keys sorted, so two specs that
 * say the same thing compare equal. The form writes `undefined` for a box it
 * cleared, the backend stores `null` or `[]` for the same, and neither is a change.
 */
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value).sort()) {
      const member = canonical((value as Record<string, unknown>)[key]);
      if (isEmpty(member)) continue;
      out[key] = member;
    }
    return out;
  }
  return value;
}

function isEmpty(value: unknown): boolean {
  if (value == null || value === '') return true;
  // An empty list has no keys either, so this covers `[]` as well as `{}`.
  return typeof value === 'object' && Object.keys(value as object).length === 0;
}

/** The part of *section* that the preset decides, ready to compare. */
function comparable(spec: PresetSpec | DeclarativeCompanion, section: PresetSection): unknown {
  const value = { ...(spec[section] as unknown as Record<string, unknown>) };
  // Only the selection has exclusions, and only the trigger has a hold, so each rule
  // leaves the other sections alone. The form writes a hold of 0 the first time the
  // trigger changes, and a hold of 0 is no hold.
  for (const field of EXCLUSION_FIELDS) delete value[field];
  if (value.for_seconds === 0) delete value.for_seconds;
  return canonical(value);
}

/** The sections of *draft* that differ from the preset's *spec*, in form order. */
export function changedSections(
  draft: DeclarativeCompanion,
  spec: PresetSpec,
): PresetSection[] {
  return PRESET_SECTIONS.filter(
    (section) =>
      JSON.stringify(comparable(draft, section)) !== JSON.stringify(comparable(spec, section)),
  );
}

/**
 * *draft* with the preset's sections put back from *spec*. The id, the name, the
 * description, enabled and the exclusions stay as the user set them.
 */
export function resetToPreset(
  draft: DeclarativeCompanion,
  spec: PresetSpec,
): DeclarativeCompanion {
  const copy = JSON.parse(JSON.stringify(spec)) as PresetSpec;
  const selection = { ...copy.selection };
  for (const field of EXCLUSION_FIELDS) selection[field] = draft.selection[field] ?? [];
  return {
    ...draft,
    selection,
    trigger: copy.trigger,
    task_template: copy.task_template,
  };
}

// Hours in one of each time unit, the same table as `_TIME_FACTORS` in
// declarative_presets.py, so the bar agrees with the trigger that opens the task.
const HOURS: Record<string, number> = {
  ms: 1 / 3600000,
  s: 1 / 3600,
  sec: 1 / 3600,
  seconds: 1 / 3600,
  min: 1 / 60,
  mins: 1 / 60,
  minutes: 1 / 60,
  h: 1,
  hr: 1,
  hrs: 1,
  hours: 1,
  d: 24,
  day: 24,
  days: 24,
  w: 168,
  week: 168,
  weeks: 168,
};

/**
 * How far a reading has come toward a limit it must rise *above*, from 0 to 1, or
 * `null` when there is no bar to draw: no limit, a limit it must fall below, or a
 * reading that is not a number.
 *
 * A time limit is in hours, and a reading in another time unit is converted first.
 * A unit that is not a time (washes, cycles) is read as it is, as the trigger does.
 */
export function limitProgress(
  state: string | null | undefined,
  unit: string | null | undefined,
  limit: PresetLimit | null | undefined,
): number | null {
  if (!limit || !limit.above || limit.value <= 0) return null;
  if (state == null || String(state).trim() === '') return null;
  const reading = Number(state);
  if (!Number.isFinite(reading)) return null;
  // Stryker disable next-line StringLiteral: no key for a missing unit is in the table.
  const factor = limit.kind === 'hours' ? (HOURS[String(unit ?? '')] ?? 1) : 1;
  return Math.min(1, Math.max(0, (reading * factor) / limit.value));
}
