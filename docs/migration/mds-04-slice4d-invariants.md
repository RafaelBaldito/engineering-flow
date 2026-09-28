# MDS #4 Slice 4D — Legacy Evidence & Recovery Projection Invariants

**Scope:** Slice 4D only. This checkpoint assumes 4A's lease and generic
mutation guards and 4B's fail-closed persisted command-prefix classification.
It does not add production resume/coordinator routing (Slice 4C).

## Implementation invariants

1. **First post-fix handling freezes legacy UNKNOWN evidence.** For every
   UNKNOWN attempt without `original_unknown_evidence`, the store must persist
   an immutable, exact copy of the pre-merge evidence before recording any
   recovery result. Absent legacy fields remain absent. Invalid JSON, scalars,
   lists, and other non-object values are retained verbatim in a dedicated
   original envelope; they are never repaired, discarded, or normalized
   destructively.

2. **Recovery evidence is append-only.** Original repository, control-state,
   process-ownership, authority, classification, and detail evidence can never
   be replaced by a later observation. Each later classification is a
   self-contained canonical recovery observation. Suppress only an exact
   duplicate; retain every materially distinct observation, including unknown
   future fields and conflicting values.

3. **Every non-terminal recovery projection is atomic and fails closed.**
   Legacy-evidence, ambiguous-context, inconsistent-linkage, identity-unknown,
   repository-changed, and inspection-failure handling must write their
   evidence, event, and workflow projection in one store transaction. A failed
   write leaves all prior evidence, attempt/command state, and lease ownership
   unchanged. Slice 4D consumes 4B's single command-state classification; an
   invalid or insufficient prefix is an unsafe recovery input, never a reason
   to invent a terminal outcome or release a lease.

4. **An exactly-owned live verifier projects to `HUMAN_ATTENTION`.** When the
   recovery service establishes `ALIVE_OWNED`, it must use a dedicated,
   exact-context store projection to durably set the workflow to
   `HUMAN_ATTENTION` and append bounded ownership evidence/event. That
   projection must not alter the verification attempt, command results,
   operation, execution, task state, lease owner, lease child identity, or
   lease retention; it neither signals, adopts, reruns, nor terminates the
   process.

5. **Unresolved verification ownership remains the controlling boundary.**
   All 4D UNKNOWN and live-owned projections preserve 4A's retained-lease and
   exact-ownership guarantees. Generic workflow/task mutation surfaces cannot
   cancel, advance, dispatch, overwrite `HUMAN_ATTENTION`, or otherwise evade
   that projection while ownership is unresolved. Only 4A's authorized normal
   or recovery terminal paths may release verification ownership.

6. **Recovery projection is idempotent, auditable, and safe to present.**
   Repeating the same recovery observation produces no duplicate event or
   observation and no ownership change; a distinct observation remains
   auditable. Status/log read models expose the classification and retained
   lease state sufficiently to distinguish live-owned, UNKNOWN, ambiguous, and
   interrupted outcomes, but never expose PIDs, process-start data, raw
   environment, secrets, or raw command output.

## Boundaries

- 4D does not decide command-prefix legality or terminal-success completeness;
  those remain store-owned 4B rules.
- 4D does not make recovery reachable from CLI/coordinator paths, start a new
  attempt, dispatch work, or continue to any successor phase; those concerns
  remain outside this slice, including Slice 4C.
