# Security model

Home Keeper has one rule: only an admin can manage the home. Any signed-in user
can use it. Admins control the configuration and the appliance costs. Any user can
see due tasks and complete them.

This page shows what a non-admin user can and cannot do.

## Why this rule exists

A Home Assistant instance usually has 1 or 2 admins and a few users, such as
a partner, older children, a housemate, or a guest account on a wall tablet.

Home Assistant reserves Settings and Developer tools for admins. Home
Assistant also restricts its own `config/*` commands, such as the device
registry, the entity registry, and config entries, to admins. Home Keeper
follows the same rule.

The risks are small. A guest account must not:

- delete appliance records
- redirect notifications away from you
- read purchase prices and serial numbers that you keep for insurance

## Admin only

The Home Keeper panel is admin-only. It is in the Home Assistant sidebar. A non-admin user does not see
the panel.

Home Keeper gates each admin operation in 2 places: the websocket API the
panel uses, and the matching `home_keeper.*` service.

| Operation | Services |
| --- | --- |
| Create, edit, delete, archive and restore appliances | `add_asset`, `update_asset`, `delete_asset`, `archive_asset`, `restore_asset` |
| Appliance documents and part files | `add_asset_document`, `update_asset_document`, `remove_asset_document`, `remove_part_file` |
| Spare-part stock adjustments | `adjust_part_stock` |
| Settings, profiles and notification delivery | `set_options` |
| The home-inventory export (costs, serials, value totals) | `export_inventory` |

Home Keeper creates a Home Assistant device for each appliance, and removes
the device when it deletes the appliance. Home Assistant reserves the
device registry for admins, so appliance changes are admin-only for this
reason too.

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

The card reads appliance data, so a non-admin user gets a narrowed view: the
appliance's documents, its link-type custom fields, and each part's name
and product URL.

The narrowed view withholds purchase costs, part costs, serial numbers,
warranty dates, and free-text custom fields. The narrowed view is an allowlist. A new appliance field stays private until a
developer adds it to the allowlist.

## Notifications

Home Keeper delivers only to 2 targets: companion-app notify services
(`notify.mobile_app_*`) and `persistent_notification`.

Home Keeper refuses any other target. A saved notification with another
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
for the panel, and 15 minutes for the `sign_document_url` and
`sign_part_file_url` services. A service result can leave the panel, so it
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
succeeds. The narrowed appliance view only lists documents already shown on
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
