# Python → Codex Execution Bridge Spike

## Decision

**GO_WITH_LIMITS.** The installed Linux-native CLI has a supported, ordinary-process execution surface that is sufficient for the narrow post-task-plan loop. The thin bridge can be a Python `subprocess` runner around `codex exec`, with no TTY, terminal emulation, UI automation, custom MCP/RPC host, API-key replacement, provider layer, or Controller redesign.

The limits are deliberate: use fresh executions for every role, collect the final result plus JSONL events, and omit session continuity, streaming presentation, rich telemetry, and automatic Wave Review. Authoritative task/review artifacts and Controller validation remain the source of lifecycle facts.

## Environment and command surface

- Installed CLI: `codex-cli 0.153.4` (`/home/bal/.local/bin/codex`).
- Supported non-interactive command: `codex exec [OPTIONS] [PROMPT]` (alias `codex e`). A prompt can also be supplied on stdin.
- Relevant per-invocation options confirmed by local `--help`: `--model`, `--config key=value`, `--profile`, `--cd`, `--sandbox`, `--json`, `--output-last-message`, `--output-schema`, and `--ephemeral`.
- Resume command: `codex exec resume <SESSION_ID> [PROMPT]`, with `--json`, `--model`, config overrides, `--output-schema`, and `--output-last-message`.
- The installed local model catalog lists `gpt-5.6-terra` / `GPT-5.6-Terra` and its supported reasoning levels include `low` and `medium` (also high, xhigh, max, ultra).

The applicable official OpenAI CLI surface is the installed CLI help. Model reasoning tiers are also consistent with the official [GPT-5.6 Terra model documentation](https://developers.openai.com/api/docs/models) and [model comparison](https://developers.openai.com/api/docs/models/compare).

## Answers to the spike questions

### 1. Non-interactive Python launch

**YES.** Python can use `subprocess.run` (or `Popen` when cancellation is needed) to launch `codex exec`. It succeeds with pipe-based stdout/stderr and no interactive terminal. The live Experiment A was launched by `.venv/bin/python3` with `subprocess.run(..., capture_output=True, text=True, timeout=120)` and exited zero.

No PTY, terminal emulation, UI automation, undocumented protocol parsing, MCP/RPC infrastructure, or separate host layer is required.

### 2. Per-role model and reasoning policy

**YES.** Both are invocation-scoped. Use `-m gpt-5.6-terra` and `-c 'model_reasoning_effort="<tier>"'`; `--strict-config` accepted the configuration key. This does not require a user to change global settings between roles. A profile is available as an optional alternative (`-p`), but is unnecessary for this small loop.

Example developer command shape:

```text
codex exec --json --strict-config -m gpt-5.6-terra \
  -c 'model_reasoning_effort="low"' -C <repo> -s workspace-write \
  --output-last-message <run-dir>/final.txt <developer-prompt>
```

Example fresh reviewer command shape:

```text
codex exec --json --strict-config -m gpt-5.6-terra \
  -c 'model_reasoning_effort="medium"' -C <repo> -s workspace-write \
  --output-last-message <run-dir>/final.txt <reviewer-prompt>
```

Experiment B printed `model: gpt-5.6-terra` and `reasoning effort: medium` in the CLI execution header. Experiment A accepted the corresponding `low` override and completed successfully. The runner should keep an explicit role map, e.g. Developer/Terra/low, Reviewer/Terra/medium, Fixer/Terra/low-or-medium, rather than rely on the user config's default.

### 3. Independent Reviewer

**YES.** Invoke a new `codex exec` process for each review and pass only Controller handoff facts: role, capability/Skill, task ID, exact authoritative paths, expected review path, checkout identity, and bounded validation requirements. Do not pass prior output or a developer session ID. This supplies fresh thread/context behavior cheaply; it matches the Controller handoff's existing `fork_turns: "none"` intent without needing subagent plumbing.

### 4. Structured caller output

**Good enough for the bootstrap.** `--json` emits JSONL, observed as:

- `thread.started` with `thread_id`;
- `turn.started`;
- `item.completed` with a typed `agent_message` and text;
- `turn.completed` with input, cached-input, cache-write-input, output, and reasoning-output token counts.

`--output-last-message <path>` supplies the final agent text separately. `--output-schema <schema>` constrains that final message to JSON; Experiment D observed the valid final object `{"result":"SKILL_SEEN"}`. The runner can parse JSONL records and the schema-constrained final file as machine data; it must not parse the normal human transcript. Tool/activity events are event records when emitted, but rich activity telemetry is not required for this loop.

### 5. Completion and failure detection

**YES.** Treat a zero process exit plus a parsed terminal `turn.completed` JSONL event and a valid final artifact/schema result as success. Treat nonzero exit, `subprocess.TimeoutExpired`, signal termination/cancellation, absent terminal event, invalid JSONL/schema, missing expected artifact, or Controller envelope rejection as distinct failure statuses. No prose heuristic is necessary.

### 6. Sessions and resume

- Session/thread ID available: **YES**, as `thread.started.thread_id`.
- Programmatic resume: **YES**, via `codex exec resume <thread-id> <prompt>`.
- Live proof: a persistent `codex exec` returned `01a08403-44aa-74d2-86a9-a2f7646b3270`; a later `codex exec resume` using that ID returned zero and `RESUME_OK` with the same ID.
- Bootstrap classification: **OPTIONAL, not required.** Fresh Developer/Fixer runs with factual task/review paths are simpler and avoid carrying stale context. Fresh Reviewers remain trivial. Do not use `--ephemeral` for a run intended to resume.

### 7. Repository instructions and Skills

**YES.** `-C <repo>` establishes the repository cwd. In the disposable fixture, an `AGENTS.md` instruction was honored (`AGENTS_SEEN`). A valid `.codex/skills/tiny-skill/SKILL.md` was honored by a fresh non-interactive run (`SKILL_SEEN`). Therefore the ordinary repository instruction/Skill discovery path remains usable. Skills must retain their normal valid YAML frontmatter; a deliberately invalid first fixture skill correctly reported a load error, which was fixed before the positive experiment.

### 8. Smallest role dispatch

The viable boundary is:

```text
Controller.next / begin_operation
  → role policy + factual prompt builder
  → Python subprocess: codex exec
  → JSONL/final-result/artifact collection
  → factual envelope builder
  → Controller.complete_operation
```

The dispatcher only maps Controller roles to model/reasoning/prompt templates. It does not choose lifecycle transitions, interpret code quality, or implement a provider abstraction.

### 9. Minimal result envelope

Use a combination of durable artifacts and Python facts:

1. The role follows its existing Skill and persists its known authoritative Markdown/code artifact(s), especially the exact task-review path for Reviewer.
2. Python records process facts (exit/timeout/cancellation), the parsed terminal JSONL event/thread ID/usage, validates expected paths and hashes, captures the Controller checkout identity after the run, and writes the schema-v1 envelope.
3. `complete_operation` remains the final validator of operation ID, scope, role, input/output checkout identities, artifact hashes, allowed reviewer path, and review decision.

The model may be asked for a tiny schema-constrained declaration such as `{"terminal_status":"COMPLETED"}` or `{"review_decision":"PASS"}`, but the runner should derive all other envelope facts itself and never depend on long prose to be a perfect protocol.

### 10. Token/context efficiency

Automation does not remove model tokens. Fresh scoped runs prevent developer rationale and prior conversational content from being sent to reviewers and permit lower reasoning for writers. Prompts should name exact task, review, TECHSPEC, and Skill paths and tell the role to read only its bounded contract. Do not serialize the repository, Controller state dump, previous transcript, or every research document into each prompt. The tiny fixture still showed roughly 14k input tokens because normal Codex/project instructions are loaded; the bridge should add only small factual handoff text.

### 11. Timeout and cancellation

Use `Popen(..., start_new_session=True)` and `communicate(timeout=...)`. On timeout, send `SIGTERM` to the child process group, wait briefly, then `SIGKILL` only if still alive; record `INTERRUPTED`/timeout facts and leave the Controller lease for its existing reconciliation/human-attention rules. This is standard Python process control, not a supervisor.

### 12. Authentication

- Existing ChatGPT Codex authentication reusable: **YES.** All live `codex exec` invocations succeeded using the existing local login; no credential was supplied to Python or the command.
- OpenAI API key required: **NO.** This bridge uses the Codex CLI account authentication, not the API/Responses CLI.

## Live experiments

Disposable repository: `/tmp/codex-bridge-spike.QhQRWV` (tiny committed marker, fixture `AGENTS.md`, and fixture Skill). It is outside Wave 3 and the project checkout.

| Experiment | Command/property | Result |
| --- | --- | --- |
| A | Python `subprocess.run` → `codex exec --json --ephemeral -m gpt-5.6-terra -c model_reasoning_effort=low` | Exit 0; final `PING_LOW`; JSONL `thread.started`, `turn.completed`, and usage. |
| B | Separate fresh `codex exec --strict-config -m gpt-5.6-terra -c model_reasoning_effort=medium` | Exit 0; header explicitly reported Terra + medium; `AGENTS_SEEN`. |
| C | `--json` and `--output-last-message` | Thread ID, typed final item, terminal completion, and token usage observed. |
| D | Fresh JSON/schema run in fixture cwd with valid `$tiny-skill` | Exit 0; schema-valid `{"result":"SKILL_SEEN"}`; confirms AGENTS/Skill behavior. |
| E (optional) | Persistent execution followed by `codex exec resume <thread-id>` | Both exit 0; same session ID returned `RESUME_OK`. |

## Estimated bootstrap implementation and validation

Implementation is plausibly one session:

- Add one small bootstrap host/runner module under `tools/wave_controller/` (for example `host.py`) containing subprocess launch, JSONL collection, role policy/prompt construction, timeout handling, artifact/hash facts, and `complete_operation` calls.
- Optionally add one CLI command or thin module entry point to start the bounded post-task-plan loop.
- Make one small `core.py` adjustment: currently `next()` immediately converts `TASKS_READY_FOR_WAVE_REVIEW` into `WAVE_REVIEW_REQUIRED` and dispatches Wave Reviewer. To meet the requested stop boundary, return a terminal `TASKS_READY_FOR_WAVE_REVIEW` result without making that conversion.
- Keep role reasoning policy in the dispatcher; no Controller redesign or production-runtime change is needed.

Estimated tests are one small end-to-end disposable-fixture suite plus focused unit tests for command construction, JSONL terminal parsing, nonzero/timeout/malformed-result handling, envelope construction, fresh review invocation, `FIX_REQUIRED → Fixer → fresh Reviewer`, next task selection, and terminal stop. The existing Controller tests should be adjusted only for the one stop-boundary assertion and then full repository validation run.

## Risks and omitted capabilities

- Codex CLI version/config semantics can change, so use `--strict-config`, preserve the actual command construction in tests, and fail closed on unexpected JSONL.
- Repository instructions add a baseline context cost; keep bridge prompts factual and bounded.
- A role can still make unintended writes within its allowed sandbox. Existing Controller checkout/artifact validation is the guard; Reviewer remains constrained to its exact review artifact by Controller validation.
- Do not add streaming UI, event dashboards, long-lived session orchestration, a generic provider interface, retry policy beyond Controller recovery, automatic Wave Review, or API/MCP integration.
- Run with an explicit sandbox appropriate to each role. The live proof used `read-only`; actual Developer/Fixer runs require the existing externally authorized workspace-write policy, while reviewers must respect their artifact-only contract.

## Strict-budget justification and recommended next step

The central bridge is proven as one ordinary process invocation with two invocation-scoped options and a supported JSONL/final-file contract. The Controller already owns selection, lease, transitions, stale protection, result-envelope validation, and the review/fix loop. Only a compact runner plus the terminal-stop correction remains, which fits one implementation session and one small end-to-end validation session.

**Recommended next step:** authorize a single bootstrap implementation task to add the bounded host/runner and terminal stop behavior, then validate one disposable two-task run that includes a `FIX_REQUIRED` cycle and ends at `TASKS_READY_FOR_WAVE_REVIEW`; keep Wave Review manual.
