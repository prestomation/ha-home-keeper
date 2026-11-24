import { afterEach, describe, expect, it } from 'vitest';
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

  it('takes the first line of a note, with a Windows line end too', () => {
    expect(historyEntryDetail({ ts: 'x', note: 'first  \nsecond' }, '', 'en')).toBe('"first"');
    expect(historyEntryDetail({ ts: 'x', note: 'first\r\nsecond' }, '', 'en')).toBe('"first"');
    expect(historyEntryDetail({ ts: 'x', note: '\n  hello  ' }, '', 'en')).toBe('"hello"');
  });

  it('cuts a note at 60 characters and trims the space before the cut', () => {
    const sixty = 'a'.repeat(60);
    expect(historyEntryDetail({ ts: 'x', note: sixty }, '', 'en')).toBe(`"${sixty}"`);
    expect(historyEntryDetail({ ts: 'x', note: `${sixty}b` }, '', 'en')).toBe(`"${sixty}…"`);
    const spaced = `${'a'.repeat(59)} tail`;
    expect(historyEntryDetail({ ts: 'x', note: spaced }, '', 'en')).toBe(`"${'a'.repeat(59)}…"`);
  });

  it('ignores a blank note', () => {
    expect(historyEntryDetail({ ts: 'x', note: '   ' }, '', 'en')).toBe('');
  });
});

describe('history delete asks first', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    document.head.querySelector('#hk-confirm-style')?.remove();
  });

  const host = () => {
    const calls = [];
    const p = {
      _hass: { callWS: async (m) => (calls.push(m), { task: {} }), language: 'en' },
      _confirmHandle: null,
      _drawerOnKey: null,
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
      .find((b) =>
        label === 'Delete'
          ? b.getAttribute('data-hk-weight') === 'danger-primary'
          : b.textContent === label,
      )
      .click();

  it('a completion waits for Delete and names its date and note', async () => {
    const { wireHistory } = await import('../src/panel-history.ts');
    const { p, calls } = host();
    const root = mount(
      '<ha-icon-button class="hk-hist-del" data-del-task="t1" data-ts="2026-03-01T10:00:00Z" data-detail="&quot;New oil&quot;" data-task="Car oil" data-who="Sam"></ha-icon-button>',
    );
    wireHistory(p, root);
    root.querySelector('.hk-hist-del').click();
    expect(calls).toEqual([]);
    expect(document.querySelector('#hk-confirm-title').textContent).toContain('2026');
    const body = document.querySelector('#hk-confirm-body').textContent;
    expect(body).toContain('New oil');
    expect(body).toContain('Car oil');
    expect(body).toContain('by Sam');
    expect(document.querySelector('[data-hk-weight="danger-primary"]').textContent).toBe(
      'Delete entry',
    );
    click('Cancel');
    await Promise.resolve();
    expect(calls).toEqual([]);
    root.querySelector('.hk-hist-del').click();
    click('Delete');
    await new Promise((r) => setTimeout(r));
    expect(calls.map((c) => c.type)).toEqual(['home_keeper/delete_completion']);
  });

  it('shows a note with HTML as the text that was typed', async () => {
    const { wireHistory } = await import('../src/panel-history.ts');
    const { escapeHTML } = await import('../src/utils.ts');
    const { p } = host();
    const note = '"<img src=x onerror=alert(1)><b>x</b>"';
    // The attribute goes through the same escaping as the row markup, and the browser
    // decodes it before `dataset` reads it.
    const root = mount(
      `<ha-icon-button class="hk-hist-del" data-del-task="t1" data-ts="2026-03-01T10:00:00Z" data-detail="${escapeHTML(note)}"></ha-icon-button>`,
    );
    expect(root.querySelector('.hk-hist-del').getAttribute('data-detail')).toBe(note);
    wireHistory(p, root);
    root.querySelector('.hk-hist-del').click();
    const body = document.querySelector('#hk-confirm-body');
    expect(body.querySelector('img, b')).toBeNull();
    expect(body.textContent).toContain(note);
    expect(body.textContent).not.toContain('&lt;');
    click('Cancel');
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
