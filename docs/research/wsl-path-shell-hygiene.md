# WSL PATH and Shell Hygiene Audit

Audit date: 2026-09-05. Scope: current running WSL Bash environment only; no configuration was changed.

## Recommendation

MINIMAL_CHANGE. The canonical development tools currently resolve to Linux-native binaries, so no corrective change is required for Engineering Flow. Retain Windows interoperability because it is available for intentional cross-platform commands. Make the optional PATH cleanup below only if a shorter, more deterministic interactive PATH is desired.

## Effective PATH

- Entries: 69 total; 54 unique; 15 redundant occurrences.
- Linux entries precede every inherited Windows entry. `/home/bal/.local/bin` is present early and contains the Linux-native `codex` and `fd` shims.
- The repository Python is intentionally invoked explicitly as `.venv/bin/python3` and is Linux-native Python 3.13.15.

### Duplicate entries

| Entry | Occurrences |
| --- | ---: |
| `/home/bal/.codex/packages/standalone/releases/0.153.4-x86_64-unknown-linux-musl/codex-path` | 2 |
| `/home/bal/.local/bin` | 4 |
| `/mnt/c/Users/BAL/bin` | 2 |
| `/mnt/c/Program Files/Git/mingw64/bin` | 2 |
| `/mnt/c/Program Files/Git/usr/bin` | 3 |
| `/mnt/c/Users/BAL/.local/bin` | 2 |
| `/mnt/c/Users/BAL/AppData/Local/Microsoft/WindowsApps` | 2 |
| `/mnt/c/Users/BAL/AppData/Local/GitHubDesktop/bin` | 2 |
| `/mnt/c/Users/BAL/AppData/Local/Programs/Microsoft VS Code/bin` | 2 |
| `/mnt/c/Users/BAL/go/bin` | 2 |
| `/mnt/c/Users/BAL/.dotnet/tools` | 2 |
| `/mnt/c/Users/BAL/AppData/Local/Python/bin` | 2 |

## Windows inherited paths

- 49 of 69 PATH occurrences are `/mnt/c/...` inherited Windows paths (34 unique Windows directories).
- These include Git, Docker Desktop, Windows system directories, Windows Python 3.11 and 3.13, Windows Codex, VS Code, Node.js, Go, .NET, and user-level application paths.
- `/etc/wsl.conf` has no `[interop]` configuration, so the Windows PATH is inherited under the current WSL defaults.

## Resolution results

| Command | Effective resolution | Assessment |
| --- | --- | --- |
| `codex` | `/home/bal/.local/bin/codex` -> `/home/bal/.codex/packages/standalone/current/bin/codex` (ELF; `codex-cli 0.153.4`) | Linux-native; safe |
| `python` | not found | Safe from accidental Windows `python`; use the repository's explicit `.venv/bin/python3` |
| `python3` | `/usr/bin/python3` (Linux Python 3.12.3) | Linux-native; distinct from required repository Python 3.13.15 |
| `pip`, `pip3` | `/usr/bin/pip`, `/usr/bin/pip3` (Linux Python 3.12) | Linux-native; do not use for this repository—use `.venv/bin/pip` |
| `git` | `/usr/bin/git` (`git version 2.43.0`) | Linux-native; safe |
| `gh` | `/usr/bin/gh` (`gh version 2.100.0`) | Linux-native; safe |
| `fd` | `/home/bal/.local/bin/fd` -> `/usr/bin/fdfind` (`fdfind 9.0.0`) | Linux-native; safe |
| `jq` | `/usr/bin/jq` (`jq-1.7`) | Linux-native; safe |
| `docker` | `/mnt/c/Program Files/Docker/Docker/resources/bin/docker` | Windows Docker Desktop WSL shim; conditional/ambiguous |

## Ambiguous or unsafe resolutions

- Explicit `python.exe`, `python3.exe`, and `pip.exe` resolve to Windows App Execution Aliases/Python paths; `git.exe` resolves to Windows Git; `codex.exe` resolves to Windows Codex. Their unqualified Linux command names do not currently select these binaries.
- `docker` has no Linux-native alternative ahead of the inherited Docker Desktop shim. The shim itself reports that it needs Docker Desktop WSL integration enabled; when integration is disabled, `docker` is an unreliable development dependency.
- `python3` and global `pip` are Linux-native but are Python 3.12, not this project's Python 3.13 virtual environment. This is deterministic but can be unsafe if used instead of the repository-local commands.

## Shell startup files affecting PATH

- `~/.profile` sources `~/.bashrc` for Bash and prepends `~/.local/bin` when it exists.
- `~/.bashrc` also prepends `/home/bal/.local/bin` in the Codex installer block. A login Bash therefore prepends it twice; inherited process setup accounts for the remaining occurrences.
- `/etc/environment` supplies the standard Linux baseline PATH. `/etc/wsl.conf` enables systemd and sets the default user only.

## Recommended changes

1. NO_CHANGE for canonical Engineering Flow use: continue with `.venv/bin/python3`, `.venv/bin/engineering-flow`, and `.venv/bin/pip`.
2. Optional hygiene only: remove one of the two `~/.local/bin` prepend operations (`~/.profile` or the Codex installer block in `~/.bashrc`) to reduce duplicate entries. This is not required for correct resolution.
3. Optional policy guard: if Docker is needed in WSL, enable Docker Desktop WSL integration or install/select a Linux-native Docker client deliberately. If Docker is not needed, leave interoperability intact and avoid relying on unqualified `docker`.
4. Do not disable Windows interoperability solely for PATH cleanliness. Current ordering preserves Linux-native canonical tools; disabling it would remove intentional access to Windows commands without resolving a present canonical-tool collision.

## Blockers

None. Optional changes require an owner decision because they affect personal shell behavior and the desired availability of Windows tools.
