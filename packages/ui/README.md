# UI (`packages/ui`)

<details>
<summary>Relevant source files</summary>

- [.gitkeep](.gitkeep) — the only file in this package besides this README; it keeps the directory in git
- [pnpm-workspace.yaml](../../pnpm-workspace.yaml) — includes `packages/*` in the pnpm workspace
- [apps/web/src/components/](../../apps/web/src/components/) — where the current UI components live

</details>

Source references verified against commit `437ce55`.

`packages/ui` is a reserved location for a shared UI package. It holds no code
and no `package.json` yet, so pnpm does not treat it as a workspace package and
nothing imports from it. This page exists so contributors know the directory is
intentionally empty of code.

## Where UI code lives today

All React components, including the Evidence Reader and Search Observatory, are
in [`apps/web/src/components`](../../apps/web/src/components/), next to their
tests. Build new components there unless a task explicitly assigns work to
`packages/ui`.

## Before adding code here

Several workstreams list `packages/ui/**` in their allowed paths alongside
`apps/web/**`, so the directory is shared territory. Check the assigned issue's
allowed paths in [`docs/handoff/workstreams.yaml`](../../docs/handoff/workstreams.yaml)
before writing here, and serialize with any other active package that claims it.
Turning it into a real package needs a `package.json`, which changes the
lockfile, a shared path; see [AGENTS.md](../../AGENTS.md).

## Related pages

- [Architecture overview](../../docs/architecture/overview.md) — containers and packages
- [Testing guide](../../docs/development/testing.md) — web component tests
- [Local development](../../docs/development/local.md) — running the web app
