/**
 * The pure logic of the Settings -> Import and export card.
 *
 * The card (`panel-settings.renderTransfer`) draws what these functions decide:
 * which sources the export lists, which `include` names a button sends, which path
 * a chosen file takes to the backend, and the rows of the preview table. No DOM and
 * no Home Assistant here, so each decision has direct tests.
 */
import { MAX_BUNDLE_BYTES, MAX_IMPORT_BYTES, MAX_IMPORT_WS_BYTES } from './limits';
import type { Companion, ImportProblem, ImportReport } from './types';

/** The capability a companion registers to join the export and the import. */
export const IMPORT_EXPORT_CAPABILITY = 'import_export';

/** The Home Keeper sections. The "Tasks and appliances" row selects both. */
export const HK_SECTIONS = ['appliances', 'tasks'] as const;

/** The `include` name that adds the settings to a bundle. */
export const SETTINGS_INCLUDE = 'settings';

/** The settings sections of a document, as the import report names them. */
export const SETTINGS_SECTIONS = ['profiles', 'notifications', 'options'] as const;

/** The key of the "Tasks and appliances" row. */
export const SOURCE_HK = 'home_keeper';
/** The key of the "Files" row. A bundle always holds the files. */
export const SOURCE_FILES = 'files';
/** The key of the "Settings" row. */
export const SOURCE_SETTINGS = 'settings';

/** One row of the export list. */
export interface ExportSource {
  /** `home_keeper`, a companion domain, `files` or `settings`. */
  key: string;
  kind: 'home_keeper' | 'companion' | 'files' | 'settings';
  /** The companion name. Empty for a Home Keeper row, which the card labels. */
  name: string;
  /** Only a bundle holds this row. */
  bundleOnly: boolean;
  /** The row cannot be cleared. */
  fixed: boolean;
}

/** The companions that join the export: connected, with the import and export
 *  capability. In the order of the list, which is the order of registration. */
export function transferCompanions(companions: Companion[]): Companion[] {
  return companions.filter(
    (c) =>
      c.status === 'connected' && (c.capabilities ?? []).includes(IMPORT_EXPORT_CAPABILITY),
  );
}

/** The rows of the export list, in the order the card shows them. */
export function exportSources(companions: Companion[]): ExportSource[] {
  return [
    { key: SOURCE_HK, kind: 'home_keeper', name: '', bundleOnly: false, fixed: false },
    ...transferCompanions(companions).map(
      (c): ExportSource => ({
        key: c.domain,
        kind: 'companion',
        name: c.name || c.domain,
        bundleOnly: false,
        fixed: false,
      }),
    ),
    { key: SOURCE_FILES, kind: 'files', name: '', bundleOnly: true, fixed: true },
    { key: SOURCE_SETTINGS, kind: 'settings', name: '', bundleOnly: true, fixed: false },
  ];
}

/** Whether the row *source* is checked. A row the user did not touch has its
 *  default: every row is on except Settings. A fixed row is always on. */
export function isPicked(source: ExportSource, picked: Record<string, boolean>): boolean {
  if (source.fixed) return true;
  return picked[source.key] ?? source.kind !== 'settings';
}

/**
 * The `include` list for an export of *kind*, or `null` when the export holds no
 * section.
 *
 * The backend reads an empty `include` as "every section", so this never returns
 * an empty list. A YAML export holds only the data rows. A bundle also holds the
 * settings when that row is checked. The files go in every bundle and have no
 * `include` name.
 */
export function exportInclude(
  sources: ExportSource[],
  picked: Record<string, boolean>,
  kind: 'yaml' | 'bundle',
): string[] | null {
  const include: string[] = [];
  for (const source of sources) {
    if (!isPicked(source, picked)) continue;
    if (source.kind === 'home_keeper') include.push(...HK_SECTIONS);
    else if (source.kind === 'companion') include.push(source.key);
    else if (source.kind === 'settings' && kind === 'bundle') include.push(SETTINGS_INCLUDE);
  }
  return include.length ? include : null;
}

/**
 * The rows that an export holds, for the line after the export.
 *
 * *include* is the list the export sent. For a YAML export, *document* is the
 * returned document: a companion that failed has no section in it, so it is not
 * named. A bundle returns only the file, so the rows come from *include*, plus the
 * files.
 */
export function exportedSources(
  sources: ExportSource[],
  include: string[],
  document: Record<string, unknown> | null,
): ExportSource[] {
  const has = (key: string): boolean => (document ? key in document : include.includes(key));
  return sources.filter((source) => {
    if (source.kind === 'home_keeper') return HK_SECTIONS.some((s) => include.includes(s) && has(s));
    if (source.kind === 'companion') return include.includes(source.key) && has(source.key);
    if (source.kind === 'files') return document === null;
    return include.includes(SETTINGS_INCLUDE) && (document === null || SETTINGS_SECTIONS.some(has));
  });
}

/** The companions an export asked for that the document does not hold. */
export function missingCompanions(
  sources: ExportSource[],
  include: string[],
  document: Record<string, unknown>,
): ExportSource[] {
  return sources.filter(
    (s) => s.kind === 'companion' && include.includes(s.key) && !(s.key in document),
  );
}

/** How a chosen file goes to the backend. */
export type FileRoute = 'read' | 'upload' | 'too_large';

/** Whether *file* is a bundle (a zip file), by its name or its type. */
export function isBundleFile(file: { name: string; type?: string }): boolean {
  return /\.zip$/i.test(file.name) || /zip/i.test(file.type ?? '');
}

/**
 * The path of a chosen file.
 *
 * - `read`: a text file that fits a websocket message. The panel reads it into the
 *   text box, so the user can see it and change it.
 * - `upload`: a bundle, or a text file over the websocket limit. It goes to the
 *   upload view as it is.
 * - `too_large`: over the limit of the backend for its kind.
 */
export function fileRoute(file: { name: string; size: number; type?: string }): FileRoute {
  if (isBundleFile(file)) return file.size > MAX_BUNDLE_BYTES ? 'too_large' : 'upload';
  if (file.size <= MAX_IMPORT_WS_BYTES) return 'read';
  return file.size > MAX_IMPORT_BYTES ? 'too_large' : 'upload';
}

/** The limit in MB that refused *file*, for the message. */
export function fileLimitMb(file: { name: string; type?: string }): number {
  return (isBundleFile(file) ? MAX_BUNDLE_BYTES : MAX_IMPORT_BYTES) / (1024 * 1024);
}

/** One row of the preview table. */
export interface ReportRow {
  /** `appliances`, `tasks`, `files`, `settings` or a companion domain. */
  key: string;
  kind: 'section' | 'files' | 'settings' | 'companion';
  /** The companion name. Empty for a Home Keeper row, which the card labels. */
  name: string;
  created: number;
  updated: number;
  /** Files: the files that the records already have. */
  unchanged: number;
  /** Tasks: the history entries. */
  history: number;
  problems: ImportProblem[];
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * The created and updated records in the `counts` of a companion report.
 *
 * Each companion owns the shape. A flat `{created, updated}` is read as it is.
 * Else each value that is an object is a section, such as `books: {created,
 * updated, skipped}`, and the sections are added. Other keys are ignored.
 */
export function sumCounts(counts: unknown): { created: number; updated: number } {
  if (!isObject(counts)) return { created: 0, updated: 0 };
  if ('created' in counts || 'updated' in counts) {
    return { created: num(counts.created), updated: num(counts.updated) };
  }
  let created = 0;
  let updated = 0;
  for (const value of Object.values(counts)) {
    if (!isObject(value)) continue;
    created += num(value.created);
    updated += num(value.updated);
  }
  return { created, updated };
}

/** The `section` of a problem, which names the part of the document it is in. */
function sectionOf(problem: ImportProblem): string {
  return problem.section ?? '';
}

/**
 * The rows of the preview table: Appliances and Tasks, then the files and the
 * settings when the report counts them, then 1 row per companion section. Each row
 * holds the problems of its part, errors first.
 */
export function reportRows(report: ImportReport, companions: Companion[]): ReportRow[] {
  const problems = [...report.problems].sort(
    (a, b) => Number(b.severity === 'error') - Number(a.severity === 'error'),
  );
  const names = new Map(companions.map((c) => [c.domain, c.name]));
  const counts = report.counts as Record<string, unknown>;
  const pick = (keys: readonly string[]): ImportProblem[] =>
    problems.filter((p) => keys.includes(sectionOf(p)));
  const row = (key: string, kind: ReportRow['kind'], name = ''): ReportRow => ({
    key,
    kind,
    name,
    created: 0,
    updated: 0,
    unchanged: 0,
    history: 0,
    problems: pick([key]),
  });

  const rows: ReportRow[] = HK_SECTIONS.map((section) => ({
    ...row(section, 'section'),
    ...sumCounts(counts[section]),
  }));
  rows[1].history = num(counts.completions);

  if (isObject(counts.files)) {
    rows.push({
      ...row('files', 'files'),
      created: num(counts.files.created),
      unchanged: num(counts.files.unchanged),
    });
  }
  if (isObject(counts.settings)) {
    const settings = counts.settings;
    const sum = sumCounts(settings);
    const options = isObject(settings.options) ? num(settings.options.changed) : 0;
    rows.push({
      ...row(SOURCE_SETTINGS, 'settings'),
      created: sum.created,
      updated: sum.updated + options,
      problems: pick(SETTINGS_SECTIONS),
    });
  }
  for (const [domain, section] of Object.entries(report.sections ?? {})) {
    rows.push({
      ...row(domain, 'companion', names.get(domain) || domain),
      ...sumCounts(isObject(section) ? section.counts : undefined),
    });
  }
  return rows;
}

/** The problems that no row of the table holds, errors first. */
export function otherProblems(report: ImportReport, rows: ReportRow[]): ImportProblem[] {
  const held = new Set(rows.flatMap((r) => r.problems));
  return [...report.problems]
    .filter((p) => !held.has(p))
    .sort((a, b) => Number(b.severity === 'error') - Number(a.severity === 'error'));
}

/** Whether the previewed document has settings sections. Then the card offers to
 *  import them. A preview without `include_settings` warns for each section it
 *  skips, and a preview with it counts them. */
export function reportHasSettings(report: ImportReport | null): boolean {
  if (!report) return false;
  if (isObject((report.counts as Record<string, unknown>).settings)) return true;
  return report.problems.some((p) =>
    (SETTINGS_SECTIONS as readonly string[]).includes(sectionOf(p)),
  );
}

/** The alert of a report: its type and the key of its message. */
export interface ReportVerdict {
  type: 'success' | 'warning' | 'error';
  key: string;
}

/**
 * The alert above the preview table. A real import that failed after its write
 * started (`partial`) keeps the data that it wrote, so it does not say that nothing
 * was imported.
 */
export function reportVerdict(report: ImportReport): ReportVerdict {
  if (report.ok) {
    return { type: 'success', key: report.dry_run ? 'transfer.previewOk' : 'transfer.importOk' };
  }
  if (!report.dry_run && report.partial === true) {
    return { type: 'warning', key: 'transfer.importPartial' };
  }
  return { type: 'error', key: 'transfer.previewFailed' };
}

/**
 * The text of a chosen file, or `null` if it is not text. A file that is not UTF-8,
 * or that holds a NUL byte, is binary. It does not go into the text box.
 */
export function decodeText(bytes: Uint8Array): string | null {
  if (bytes.includes(0)) return null;
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}
