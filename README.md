# Ordo — Review Path

## What it does

[Ordo](https://github.com/Spot2025/ordo/tree/v0.2.0) analyzes the Go call graph
and recommends a dependency-aware review order: callees before callers.
This composite Action publishes that Review Path in a GitHub Actions Job Summary.
Each location links to the PR's **Files changed** view; **source** opens the exact
head commit. Cycles stay grouped and probable call-graph artifacts stay labelled.

## Quick start

Add `.github/workflows/ordo-review-path.yml`:

```yaml
name: Ordo — Review Path

on:
  pull_request:
    types:
      - opened
      - synchronize
      - reopened
      - ready_for_review

permissions:
  contents: read

concurrency:
  group: ordo-review-path-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review-path:
    if: ${{ github.event.pull_request.draft == false }}
    name: Ordo — Review Path
    runs-on: ubuntu-latest

    steps:
      - uses: Spot2025/ordo-action@v1
```

The Action performs checkout itself; no preceding checkout step is needed.
The caller job's `name` determines the GitHub check name. Grant `contents: read`.
A root Go module needs no `with`. For a nested module, replace the action step:

```yaml
      - uses: Spot2025/ordo-action@v1
        with:
          path: awesomeProject
```

Use `Spot2025/ordo-action@v1` to receive compatible v1 updates,
`Spot2025/ordo-action@v1.0.0` to pin this release,
or a full commit SHA for maximum supply-chain stability.

## Example output

Location labels below represent clickable PR diff links, with exact-source
fallback links alongside them:

```text
# Ordo — Review Path

Changed functions: 4
Review steps: 3

## 1 · internal/model/user.go:42 (source)
User.Validate()

## 2 · internal/service/user.go:18 (source)
StoreUser()

## 3 · Cycle · 2 functions
🔁 These functions form a dependency cycle; review them together.
- Even() — internal/parity/parity.go:9 (source)
- Odd() — internal/parity/parity.go:16 (source)

▸ Full function IDs
```

No changed Go functions produces a successful, concise empty summary.

## How it works

```text
pull_request
      ↓
checkout exact head + base SHA
      ↓
Ordo v0.2.0
      ↓
stable JSON
      ↓
Markdown renderer
      ↓
GitHub Job Summary
```

Both checkouts fetch full history with credentials persistence disabled. The
base history is imported locally into the head checkout as `refs/remotes/ordo/base`;
its merge base with the exact head determines the diff. Analysis never uses the
synthetic merge commit or a moving base branch name.

Go is set up with `actions/setup-go@v7`, Go `1.25.x`, and caching disabled.
Ordo is installed using
`go install github.com/Spot2025/ordo/cmd/ordo@v0.2.0` in an isolated directory
under `$RUNNER_TEMP` with `GOWORK=off` during installation and standard Go checksum
verification. From the canonical module directory, the command is:

```sh
"${ORDO_BIN}" --diff --diff-base refs/remotes/ordo/base --format json "./..."
```

The renderer validates the report and preserves its step and SCC-member order.
It publishes a complete Markdown file only after rendering succeeds. Internal
failures fail the Action and add a friendly summary; diagnostics remain in logs.

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| `path` | `.` | Repository-relative Go module or Go workspace directory in the PR head. Must contain `go.mod` or `go.work`. |

Spaces and Unicode are supported. Absolute paths, `..` components, backslashes,
control characters and symlinks escaping the head checkout are rejected.
There are no public outputs. The v1 contract is Job Summary and exit status.

## Security

- Use `pull_request`. The Action rejects `pull_request_target` and every other event.
- No repository secrets, PAT, App token, OIDC or write permissions are required.
  Checkout uses the standard read-only `GITHUB_TOKEN`; credentials are not persisted.
- The Action executes its versioned scripts, Ordo and Go/Git tooling. It does not
  run target tests, `go generate`, Makefiles, scripts, application binaries,
  containers or linters.
- Go tooling still reads, parses and type-checks PR-controlled source and module
  metadata and may download dependencies. Use a GitHub-hosted ephemeral runner.
- Consumers can pin `Spot2025/ordo-action` to a full commit SHA for maximum
  supply-chain stability. See GitHub's [action pinning guidance](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions).

## Current limitations

- GitHub.com, `pull_request` and `ubuntu-latest` are the supported environment;
  no GHES, Windows, macOS, merge queue, submodule or Git LFS guarantee.
- Go only. Public and private same-repository PRs work when dependencies are
  available to the runner. No credentials for private Go dependencies are provided.
- Public fork PRs use separate head and base repositories, within standard token
  access and GitHub's fork-workflow approval policy. Private fork PRs are unsupported.
- Analysis covers the whole module before filtering changed functions. Go must
  accept `./...` from the selected directory, including when using `go.work`;
  the Action does not expand workspace modules into custom package patterns.
- CHA may over-approximate interface/callback edges; an artifact warning denotes
  Ordo's classification, not proof of a runtime dependency cycle.
- Large reports are bounded to **900 KiB of UTF-8 Markdown**. Full function IDs
  have lower priority than the Review Path. Oversized paths keep complete steps;
  a large SCC keeps its warnings and as many complete function bullets as fit,
  with displayed/omitted counts. Run Ordo locally for the complete result.
- A PR diff anchor can land on an exact line only when that line is in the diff
  hunk. The adjacent **source** link points to the exact head source, including forks.
- No comments, annotations, GitHub App or backend.

## Versioning

`v1.0.0` is the intended immutable release version; `v1` is a convenient moving
major tag for compatible updates. A full commit SHA is the safest consumer pin.
Action v1 owns compatibility with Ordo v0.2.0 internally; the Ordo version is
not an input. Releases and tag updates are performed manually by the owner.

## Development

Python uses only the standard library. Run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v
bash -n scripts/*.sh
for script in scripts/*.sh; do bash -n "$script"; done
git diff --check
```

CI also installs `github.com/rhysd/actionlint/cmd/actionlint@v1.7.7` and validates
the workflows and referenced local Action metadata. Tests include the 16 extracted
renderer cases, a full dogfood Markdown snapshot, validation/link/size checks,
and subprocess tests of action glue using disposable local repositories and an
Ordo stub. They are **not a GitHub PR E2E test**. Release candidates must first be
tested in real root-module, nested-module, empty-diff, cycle, large and fork PRs
using the pushed candidate's exact commit SHA.

MIT licensed; see [LICENSE](LICENSE).
