/**
 * The recipe dialog's **More filters** block (#373): the selection filters past
 * integration and domain, and the four exclusion lists.
 *
 * Pure helpers only, so the mutation gate can score them. The dialog in
 * `panel-declarative.ts` builds the DOM from these schemas and reads the summary
 * line and the default open state from here.
 */

import { selArea, selDevice, selEntity, selLabel, selText, type FormField } from './forms';
import { t, tn } from './i18n';
import type { DeclarativeCompanionSelection } from './types';

/** The four exclusion lists, in the order the dialog shows their pickers. */
export const EXCLUSION_FIELDS = [
  'exclude_entity_ids',
  'exclude_device_ids',
  'exclude_area_ids',
  'exclude_label_ids',
] as const;
export type ExclusionField = (typeof EXCLUSION_FIELDS)[number];

/** The filters inside **More filters**, above the exclusions. */
export function moreFiltersSchema(): FormField[] {
  return [
    { name: 'device_class', selector: selText() },
    { name: 'area_ids', selector: selArea(true) },
    { name: 'label_ids', selector: selLabel(true) },
    { name: 'entity_regex', selector: selText() },
  ];
}

/**
 * The four exclusion pickers. The entity picker has no domain filter: the domain
 * box above it can change while the dialog is open, and a filter set at render
 * time would then hide the entities the user wants to pick.
 */
export function exclusionsSchema(): FormField[] {
  return [
    { name: 'exclude_entity_ids', selector: selEntity({}, true) },
    { name: 'exclude_device_ids', selector: selDevice(true) },
    { name: 'exclude_area_ids', selector: selArea(true) },
    { name: 'exclude_label_ids', selector: selLabel(true) },
  ];
}

/** How many filters inside **More filters** are set. A list counts once. */
export function filterCount(sel: Partial<DeclarativeCompanionSelection>): number {
  return [
    Boolean(sel.device_class),
    Boolean(sel.entity_regex),
    (sel.area_ids?.length ?? 0) > 0,
    (sel.label_ids?.length ?? 0) > 0,
  ].filter(Boolean).length;
}

/** How many ids the four exclusion lists hold together. */
export function exclusionCount(sel: Partial<DeclarativeCompanionSelection>): number {
  return EXCLUSION_FIELDS.reduce((n, f) => n + (sel[f]?.length ?? 0), 0);
}

/** Whether **More filters** holds anything. It then opens by default. */
export function hasMoreFilters(sel: Partial<DeclarativeCompanionSelection>): boolean {
  return filterCount(sel) + exclusionCount(sel) > 0;
}

/** The closed row's summary: "2 filters · 3 exclusions", or a line that says none. */
export function moreFiltersSummary(sel: Partial<DeclarativeCompanionSelection>): string {
  const filters = filterCount(sel);
  const excluded = exclusionCount(sel);
  const parts: string[] = [];
  if (filters) parts.push(tn('declarative.companions.summary_filters', filters));
  if (excluded) parts.push(tn('declarative.companions.summary_exclusions', excluded));
  return parts.length ? parts.join(' · ') : t('declarative.companions.more_filters_none');
}

/** *list* with *id* added at the end, or removed when it is already there. */
export function toggleId(list: readonly string[] | undefined, id: string): string[] {
  const ids = list ?? [];
  return ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
}

/** A form value read as a list of ids; anything that is not a list is empty. */
export function idList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}
