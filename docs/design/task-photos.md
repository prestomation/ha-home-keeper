---
title: Task photos
summary: Stores up to 6 photos on a task, makes a thumbnail of each, and shows the cover on each surface.
implements:
  - custom_components/home_keeper/task_photos.py
  - custom_components/home_keeper/photo_thumbs.py
  - custom_components/home_keeper/frontend/src/task-photos.ts
  - custom_components/home_keeper/frontend/src/photo-staging.ts
  - custom_components/home_keeper/frontend/src/panel-task-photos.ts
  - custom_components/home_keeper/frontend/src/panel-photo-markup.ts
related: [documents-photos, store, completions, transfer, frontend, events-api]
source_hash: 8f50868d8808
---

# Task photos

A task holds up to 6 uploaded photos, and the first photo is the cover. The panel and the
card show the cover on each row of the task list. The panel also shows it on the task page
and in the completion dialog. Home Keeper keeps each photo on disk with a small JPEG copy.
A completion photo is a different record, which [completions](completions.md) describes.

## Goals

- **G1. Photos are task data.** Any user who can use a task can add, remove and reorder its
  photos ([architecture](architecture.md#administration-usage-and-privilege)).
- **G2. Files stay on disk.** The store keeps the photo metadata. The bytes go to 1 folder
  per task, and the folder goes when the task goes.
- **G3. Light lists.** A list shows the thumbnail. The original loads only on a tap.
- **G4. Photos at creation.** The New task form takes photos before the task has an id.
- **G5. Upload-only.** Only the upload view adds a photo, so each photo record has its file.

## Non-goals

- Upload of bytes through a service or a websocket command
  ([documents-photos](documents-photos.md#non-goals)).
- Photos in the export. The export counts them in `skipped.task_photos` ([transfer](transfer.md)).

## Design

### Stored shape

`photos` on a task is a list of `{id, name, filename, content_type, size, created}`.
`photos[0]` is the cover. `MAX_TASK_PHOTOS` (6) and `MAX_TASK_PHOTO_BYTES` (25 MB) are in
`const.py`, and `limits.ts` mirrors both. `task_photos.py` imports no Home Assistant code.
`task_photos.append_photo` refuses a 7th photo and gives a taken id a new uuid.
`task_photos.make_cover` moves a photo to the front. `task_photos.normalize_photo_entry`
refuses a type outside `IMAGE_TYPES` and a filename that `documents.safe_segment` changes.
`models.build_task` and `models.merge_update` take no `photos` key, so `add_task`,
`update_task` and an import cannot add a photo. The export drops `photos`
(`transfer.EXCLUDED_TASK_KEYS`), and `transfer.count_task_photos` gives `skipped.task_photos`.
Diagnostics redact `photos` (`diagnostics.TO_REDACT`).

### Files on disk

The root is `<config>/home_keeper/task_photos/` (`TASK_PHOTOS_SUBDIR`), beside the documents
tree. `task_photos.photo_path` gives `<task_id>/<photo_id>__<filename>`, and
`task_photos.thumb_path` gives `<task_id>/thumb_<photo_id>__thumb.jpg`. The `thumb_` key
keeps a photo named `thumb.jpg` off the path of the thumbnail. Both call
`documents.document_path`, which keeps each path under the root.

### Upload

`manuals.HomeKeeperTaskPhotoView` serves `/api/home_keeper/task_photo/{task_id}/{photo_id}`.
It has no admin gate. A multipart `POST` runs these steps:

1. `manuals._uploader_is_a_real_user` refuses a request from a system user, so a signed URL
   cannot write. The task must exist.
2. `manuals._parse_upload` streams the file to a temp file and stops at 25 MB.
3. `task_photos.validate_photo_upload` runs the document checks. Then it refuses a type
   outside `IMAGE_TYPES`: PNG, JPEG, WebP and GIF.
4. `manuals._store_task_photo` makes the thumbnail first, then moves the file into place.
5. `store.add_task_photo` saves the entry. If the task is gone or full, the view deletes the
   files. The reply holds the task and the entry.

`photo_thumbs.make_thumbnail` runs in the executor and imports Pillow on first use. It opens
only the 4 upload formats. It applies the EXIF orientation, puts transparency on white, and
writes a JPEG of at most `TASK_PHOTO_THUMB_PX` (256) pixels on the long side. A pixel limit
stops a decompression bomb before the decode. The limit is 50 megapixels, or 250 for a
baseline JPEG that draft mode decodes at a smaller size. A file that does not decode raises
`photo_thumbs.ThumbnailError`, and the view returns 400 before a file is in the folder.

### Serve and sign

A `GET` returns 404 unless the task names the photo. `?size=thumb` serves the thumbnail.
`manuals.async_sign_task_photo_url` signs the path with its query, so a signed thumbnail URL
cannot open the original. The signing identity and the TTLs are the same as for a document
([documents-photos](documents-photos.md#serving-with-signed-paths)). The `sign_task_photo_url`
service gives a URL for a notification. The websocket command `home_keeper/sign_task_photo_urls`
signs a list in 1 call, and a photo that is gone gets `url: null`.

### Services, events and deletes

`remove_task_photo` and `set_task_photo_cover` are open, as `update_task` is. Each has a
websocket twin that returns the task. `store._mutate_task_photos` runs the change, saves, and
fires `home_keeper_task_updated` with `changed_fields: ["photos"]`. A cover that is already
first gives no save and no event. `store.remove_task_photo` also deletes the 2 files.

`store._save` keeps the ids of the tasks that have photos. After each save, it removes the
folder of each such task that the save dropped, whatever path deleted the task. The files
go only after a save that succeeds. At setup, `manuals.async_sweep_task_photos`
removes each folder that `task_photos.stale_task_dirs` finds with no live task.

### Panel and card

- `panel-photo-markup.ts` builds each `<img>` and link with `data-sign`. The panel fills in
  the URL after the render if the cache had none (`_signedUrl`).
- `task-photos.TaskPhotoUrlCache` signs every stale ref of a render in 1 batch. It keeps the
  refresh time of `SignedUrlCache` and drops the refs that the surface no longer shows.
- The task page shows the cover beside the name. If the last completion has a photo, a pair
  shows. A one-off labels it Before and After, and other types use Cover and Last completion.
  `task-photos.lastCompletion` finds the entry that set `last_completed`.
- `panel-task-photos.photosSection` puts the Photos strip at the top of the Schedule tab, with
  Add, Make cover and Remove. `panel-upload.runUpload` sends 1 photo at a time. If
  `managed_by.locked_fields` holds `photos`, the strip shows no controls.
- A list row shows the 40px cover. A completed one-off shows its completion photo instead.
- The task form has a Photos section under Basics. Edit shows the strip of the task page.
  The card shows the 40px cover on each row, and a tap opens the original.

### Photos in the New task form

`photo-staging.ts` has no DOM and no network. The caller gives the preview URL and the upload
call, so the panel and the card use the same module. `stageFiles` refuses a file of the wrong
type, a file over 25 MB, and a file past the cap. In the panel, Make cover moves a staged
photo to the front. After `add_task` returns the id, `uploadStaged` sends the photos in order,
1 at a time, so the first one is the cover. A failed photo keeps the task, and a toast gives
the count. The panel then opens the task page, where the user can add the photo again.

## Trade-offs

- **A thumbnail at upload** over **a resize on each read**: a list of covers loads small
  files. The cost is Pillow work at upload and a second file per photo.
- **Open writes** over **admin-only writes**: a photo is task data. The cost is that any user
  can remove a photo.
- **Photos kept in the browser** over **a draft task on the server**: no task exists until
  Create. A closed tab loses the picked photos.
- **1 signing batch** over **1 call per photo**: a long list costs 1 websocket call.
- **Folder removal in `_save`** over **removal in each delete path**: every path that drops a
  task removes its folder.

## One-way doors

- The stored `photos` field and its entry keys `id`, `name`, `filename`, `content_type`,
  `size`, `created`. The first entry is the cover.
- The route `/api/home_keeper/task_photo/{task_id}/{photo_id}` and its `?size=thumb` query.
- The services `remove_task_photo`, `set_task_photo_cover` and `sign_task_photo_url`.
- `home_keeper_task_updated` with `changed_fields: ["photos"]` for each photo change.
- The export count `skipped.task_photos`.
- The disk layout `home_keeper/task_photos/<task_id>/` with `<photo_id>__<filename>` and
  `thumb_<photo_id>__thumb.jpg`.
