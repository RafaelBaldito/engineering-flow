# Bootstrap Controller Technical Spike

## Purpose

Execute a bounded, disposable-fixture validation of the three deterministic
primitives proposed for a thin Python bootstrap Wave Controller: checkout
identity/stale detection, atomic control-state replacement/recovery, and its
single-writer logical lease. This is not a Controller implementation.

## Scope and non-goals

The spike exercised only small Python experiment code and a newly initialized
temporary Git repository. It did not use, start, or change any existing Wave
(including Wave 3), Skills, production source, workflow artifacts, or Codex
configuration. Reviewer behavioral isolation is explicitly out of scope.

## Environment and disposable fixture

- Repository environment: Linux/WSL; `.venv/bin/python3` reported Python
  3.13.15 by `./scripts/env-preflight`.
- Fixture: `/tmp/bootstrap-controller-spike/fixture-repo`, initialized with
  one committed `tracked.txt`; state was `/tmp/bootstrap-controller-spike/state.json`.
- Execution: `.venv/bin/python3 /tmp/bootstrap-controller-spike/spike.py`.
- Result: all 16 asserted scenarios printed `PASS`; final line was
  `ALL_EXPERIMENTS_PASS`.

## Experiment 1 — checkout fingerprint

### Chosen exact algorithm

For the disposable Git checkout, the experiment collected these components:

1. `git rev-parse HEAD` (trimmed SHA) as `head`.
2. Raw bytes from `git status --porcelain=v2 -z --untracked-files=all`, hashed
   with SHA-256 as `status_hash`.
3. Raw bytes from `git diff --binary HEAD`, hashed with SHA-256 as `diff_hash`.
4. Paths from `git ls-files --others --exclude-standard -z`; for each
   byte-sorted path, append `path + NUL + SHA-256(file bytes) + NUL`, then hash
   that manifest as `untracked_hash`.
5. Union of `git diff --name-only -z HEAD` paths and those untracked paths,
   byte-sorted and serialized as `path + NUL`; SHA-256 is `changed_paths_hash`.
6. Serialize the five named values as canonical compact JSON (sorted keys,
   UTF-8) and SHA-256 it as the overall fingerprint.

The status and diff inputs remain binary-safe; untracked identity includes file
content, while the changed-path manifest captures the affected-path set.

| Scenario | Expected | Actual | Result |
| --- | --- | --- | --- |
| Capture same clean checkout twice | Equal | Equal | PASS |
| Change tracked content | Different | Different | PASS |
| Add untracked file | Different | Different | PASS |
| Change untracked content | Different | Different | PASS |
| Restore tracked bytes and remove untracked file | Original identity | Original identity | PASS |
| Result captured at A, checkout changed to B | `STALE`, not accepted | `STALE` | PASS |

The clean baseline fingerprint was
`708a4e09290d9fbd38ffd8a4f5230bf41f0a6f7f433023b1a2c1ef1ee69a134b` in this
fixture. The stale test compared A with the tracked-content-mutated B and
classified it `STALE`; no acceptance path was taken.

**Classification: PASS.**

## Experiment 2 — atomic state replacement and recovery

### Chosen mechanism

The experiment wrote a compact JSON representative control record with
`lifecycle_state`, `current_task_id`, `active_operation`, and `updated_at` to a
same-directory temporary file created by `tempfile.mkstemp`. It serialized the
complete JSON, flushed and `fsync`ed the file, then used `os.replace(temp,
state_path)`, followed by `fsync` of the containing directory. The temporary
file was removed on simulated interruption.

| Scenario | Expected | Actual | Result |
| --- | --- | --- | --- |
| Normal transition `TASK_IMPLEMENTATION` → `TASK_REVIEW_REQUIRED` | New state | New parseable JSON state | PASS |
| Read canonical state after replacement | Complete/parseable | Complete dict | PASS |
| Raise simulated interruption after temp fsync, before `os.replace` | Previous state readable | `TASK_IMPLEMENTATION` readable | PASS |
| Retry normal replacement | New state readable | `TASK_REVIEW_REQUIRED` readable | PASS |
| Observe canonical file during these checks | No partial record | Only complete JSON records | PASS |

This establishes the required same-filesystem atomic-replace behavior for the
tested Linux environment. It is not a database or general persistence layer.

**Atomic state replacement: PASS. Interruption recovery: PASS.**

## Experiment 3 — single-writer lease

The minimal logical lease stored `active_operation` as either null or a
`{role, status: ACTIVE}` record. Acquisition permits a role only when null;
an active known writer (`Developer` or `Fixer`) returns `REJECT`, and an active
unknown/unresolved record returns `BLOCK`. Clearing a completed Developer lease
allows the next writer.

| Scenario | Expected | Actual | Result |
| --- | --- | --- | --- |
| No active writer; Developer acquires | `ACQUIRED` | `ACQUIRED` | PASS |
| Active Developer; second Developer | `REJECT` | `REJECT` | PASS |
| Active Developer; Fixer | `REJECT` | `REJECT` | PASS |
| Release Developer; Fixer acquires | `ACQUIRED` | `ACQUIRED` | PASS |
| Unknown active writer; Developer attempts acquisition | `BLOCK` | `BLOCK` | PASS |

**Classification: PASS.**

## Findings and remaining risks

All three isolated deterministic primitives behaved deterministically in the
disposable Linux fixture. The test did not validate reviewer artifact-only
allowances, symlink/submodule/unusual filename policy, crashes during or after
the OS-level replace itself, concurrent processes, or reviewer write restraint.
Those remain integration/design-boundary risks, not failures of the tested
primitives. Future Controller reconciliation must retain the design's rule that
an unknown/interrupted writer blocks human attention rather than being retried.

## Recommendation

**PROCEED_TO_CONTROLLER_IMPLEMENTATION.** All required primitives independently
passed this bounded experiment. The next step is to implement the minimal
Controller only under its approved scope, preserving the selected identity,
atomic-replace, and block-on-unknown-lease semantics; validate reviewer
artifact allowance and behavioral isolation later in the integrated dry-run.

## Proposed deterministic primitives for the future Controller

1. Capture and persist the five checkout identity components and their
   canonical aggregate fingerprint before/after relevant operations; reject
   identity mismatch as `STALE`.
2. Replace the sole control record through same-directory temp write, file
   `fsync`, atomic `os.replace`, and directory `fsync`; reconcile only complete
   canonical records.
3. Permit exactly one active writer lease in that record; reject known active
   writers and block on unknown/unresolved ownership.
