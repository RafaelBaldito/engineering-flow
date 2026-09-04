# Wave 2 Manual Acceptance

Run this future operator check only in a disposable authenticated Git
worktree. It is deliberately separate from the offline automated suite.

1. Initialize Engineering Flow in the disposable repository and complete the
   Wave 1 planning approvals with an approved task-plan manifest containing
   two ordered tasks and exact required test commands.
2. Resume Wave 2. Confirm that only the first task is dispatched, its required
   tests pass, and a fresh read-only Reviewer returns `PASS` before the second
   task begins. Confirm the same ordering for the second task.
3. For one task, have the Reviewer return a blocking `FIX_REQUIRED` result.
   Confirm the Developer receives the persisted findings and task evidence,
   reruns the exact tests, and a distinct Reviewer session performs the
   re-review.
4. Repeat blocking review until the configured review-cycle limit pauses the
   task. Confirm `status` and `logs` identify the task/cycle and durable
   intervention boundary; use `intervene --task <id> --reason <reason>` and
   confirm that it opens a new review window without accepting or skipping the
   task.
5. Restart the process at a pending operation, after Developer evidence,
   after review evidence, and after acceptance. Confirm persisted outcomes are
   reconciled without another provider execution, duplicate evidence,
   duplicate acceptance, or an extra task launch.
6. Inspect Git state and the hosting service: this workflow must not create a
   commit, push, branch delivery, pull request, or any other Git/PR side
   effect. Retain the sanitized status/log output as operator evidence.
