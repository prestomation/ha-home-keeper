import { afterEach, describe, expect, it, vi } from 'vitest';
import { withTimeout } from '../src/utils.ts';

afterEach(() => {
  vi.useRealTimers();
});

describe('withTimeout', () => {
  const late = () => new Error('late');

  it('gives the value of work that ends in time, and clears its timer', async () => {
    vi.useFakeTimers();
    const p = withTimeout(Promise.resolve(7), 100, late);
    await expect(p).resolves.toBe(7);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('gives the error of work that fails in time, and clears its timer', async () => {
    vi.useFakeTimers();
    const p = withTimeout(Promise.reject(new Error('boom')), 100, late);
    await expect(p).rejects.toThrow('boom');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('rejects with the time-limit error when the work does not end in time', async () => {
    vi.useFakeTimers();
    const p = withTimeout(new Promise(() => {}), 100, late);
    const caught = p.catch((e) => e);
    await vi.advanceTimersByTimeAsync(99);
    let settled = false;
    void p.then(
      () => (settled = true),
      () => (settled = true),
    );
    await Promise.resolve();
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect((await caught).message).toBe('late');
  });

  it('keeps the time-limit error when the work ends after it', async () => {
    vi.useFakeTimers();
    let finish;
    const p = withTimeout(new Promise((r) => (finish = r)), 50, late);
    const caught = p.catch((e) => e);
    await vi.advanceTimersByTimeAsync(50);
    finish(1);
    expect((await caught).message).toBe('late');
  });
});
