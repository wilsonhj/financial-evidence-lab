# Required pull-request checks

Target: `main`. Keep these exact check names synchronized with workflow job
names. All seven checks must succeed on the current PR head before merge:

- `Secret scan (gitleaks)`
- `JS/TS — format, lint, typecheck, test, audit`
- `Web — Playwright E2E (fixture mode)`
- `Python — format, lint, typecheck, test, security`
- `Python — reproducible production installs`
- `DB — migration and backup-restore smoke`
- `Shared-path changes carry contract-change`

Vercel preview status is supplemental; GitHub's fixture and runtime checks own
repository acceptance. Do not make a provider's informational preview comment
a required check. Enable strict checks against the current base and prohibit
force-push/deletion of `main`. Shared-path changes continue to require the
`contract-change` label and integration-lead review under AGENTS.md.

This file records intent; it does not itself configure GitHub. The September
10, 2026 read-only API audit found `main` unprotected and no repository rulesets.
Apply and read back required checks after their implementation PR is merged;
record the resulting protection/ruleset artifact in #203. No actual protection
application is claimed by this document.

CODEOWNERS still names the existing real integration lead. Adding a second
reviewer requires an identified GitHub account/team with repository access;
a placeholder or fabricated reviewer would not enforce review separation.
