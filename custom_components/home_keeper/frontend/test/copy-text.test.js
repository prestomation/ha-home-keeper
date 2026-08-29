import { afterEach, describe, it, expect, vi } from 'vitest';

import { copyText } from '../src/utils.ts';

/** Replace `navigator.clipboard` for one test, restoring it afterwards. */
function withClipboard(clipboard) {
  const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  Object.defineProperty(navigator, 'clipboard', {
    value: clipboard,
    configurable: true,
  });
  return () => {
    if (original) Object.defineProperty(navigator, 'clipboard', original);
    else delete navigator.clipboard;
  };
}

const restores = [];
afterEach(() => {
  while (restores.length) restores.pop()();
  delete document.execCommand;
  vi.restoreAllMocks();
});

function clipboard(impl) {
  restores.push(withClipboard(impl));
}

describe('copyText', () => {
  it('uses the async clipboard when it is available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    clipboard({ writeText });
    await expect(copyText('a1b2')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('a1b2');
  });

  it('falls back to execCommand outside a secure context', async () => {
    // `navigator.clipboard` is undefined over plain HTTP — the LAN case.
    clipboard(undefined);
    document.execCommand = vi.fn(() => true);
    await expect(copyText('a1b2')).resolves.toBe(true);
    expect(document.execCommand).toHaveBeenCalledWith('copy');
  });

  it('falls back when the clipboard write is rejected', async () => {
    clipboard({ writeText: vi.fn().mockRejectedValue(new Error('denied')) });
    document.execCommand = vi.fn(() => true);
    await expect(copyText('a1b2')).resolves.toBe(true);
    expect(document.execCommand).toHaveBeenCalled();
  });

  it('reports failure when execCommand says the copy did not happen', async () => {
    clipboard(undefined);
    document.execCommand = vi.fn(() => false);
    await expect(copyText('a1b2')).resolves.toBe(false);
  });

  it('reports failure when execCommand is missing entirely', async () => {
    clipboard(undefined);
    await expect(copyText('a1b2')).resolves.toBe(false);
  });

  it('reports failure when execCommand throws', async () => {
    clipboard(undefined);
    document.execCommand = vi.fn(() => {
      throw new Error('nope');
    });
    await expect(copyText('a1b2')).resolves.toBe(false);
  });

  it('puts the exact text in the textarea it copies from', async () => {
    clipboard(undefined);
    let seen;
    document.execCommand = vi.fn(() => {
      seen = document.querySelector('textarea')?.value;
      return true;
    });
    await copyText('  spaces and \n newlines  ');
    expect(seen).toBe('  spaces and \n newlines  ');
  });

  it('keeps the fallback textarea off-screen and uneditable', async () => {
    // It is appended to the live document, so a visible one would flash on screen
    // and, without `readonly`, take a caret on a phone.
    clipboard(undefined);
    let area;
    document.execCommand = vi.fn(() => {
      area = document.querySelector('textarea');
      return true;
    });
    await copyText('a1b2');
    expect(area.getAttribute('readonly')).toBe('');
    expect(area.style.position).toBe('fixed');
    expect(parseInt(area.style.top, 10)).toBeLessThan(-1000);
  });

  it('leaves no textarea behind, on success or on failure', async () => {
    clipboard(undefined);
    document.execCommand = vi.fn(() => true);
    await copyText('a1b2');
    expect(document.querySelector('textarea')).toBeNull();

    document.execCommand = vi.fn(() => {
      throw new Error('nope');
    });
    await copyText('a1b2');
    expect(document.querySelector('textarea')).toBeNull();
  });

  it('does not reach the fallback when the async clipboard succeeds', async () => {
    clipboard({ writeText: vi.fn().mockResolvedValue(undefined) });
    document.execCommand = vi.fn(() => true);
    await copyText('a1b2');
    expect(document.execCommand).not.toHaveBeenCalled();
  });
});
