# Codex reasoning profiles: WSL environment analysis

Date: 2026-09-05  
Scope: personal Codex configuration only. This analysis does not change Codex
configuration, repository source, Skills, `AGENTS.md`, or Engineering Flow
workflow contracts.

## Recommendation

Use Codex's native file-backed profiles. Keep the current
`~/.codex/config.toml` as the base configuration and add three small,
personal files that contain only the differing reasoning setting:

| Operational name | Profile file | Contents |
| --- | --- | --- |
| FAST | `~/.codex/fast.config.toml` | `model_reasoning_effort = "low"` |
| STANDARD | `~/.codex/standard.config.toml` | `model_reasoning_effort = "medium"` |
| DEEP | `~/.codex/deep.config.toml` | `model_reasoning_effort = "high"` |

The base configuration already sets `model = "gpt-5.6-terra"`, so it should
remain defined once, in `~/.codex/config.toml`. The profiles should not repeat
the model, trust entries, sandbox settings, approval settings, plugin settings,
or MCP settings.

Use the following interactive invocations from WSL:

```bash
codex --profile fast
codex --profile standard
codex --profile deep
```

The same global option is accepted before `exec`, for example:

```bash
codex --profile fast exec "inspect repository status only"
```

Optional shell functions may make the choice even more visible, but are a
convenience layer only:

```bash
codex-fast() { codex --profile fast "$@"; }
codex-standard() { codex --profile standard "$@"; }
codex-deep() { codex --profile deep "$@"; }
```

These belong in a personal WSL shell startup file, not this repository.

## Current observed configuration

Read-only checks were performed in the WSL checkout on 2026-09-05.

| Item | Observation |
| --- | --- |
| CLI | `codex-cli 0.153.4`, standalone Linux install at `~/.local/bin/codex` |
| Codex home | `~/.codex` |
| Active user config | `~/.codex/config.toml`; `codex doctor` reports it loaded and parses successfully |
| Current model default | `gpt-5.6-terra` |
| Current reasoning default | `low` |
| Project trust | `[projects."/home/bal/projects/engineering-flow"] trust_level = "trusted"` exists in the base config |
| Plugins | Context7 marketplace and `context7@context7-marketplace` are enabled in the base config |
| Configured MCP servers | None reported by `codex doctor` |
| Effective sandbox / approval reported by doctor | Restricted filesystem and network; approval `OnRequest` |
| Checkout | `./scripts/env-preflight` passed; Git worktree was clean before this research artifact was created |

No `CODEX_*` or `OPENAI_*` environment variable that selects a model,
reasoning level, or profile was present. No existing Codex shell aliases or
functions were found in the inspected Bash startup files.

The configured base does not explicitly set sandbox or approval policy;
therefore the observed policies are Codex defaults/effective settings. Profile
files must omit those keys to preserve that behavior.

## Locally verified support and syntax

`codex --help` and `codex exec --help` for 0.153.4 expose:

```text
-p, --profile <CONFIG_PROFILE_V2>
    Layer $CODEX_HOME/<name>.config.toml on top of the base user config
```

This is direct evidence that named file-backed profiles are supported and that
selection syntax is `codex --profile <name>` (or `codex -p <name>`). For the
recommended names, Codex resolves the files as
`~/.codex/fast.config.toml`, `~/.codex/standard.config.toml`, and
`~/.codex/deep.config.toml`.

The local model catalog reports that `gpt-5.6-terra` supports `low`, `medium`,
and `high` reasoning efforts. The exact configuration key is locally observed
in the active config as `model_reasoning_effort`; it is also accepted in the
official Codex profile schema.

The CLI also locally documents one-off TOML overrides:

```bash
codex -c 'model_reasoning_effort="high"'
codex --model gpt-5.6-terra -c 'model_reasoning_effort="medium"'
```

`-c` values are parsed as TOML. `--model/-m` selects the model, while there is
no dedicated reasoning-effort command-line flag in this installed version.

The official Codex documentation/source metadata consulted through Context7
corroborates that a profile contains ordinary configuration fields and that
strict mode validates base, profile, and CLI-override layers. Local CLI help is
the authority for the installed 0.153.4 file naming and selection behavior.

## Inheritance and safety

The installed CLI explicitly describes a profile as a layer applied on top of
the base user configuration. Accordingly, an overlay containing only
`model_reasoning_effort` inherits the base model and all unrelated base values.
This preserves the existing trusted-project entry, enabled plugin configuration,
and any current or future base MCP configuration without duplication.

Codex command-line settings remain an upper layer for the invocation. For
example, `codex --profile deep -c 'model_reasoning_effort="low"'` should use
the CLI override for that launch. Avoid such conflicting combinations in normal
use because they obscure the operational profile selected.

Avoid placing `sandbox_mode`, `approval_policy`, trust-related settings,
plugins, or MCP configuration in these profiles. A profile that declares any
of them can intentionally change effective behavior for that profile. A
reasoning-only overlay does not.

Use `--strict-config` during initial validation to catch misspelled or removed
configuration fields. It validates all loaded layers but does not make a
profile safer by itself.

## Option evaluation

| Option | Assessment |
| --- | --- |
| A. Native Codex profiles | Recommended. It is supported locally, inherits the base configuration, needs three one-line files, is obvious at invocation, and is easy to remove. |
| B. Shell aliases/functions | Useful only as optional readable shortcuts over native profiles. Alone, aliases need repeated `-c` quoting and do not provide a profile artifact. |
| C. Separate complete config files | Do not use. The installed profile mechanism is already a separate overlay file; complete copies would duplicate trust/plugin settings and drift. `CODEX_HOME` swapping also risks separating auth/state. |
| D. Explicit `-c` / CLI overrides | Appropriate for a temporary exception or automation. It is more error-prone and less self-describing for routine use than `--profile`. |
| E. Manual selection | No configuration work and acceptable for occasional use, but it makes a reasoning mismatch easy and does not meet the requested easy operational selection. |

## Intended operational mapping

| Profile | Model | Reasoning | Intended work |
| --- | --- | --- | --- |
| FAST | inherited `gpt-5.6-terra` | `low` | Deterministic inspection, status, preflight, and simple commands. |
| STANDARD | inherited `gpt-5.6-terra` | `medium` | Bounded research, planning, routine implementation, and scoped fixes. |
| DEEP | inherited `gpt-5.6-terra` | `high` | Architecture, complex state/provider work, and independent task, Wave, or final reviews. |

Reasoning effort is a task-quality/latency control, not a claim of quota or
billing savings.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A profile unintentionally changes approvals, sandbox, trust, plugins, or MCPs. | Keep every profile reasoning-only; inspect its short content before use. |
| A future Codex update changes supported syntax or effort values. | Run `codex --version`, `codex --help`, `codex debug models`, and a strict-config smoke test after upgrades. |
| A profile name/file mismatch silently falls back or errors. | Use lowercase names and the exact `<name>.config.toml` convention; validate each invocation before adopting aliases. |
| A CLI `-c` override masks the selected profile. | Do not combine routine profiles with a conflicting reasoning override. |
| Profile selection is mistaken for an execution-permission change. | Continue to select sandbox/approval only through existing policy and explicit CLI controls when needed. |

## Validation plan before adoption

1. Back up or record the existing `~/.codex/config.toml`; do not edit it for
   this proposal.
2. Create the three personal one-line profile files shown above.
3. Run `codex --strict-config --profile fast --help`, then repeat for
   `standard` and `deep`, to validate profile parsing without starting an
   agent task.
4. Run a harmless interactive or `exec` prompt under each profile and verify
   the displayed/effective model settings, if exposed by that CLI session.
5. Run `codex doctor` from this checkout and verify the trust entry, enabled
   plugin, sandbox, and approval report remain unchanged from the observations
   above.
6. Test a normal non-mutating command under one profile in the trusted project
   and confirm existing approval/sandbox prompts behave as before.
7. Only then add optional shell functions and open a new shell to test their
   argument forwarding.

## Rollback

Remove `~/.codex/fast.config.toml`, `~/.codex/standard.config.toml`, and
`~/.codex/deep.config.toml`; remove the optional shell functions from the
personal startup file if added. The original `~/.codex/config.toml`, project
trust, authentication, plugin state, and repository remain untouched. Launch
plain `codex` to return to the current base default of Terra with low
reasoning.

## Repository impact

This research artifact is the only repository change. Implementing the
recommended profiles requires no Engineering Flow, source-code, Skill,
`AGENTS.md`, workflow-contract, or repository configuration change. It would
modify only personal files under `~/.codex/` and, optionally, a personal WSL
shell startup file.
