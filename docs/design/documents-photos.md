---
title: Documents and photos
summary: Stores uploaded appliance files, serves them by signed URL, and renders notes as Markdown.
implements:
  - custom_components/home_keeper/documents.py
  - custom_components/home_keeper/manuals.py
  - custom_components/home_keeper/frontend/src/documents.ts
  - custom_components/home_keeper/frontend/src/panel-upload.ts
  - custom_components/home_keeper/frontend/src/markdown.ts
related: [appliances, completions, store, frontend, events-api]
source_hash: 87a9afa8918c
---

# Documents and photos

An appliance holds a list of documents (manuals, warranties, receipts), and each part has
1 optional attached file. A document is a `link` (an external URL) or a `file` (an upload
that Home Keeper keeps on disk, so it opens offline). Notes on tasks, appliances, parts and
completions render as Markdown. Home Assistant stores a completion photo, and Home Keeper
keeps only its URL. Photos on a task are in [task-photos](task-photos.md).

## Goals

- **G1. Files stay out of the JSON store.** The store keeps metadata only. The bytes go to
  a directory tree that a single delete removes with its appliance.
- **G2. An upload cannot harm the host.** The server identifies the type from the bytes, caps
  the size, holds a bounded amount in memory, and keeps every path under the storage root.
- **G3. A file opens with a native tap.** Each surface signs the URL before the click, so the
  iOS app opens it and long-press and middle-click work.
- **G4. Notes render safely.** User text never goes into the DOM as raw HTML.

## Non-goals

- Upload of bytes through a service or a websocket command. A binary does not fit in a
  service call. Link documents and file removal are services (the appliances doc).
- Storage of completion photos. Home Assistant's own image store keeps them.
- Thumbnails, previews or file conversion.
- The privilege model outside file serving: see [../SECURITY.md](../SECURITY.md).

## Design

### Pure checks and HA input/output are 2 modules

`documents.py` has no Home Assistant import, so unit tests reach every security check.
`manuals.py` does the disk work, the HTTP views and the URL signing, with every blocking
file call in the executor (`documents.resolve_under_root` calls `Path.resolve`).

### Where files live

The root is `<config>/home_keeper/documents/` (`MANUALS_SUBDIR` in `const.py`).
`documents.document_path` gives `<asset_id>/<document_id>__<safe_filename>`. A part file uses
the key `part_<part_id>` in the same appliance directory, so the 2 kinds share 1 tree and
cannot collide. Uploads stream into `.incoming/`, which no id can map onto, because
`documents.safe_segment` removes a leading dot. An atomic `os.replace` moves a finished upload
into place, so a reader never sees half a file.

### The upload views

`HomeKeeperDocumentView` (`/api/home_keeper/document/{asset_id}/{document_id}`) and
`HomeKeeperPartFileView` (`/api/home_keeper/part_document/{asset_id}/{part_id}`) take a
multipart `POST`. The steps:

1. `require_admin`, then `manuals._begin_upload`: the request must carry a real user that is
   not system-generated, the entry must be loaded, and the appliance must exist.
2. `manuals._parse_upload` streams the 1 file part to a temp file in 256 KB reads and
   1 MB writes. It stops at its `max_bytes` cap, by default `MAX_DOCUMENT_BYTES` (100 MB),
   and returns 413. The view raises the aiohttp body cap per request, because Home
   Assistant's global cap is 16 MB.
3. `documents.validate_upload_stream` rejects an empty file, an oversize file, and a type
   outside `TYPE_EXTENSIONS` (PDF, PNG, JPEG, WebP, GIF). `documents.sniff_content_type` reads
   the magic bytes. The client's MIME header is never read.
4. `manuals._replaced_response` stops an upload that spans an entry reload, and
   `documents.upload_document_id` keeps the client id only if it is a plain, free uuid.
5. The file moves into place first, then `store.add_asset_document` writes the metadata and
   fires `home_keeper_asset_updated`, so a listener never sees a record without its file.

Every exit path calls `manuals.async_discard_upload`, also on a client abort. At setup,
`manuals.async_cleanup_temp_uploads` deletes temp files older than 24 hours, not all of
them, because a reload can run while an upload is in progress.

### File names, including Unicode

`documents.safe_filename` makes the key on disk: path removed, every character outside
`[A-Za-z0-9._-]` replaced, a fallback stem, and the extension of the sniffed type.
`documents.display_filename` keeps the real name for the user: NFC-normalized, control
characters removed, 200 characters at most. `documents.content_disposition` sends both: an
ASCII `filename` and an RFC 6266 `filename*` in UTF-8, so a download keeps a Cyrillic name.

### Serving with signed paths

A `GET` gets 404 unless a record of that appliance names the file.
`manuals.async_sign_document_url` and `manuals.async_sign_part_file_url` call
`async_sign_path` with `use_content_user=True`, so every caller gets the same read-only
identity. `DOCUMENT_URL_TTL` (1 hour) serves the panel and the card. The services use
`SERVICE_DOCUMENT_URL_TTL` (15 minutes), because a service result can leave the instance.

In the browser, `SignedUrlCache` in `documents.ts` signs each file ahead of the click and
re-signs after 45 minutes. It drops entries the surface no longer shows and joins a sign that
is in progress. `openDocument` and `openPartFile` are a fallback until the first sign.

### Deletion follows the owner

`store.remove_asset_document` and `store.remove_part_file` delete 1 file, and
`store._delete_dropped_part_files` deletes the file of a part that an update removed.
`store.delete_asset` removes the appliance directory with 1 `rmtree`, and
`async_remove_entry` removes this tree and the task photo tree. A generic asset write keeps
stored `file` documents unchanged, so only the view and these calls can add or remove a file.

### Panel upload and completion photos

`panel-upload.ts` runs 1 upload at a time. `runUpload` refuses a file over the limit before
it sends a byte. The default limit is `MAX_DOCUMENT_BYTES` in `limits.ts`, which mirrors
`const.py`, and a caller can give a lower one. `runUpload` shows a progress bar after a short
delay and has a cancel button. A 413 with no Home Keeper message means a reverse proxy refused
the body, so the error links to the proxy fix. `filePicker` takes the types to accept.

The completion dialog uses Home Assistant's `ha-picture-upload`, which stores the image in
the `image_upload` integration and returns a path such as `/api/image/serve/<id>/original`.
The completion's `photo` key holds only that string. `models.normalize_completion_metadata`
accepts an `http(s)` URL or a site-relative path, and the panel checks it with `isSafeImageUrl`.

### Markdown notes

`markdown.ts` renders through Home Assistant's `<ha-markdown>`, which parses with `marked`
and sanitizes with DOMPurify in a Web Worker. Home Keeper bundles no parser or sanitizer.
`markdownBlock` puts the escaped text in `data-md`, and `wireMarkdown` sets the `content`
property after the render. `ensureMarkdown` loads the element through the card helpers;
without it, the note shows as escaped text in `pre-wrap`. `createPreview` shows a debounced
preview only when `looksLikeMarkdown` finds markup. Its bounded patterns keep each keystroke
linear.

## Trade-offs

- **Files on disk** over **bytes in `.storage`**: a 100 MB manual in the JSON store makes
  every save slow. The cost is a second thing to back up and clean up.
- **A signed URL that any user can mint** over **admin-only signing**: the card must open a
  document for a non-admin. A user who guesses an appliance id and a document id learns that
  the pair exists.
- **Streaming to a temp file** over **reading the body into memory**: about 1 MB per upload.
  The cost is temp-file cleanup on every exit path.
- **`ha-markdown`** over **a bundled parser**: no sanitizer code to keep current. The cost:
  the element is sometimes absent, and notes then show as plain text.

## One-way doors

- Document record fields: `id`, `kind` (`link` | `file`), `name`, `url`, `filename`,
  `content_type`, `size`. Part file fields: `file_name`, `file_content_type`, `file_size`.
- The disk layout `home_keeper/documents/<asset_id>/<key>__<filename>`.
- The 2 view routes, and the `sign_document_url` and `sign_part_file_url` services.
- The completion `photo` key holds a URL string, not an id or bytes.
