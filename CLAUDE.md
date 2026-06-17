# Home Keeper — Claude Code memory

@AGENTS.md

The project's workflow, conventions, and **hard gates** live in `AGENTS.md`
(imported above) and `.amazonq/rules/`. Read them before pushing.

One gate worth repeating because it is easy to miss: **every PR that touches the
panel UI (`custom_components/home_keeper/frontend/src/`) MUST include current
screenshots** of the changed surface — captured with the Playwright harness,
committed under `docs/images/`, and embedded in the PR body (SHA-pinned
`raw.githubusercontent.com` URL, HTML `<img>` tag). See AGENTS.md "Workflow".
