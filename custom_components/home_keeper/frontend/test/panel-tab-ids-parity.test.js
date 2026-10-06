import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { RESERVED_TAB_IDS } from '../src/utils.ts';

// The panel and the backend refuse the same tab ids. This file reads
// `panel_tabs.py` off disk, so it is a parity file and not in the mutation run
// (see `vitest.stryker.config.js`).

function backendIds() {
  const source = readFileSync(resolve(__dirname, '../../panel_tabs.py'), 'utf8');
  const ids = new Set();
  for (const name of ['ROUTED_TAB_IDS', 'FUTURE_TAB_IDS']) {
    const match = source.match(new RegExp(`^${name} = frozenset\\(([\\s\\S]*?)\\)\\n`, 'm'));
    expect(match, name).not.toBeNull();
    for (const id of match[1].matchAll(/"([a-z-]+)"/g)) ids.add(id[1]);
  }
  return ids;
}

describe('reserved tab ids', () => {
  it('are the same in the panel and the backend', () => {
    expect(new Set(RESERVED_TAB_IDS)).toEqual(backendIds());
  });
});
