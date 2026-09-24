# Source of this skill

This directory is a copy of `skills/ux-review/` from
https://github.com/crowecawcaw/ux-skills at commit
`b772a0945bbe1918ccf919ea95a50ce5216f5f53` (2026-07-07). Do not edit the copied
files. To update the skill, copy the directory again from a newer commit and
change the commit in this file.

## How to use the skill in this repository

- **The running app.** Start Home Assistant with the seeded data:
  `KEEP_UP=1 bash ci/e2e-up.sh`. The panel is at `http://localhost:8123/home-keeper`.
  Log in as the e2e user from `tests/e2e/global-setup.ts`, or use the saved
  session state that the global setup writes.
- **The screenshots.** Use the Playwright harness in `tests/e2e/` in place of the
  upstream `shoot.mjs` helper. Write review screenshots to the output directory of
  the review, not to `docs/images/`.
- **The style inventory.** `tools/style-inventory.mjs` needs `playwright-core`.
  `tests/e2e/node_modules` has it. The panel is behind a login, so give the tool a
  URL only after you add the session state, or measure from a Playwright script.
- **The brief.** Write the brief for the surface that you review. The persona is a
  Home Assistant user who keeps a house in order. The surface type is usually
  `dashboard` or `list`. The tone words come from the Home Assistant frontend:
  calm, dense, functional.
- **Phone and desktop.** Below 700px the panel is a different layout. Review both
  widths (`DESKTOP` and `PHONE` in `tests/e2e/viewports.ts`).
