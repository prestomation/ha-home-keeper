/**
 * `writeQueue` — the queue every options write from the Settings tab goes through
 * (X12-2).
 *
 * Each options write reloads the config entry, and the backend answers `not_loaded`
 * to any write that arrives during that reload. So the queue sends one write at a
 * time and tries a `not_loaded` write again after a wait.
 */
import { describe, expect, it } from 'vitest';
import { RELOAD_RETRIES, RELOAD_RETRY_MS, writeQueue } from '../src/utils.ts';

const retryable = (err) => err?.code === 'not_loaded';
const notLoaded = () => Object.assign(new Error('not loaded'), { code: 'not_loaded' });

/** A write that records when it starts and ends, and answers after *ms*. */
function tracked(log, name, ms, answer = name) {
  return () => {
    log.push(`start ${name}`);
    return new Promise((r) =>
      setTimeout(() => {
        log.push(`end ${name}`);
        r(answer);
      }, ms),
    );
  };
}

describe('writeQueue (X12-2)', () => {
  it('waits for a reload of five one-second tries by default', () => {
    expect(RELOAD_RETRIES).toBe(5);
    expect(RELOAD_RETRY_MS).toBe(1000);
  });

  it('sends each write only after the one before it has answered', async () => {
    const queue = writeQueue(retryable, 0, 1);
    const log = [];
    const a = queue(tracked(log, 'a', 30));
    const b = queue(tracked(log, 'b', 0));
    expect(await Promise.all([a, b])).toEqual(['a', 'b']);
    expect(log).toEqual(['start a', 'end a', 'start b', 'end b']);
  });

  it('does not stop the writes after a failed one', async () => {
    const queue = writeQueue(retryable, 0, 1);
    const a = queue(() => Promise.reject(new Error('refused')));
    const b = queue(() => Promise.resolve('b'));
    await expect(a).rejects.toThrow('refused');
    await expect(b).resolves.toBe('b');
  });

  it('tries a retryable failure again after the wait', async () => {
    const queue = writeQueue(retryable, 2, 40);
    let calls = 0;
    const started = Date.now();
    const answer = await queue(() => {
      calls += 1;
      return calls < 3 ? Promise.reject(notLoaded()) : Promise.resolve('saved');
    });
    expect(answer).toBe('saved');
    expect(calls).toBe(3);
    // Two waits of 40ms, not zero: the retries do not spin.
    expect(Date.now() - started).toBeGreaterThanOrEqual(70);
  });

  it('gives up once the tries are spent', async () => {
    const queue = writeQueue(retryable, 2, 1);
    let calls = 0;
    const run = queue(() => {
      calls += 1;
      return Promise.reject(notLoaded());
    });
    await expect(run).rejects.toMatchObject({ code: 'not_loaded' });
    expect(calls).toBe(3);
  });

  it('does not try again for an error that is not retryable', async () => {
    const queue = writeQueue(retryable, 3, 1);
    let calls = 0;
    const run = queue(() => {
      calls += 1;
      return Promise.reject(new Error('refused'));
    });
    await expect(run).rejects.toThrow('refused');
    expect(calls).toBe(1);
  });

  it('holds the next write while one is retrying', async () => {
    const queue = writeQueue(retryable, 1, 20);
    const log = [];
    let first = true;
    const a = queue(() => {
      log.push('try a');
      if (first) {
        first = false;
        return Promise.reject(notLoaded());
      }
      return Promise.resolve('a');
    });
    const b = queue(() => {
      log.push('try b');
      return Promise.resolve('b');
    });
    await Promise.all([a, b]);
    expect(log).toEqual(['try a', 'try a', 'try b']);
  });

  it('uses the reload defaults when none are given', async () => {
    const queue = writeQueue(retryable);
    let calls = 0;
    const started = Date.now();
    await queue(() => {
      calls += 1;
      return calls < 2 ? Promise.reject(notLoaded()) : Promise.resolve('ok');
    });
    expect(calls).toBe(2);
    expect(Date.now() - started).toBeGreaterThanOrEqual(RELOAD_RETRY_MS - 20);
  });
});
