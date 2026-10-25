<!--
Link the issue this fixes with `Fixes #N` below.

Closing-on-merge is off for this repo, so the keyword links the PR to the issue
without closing it. The issue stays open until the fix actually ships, and
release.yml's notify-issues job closes it on the release that carries it — so the
reporter's "closed" notification names a version they can install.

For that to happen the issue also needs a `(Fixes #N)` line in the CHANGELOG entry:
that section is what the release reads to decide who gets told.
-->

Fixes #

## What changed

## One-way doors

<!-- Each external contract this change commits to. See .amazonq/rules/pr-workflow.md. -->

## Security

<!-- 1 row for each surface this change adds or changes: admin-only or open, and why. -->
<!-- See .amazonq/rules/pr-workflow.md. Write "No surface changed" if there is none. -->

| Surface | Before | After | Rule | What a user who is not an admin can now do |
| --- | --- | --- | --- | --- |

## Checklist

- [ ] Tests run locally (`pytest tests/unit -v`, `bash ci/test-frontend.sh`)
- [ ] `CHANGELOG.md` updated — user-facing changes only, with `(Fixes #N)` for each
      issue this fixes (developer-only changes don't need an entry)
- [ ] Panel UI changed → current screenshots committed under `docs/images/` and
      embedded above with an HTML `<img>` tag
- [ ] New user-facing UI surface → `tests/e2e/walkthrough.capture.ts` extended to
      step through it
- [ ] New user-facing feature → version bumped to the next beta (`manifest.json` +
      `const.py`), `preview-release` label applied
- [ ] `python3 ci/docs.py check` is clean. For each design doc re-stamped, say if
      its text changed, or why the code change needs no doc change
- [ ] A design doc's Goals or Non-goals changed → a **Goal changes** section below
      that says what changed and that the maintainer agreed
- [ ] The **Security** section lists each changed surface as admin-only or open, and
      `api_surface.py`, `docs/SECURITY.md` and `test_admin_gates.py` agree with it
