---
title: Security model
summary: What admins and non-admin users can do in Home Keeper, for maintainers and admins.
---

# Security model

Home Keeper has one rule: only an admin can manage the home. Any signed-in user
can use it. Admins control the configuration and the appliance costs. Any user can
see due tasks and complete them.

## Why this rule exists

A Home Assistant instance usually has 1 or 2 admins and a few users, such as
a partner, older children, a housemate, or a guest account on a wall tablet.

Home Assistant reserves Settings and Developer tools for admins. Home
Assistant also restricts the changes that its own `config/*` commands make,
such as changes to the device registry and the entity registry, and to config
entries, to admins. Home Keeper follows the same rule.

The risks are small. A guest account must not:

- delete appliance records
- redirect notifications away from you
- read purchase prices and serial numbers that you keep for insurance

## Admin only

The Home Keeper panel in the Home Assistant sidebar is admin-only. A non-admin user does
not see the panel.

Home Keeper gates each admin operation in 2 places: the websocket API the
panel uses, and the matching `home_keeper.*` service.

| Operation | Services |
| --- | --- |
| Create, edit, delete, archive and restore appliances | `add_asset`, `update_asset`, `delete_asset`, `archive_asset`, `restore_asset` |
| Appliance documents and part files | `add_asset_document`, `update_asset_document`, `remove_asset_document`, `remove_part_file`, and a file upload (`POST`) to `/api/home_keeper/document/…` or `/api/home_keeper/part_document/…` |
| Task photos | `remove_task_photo`, `set_task_photo_cover`, and a photo upload (`POST`) to `/api/home_keeper/task_photo/…` |
| Delete an archived completion from an appliance's history | `delete_archived_completion` |
| Delete every orphaned task (a task whose managing integration is not loaded) | `delete_orphaned_tasks` |
| Spare-part stock adjustments | `adjust_part_stock` |
| Settings, profiles and notification delivery | `set_options` |
| The appliance report (costs, serials, value totals) | `export_appliance_report` |
| Data export and import (every task, note, serial and cost) | `export_data`, `import_data` |

Home Keeper creates a Home Assistant device for each appliance and removes it with the
appliance. Home Assistant reserves device registry changes for admins, so this is a second
reason that appliance changes are admin-only.

Any signed-in user can read the device registry, which shows the name, make,
model and area of each appliance. For this reason, Home Keeper keeps the serial
number only in the appliance record and does not copy it to the device.

A websocket command and its service twin share one authenticated
connection. If Home Keeper gates only the websocket command, `call_service`
bypasses the gate. When you add a new admin operation, gate both the
websocket command and the service.

Home Keeper trusts calls with no user, such as a scheduled automation, the
same way Home Assistant does.

## Open to any signed-in user

Any signed-in user can use these surfaces:

- The to-do list, the calendar, and the per-task device-page entities.
- The dashboard task card, with its document and product links.
- Complete, snooze, skip and create tasks.
- Read tasks and profiles.

The card reads appliance data, so a non-admin user gets a narrowed view. It holds the
appliance's documents and its link-type custom fields. For each part it holds the name,
product URL, stock count, reorder point and stock unit. Stock is not private: the
spares `number` entity of each part shows the count to every user.

For a counted wear item, the narrowed view also has the replacement target, the
name of the uses, and the count that came in with an import. The card uses these
fields to show the progress, such as "17 of 25 wears". The user who records the
uses can then see the count.

The narrowed view withholds purchase costs, part costs, part vendors, part numbers,
serial numbers, warranty dates, and free-text custom fields. The narrowed view is an
allowlist. A new appliance field stays private until a developer adds it.

## Notifications

Home Keeper delivers only to 2 targets: companion-app notify services
(`notify.mobile_app_*`) and `persistent_notification`.

Home Keeper rejects any other target. A saved notification with another
target is dropped, with a warning in the log. A call to `home_keeper.notify`
with another target fails.

This stops Home Keeper from relaying text through a channel the caller
cannot reach directly, such as an email or chat integration an admin
configured. `persistent_notification` is allowed because it never leaves
the instance.

## Files and links

Home Keeper serves uploaded manuals, receipts and photos through an
authenticated Home Assistant view.

To open a file, the panel creates a signed URL. The signed URL lasts 1 hour
for the panel, and 15 minutes for the `sign_document_url`,
`sign_part_file_url` and `sign_task_photo_url` services. A service result can leave the panel, so it
gets the shorter lifetime.

A signed URL is a bearer credential. Anyone who has the link can get the
file until it expires, without a login. A screenshot with a signed URL
needs the same care as the file itself.

Home Assistant accepts a signature on `GET` and `HEAD` requests only. The
upload endpoints also require a real authenticated user, so a link that can
read a file can never replace it.

A signed URL is not admin-only. The card needs one to open a document on a task
that any user can complete.

Home Keeper accepts one consequence: a non-admin user who guesses an appliance id
and a document id learns whether that pair exists, from whether the request
succeeds. The same applies to a task id and a photo id.

Home Keeper reads the whole image of a task photo to make its thumbnail. It refuses
a file that is not a readable PNG, JPEG, WebP or GIF image.

The pixel limit is 50 million. A baseline RGB or greyscale JPEG has a limit of 250
million, because Home Keeper decodes it at 1/8 of its size or less. The narrowed appliance view only lists documents already shown on
a card.

Home Assistant serves only the 2 built JavaScript bundles as a static path. Home
Assistant serves static paths before authentication, so Home Keeper does
not mount the panel's source tree or its dependencies.

Home Keeper escapes every URL it renders as a link, and it also checks that the
URL scheme is safe, because an escaped `javascript:` link is still a live link.
Some links come from other integrations through `add_task`, so the scheme check
runs at render time even if the stored value was already validated.

## Limits of this security model

- **An admin is an admin.** Home Keeper does not protect an instance from
  its own admins. Anyone who can read the Home Assistant configuration
  directory can read the integration's data.
- **Home Assistant's own authentication is the security perimeter.** This
  page does not help if an account is shared or a long-lived token leaks.
- **A non-admin user can create and complete tasks.** Home Keeper has no
  read-only user. Use Home Assistant's own user model for that.

## Report a problem

Open an issue at
[github.com/prestomation/ha-home-keeper/issues](https://github.com/prestomation/ha-home-keeper/issues).

For a problem you do not want to post publicly, use GitHub's private
vulnerability reporting on the same repository.
