import { describe, expect, it } from 'vitest';
import { blank, scan } from './destructive-scan-lib.js';

const file = (source, name = 'panel-x.ts') => [{ name, source }];

describe('the destructive-action scanner', () => {
  it('flags a delete that runs at once', () => {
    const { violations } = scan(
      file(`
        async function deleteThing(p) { await api.deleteTask(p, 1); }
        function wire(p) { btn.addEventListener('click', () => void deleteThing(p)); }
      `),
    );
    expect(violations.map((v) => v.key)).toEqual(['panel-x.ts::wire::deleteThing']);
  });

  it('accepts a delete inside confirmDestructive, and one inside mountConfirm', () => {
    const { violations } = scan(
      file(`
        async function deleteThing(p) { await api.deleteTask(p, 1); }
        function wire(p) {
          btn.addEventListener('click', () =>
            confirmDestructive(p, { title: 'x', onConfirm: () => void deleteThing(p) }));
          mountConfirm(c, { onCancel: close, onConfirm: () => { deleteThing(p); } });
        }
      `),
    );
    expect(violations).toEqual([]);
  });

  it('flags the api call of a handler with no function around it', () => {
    const { violations } = scan([
      { name: 'api.ts', source: 'export async function deleteSkip(h, a, b) {}' },
      ...file(`function wire(p) { b.addEventListener('click', () => api.deleteSkip(h, 1, 2)); }`),
    ]);
    expect(violations).toHaveLength(1);
    expect(violations[0].callee).toBe('deleteSkip');
  });

  it('does not take a call before the confirmation for one inside it', () => {
    const { violations } = scan(
      file(`
        function deleteThing() {}
        function wire(p) {
          deleteThing(p);
          confirmDestructive(p, { title: 't', onConfirm: () => {} });
        }
      `),
    );
    expect(violations).toHaveLength(1);
  });

  it('lets a destructive function call another one: the outer call is checked', () => {
    const { violations } = scan(
      file(`
        function deleteInner() {}
        function deleteOuter() { deleteInner(); }
        function wire(p) { deleteOuter(); }
      `),
    );
    expect(violations.map((v) => v.callee)).toEqual(['deleteOuter']);
  });

  it('honours an allowlist entry, and reports one that nothing needs', () => {
    const src = file(`
      function removeDraft() {}
      function wire() { removeDraft(); }
    `);
    const key = 'panel-x.ts::wire::removeDraft';
    expect(scan(src, { [key]: 'why' }).violations).toEqual([]);
    expect(scan(src, { [key]: 'why', 'panel-x.ts::gone::removeDraft': 'x' }).stale).toEqual([
      'panel-x.ts::gone::removeDraft',
    ]);
  });

  it('ignores the platform: a Set or a node with the same verb', () => {
    const { violations } = scan(
      file(`
        function removeThing() {}
        function wire(set, el) { set.delete(1); el.remove(); items.removeThing(); }
      `),
    );
    expect(violations).toEqual([]);
  });

  it('ignores a name in a comment or a string', () => {
    const { violations } = scan(
      file(`
        function deleteThing() {}
        // deleteThing() runs here
        const s = 'deleteThing()';
        /* deleteThing(1) */
      `),
    );
    expect(violations).toEqual([]);
  });

  it('treats the import entry points as destructive', () => {
    const { violations } = scan(file(`function wire(p) { p._runImport(); }`));
    expect(violations.map((v) => v.callee)).toEqual(['_runImport']);
  });

  it('keeps offsets when it blanks text', () => {
    const src = "const a = 'x(';\n// c )\nfoo();";
    expect(blank(src)).toHaveLength(src.length);
    expect(blank(src).split('\n')).toHaveLength(3);
  });
});
