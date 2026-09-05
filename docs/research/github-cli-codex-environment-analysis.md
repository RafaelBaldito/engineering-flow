# GitHub CLI for the Personal WSL Codex Environment

**Date:** 2026-09-05  
**Scope:** Adopted personal WSL Codex development tooling only. This records a personal tool installation and credential state; it does not add a repository dependency or Engineering Flow runtime behavior.

## Recommendation

GitHub CLI (`gh`) is installed and adopted for personal Ubuntu-on-WSL use when GitHub repository, pull request (PR), issue, or Actions work is routine. It complements Git; it does not replace it. Use it as the first GitHub-hosting integration before considering a GitHub MCP server.

This is **not** a recommendation to make `gh` a dependency of Engineering Flow. The application must remain able to run and validate without it unless a future, explicitly approved provider integration chooses an implementation and declares its dependency contract.

## Adopted environment and validation

| Observation | Evidence and consequence |
|---|---|
| WSL distribution | Ubuntu 24.04. Use a Linux-native installation; do not rely on a Windows executable or Windows credential state. |
| `gh` installation | Installed successfully in WSL: `gh version 2.100.0 (2026-09-03)`. |
| Authentication | `gh auth status` confirmed active account `RafaelBaldito`, HTTPS Git protocol, and scopes `gist`, `read:org`, `repo`, and `workflow`. |
| Credential storage | Credentials are currently stored in plain text at `/home/bal/.config/gh/hosts.yml`. This is an accepted current personal-environment limitation, not an Engineering Flow product decision. |
| Read-only smoke test | `gh repo view RafaelBaldito/engineering-flow --json nameWithOwner,defaultBranchRef,url,visibility` succeeded and confirmed `RafaelBaldito/engineering-flow`, default branch `main`, and `PUBLIC` visibility. |
| Current repository identity | `origin` is `https://github.com/RafaelBaldito/engineering-flow.git`; `main` tracks `origin/main`. Git already supplies local repository, remote, commit, branch, and tracking information. |
| Codex MCP state | `codex mcp list` reported only Context7; no GitHub MCP is configured in this WSL client. |
| Existing project decision | The existing environment audit recommends WSL `gh` with least privilege before GitHub MCP, and defers GitHub MCP until a measured gap exists. |
| Product boundary | The delivery plan reserves commit, push, and PR creation for future Wave 4 controlled delivery; Wave 3 explicitly has no hosting side effects. |

The working tree had one unrelated, untracked research document before this analysis. It was not changed.

## Recommended installation and authentication

### Installation record

`gh` was installed successfully as an OS-level personal WSL tool, outside this repository, its Python environment, and its `env-preflight` contract. GitHub's official Debian/Ubuntu APT repository remains the recommended installation source. [GitHub CLI Linux installation guide](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)

### Authentication

After installation, use the interactive GitHub.com browser/device flow:

```text
gh auth login --hostname github.com --git-protocol https --web --skip-ssh-key
```

This matches the existing HTTPS remote. Authentication completed successfully for `RafaelBaldito`; `gh auth status` confirmed the active account, HTTPS protocol, and scopes `gist`, `read:org`, `repo`, and `workflow`. Credentials are presently stored in the documented plain-text fallback at `/home/bal/.config/gh/hosts.yml`. [GitHub CLI authentication manual](https://cli.github.com/manual/gh_auth_login)

Prefer this interactive OAuth login for a personal, attended environment. Do not place a long-lived token in shell startup files, a repository `.env`, a prompt, or a committed config. `GH_TOKEN` is appropriate only for deliberately headless, narrowly scoped automation; it would be inherited by child processes and is therefore not the preferred interactive Codex setup.

### Minimum practical scopes and permissions

For the stated normal repository workflow, accept only the scopes requested by the standard `gh auth login` flow; do not add `project`, `workflow`, `admin:org`, `delete_repo`, or other extra scopes merely in anticipation of future work. GitHub CLI documents the classic-token minimum it expects when a token is supplied on standard input as `repo`, `read:org`, and `gist`; that is why a hand-created restrictive fine-grained PAT can behave unexpectedly with some CLI commands. [GitHub CLI authentication manual](https://cli.github.com/manual/gh_auth_login)

Repository permission is inherently broad for private repositories: it permits reading private repository content and, where the account has write access, writing PRs/issues/comments and other supported resources. The minimum practical *operational* posture is therefore:

- Allow read-only `gh` commands by default.
- Require an explicit, task-specific instruction before a command creates or edits a PR, issue, comment, label, review, workflow run, merge, or release.
- Use a separate fine-grained PAT or GitHub App only if unattended automation becomes necessary, restricted to selected repositories and only the required permissions.
- Keep Actions write/re-run, project, organization, administration, secret, and deletion operations out of the normal Codex command allowlist.

## Tool choice by operation

| Operation | Preferred tool | Why |
|---|---|---|
| Repository identity, remotes, local/upstream branches, commits, log, blame, worktree, status, staging, commit, merge/rebase, fetch/push | **Git** | These are Git transport/history concerns. `gh` adds no material value and should not replace familiar, local, offline-capable Git commands. |
| Open a repository/PR/issue in its web UI; rich visual review, threaded discussion, settings, or a one-off manual decision | **Browser/manual GitHub** (optionally `gh … --web`) | The browser remains best when visual context or human interaction matters. |
| Current-branch PR identity; concise PR metadata, review decision, mergeability, check rollup, review requests, or comments | **`gh pr view` / `gh pr checks`** | Git does not know GitHub's PR and review state. `gh pr view` can select only requested JSON fields. [PR view manual](https://cli.github.com/manual/gh_pr_view) |
| List/filter PRs or inspect PR changes without browser copying | **`gh pr list`, `gh pr diff`, `gh pr view`** | Adds GitHub PR state and review data on top of local Git diffs. `gh pr list` supports server-side filters, limits, explicit JSON fields, and built-in `--jq`. [PR list manual](https://cli.github.com/manual/gh_pr_list) |
| Create a review-ready PR after an explicit human/task authorization | **`gh pr create`** | Converts an already-pushed branch into a PR with title/body/base/reviewer/template flags. It is an external write and is never an implicit follow-on to local Git work. [PR create manual](https://cli.github.com/manual/gh_pr_create) |
| List, search, view, or create GitHub issues | **`gh issue`** | Issues are GitHub records, unavailable through Git. Use filters and limits. [Issue list manual](https://cli.github.com/manual/gh_issue_list) |
| GitHub Actions/Checks status and focused failure inspection | **`gh pr checks`, `gh run list`, `gh run view`** | Git has no hosted CI status. `gh run list` supports branch/commit/status filters, a limit, JSON fields, and `--jq`. [Run list manual](https://cli.github.com/manual/gh_run_list) |
| Uncommon endpoint, pagination, preview API, or repeatable custom data query | **`gh api` first; direct GitHub API integration only when reusable product code needs it** | `gh api` reuses CLI authentication and is low ceremony. A direct API client is justified only for durable, tested, provider-specific integration with a stable contract, retry/rate-limit handling, and explicit auth design. |

## Agent-friendly, bounded output

`gh` JSON is useful for Codex when commands state an explicit repository, small limit, and the minimum fields needed. It avoids scraping browser pages and turns a hosted-state question into a small, machine-readable result. It does not eliminate the need to bound a diff, log, check output, or comment body.

Examples (illustrative):

```text
gh pr list --repo RafaelBaldito/engineering-flow --author @me --limit 10 \
  --json number,title,url,headRefName,reviewDecision,statusCheckRollup

gh pr view --repo RafaelBaldito/engineering-flow --json \
  number,title,state,reviewDecision,mergeStateStatus,statusCheckRollup,url

gh run list --repo RafaelBaldito/engineering-flow --branch main --limit 5 \
  --json databaseId,displayTitle,status,conclusion,url

gh issue list --repo RafaelBaldito/engineering-flow --state open --limit 10 \
  --json number,title,labels,assignees,url
```

Use `--jq` only to reduce an already limited JSON response further; it is built into `gh`. Avoid unbounded `--comments`, broad search queries, raw run logs, or PR diffs unless the task needs them. Request exact fields rather than a full API response. The CLI documents JSON-field selection and `--jq` for PR, issue, and run list commands. [PR JSON options](https://cli.github.com/manual/gh_pr_list), [issue JSON options](https://cli.github.com/manual/gh_issue_list), [run JSON options](https://cli.github.com/manual/gh_run_list)

## GitHub MCP and direct API comparison

For the current personal environment, GitHub MCP has no material capability gap after `gh` for the stated operations: repository identification, PR and issue lookup/creation, PR diff/review/check information, and Actions status are all available through Git plus `gh`. MCP could offer discovery-oriented tool schemas or an integration with a service that exposes a feature absent from the CLI, but it also adds a server, credential/auth configuration, tool schema, maintenance path, and another potential write surface.

**Do not install GitHub MCP now.** Re-evaluate only after a recurring, documented workflow remains awkward with bounded `gh` commands and the browser, or requires a GitHub capability that `gh` and `gh api` cannot meet. If that happens, define per-tool read/write permissions, repository scope, response limits, audit behavior, and whether its credential is separate from `gh`.

Direct GitHub API integration is not a better personal default. It is more flexible than `gh` for custom schema, application-owned tokens, webhooks, pagination, and provider-specific reusable code, but it requires implementing authentication, error/rate-limit behavior, output shaping, and maintenance. It belongs only in an approved product integration, not as a replacement for a personal command-line client.

## Security implications for Codex invoking `gh`

Giving Codex access to `gh` gives any permitted shell command the authority of the authenticated GitHub account. A malicious repository instruction, prompt injection in an issue/PR, or command-construction error could read private metadata or make remote changes. It may also expose sensitive issue/PR content, CI logs, artifact links, or token-adjacent configuration in command output.

Mitigations are explicit command authorization for writes, least privilege, per-command repository selection, no token display/export, bounded JSON fields/limits, no automatic merge/retry/cancel/delete/secret commands, periodic `gh auth status` review, and revocation/logout when the environment is no longer trusted. GitHub-side branch protection and required reviews remain important independent controls; `gh` does not bypass account or repository permissions.

## Potential future Engineering Flow capability (separate from this decision)

The future product capability demonstrated by `gh` is a **provider-adapter boundary for controlled GitHub delivery and reconciliation**: after the existing Wave 4 authorization gates, create or locate the PR for the exact pushed branch, capture a bounded PR URL/number/state/check summary, and reconcile it into durable delivery evidence. `gh` could be one implementation candidate during an explicitly approved design, alongside direct API or another hosting adapter. It is not a present runtime capability, it must remain provider-neutral at the domain boundary, and this personal-tool decision does not authorize implementing it.

## Decision and blockers

**Decision:** `gh` is adopted optional personal WSL tooling; do not add GitHub MCP now and do not alter Engineering Flow.

**Blockers:** none. This adoption does not authorize external-write commands without an explicit, task-specific instruction.
