/**
 * Which shipped presets the Tasks tab suggests, and what the user has already seen.
 *
 * The panel suggests a preset when it matches at least one entity in this home, no
 * declarative companion made from it exists yet, and this user has not dismissed it.
 * A one-time dialog lists the suggestions first; after "Not now", a card above the
 * task list keeps them until the user sets them up or hides them. The card lists
 * only presets the panel has offered, so the dialog is always the first thing a
 * user sees about a preset.
 *
 * A preset that matches more than `ONE_STEP_MAX` entities stays out of the dialog,
 * because one click there would make that many tasks with no review. It goes to the
 * card, where Set up opens the Add dialog and its preview.
 *
 * The user's answers live in Home Assistant's per-user frontend data under
 * `home_keeper_preset_nudge`, as `{ shown, dismissed }` lists of preset ids. Both
 * lists only grow, so two copies merge by union and a write can never undo another.
 *
 * Pure: no DOM, no `t()`, no Home Assistant calls. The panel renders what this
 * returns (`panel-preset-nudge.ts`).
 */

import type { DeclarativeCompanion, DeclarativeCompanionPreset } from './types';

export interface PresetNudgeState {
  /** Preset ids the one-time dialog has offered to this user. */
  shown: string[];
  /** Preset ids this user hid from the card. */
  dismissed: string[];
}

/** Above this many matches a preset needs the Add dialog's review, not one click.
 *  The same number as `const.MAX_DECLARATIVE_MATCH_WARN`, where the preview warns. */
export const ONE_STEP_MAX = 50;

/**
 * A guard against a corrupt stored value, far above the catalog. It was 100, which
 * the catalog passed when the integration presets came in: an id past the limit was
 * dropped on read, so a preset hidden late came back on the next load.
 */
export const MAX_IDS = 1000;

function idList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const id of raw) {
    if (typeof id === 'string' && id && !out.includes(id)) out.push(id);
    if (out.length === MAX_IDS) break;
  }
  return out;
}

/** The stored value as a state; anything that is not the expected shape reads empty. */
export function parseNudgeState(raw: unknown): PresetNudgeState {
  if (!raw || typeof raw !== 'object') return { shown: [], dismissed: [] };
  const value = raw as { shown?: unknown; dismissed?: unknown };
  return { shown: idList(value.shown), dismissed: idList(value.dismissed) };
}

function union(a: string[], b: string[]): string[] {
  return [...a, ...b.filter((id) => !a.includes(id))];
}

/** Both states in one: an id either copy holds stays. *a* may be null (not loaded). */
export function mergeNudgeState(
  a: PresetNudgeState | null,
  b: PresetNudgeState,
): PresetNudgeState {
  if (!a) return { shown: [...b.shown], dismissed: [...b.dismissed] };
  return { shown: union(a.shown, b.shown), dismissed: union(a.dismissed, b.dismissed) };
}

/** A copy of *state* with *ids* added to `shown`. */
export function markShown(state: PresetNudgeState, ids: string[]): PresetNudgeState {
  return { shown: union(state.shown, ids), dismissed: [...state.dismissed] };
}

/** A copy of *state* with *ids* added to `dismissed`. */
export function markDismissed(state: PresetNudgeState, ids: string[]): PresetNudgeState {
  return { shown: [...state.shown], dismissed: union(state.dismissed, ids) };
}

/** The presets that match something here and have no companion yet, in catalog order. */
export function usablePresets(
  presets: DeclarativeCompanionPreset[] | null,
  companions: DeclarativeCompanion[],
): DeclarativeCompanionPreset[] {
  return (presets ?? []).filter(
    (preset) =>
      (preset.matches ?? 0) > 0 && !companions.some((c) => c.preset_id === preset.id),
  );
}

/**
 * The ids of the presets that have a companion, which the panel marks offered. A
 * user who made one from Settings and later deleted it has already met the preset,
 * so its return shows on the card and does not open the dialog.
 */
export function presetIdsWithCompanion(
  presets: DeclarativeCompanionPreset[] | null,
  companions: DeclarativeCompanion[],
): string[] {
  return (presets ?? [])
    .filter((preset) => companions.some((c) => c.preset_id === preset.id))
    .map((preset) => preset.id);
}

function notDismissed(
  usable: DeclarativeCompanionPreset[],
  state: PresetNudgeState,
): DeclarativeCompanionPreset[] {
  return usable.filter((preset) => !state.dismissed.includes(preset.id));
}

/** The usable presets the panel has not offered to this user yet. */
export function newPresets(
  usable: DeclarativeCompanionPreset[],
  state: PresetNudgeState,
): DeclarativeCompanionPreset[] {
  return notDismissed(usable, state).filter((preset) => !state.shown.includes(preset.id));
}

/** What the card lists: the usable presets already offered and not hidden. */
export function cardPresets(
  usable: DeclarativeCompanionPreset[],
  state: PresetNudgeState,
): DeclarativeCompanionPreset[] {
  return notDismissed(usable, state).filter((preset) => state.shown.includes(preset.id));
}

/**
 * What the dialog lists, or nothing when it should stay closed. It opens when a
 * usable preset is new to the user, and then it lists every usable preset that is
 * small enough to add in one step, so the user sees the whole choice in one place.
 */
export function dialogPresets(
  usable: DeclarativeCompanionPreset[],
  state: PresetNudgeState,
): DeclarativeCompanionPreset[] {
  if (!newPresets(usable, state).length) return [];
  return notDismissed(usable, state).filter(
    (preset) => (preset.matches ?? 0) <= ONE_STEP_MAX,
  );
}

export interface AddOutcome {
  /** `all` added, `some` added, or `none` added. */
  kind: 'all' | 'some' | 'none';
  added: number;
  total: number;
  /** The first error message, for the toast when nothing was added. */
  error: string;
}

/** Sum up the results of adding presets one by one. */
export function addOutcome(results: { ok: boolean; error?: string }[]): AddOutcome {
  const added = results.filter((r) => r.ok).length;
  const total = results.length;
  const error = results.find((r) => !r.ok)?.error ?? '';
  const kind = added === total ? 'all' : added === 0 ? 'none' : 'some';
  return { kind, added, total, error };
}
