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

This file documents GitHub configuration; editing it does not apply settings.
The September 10, 2026 initial API audit found `main` unprotected with no
repository rulesets. After PR #269 merged, the integration lead applied and
read back branch protection: all seven checks above are bound to the GitHub
Actions app (15368), strict/up-to-date checking and administrator enforcement
are enabled, and force-pushes/deletion are disabled. The application record is
in [issue #203](https://github.com/wilsonhj/financial-evidence-lab/issues/203).
No required-review count or fabricated second CODEOWNER was configured.

CODEOWNERS still names the existing real integration lead. Adding a second
reviewer requires an identified GitHub account/team with repository access;
a placeholder or fabricated reviewer would not enforce review separation.
