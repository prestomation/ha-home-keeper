import { readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { scan } from './destructive-scan-lib.js';

// Every call of a function that deletes, removes or replaces data must sit under a
// confirmation. A new delete button that calls the action at once fails this test.
//
// It reads `src/*.ts` as text, so it is a `*-parity` test and the mutation run skips
// it (see `vitest.stryker.config.js`). `destructive-scan-lib.test.js` tests the
// scanner itself on small snippets.

// A call that is allowed to run without a question. The key is
// `file::function that holds the call::callee`. Each entry says why, and an entry
// that no call needs any more fails the test, so this list cannot collect dead names.
const ALLOW = {
  'panel-controls.ts::wireChips::_clearListFilter':
    'Clears 1 filter of the task list. It is state of this screen and nothing is stored.',
  'panel-detail.ts::wireDetailActions::_archiveAsset':
    'Archive only hides an appliance, and Restore brings it back with all its data. ' +
    'An easy-to-reverse action asks nothing.',
  'panel-task-form.ts::seasonWindow::removeSeasonWindow':
    'Edits the open draft of the task form. The drawer Cancel throws the draft away, ' +
    'and nothing is stored before Save.',
  'panel.ts::_undoComplete::deleteCompletion':
    'The Undo button of the Done toast. Pressing Undo is itself the answer to "keep it?", ' +
    'and the entry that goes is the one that Done added a moment before.',
  'panel.ts::_transferCall::importData':
    'Also runs for Preview, which writes nothing (dryRun). The real import starts in ' +
    '_runImport, and its only caller is inside the Import confirmation.',
  'panel.ts::_transferCall::importUpload':
    'Same as importData: Preview writes nothing, and the real import starts in ' +
    '_runImport, behind the Import confirmation.',
};

const SRC = resolve(__dirname, '../src');
const files = readdirSync(SRC)
  .filter((f) => f.endsWith('.ts'))
  .map((name) => ({ name, source: readFileSync(resolve(SRC, name), 'utf8') }));

describe('destructive actions are confirmed', () => {
  const { violations, stale } = scan(files, ALLOW);

  it('has no call that runs a delete without a confirmation', () => {
    const lines = violations.map((v) => `${v.file}:${v.line} ${v.where} calls ${v.callee}`);
    expect(lines, 'wrap it in confirmDestructive(...), or add a reasoned ALLOW entry').toEqual([]);
  });

  it('has no allowlist entry that nothing needs', () => {
    expect(stale).toEqual([]);
  });

  it('gives every allowlist entry a real reason', () => {
    for (const [key, reason] of Object.entries(ALLOW)) {
      expect(reason.length, key).toBeGreaterThan(40);
    }
  });

  it('keeps every destructive websocket command inside api.ts', () => {
    // A direct `callWS({ type: 'home_keeper/delete_...' })` would bypass the names the
    // scan follows. The panel calls the helpers of `api.ts` for each data action.
    const direct = files
      .filter((f) => f.name !== 'api.ts')
      .filter((f) =>
        /['"`]home_keeper\/(delete_|remove_|archive_|import_data|import_upload)/.test(f.source),
      )
      .map((f) => f.name);
    expect(direct).toEqual([]);
  });

  it('finds the guarded calls that it should', () => {
    // A scan that sees no call at all would pass for the wrong reason.
    const file = files.find((f) => f.name === 'panel-history.ts');
    expect(file, 'panel-history.ts must be in src/').toBeDefined();
    const history = file.source;
    expect(history).toContain('confirmDestructive');
    expect(history).toContain('deleteCompletion');
  });
});
