import { describe, expect, it } from 'vitest';
import { historyEntryDetail } from '../src/utils.ts';

describe('historyEntryDetail', () => {
  it('is empty for an entry with no reading and no note', () => {
    expect(historyEntryDetail({ ts: '2026-01-02T10:00:00Z' }, '', 'en')).toBe('');
  });

  it('names the reading with its unit', () => {
    expect(historyEntryDetail({ ts: 'x', reading: 45000 }, 'km', 'en')).toBe('at 45,000 km');
  });

  it('names the note in quotes', () => {
    expect(historyEntryDetail({ ts: 'x', note: 'New oil' }, '', 'en')).toBe('"New oil"');
  });

  it('joins reading and note', () => {
    expect(historyEntryDetail({ ts: 'x', reading: 5, note: 'Tires' }, '', 'en')).toBe(
      'at 5 · "Tires"',
    );
  });

  it('keeps a long note to one short line', () => {
    const out = historyEntryDetail({ ts: 'x', note: 'a'.repeat(200) + '\nsecond' }, '', 'en');
    expect(out.length).toBeLessThan(100);
    expect(out).not.toContain('\n');
    expect(out).toContain('…');
  });

  it('ignores a blank note', () => {
    expect(historyEntryDetail({ ts: 'x', note: '   ' }, '', 'en')).toBe('');
  });
});

describe('history delete asks first', () => {
  const host = () => {
    const calls = [];
    const p = {
      _hass: { callWS: async (m) => (calls.push(m), { task: {} }), language: 'en' },
      _confirmDelete: { label: '', body: '', onConfirm: null },
      _confirmScrim: null,
      _confirmOnKey: null,
      _lang: () => 'en',
      _refresh: async () => {},
      _render: () => {},
      _openOverlay: () => {},
      _closeOverlay: () => {},
      _isOpen: () => false,
      _syncDrawerModality: () => {},
      _flushOverlayFocus: () => {},
    };
    return { p, calls };
  };
  const mount = (html) => {
    const root = document.createElement('div');
    root.innerHTML = html;
    document.body.appendChild(root);
    return root;
  };
  const click = (label) =>
    [...document.querySelectorAll('.hk-confirm-scrim ha-button')]
      .find((b) => b.textContent === label)
      .click();

  it('a completion waits for Delete and names its date and note', async () => {
    const { wireHistory } = await import('../src/panel-history.ts');
    const { p, calls } = host();
    const root = mount(
      '<ha-icon-button class="hk-hist-del" data-del-task="t1" data-ts="2026-03-01T10:00:00Z" data-detail="&quot;New oil&quot;"></ha-icon-button>',
    );
    wireHistory(p, root);
    root.querySelector('.hk-hist-del').click();
    expect(calls).toEqual([]);
    expect(document.querySelector('#hk-confirm-title').textContent).toContain('2026');
    expect(document.querySelector('#hk-confirm-body').textContent).toContain('New oil');
    click('Cancel');
    await Promise.resolve();
    expect(calls).toEqual([]);
    root.querySelector('.hk-hist-del').click();
    click('Delete');
    await new Promise((r) => setTimeout(r));
    expect(calls.map((c) => c.type)).toEqual(['home_keeper/delete_completion']);
  });

  it('an archived completion and a skip wait too', async () => {
    const { wireHistory } = await import('../src/panel-history.ts');
    const { wireSkipHistoryRows } = await import('../src/panel-defer.ts');
    const { p, calls } = host();
    const root = mount(
      '<ha-icon-button class="hk-hist-del" data-del-asset="a1" data-del-arch="t9" data-ts="2026-03-01T10:00:00Z"></ha-icon-button>' +
        '<ha-icon-button class="hk-hist-skip-del" data-del-skip="t1" data-ts="2026-03-02T10:00:00Z"></ha-icon-button>',
    );
    wireHistory(p, root);
    wireSkipHistoryRows(p, root);
    root.querySelector('.hk-hist-del').click();
    expect(document.querySelector('.hk-confirm-scrim')).toBeTruthy();
    click('Cancel');
    root.querySelector('.hk-hist-skip-del').click();
    expect(document.querySelector('.hk-confirm-scrim')).toBeTruthy();
    expect(document.querySelector('#hk-confirm-title').textContent).toContain('skip');
    expect(calls).toEqual([]);
  });
});
