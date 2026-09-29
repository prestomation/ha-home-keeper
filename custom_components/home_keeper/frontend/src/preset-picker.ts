/**
 * The preset picker's grouping and search.
 *
 * About a hundred integration presets ship next to the general ones, so the picker
 * cannot be one flat list. It shows three groups: the presets for integrations the
 * household has, then the general presets, then the other integrations, which stay
 * hidden until the user asks for them or searches. Pure helpers only, so the mutation
 * gate can score them; `panel-declarative.ts` builds the DOM.
 */

import type { DeclarativeCompanionPreset } from './types';

export interface PresetGroups {
  /** Integration presets whose integration is installed. */
  mine: DeclarativeCompanionPreset[];
  /** The general presets, in catalog order. */
  general: DeclarativeCompanionPreset[];
  /** Integration presets whose integration is not installed, when they are shown. */
  other: DeclarativeCompanionPreset[];
  /** How many presets **Show all** would add. */
  hidden: number;
}

/** The distinct task names a preset gives its tasks, in catalog order. */
export function presetTaskNames(preset: DeclarativeCompanionPreset): string[] {
  const names = preset.default_spec.task_template.task_names ?? {};
  return [...new Set(Object.values(names))];
}

/** Whether *preset* matches the search *query*: name, description, domain or a task. */
export function presetMatches(preset: DeclarativeCompanionPreset, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const text = [
    preset.name,
    preset.description,
    preset.requires_integration ?? '',
    ...presetTaskNames(preset),
  ]
    .join('\n')
    .toLowerCase();
  return text.includes(q);
}

const byName = (a: DeclarativeCompanionPreset, b: DeclarativeCompanionPreset): number =>
  a.name.localeCompare(b.name);

/**
 * Split *presets* into the picker's groups. A search shows every group that has a
 * match, the other integrations included; with no search they show only when
 * *showAll* is set.
 */
export function groupPresets(
  presets: readonly DeclarativeCompanionPreset[],
  installed: ReadonlySet<string>,
  query: string,
  showAll: boolean,
): PresetGroups {
  const searching = query.trim() !== '';
  const matching = presets.filter((p) => presetMatches(p, query));
  const general = matching.filter((p) => p.group !== 'integration');
  const integration = matching.filter((p) => p.group === 'integration');
  const mine = integration
    .filter((p) => installed.has(p.requires_integration ?? ''))
    .sort(byName);
  const rest = integration
    .filter((p) => !installed.has(p.requires_integration ?? ''))
    .sort(byName);
  const shown = showAll || searching;
  return { mine, general, other: shown ? rest : [], hidden: shown ? 0 : rest.length };
}
