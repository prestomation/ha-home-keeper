/**
 * The import ceiling the panel enforces before it sends anything.
 *
 * Home Assistant closes the websocket on a frame past aiohttp's 4 MiB default rather
 * than answering, so this measurement is the last point at which a useful message can
 * be produced. It has to measure the *encoded* frame: a document is escaped on its
 * way into JSON, so the raw string is always the smaller number and checking it would
 * wave through files the socket then refuses.
 */
import { describe, expect, it } from 'vitest';
import {
  MAX_IMPORT_BYTES,
  MAX_IMPORT_WS_BYTES,
  importFitsWebsocket,
  importFrameBytes,
} from '../src/limits.ts';

describe('the two ceilings', () => {
  // Both numbers reach a user: the panel refuses at one and its message names the
  // other. `tests/unit/test_upload_limit_parity.py` pins them against const.py; these
  // pin the values the panel actually renders, which that test cannot see.
  it('refuses at aiohttp own 4 MiB websocket default', () => {
    expect(MAX_IMPORT_WS_BYTES).toBe(4 * 1024 * 1024);
  });

  it('names the service 8 MiB ceiling', () => {
    expect(MAX_IMPORT_BYTES).toBe(8 * 1024 * 1024);
  });

  it('keeps the panel ceiling below the service one', () => {
    // The message tells a reader to take a document the panel refused to the service.
    // If these ever crossed, it would be sending them somewhere smaller.
    expect(MAX_IMPORT_WS_BYTES).toBeLessThan(MAX_IMPORT_BYTES);
  });

  it('states both as a whole number of megabytes', () => {
    // Each is divided by 1024*1024 for the message, so a fractional value would be
    // rendered as a number that is not the one enforced.
    for (const bytes of [MAX_IMPORT_WS_BYTES, MAX_IMPORT_BYTES]) {
      expect(bytes % (1024 * 1024)).toBe(0);
    }
  });
});

describe('importFrameBytes', () => {
  it('counts the encoded document, not the raw string', () => {
    // Two quotes for the JSON string, plus the two characters themselves.
    expect(importFrameBytes('ab')).toBe(4 + 128);
  });

  it('charges two bytes for a newline, because JSON escapes it', () => {
    expect(importFrameBytes('\n') - importFrameBytes('a')).toBe(1);
  });

  it('charges a quotation mark as an escape', () => {
    expect(importFrameBytes('"') - importFrameBytes('a')).toBe(1);
  });

  it('counts UTF-8 bytes rather than UTF-16 code units', () => {
    // A CJK character is 3 bytes in UTF-8 and one code unit in JavaScript, so a
    // length-based count would undercount a translated document by two thirds.
    expect(importFrameBytes('\u66f4') - importFrameBytes('a')).toBe(2);
  });
});

describe('importFitsWebsocket', () => {
  it('accepts an ordinary document', () => {
    expect(importFitsWebsocket('home_keeper:\n  format: 1\n')).toBe(true);
  });

  it('refuses a document past the ceiling', () => {
    expect(importFitsWebsocket('x'.repeat(MAX_IMPORT_WS_BYTES))).toBe(false);
  });

  it('is decided on the encoded size, so a file of newlines is refused early', () => {
    // Half the ceiling in newlines encodes to the whole ceiling. A raw-length check
    // would call this comfortably within budget and then lose the connection.
    const raw = '\n'.repeat(MAX_IMPORT_WS_BYTES / 2);
    expect(raw.length).toBeLessThan(MAX_IMPORT_WS_BYTES);
    expect(importFitsWebsocket(raw)).toBe(false);
  });

  it('draws the line at the ceiling itself', () => {
    // The largest document that fits, and one byte more.
    const fits = 'x'.repeat(MAX_IMPORT_WS_BYTES - 2 - 128);
    expect(importFrameBytes(fits)).toBe(MAX_IMPORT_WS_BYTES);
    expect(importFitsWebsocket(fits)).toBe(true);
    expect(importFitsWebsocket(`${fits}x`)).toBe(false);
  });
});
