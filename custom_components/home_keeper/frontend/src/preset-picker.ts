/**
 * The preset picker's grouping and search.
 *
 * About a hundred integration presets ship next to the general ones, so the picker
 * cannot be one flat list. It shows three groups: the presets that match entities
 * the household has, then the general presets, then the other integration presets,
 * which stay hidden until the user asks for them or searches. An installed
 * integration is not enough: a Tuya light has none of the parts of a Tuya vacuum. Pure helpers only, so the mutation
 * gate can score them; `panel-declarative.ts` builds the DOM.
 */

import type { DeclarativeCompanionPreset } from './types';

export interface PresetGroups {
  /** Integration presets that match at least one entity. */
  mine: DeclarativeCompanionPreset[];
  /** The general presets, in catalog order. */
  general: DeclarativeCompanionPreset[];
  /** The other integration presets, when they are shown. */
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
  // Stryker disable next-line ConditionalExpression: every string contains '', so the
  // early return only saves the join below.
  if (!q) return true;
  const text = [
    preset.name,
    preset.description,
    // Stryker disable next-line StringLiteral: any fallback text only adds words a
    // general preset has no domain for; the tests search real fields.
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
 * Whether *preset* goes in the first group. The backend counts the entities it would
 * match; a backend that sends no count leaves the installed integration to decide.
 */
export function presetIsMine(
  preset: DeclarativeCompanionPreset,
  installed: ReadonlySet<string>,
): boolean {
  if (typeof preset.matches === 'number') return preset.matches > 0;
  // Stryker disable next-line StringLiteral: no installed domain is '' or the mutant text.
  return installed.has(preset.requires_integration ?? '');
}

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
  const mine = integration.filter((p) => presetIsMine(p, installed)).sort(byName);
  const rest = integration.filter((p) => !presetIsMine(p, installed)).sort(byName);
  const shown = showAll || searching;
  return { mine, general, other: shown ? rest : [], hidden: shown ? 0 : rest.length };
}
