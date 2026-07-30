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
export const MAX_DOCUMENT_BYTES = 25 * 1024 * 1024;
