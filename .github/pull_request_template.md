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
