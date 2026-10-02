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
- **The style inventory.** Use `tools/style-inventory-ha.mjs`, not the upstream
  `tools/style-inventory.mjs`. The upstream tool does not look inside shadow roots,
  so on Home Assistant it measures only the loading screen. The copy collects the
  elements in every open shadow root and logs in with the session state that
  `tests/e2e/global-setup.ts` writes. Run it from `tests/e2e`, so that
  `playwright-core` resolves:
  `STORAGE_STATE=.auth/state.json node ../../.claude/skills/ux-review/tools/style-inventory-ha.mjs <scenario.json> <out.md>`.
  Give the scenario a first `wait` of about 9000 ms. A cold panel is still on the
  loading screen after 4 s. A scenario that picks a layout changes the stored
  layout for the e2e user, so end with a scenario that picks `rows` again.
  The report covers the whole page, with the Home Assistant sidebar, so judge only
  the elements of the surface that you review.
- **The brief.** Write the brief for the surface that you review. The persona is a
  Home Assistant user who keeps a house in order. The surface type is usually
  `dashboard` or `list`. The tone words come from the Home Assistant frontend:
  calm, dense, functional.
- **Phone and desktop.** Below 700px the panel is a different layout. Review both
  widths (`DESKTOP` and `PHONE` in `tests/e2e/viewports.ts`).
