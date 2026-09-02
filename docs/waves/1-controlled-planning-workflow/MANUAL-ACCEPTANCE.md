# Wave 1 Manual Acceptance

Use a disposable Git repository and an authenticated local Codex CLI. These
steps verify the provider-backed boundary without changing the repository's
branch, commits, remotes, or pull requests.

1. Create and enter an empty disposable repository, then run
   `engineering-flow init --repo PATH`. Confirm `.engineering-flow/config.toml`
   contains the normative read-only settings and that existing `.gitignore`
   lines remain intact.
2. Add a feature request outside `.engineering-flow` and run
   `engineering-flow run --repo PATH --feature-file FEATURE.md`. Confirm the
   command reports `prd`/`awaiting_approval` and that one immutable PRD is
   present under `.engineering-flow/workflows/<id>/artifacts/`.
3. Use `engineering-flow status --repo PATH --workflow ID` and
   `engineering-flow logs --repo PATH --workflow ID --json`. Record the exact
   artifact ID, approve it, and repeat for the techspec and task-plan stages.
   Each next stage must remain unavailable until the exact prior artifact is
   approved; the terminal state must be `ready_for_wave_2`/`completed`.
4. Interrupt a run between commands, reopen the terminal, and use
   `engineering-flow resume --repo PATH --workflow ID`. Confirm persisted
   events are monotonic, artifacts are preserved, and no duplicate completed
   artifact or approval is created.
5. Inspect the disposable repository after completion. Confirm no task,
   review, test, Git delivery, commit, push, or pull-request action occurred.

Do not use production repositories or credentials in captured logs. Automated
validation deliberately uses a fake runtime and does not perform this live
workflow.
