# Security model

Home Keeper draws one line: **managing your home is an admin job, using it is not.**
Everything that changes configuration or reveals what your things cost belongs to
Home Assistant administrators. Everything a household member needs to see what is
due and mark it done stays open to any signed-in user.

This page says where that line falls, so you know what a non-admin account in your
household can and cannot do.

## Why the line is there

A Home Assistant instance usually has one or two admins and a handful of ordinary
users. A partner, older kids, a housemate, maybe a guest account on the wall tablet.
Home Assistant already reserves Settings and Developer tools for admins, and its own
`config/*` commands (device registry, entity registry, config entries) are
admin-only. Home Keeper follows the same convention rather than inventing a second,
weaker one.

The risks here are modest and domestic. A guest account should not be able to delete
the appliance records you built up. It should not be able to redirect your reminders
somewhere you won't see them, or read the purchase prices and serial numbers you keep
for insurance.

## Admin only

Administration lives in the **Home Keeper sidebar panel**, which is registered as an
admin-only panel. A non-admin does not see it in the sidebar. Behind it, these
operations are gated on the server, in both the websocket API the panel uses and the
matching `home_keeper.*` service:

| Operation | Services |
| --- | --- |
| Create, edit, delete, archive and restore appliances | `add_asset`, `update_asset`, `delete_asset`, `archive_asset`, `restore_asset` |
| Appliance documents and part files | `add_asset_document`, `update_asset_document`, `remove_asset_document`, `remove_part_file` |
| Spare-part stock adjustments | `adjust_part_stock` |
| Settings, profiles and notification delivery | `set_options` |
| The home-inventory export (costs, serials, value totals) | `export_inventory` |

Appliance changes are admin-only for a second reason: creating an appliance creates a
Home Assistant **device**, and deleting one removes that device and its entities.
Writing the device registry is a privilege Home Assistant reserves for admins, and
Home Keeper does not hand it out through a side door.

Both surfaces are gated, deliberately. A websocket command and its service twin are
the same operation over the same authenticated connection, so gating only the
websocket command leaves `call_service` as an open door. When you add a new
administrative operation, gate both.

Calls that carry no user, such as an automation firing on a schedule, are treated as
trusted, the same way Home Assistant treats them.

## Open to any signed-in user

Usage is not gated, because a reminder nobody can act on is not a reminder:

- The **to-do list**, the **calendar**, and the per-task **device-page entities**.
- The **dashboard task card**, including its document and product links.
- Completing, snoozing and skipping tasks, and creating tasks.
- Reading tasks and profiles.

Appliance data is readable by the card, so it is not admin-only, but a non-admin
receives a **narrowed view** holding only what the card renders. That means an
appliance's documents, its link-type custom fields, and the name and product URL of
each part. Purchase costs, part costs, serial numbers, warranty dates and free-text
custom fields are withheld. The narrowed view is a whitelist, so a field added to the
appliance record later stays private until someone publishes it on purpose.

## Notifications

Home Keeper delivers only to companion-app notify services (`notify.mobile_app_*`)
and to `persistent_notification`. Any other target on a saved notification, or passed
to `home_keeper.notify`, is refused: a saved one is dropped with a warning in the
log, an explicitly requested one fails the call.

The restriction exists so that Home Keeper cannot be used to relay text through a
channel the caller could not reach on their own, such as an email or chat integration
an admin configured. `persistent_notification` is allowed because it never leaves the
instance.

## Files and links

Uploaded manuals, receipts and photos are served through an authenticated Home
Assistant view. To open one in a browser tab, the panel mints a **signed URL** with a
short lifetime (one hour for the panel, fifteen minutes for the
`sign_document_url` / `sign_part_file_url` services, whose result may travel further).

A signed URL is a bearer credential for the file it names. Anyone holding the link can
fetch that file until it expires, without logging in, so a screenshot of a dashboard
carrying one deserves the same care as the file itself. Home Assistant honours a
signature on `GET` and `HEAD` only, and the upload endpoints also refuse any request
that is not authenticated as a real user, so a link that can read a file can never be
used to replace it.

Minting a signed URL is not admin-only, because the card needs one to open a document
on a task anyone can complete. A known consequence, accepted rather than overlooked:
a non-admin who guesses an appliance and document id learns whether that pair exists,
from whether the request succeeds. Guessing is the operative word. The narrowed
appliance view only lists documents already surfaced on a card.

Only the two built JavaScript bundles are published as a static path. Home Assistant
serves static paths before authentication, so the panel's source tree and its
dependencies are deliberately not mounted.

Every URL Home Keeper renders into a link is scheme-checked as well as escaped.
Escaping alone does not neutralise a `javascript:` link, and some links come from
other integrations through `add_task`, so the check runs at the point of rendering
even where the stored value was already validated.

## Outside the boundary

- **An admin is an admin.** Home Keeper does not defend an instance against its own
  administrators, and the integration's data is readable by anyone who can read the
  Home Assistant configuration directory.
- **Home Assistant's own authentication is the perimeter.** Nothing here helps if an
  account is shared or a long-lived token leaks.
- **A non-admin can still create and complete tasks**, which is the point. If you need
  a read-only member, Home Assistant's own user model, not Home Keeper, is where that
  belongs.

## Reporting a problem

Open an issue at
[github.com/prestomation/ha-home-keeper/issues](https://github.com/prestomation/ha-home-keeper/issues).
For something you would rather not post publicly, use GitHub's private vulnerability
reporting on the same repository.
