# MDS #2.2.1 — Workflow Lifecycle UX Closure

This small pre-MDS #3 correction closes two human lifecycle gaps found after
MDS #2.2. Repository-scoped human workflow commands now default `--repo` to
the current directory (`.`); an explicit `--repo PATH` still takes precedence.
`init` remains explicit because it creates a workspace at a target path.

`cancel` explicitly abandons the selected (or `--workflow`) V2 workflow. It
sets only lifecycle status to `CANCELLED`, preserves selection and every
artifact, record, operation, event, log, hash, and UUID, and is idempotent for
an already cancelled workflow. It is available only for active V2 workflows;
existing terminal workflows are not rewritten. A later `run` creates and
selects a new workflow normally.

Ctrl+C still means interruption only: persisted recovery evidence remains
resumable. `cancel` is distinct from Plan `reject`: it may happen before a
Plan exists and creates no approval decision. Cancelled workflows cannot be
resumed, answered, given Plan feedback, approved, or rejected. MDS #3 remains
the next delivery scope; this change adds no task execution.
