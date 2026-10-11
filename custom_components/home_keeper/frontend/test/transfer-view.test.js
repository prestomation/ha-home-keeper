/**
 * The pure decisions of the Import and export card: the export rows, the `include`
 * list of each button, the path of a chosen file, and the rows of the preview table.
 */
import { describe, expect, it } from 'vitest';
import {
  HK_SECTIONS,
  IMPORT_EXPORT_CAPABILITY,
  SETTINGS_INCLUDE,
  SETTINGS_SECTIONS,
  SOURCE_FILES,
  SOURCE_HK,
  SOURCE_SETTINGS,
  exportInclude,
  exportSources,
  exportedSources,
  fileLimitMb,
  fileRoute,
  isBundleFile,
  isPicked,
  missingCompanions,
  otherProblems,
  reportHasSettings,
  reportRows,
  sumCounts,
  transferCompanions,
} from '../src/transfer-view.ts';

const MB = 1024 * 1024;

const companion = (domain, extra = {}) => ({
  domain,
  name: domain[0].toUpperCase() + domain.slice(1),
  status: 'connected',
  capabilities: ['import_export'],
  ...extra,
});

describe('constants', () => {
  it('names the contract values of the backend', () => {
    expect(IMPORT_EXPORT_CAPABILITY).toBe('import_export');
    expect(HK_SECTIONS).toEqual(['appliances', 'tasks']);
    expect(SETTINGS_INCLUDE).toBe('settings');
    expect(SETTINGS_SECTIONS).toEqual(['profiles', 'notifications', 'options']);
    expect([SOURCE_HK, SOURCE_FILES, SOURCE_SETTINGS]).toEqual(['home_keeper', 'files', 'settings']);
  });
});

describe('transferCompanions', () => {
  it('keeps the connected companions with the capability, in order', () => {
    const list = [
      companion('library'),
      companion('suggested', { status: 'suggested' }),
      companion('nocap', { capabilities: ['care_schedules'] }),
      companion('none', { capabilities: undefined }),
      companion('pawsistant'),
    ];
    expect(transferCompanions(list).map((c) => c.domain)).toEqual(['library', 'pawsistant']);
  });
});

describe('exportSources', () => {
  it('lists Home Keeper, the companions, the files and the settings', () => {
    const sources = exportSources([companion('library'), companion('x', { name: '' })]);
    expect(sources).toEqual([
      { key: 'home_keeper', kind: 'home_keeper', name: '', bundleOnly: false, fixed: false },
      { key: 'library', kind: 'companion', name: 'Library', bundleOnly: false, fixed: false },
      // A companion with no name shows its domain.
      { key: 'x', kind: 'companion', name: 'x', bundleOnly: false, fixed: false },
      { key: 'files', kind: 'files', name: '', bundleOnly: true, fixed: true },
      { key: 'settings', kind: 'settings', name: '', bundleOnly: true, fixed: false },
    ]);
  });
});

describe('isPicked', () => {
  const [hk, lib, files, settings] = exportSources([companion('library')]);

  it('turns every row on by default, except the settings', () => {
    expect([hk, lib, files, settings].map((s) => isPicked(s, {}))).toEqual([true, true, true, false]);
  });

  it('reads the choice of the user', () => {
    const picked = { home_keeper: false, library: false, settings: true };
    expect([hk, lib, settings].map((s) => isPicked(s, picked))).toEqual([false, false, true]);
  });

  it('keeps a fixed row on', () => {
    expect(isPicked(files, { files: false })).toBe(true);
  });
});

describe('exportInclude', () => {
  const sources = exportSources([companion('library'), companion('pawsistant')]);

  it('sends the data rows for a YAML file, never the settings', () => {
    expect(exportInclude(sources, { settings: true }, 'yaml')).toEqual([
      'appliances',
      'tasks',
      'library',
      'pawsistant',
    ]);
  });

  it('adds the settings to a bundle only when the row is on', () => {
    expect(exportInclude(sources, {}, 'bundle')).toEqual(['appliances', 'tasks', 'library', 'pawsistant']);
    expect(exportInclude(sources, { settings: true }, 'bundle')).toEqual([
      'appliances',
      'tasks',
      'library',
      'pawsistant',
      'settings',
    ]);
  });

  it('leaves out a cleared row', () => {
    expect(exportInclude(sources, { home_keeper: false, library: false }, 'yaml')).toEqual([
      'pawsistant',
    ]);
  });

  it('answers null for an export with no section, because an empty list means all', () => {
    const none = { home_keeper: false, library: false, pawsistant: false };
    expect(exportInclude(sources, none, 'yaml')).toBe(null);
    expect(exportInclude(sources, none, 'bundle')).toBe(null);
    expect(exportInclude(sources, { ...none, settings: true }, 'yaml')).toBe(null);
    expect(exportInclude(sources, { ...none, settings: true }, 'bundle')).toEqual(['settings']);
  });
});

describe('exportedSources', () => {
  const sources = exportSources([companion('library'), companion('pawsistant')]);
  const keys = (list) => list.map((s) => s.key);

  it('names the rows of a YAML file that are in the document', () => {
    const include = ['appliances', 'tasks', 'library', 'pawsistant'];
    const document = { home_keeper: {}, appliances: [], tasks: [], library: {} };
    expect(keys(exportedSources(sources, include, document))).toEqual(['home_keeper', 'library']);
  });

  it('names Home Keeper when 1 of its sections is in the document', () => {
    expect(keys(exportedSources(sources, ['tasks'], { tasks: [] }))).toEqual(['home_keeper']);
    // A section the export did not ask for does not count.
    expect(keys(exportedSources(sources, ['library'], { tasks: [], library: {} }))).toEqual([
      'library',
    ]);
  });

  it('names the settings of a YAML file only when the document has them', () => {
    const include = ['tasks', 'settings'];
    expect(keys(exportedSources(sources, include, { tasks: [] }))).toEqual(['home_keeper']);
    expect(keys(exportedSources(sources, include, { tasks: [], profiles: [] }))).toEqual([
      'home_keeper',
      'settings',
    ]);
    expect(keys(exportedSources(sources, ['tasks'], { tasks: [], options: {} }))).toEqual([
      'home_keeper',
    ]);
  });

  it('names the requested rows and the files for a bundle', () => {
    expect(keys(exportedSources(sources, ['appliances', 'pawsistant', 'settings'], null))).toEqual([
      'home_keeper',
      'pawsistant',
      'files',
      'settings',
    ]);
    expect(keys(exportedSources(sources, ['library'], null))).toEqual(['library', 'files']);
  });
});

describe('missingCompanions', () => {
  it('names each requested companion that the document lacks', () => {
    const sources = exportSources([companion('library'), companion('pawsistant')]);
    const missing = missingCompanions(sources, ['tasks', 'library', 'pawsistant'], {
      tasks: [],
      library: {},
    });
    expect(missing.map((s) => s.key)).toEqual(['pawsistant']);
    // A companion that the export did not ask for is not missing.
    expect(missingCompanions(sources, ['tasks', 'tasks'], { tasks: [] })).toEqual([]);
  });
});

describe('isBundleFile and fileRoute', () => {
  it('knows a bundle by its extension or its type', () => {
    expect(isBundleFile({ name: 'home.ZIP' })).toBe(true);
    expect(isBundleFile({ name: 'home', type: 'application/x-zip-compressed' })).toBe(true);
    expect(isBundleFile({ name: 'home.zip.yaml', type: 'application/yaml' })).toBe(false);
    expect(isBundleFile({ name: 'zip.yaml' })).toBe(false);
  });

  it('reads a text file that fits the websocket', () => {
    expect(fileRoute({ name: 'a.yaml', size: 0 })).toBe('read');
    expect(fileRoute({ name: 'a.yaml', size: 4 * MB })).toBe('read');
  });

  it('uploads a text file over the websocket limit, up to the service limit', () => {
    expect(fileRoute({ name: 'a.yaml', size: 4 * MB + 1 })).toBe('upload');
    expect(fileRoute({ name: 'a.yaml', size: 8 * MB })).toBe('upload');
    expect(fileRoute({ name: 'a.yaml', size: 8 * MB + 1 })).toBe('too_large');
  });

  it('uploads a bundle of any size up to the bundle limit', () => {
    expect(fileRoute({ name: 'a.zip', size: 10 })).toBe('upload');
    expect(fileRoute({ name: 'a.zip', size: 500 * MB })).toBe('upload');
    expect(fileRoute({ name: 'a.zip', size: 500 * MB + 1 })).toBe('too_large');
  });

  it('names the limit that refused the file', () => {
    expect(fileLimitMb({ name: 'a.zip' })).toBe(500);
    expect(fileLimitMb({ name: 'a.yaml' })).toBe(8);
  });
});

describe('sumCounts', () => {
  it('reads a flat count as it is', () => {
    expect(sumCounts({ created: 2, updated: 3, books: { created: 9 } })).toEqual({
      created: 2,
      updated: 3,
    });
    expect(sumCounts({ updated: 4 })).toEqual({ created: 0, updated: 4 });
    expect(sumCounts({ created: 4 })).toEqual({ created: 4, updated: 0 });
  });

  it('adds the sections of a companion, whatever other counts they hold', () => {
    // Library: {created, updated, skipped}. Pawsistant: {created, updated, unchanged}.
    expect(
      sumCounts({
        books: { created: 12, updated: 400, skipped: 1 },
        loans: { created: 0, updated: 6 },
        events: { created: 40, unchanged: 7 },
        total: 99,
        list: [{ created: 5 }],
        empty: null,
      }),
    ).toEqual({ created: 52, updated: 406 });
  });

  it('reads a value that is not a number as 0', () => {
    expect(sumCounts({ a: { created: '3', updated: NaN }, b: { created: Infinity } })).toEqual({
      created: 0,
      updated: 0,
    });
  });

  it('answers 0 for a count that is not an object', () => {
    for (const value of [undefined, null, 3, 'x', []]) {
      expect(sumCounts(value)).toEqual({ created: 0, updated: 0 });
    }
  });
});

const problem = (section, severity = 'warning', path = section) => ({
  section,
  index: null,
  path,
  message: `${section} ${severity}`,
  severity,
});

const report = (extra = {}) => ({
  ok: true,
  dry_run: true,
  counts: {
    appliances: { created: 2, updated: 29 },
    tasks: { created: 5, updated: 137 },
    completions: 9,
    skips: 0,
  },
  records: [],
  problems: [],
  ...extra,
});

describe('reportRows', () => {
  it('starts with Appliances and Tasks, with the history on the Tasks row', () => {
    const rows = reportRows(report(), []);
    expect(rows).toEqual([
      { key: 'appliances', kind: 'section', name: '', created: 2, updated: 29, unchanged: 0, history: 0, problems: [] },
      { key: 'tasks', kind: 'section', name: '', created: 5, updated: 137, unchanged: 0, history: 9, problems: [] },
    ]);
  });

  it('adds the files and the settings when the report counts them', () => {
    const rows = reportRows(
      report({
        counts: {
          ...report().counts,
          files: { created: 3, unchanged: 4 },
          settings: {
            profiles: { created: 1, updated: 2 },
            notifications: { created: 0, updated: 1 },
            options: { changed: 5 },
          },
        },
        problems: [problem('notifications'), problem('files'), problem('options', 'error')],
      }),
      [],
    );
    expect(rows.map((r) => [r.key, r.kind, r.created, r.updated, r.unchanged])).toEqual([
      ['appliances', 'section', 2, 29, 0],
      ['tasks', 'section', 5, 137, 0],
      ['files', 'files', 3, 0, 4],
      ['settings', 'settings', 1, 8, 0],
    ]);
    expect(rows[2].problems.map((p) => p.section)).toEqual(['files']);
    // Errors first.
    expect(rows[3].problems.map((p) => p.section)).toEqual(['options', 'notifications']);
  });

  it('counts the settings with no options count', () => {
    const rows = reportRows(
      report({ counts: { ...report().counts, settings: { profiles: { created: 1, updated: 1 } } } }),
      [],
    );
    expect(rows[2].updated).toBe(1);
  });

  it('adds 1 row per companion section, named from the companion list', () => {
    const rows = reportRows(
      report({
        sections: {
          home_keeper_library: { counts: { books: { created: 12, updated: 406, skipped: 0 } } },
          pawsistant: { counts: { events: { created: 40, updated: 0, unchanged: 3 } } },
          broken: 'not a report',
        },
        problems: [
          problem('home_keeper_library', 'warning', 'home_keeper_library.people[0]'),
          problem('tasks', 'error', 'tasks[1].interval'),
        ],
      }),
      [companion('home_keeper_library', { name: 'Library' })],
    );
    expect(rows.slice(2).map((r) => [r.key, r.kind, r.name, r.created, r.updated])).toEqual([
      ['home_keeper_library', 'companion', 'Library', 12, 406],
      ['pawsistant', 'companion', 'pawsistant', 40, 0],
      ['broken', 'companion', 'broken', 0, 0],
    ]);
    expect(rows[2].problems.map((p) => p.path)).toEqual(['home_keeper_library.people[0]']);
    expect(rows[1].problems.map((p) => p.path)).toEqual(['tasks[1].interval']);
  });

  it('reads a report with no count for a section as 0', () => {
    const rows = reportRows(report({ counts: { completions: 0, skips: 0 } }), []);
    expect(rows.map((r) => [r.created, r.updated, r.history])).toEqual([
      [0, 0, 0],
      [0, 0, 0],
    ]);
  });
});

describe('otherProblems', () => {
  it('lists the problems that no row holds, errors first', () => {
    const r = report({
      problems: [
        problem('tasks'),
        problem('home_keeper', 'warning'),
        problem('profiles', 'warning'),
        problem('unknown_companion', 'error'),
      ],
    });
    const rows = reportRows(r, []);
    expect(otherProblems(r, rows).map((p) => p.section)).toEqual([
      'unknown_companion',
      'home_keeper',
      'profiles',
    ]);
  });
});

describe('reportHasSettings', () => {
  it('is false with no report, and for a report with no settings', () => {
    expect(reportHasSettings(null)).toBe(false);
    expect(reportHasSettings(report({ problems: [problem('tasks')] }))).toBe(false);
  });

  it('is true when the report counts the settings', () => {
    expect(reportHasSettings(report({ counts: { ...report().counts, settings: {} } }))).toBe(true);
  });

  it('is true when the report skipped a settings section', () => {
    for (const section of ['profiles', 'notifications', 'options']) {
      expect(reportHasSettings(report({ problems: [problem(section)] }))).toBe(true);
    }
  });

  it('reads a problem with no section', () => {
    expect(reportHasSettings(report({ problems: [{ ...problem('x'), section: undefined }] }))).toBe(
      false,
    );
  });
});
