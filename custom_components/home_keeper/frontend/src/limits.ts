/**
 * Limits the panel shares with the backend.
 *
 * These mirror constants in `const.py`. The panel checks them *client-side* so an
 * oversized file is refused instantly instead of being streamed to Home Assistant
 * just to come back as a 413 — but the backend remains the authority (see
 * `manuals.py` `_parse_upload` and `documents.py` `validate_upload`).
 *
 * Keep them in sync: `tests/unit/test_upload_limit_parity.py` fails the build if
 * this value and `const.py`'s drift apart.
 */

/** Hard per-file upload ceiling — mirrors MAX_DOCUMENT_BYTES in const.py. */
export const MAX_DOCUMENT_BYTES = 100 * 1024 * 1024;

/**
 * The largest websocket frame Home Assistant accepts — mirrors MAX_IMPORT_WS_BYTES
 * in const.py.
 *
 * Home Assistant does not override aiohttp's 4 MiB default, and going over it is not
 * a failed command: the connection is closed with "Decompressed message exceeds size
 * limit". So the panel checks the encoded frame itself and refuses first, which is
 * the only place a useful message can be produced.
 *
 * Deliberately smaller than the backend's own MAX_IMPORT_BYTES (8 MiB). That one is
 * the ceiling for `home_keeper.import_data`, which a script can call without going
 * through a websocket.
 */
export const MAX_IMPORT_WS_BYTES = 4 * 1024 * 1024;

/**
 * The largest document `home_keeper.import_data` reads — mirrors MAX_IMPORT_BYTES in
 * const.py.
 *
 * The panel cannot reach it, and names it anyway: the message for a document between
 * the two sizes has to say what *does* import it, or it is only a refusal.
 */
export const MAX_IMPORT_BYTES = 8 * 1024 * 1024;

/**
 * The size of the websocket frame an import of *document* would send.
 *
 * Measured as the JSON-encoded document plus the rest of the command, because that
 * is what aiohttp weighs. Encoding is not free: every newline in a pasted YAML file
 * becomes two bytes as `\n`, and a document full of quoted strings gains more, so a
 * check against the raw string would wave through a file the socket then refuses —
 * which is the whole failure this guard removes.
 */
export function importFrameBytes(document: string): number {
  // `Blob` counts UTF-8 bytes rather than UTF-16 code units, so a document of
  // accented or CJK text is not undercounted. The constant covers the command's own
  // keys (`type`, `dry_run`, `match`, `id`), rounded up.
  return new Blob([JSON.stringify(document)]).size + 128;
}

/** Whether *document* can be imported through the panel at all. */
export function importFitsWebsocket(document: string): boolean {
  return importFrameBytes(document) <= MAX_IMPORT_WS_BYTES;
}
