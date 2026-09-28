import json
import hashlib
import inspect
import unittest
from unittest import mock

from engineering_flow.domain import (ConflictFailure, DomainFailure, ValidationFailure,
    WorkflowStatus)
from engineering_flow.cli import _event_payload
from engineering_flow.process_identity import (HostBootIdentity, ProcessGroupObservation,
    observe_exact_process_group)
from engineering_flow.repository import RepositoryInspector, control_state_fingerprint
from engineering_flow.verification import (VerificationRecoveryOutcome,
    VerificationRecoveryService)
from engineering_flow.store import VerificationRecoveryDecision, WorkflowStore
from tests import test_mds4_slice3 as slice3_tests


class Mds4Slice4RecoveryTests(unittest.TestCase):
    setUp = slice3_tests.Mds4Slice3RunnerTests.setUp
    tearDown = slice3_tests.Mds4Slice3RunnerTests.tearDown
    prepare = slice3_tests.Mds4Slice3RunnerTests.prepare

    def pending_attempt(self, commands=None, *, start=True):
        workflow, preflight, orchestrator = self.prepare(commands or [["/bin/true"]])
        inspector = RepositoryInspector(self.root)
        baseline = inspector.capture().as_payload()
        baseline["control_state_fingerprint"] = control_state_fingerprint(self.root)
        binding = preflight.manifest_binding
        intent = self.store.create_verification_intent(workflow.id,
            repository_key=inspector.repository_key(), canonical_root=str(self.root),
            producer_operation_id=preflight.producer.operation_id,
            task_contract_id=preflight.producer.task_contract_id,
            task_contract_sha256=preflight.producer.task_contract_sha256,
            authority_sha256=preflight.authority_sha256, request_hash=preflight.request_hash,
            manifest_binding={"path": binding.path, "head_sha": binding.head_sha,
                "head_blob_sha256": binding.head_blob_sha256,
                "worktree_sha256": binding.worktree_sha256,
                "canonical_commands_sha256": binding.canonical_commands_sha256,
                "commands": [command.as_payload() for command in binding.manifest.commands]},
            baseline=baseline, owner_instance_id="recover-owner",
            owner_pid=111, owner_host_id="host", owner_boot_id="boot")
        command = preflight.manifest_binding.manifest.commands[0]
        command_result_id = self.store.record_verification_command_intent(
            intent["attempt_id"], intent["lease_id"], owner_instance_id="recover-owner",
            ordinal=1, command_id=command.id,
            canonical_command_sha256=orchestrator._command_hash(command), argv=command.argv,
            timeout_seconds=command.timeout_seconds)
        if start:
            self.store.record_verification_command_started(intent["attempt_id"], intent["lease_id"],
                command_result_id, owner_instance_id="recover-owner", child_pid=4242,
                child_process_start="start-1", child_process_group=4242,
                child_process_session=4242, child_host_id="host", child_boot_id="boot")
        return workflow, intent

    def complete_current_command(self, intent):
        command_result_id = self.store._connection.execute(
            "SELECT id FROM verification_command_results WHERE result_at IS NULL").fetchone()[0]
        snapshot = RepositoryInspector(self.root).capture().as_payload()
        self.store.record_verification_command_result(intent["attempt_id"], intent["lease_id"],
            command_result_id, owner_instance_id="recover-owner", exit_code=0, timed_out=False,
            output_sha256="0" * 64, output_bytes=0, output_truncated=False,
            post_command_inspection={"repository": snapshot,
                "control_state_fingerprint": control_state_fingerprint(self.root), "safe": True},
            classification="passed")

    def recovery_rows(self, intent):
        attempt = tuple(self.store._connection.execute(
            "SELECT status,classification,final_inspection_json,finished_at FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone())
        workflow_id = self.store._connection.execute(
            "SELECT workflow_id FROM verification_attempts WHERE id=?", (intent["attempt_id"],)).fetchone()[0]
        workflow = tuple(self.store._connection.execute(
            "SELECT stage,status FROM workflows WHERE id=?", (workflow_id,)).fetchone())
        operation = tuple(self.store._connection.execute(
            "SELECT status FROM operations WHERE id=?", (intent["operation_id"],)).fetchone())
        execution = tuple(self.store._connection.execute(
            "SELECT lifecycle,terminal_result,failure_detail FROM executions WHERE id=?",
            (intent["execution_id"],)).fetchone())
        task = tuple(self.store._connection.execute("""SELECT status FROM task_implementation_states
            WHERE workflow_id=?""", (workflow_id,)).fetchone())
        events = [tuple(row) for row in self.store._connection.execute(
            "SELECT type,payload FROM events WHERE workflow_id=? ORDER BY id", (workflow_id,)).fetchall()]
        commands = [tuple(row) for row in self.store._connection.execute(
            "SELECT * FROM verification_command_results WHERE verification_attempt_id=? ORDER BY ordinal",
            (intent["attempt_id"],)).fetchall()]
        leases = [tuple(row) for row in self.store._connection.execute(
            "SELECT * FROM workspace_operation_leases WHERE lease_id=?", (intent["lease_id"],)).fetchall()]
        return attempt, workflow, task, operation, execution, events, commands, leases

    def service(self, observation):
        return VerificationRecoveryService(self.store, identity=HostBootIdentity("host", "boot"),
            observer=lambda **kwargs: observation)

    def recovery_decision(self, workflow):
        context = self.store.active_verification_recovery_context(workflow.id)
        lease, attempt = context["lease"], context["attempt"]
        command = next((row for row in context["commands"] if row["result_at"] is None),
            context["commands"][-1])
        return VerificationRecoveryDecision(workflow_id=workflow.id,
            process_observation="dead",
            observed_identity=VerificationRecoveryService._identity_evidence(lease, command),
            repository=RepositoryInspector(self.root).capture().as_payload(),
            control_state_fingerprint=control_state_fingerprint(self.root),
            authority=VerificationRecoveryService._authority_evidence(attempt),
            detail="verification process is dead and repository is unchanged")

    def assert_completed_evidence_fails_closed(self, workflow, intent):
        self.assertEqual(self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id),
            VerificationRecoveryOutcome.STATE_INCONSISTENT)
        self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))
        attempt = self.store._connection.execute(
            "SELECT status,classification FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()
        self.assertEqual(tuple(attempt), ("unknown", "verification_unknown"))
        self.assertEqual(self.store.get_workflow(workflow.id).status,
            WorkflowStatus.HUMAN_ATTENTION)

    def reset_fixture(self):
        if self.store is not None:
            self.store.close(); self.store = None
        self.temp.cleanup(); self.setUp()

    def test_exact_alive_process_retains_lease_and_does_not_dispatch(self):
        workflow, intent = self.pending_attempt()
        with mock.patch("engineering_flow.process_identity.os.killpg") as signal_group:
            result = self.service(ProcessGroupObservation.ALIVE_OWNED).reconcile(workflow.id)
        self.assertEqual(result, VerificationRecoveryOutcome.PROCESS_ALIVE_OWNED)
        self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))
        row = self.store._connection.execute(
            "SELECT status,classification FROM verification_attempts WHERE id=?", (intent["attempt_id"],)).fetchone()
        self.assertEqual(tuple(row), ("verifying", None))
        self.assertIsNone(self.store._connection.execute(
            "SELECT result_at FROM verification_command_results").fetchone()[0])
        signal_group.assert_not_called()

    def test_exact_alive_process_projects_human_attention_without_changing_ownership(self):
        workflow, intent = self.pending_attempt()
        before = self.recovery_rows(intent)
        self.assertEqual(self.service(ProcessGroupObservation.ALIVE_OWNED).reconcile(workflow.id),
            VerificationRecoveryOutcome.PROCESS_ALIVE_OWNED)
        after = self.recovery_rows(intent)
        # Only the workflow safety projection and its audit event may change.
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[2:5], before[2:5])
        self.assertEqual(after[6:], before[6:])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        self.assertEqual(sum(kind == "verification.recovery.live_owned" for kind, _ in after[5]), 1)
        self.assertEqual(self.service(ProcessGroupObservation.ALIVE_OWNED).reconcile(workflow.id),
            VerificationRecoveryOutcome.PROCESS_ALIVE_OWNED)
        self.assertEqual(sum(kind == "verification.recovery.live_owned" for kind, _ in
            self.recovery_rows(intent)[5]), 1)

    def test_human_attention_active_lifecycle_requires_live_owned_projection(self):
        workflow, intent = self.pending_attempt()
        self.store._connection.execute("UPDATE workflows SET status='human_attention' WHERE id=?",
            (workflow.id,))
        self.assertEqual(self.service(ProcessGroupObservation.ALIVE_OWNED).reconcile(workflow.id),
            VerificationRecoveryOutcome.STATE_INCONSISTENT)
        self.assertFalse(any(kind == "verification.recovery.live_owned" for kind, _ in
            self.recovery_rows(intent)[5]))

    def test_live_projection_event_failure_rolls_back_without_releasing_or_rewriting(self):
        workflow, intent = self.pending_attempt()
        before = self.recovery_rows(intent)
        self.store._connection.execute("""CREATE TRIGGER fail_live_projection BEFORE INSERT ON events
            WHEN NEW.type='verification.recovery.live_owned'
            BEGIN SELECT RAISE(ABORT, 'fault injected'); END""")
        with self.assertRaises(DomainFailure):
            self.service(ProcessGroupObservation.ALIVE_OWNED).reconcile(workflow.id)
        self.assertEqual(self.recovery_rows(intent), before)

    def test_legacy_unknown_raw_evidence_is_frozen_before_recovery_merge(self):
        workflow, intent = self.pending_attempt()
        self.store.retain_verification_unknown(intent["attempt_id"], intent["lease_id"],
            owner_instance_id="recover-owner", final_inspection={"temporary": "seed"}, detail="seed")
        legacy = '{"identity":{"legacy":true},"unknown_future":{"left":"absent elsewhere"}}'
        self.store._connection.execute("""UPDATE verification_attempts
            SET final_inspection_json=? WHERE id=?""", (legacy, intent["attempt_id"]))
        self.assertEqual(self.service(ProcessGroupObservation.ALIVE_OWNED).reconcile(workflow.id),
            VerificationRecoveryOutcome.PROCESS_ALIVE_OWNED)
        retained = json.loads(self.store._connection.execute(
            "SELECT final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0])
        self.assertEqual(retained["original_unknown_evidence"], {
            "format": "legacy-final-inspection-json-v1", "raw": legacy})
        self.assertEqual(retained["unknown_future"], {"left": "absent elsewhere"})
        self.assertEqual(retained["recovery_observations"][0]["classification"], "process_alive_owned")

    def test_legacy_unknown_nonobject_and_invalid_json_are_retained_verbatim(self):
        for legacy in ('["legacy",{"future":true}]', '"legacy scalar"', '{not json'):
            with self.subTest(legacy=legacy):
                self.reset_fixture()
                workflow, intent = self.pending_attempt()
                self.store.retain_verification_unknown(intent["attempt_id"], intent["lease_id"],
                    owner_instance_id="recover-owner", final_inspection={"temporary": "seed"}, detail="seed")
                self.store._connection.execute("UPDATE verification_attempts SET final_inspection_json=? WHERE id=?",
                    (legacy, intent["attempt_id"]))
                self.assertEqual(self.service(ProcessGroupObservation.ALIVE_OWNED).reconcile(workflow.id),
                    VerificationRecoveryOutcome.PROCESS_ALIVE_OWNED)
                retained = json.loads(self.store._connection.execute(
                    "SELECT final_inspection_json FROM verification_attempts WHERE id=?",
                    (intent["attempt_id"],)).fetchone()[0])
                self.assertEqual(retained["original_unknown_evidence"]["raw"], legacy)

    def test_recovery_observation_deduplication_is_global_and_distinct_values_append(self):
        workflow, intent = self.pending_attempt()
        self.store.retain_verification_unknown(intent["attempt_id"], intent["lease_id"],
            owner_instance_id="recover-owner", final_inspection={"temporary": "seed"}, detail="seed")
        self.assertEqual(self.service(ProcessGroupObservation.PID_REUSED).reconcile(workflow.id),
            VerificationRecoveryOutcome.PID_REUSED)
        self.assertEqual(self.service(ProcessGroupObservation.ALIVE_OWNED).reconcile(workflow.id),
            VerificationRecoveryOutcome.PROCESS_ALIVE_OWNED)
        self.assertEqual(self.service(ProcessGroupObservation.PID_REUSED).reconcile(workflow.id),
            VerificationRecoveryOutcome.PID_REUSED)
        retained = json.loads(self.store._connection.execute(
            "SELECT final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0])
        self.assertEqual([item["classification"] for item in retained["recovery_observations"]],
            ["pid_reused", "process_alive_owned"])

    def test_mixed_recovery_observations_deduplicate_a_valid_exact_replay(self):
        workflow, intent = self.pending_attempt()
        self.assertEqual(self.service(ProcessGroupObservation.PID_REUSED).reconcile(workflow.id),
            VerificationRecoveryOutcome.PID_REUSED)
        retained = json.loads(self.store._connection.execute(
            "SELECT final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0])
        valid_observation = retained["recovery_observations"][0]
        malformed_observation = ["malformed historical observation"]
        retained["recovery_observations"] = [valid_observation, malformed_observation]
        self.store._connection.execute("UPDATE verification_attempts SET final_inspection_json=? WHERE id=?",
            (json.dumps(retained), intent["attempt_id"]))
        events_before = self.store._connection.execute("""SELECT count(*) FROM events WHERE workflow_id=?
            AND type='verification.recovery.unknown_retained'""", (workflow.id,)).fetchone()[0]

        self.assertEqual(self.service(ProcessGroupObservation.PID_REUSED).reconcile(workflow.id),
            VerificationRecoveryOutcome.PID_REUSED)

        after = json.loads(self.store._connection.execute(
            "SELECT final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0])
        self.assertEqual(after["recovery_observations"],
            [valid_observation, malformed_observation])
        self.assertEqual(self.store._connection.execute("""SELECT count(*) FROM events WHERE workflow_id=?
            AND type='verification.recovery.unknown_retained'""", (workflow.id,)).fetchone()[0], events_before)

    def test_recovery_read_models_show_classification_and_lease_without_process_identity(self):
        workflow, intent = self.pending_attempt()
        self.service(ProcessGroupObservation.ALIVE_OWNED).reconcile(workflow.id)
        projection = self.store.list_verification_attempt_projections(workflow.id)[0]
        self.assertEqual(projection["recovery_classification"], "process_alive_owned")
        self.assertTrue(projection["lease_held"])
        self.assertFalse({"pid", "owner_pid", "process_start", "process_group", "process_session"}
            & set(projection))
        event = next(event for event in self.store.list_events(workflow.id)
            if event.type == "verification.recovery.live_owned")
        rendered = json.dumps(_event_payload(event), sort_keys=True)
        self.assertNotIn("4242", rendered)
        self.assertNotIn("start-1", rendered)

    def test_non_passing_command_never_authorizes_a_successor(self):
        cases = {
            "failed": dict(exit_code=1, timed_out=False, output_truncated=False, safe=True),
            "timed_out": dict(exit_code=None, timed_out=True, output_truncated=False, safe=True),
            "output_limited": dict(exit_code=0, timed_out=False, output_truncated=True, safe=True),
            "spawn_blocked": dict(exit_code=None, timed_out=False, output_truncated=False, safe=True),
            "repository_mutated": dict(exit_code=0, timed_out=False, output_truncated=False, safe=False),
        }
        for classification, facts in cases.items():
            with self.subTest(classification=classification):
                self.reset_fixture()
                workflow, intent = self.pending_attempt([["/bin/true"], ["/bin/true"]],
                    start=classification != "spawn_blocked")
                command_id = self.store._connection.execute(
                    "SELECT id FROM verification_command_results WHERE verification_attempt_id=?",
                    (intent["attempt_id"],)).fetchone()[0]
                snapshot = RepositoryInspector(self.root).capture().as_payload()
                inspection = {"repository": snapshot,
                    "control_state_fingerprint": control_state_fingerprint(self.root),
                    "safe": facts["safe"]}
                self.store.record_verification_command_result(intent["attempt_id"], intent["lease_id"], command_id,
                    owner_instance_id="recover-owner", output_sha256="0" * 64, output_bytes=0,
                    post_command_inspection=inspection, classification=classification,
                    **{key: value for key, value in facts.items() if key != "safe"})
                bound = json.loads(self.store._connection.execute(
                    "SELECT manifest_binding_json FROM verification_attempts WHERE id=?",
                    (intent["attempt_id"],)).fetchone()[0])["commands"][1]
                with self.assertRaises(ConflictFailure):
                    self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"],
                        owner_instance_id="recover-owner", ordinal=2, command_id=bound["id"],
                        canonical_command_sha256=self.store._command_hash(bound),
                        argv=bound["argv"], timeout_seconds=bound["timeout_seconds"])
                self.assertEqual(self.store._connection.execute(
                    "SELECT count(*) FROM verification_command_results WHERE verification_attempt_id=?",
                    (intent["attempt_id"],)).fetchone()[0], 1)

    def test_contradictory_passing_result_rolls_back_and_blocks_a_successor(self):
        workflow, intent = self.pending_attempt([["/bin/true"], ["/bin/true"]])
        command_id = self.store._connection.execute(
            "SELECT id FROM verification_command_results WHERE verification_attempt_id=?",
            (intent["attempt_id"],)).fetchone()[0]
        snapshot = RepositoryInspector(self.root).capture().as_payload()
        with self.assertRaises(ConflictFailure):
            self.store.record_verification_command_result(intent["attempt_id"], intent["lease_id"], command_id,
                owner_instance_id="recover-owner", exit_code=1, timed_out=False,
                output_sha256="0" * 64, output_bytes=0, output_truncated=False,
                post_command_inspection={"repository": snapshot,
                    "control_state_fingerprint": control_state_fingerprint(self.root), "safe": True},
                classification="passed")
        bound = json.loads(self.store._connection.execute(
            "SELECT manifest_binding_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0])["commands"][1]
        with self.assertRaises(ConflictFailure):
            self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"],
                owner_instance_id="recover-owner", ordinal=2, command_id=bound["id"],
                canonical_command_sha256=self.store._command_hash(bound), argv=bound["argv"],
                timeout_seconds=bound["timeout_seconds"])
        self.assertIsNotNone(self.store.active_workspace_operation_lease(
            RepositoryInspector(self.root).repository_key()))

    def test_early_verified_and_corrupt_recovery_prefix_fail_closed_before_observation(self):
        workflow, intent = self.pending_attempt([["/bin/true"], ["/bin/true"]])
        with self.assertRaises(ConflictFailure):
            self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"],
                owner_instance_id="recover-owner", outcome="verified", final_inspection={})
        self.store._connection.execute("UPDATE verification_command_results SET ordinal=2 WHERE verification_attempt_id=?",
            (intent["attempt_id"],))
        observer = mock.Mock(return_value=ProcessGroupObservation.DEAD)
        service = VerificationRecoveryService(self.store, identity=HostBootIdentity("host", "boot"),
            observer=observer)
        self.assertEqual(service.reconcile(workflow.id), VerificationRecoveryOutcome.STATE_INCONSISTENT)
        observer.assert_not_called()
        self.assertIsNotNone(self.store.active_workspace_operation_lease(
            RepositoryInspector(self.root).repository_key()))

    def test_corrupt_completed_passing_identity_cannot_authorize_a_successor(self):
        workflow, intent = self.pending_attempt([["/bin/true"], ["/bin/true"]])
        self.complete_current_command(intent)
        self.store._connection.execute("""UPDATE verification_command_results
            SET child_process_start=NULL WHERE verification_attempt_id=?""", (intent["attempt_id"],))
        bound = json.loads(self.store._connection.execute(
            "SELECT manifest_binding_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0])["commands"][1]
        with self.assertRaises(ConflictFailure):
            self.store.record_verification_command_intent(intent["attempt_id"], intent["lease_id"],
                owner_instance_id="recover-owner", ordinal=2, command_id=bound["id"],
                canonical_command_sha256=self.store._command_hash(bound), argv=bound["argv"],
                timeout_seconds=bound["timeout_seconds"])

    def test_corrupt_completed_passing_identity_cannot_authorize_terminalization(self):
        workflow, intent = self.pending_attempt()
        self.complete_current_command(intent)
        self.store._connection.execute("""UPDATE verification_command_results
            SET child_owner_instance_id='other-owner' WHERE verification_attempt_id=?""",
            (intent["attempt_id"],))
        with self.assertRaises(ConflictFailure):
            self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"],
                owner_instance_id="recover-owner", outcome="verified", final_inspection={})
        self.assertIsNotNone(self.store.active_workspace_operation_lease(
            RepositoryInspector(self.root).repository_key()))

    def test_corrupt_completed_passing_identity_cannot_authorize_recovery_release(self):
        workflow, intent = self.pending_attempt()
        self.complete_current_command(intent)
        self.store._connection.execute("""UPDATE verification_command_results
            SET child_process_session=0 WHERE verification_attempt_id=?""", (intent["attempt_id"],))
        with self.assertRaises(ConflictFailure):
            self.store.finish_interrupted_verification_recovery(self.recovery_decision(workflow))
        self.assertIsNotNone(self.store.active_workspace_operation_lease(
            RepositoryInspector(self.root).repository_key()))

    def test_dead_unchanged_is_interrupted_and_exact_lease_is_released_idempotently(self):
        workflow, intent = self.pending_attempt()
        service = self.service(ProcessGroupObservation.DEAD)
        self.assertEqual(service.reconcile(workflow.id), VerificationRecoveryOutcome.PROCESS_DEAD_UNCHANGED)
        self.assertIsNone(self.store.active_verification_recovery_context(workflow.id))
        row = self.store._connection.execute(
            "SELECT status,classification FROM verification_attempts WHERE id=?", (intent["attempt_id"],)).fetchone()
        self.assertEqual(tuple(row), ("terminal", "interrupted_unchanged"))
        event_count = self.store._connection.execute(
            "SELECT count(*) FROM events WHERE type='verification.attempt.terminal'").fetchone()[0]
        self.assertIsNone(service.reconcile(workflow.id))
        self.assertEqual(self.store._connection.execute(
            "SELECT count(*) FROM events WHERE type='verification.attempt.terminal'").fetchone()[0], event_count)

    def test_persistence_recovery_boundary_accepts_only_complete_durable_authority(self):
        workflow, intent = self.pending_attempt()
        self.store.finish_interrupted_verification_recovery(self.recovery_decision(workflow))
        self.assertIsNone(self.store._connection.execute(
            "SELECT 1 FROM workspace_operation_leases WHERE lease_id=?",
            (intent["lease_id"],)).fetchone())
        terminal = self.store._connection.execute(
            "SELECT status,classification,final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()
        self.assertEqual(tuple(terminal[:2]), ("terminal", "interrupted_unchanged"))
        self.assertEqual(json.loads(terminal[2])["process_observation"], "dead")

    def test_persistence_boundary_does_not_trust_stale_caller_repository_evidence(self):
        workflow, intent = self.pending_attempt()
        decision = self.recovery_decision(workflow)
        (self.root / "source.py").write_text("changed after caller inspection\n")

        with self.assertRaises(ConflictFailure):
            self.store.finish_interrupted_verification_recovery(decision)

        self.assertIsNotNone(self.store._connection.execute(
            "SELECT 1 FROM workspace_operation_leases WHERE lease_id=?",
            (intent["lease_id"],)).fetchone())

    def test_persistence_boundary_requires_the_full_exact_repository_snapshot(self):
        workflow, intent = self.pending_attempt()
        decision = self.recovery_decision(workflow)
        forged_repository = dict(decision.repository)
        forged_repository["status_sha256"] = "f" * 64
        fields = {key: value for key, value in forged_repository.items()
                  if key != "fingerprint"}
        forged_repository["fingerprint"] = hashlib.sha256(json.dumps(
            fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        forged = VerificationRecoveryDecision(
            workflow_id=decision.workflow_id,
            process_observation=decision.process_observation,
            observed_identity=decision.observed_identity,
            repository=forged_repository,
            control_state_fingerprint=decision.control_state_fingerprint,
            authority=decision.authority,
            detail=decision.detail,
        )

        with self.assertRaises(ConflictFailure):
            self.store.finish_interrupted_verification_recovery(forged)

        self.assertIsNotNone(self.store._connection.execute(
            "SELECT 1 FROM workspace_operation_leases WHERE lease_id=?",
            (intent["lease_id"],)).fetchone())

    def test_forged_or_incomplete_recovery_decisions_retain_exact_lease(self):
        mutations = {
            "attempt": lambda value: {**value, "attempt_id": "other-attempt"},
            "operation": lambda value: {**value, "operation_id": "other-operation"},
            "workflow": lambda value: {**value, "workflow_id": "other-workflow"},
            "lease": lambda value: {**value, "lease_id": "other-lease"},
            "owner": lambda value: {**value, "owner_instance_id": "other-owner"},
        }
        for label, mutate in mutations.items():
            with self.subTest(authority=label):
                self.reset_fixture()
                workflow, intent = self.pending_attempt()
                decision = self.recovery_decision(workflow)
                forged = VerificationRecoveryDecision(workflow_id=decision.workflow_id,
                    process_observation=decision.process_observation,
                    observed_identity=mutate(dict(decision.observed_identity)),
                    repository=decision.repository,
                    control_state_fingerprint=decision.control_state_fingerprint,
                    authority=decision.authority, detail=decision.detail)
                with self.assertRaises(ConflictFailure):
                    self.store.finish_interrupted_verification_recovery(forged)
                self.assertIsNotNone(self.store._connection.execute(
                    "SELECT 1 FROM workspace_operation_leases WHERE lease_id=?",
                    (intent["lease_id"],)).fetchone())
        self.reset_fixture()
        workflow, intent = self.pending_attempt()
        decision = self.recovery_decision(workflow)
        incomplete = VerificationRecoveryDecision(workflow_id=workflow.id,
            process_observation="dead", observed_identity=decision.observed_identity,
            repository=decision.repository,
            control_state_fingerprint=decision.control_state_fingerprint,
            authority={}, detail=decision.detail)
        with self.assertRaises(ConflictFailure):
            self.store.finish_interrupted_verification_recovery(incomplete)
        self.assertIsNotNone(self.store._connection.execute(
            "SELECT 1 FROM workspace_operation_leases WHERE lease_id=?",
            (intent["lease_id"],)).fetchone())

        for label, forged in (
            ("live_process", VerificationRecoveryDecision(workflow_id=workflow.id,
                process_observation="alive_owned", observed_identity=decision.observed_identity,
                repository=decision.repository,
                control_state_fingerprint=decision.control_state_fingerprint,
                authority=decision.authority, detail=decision.detail)),
            ("changed_repository", VerificationRecoveryDecision(workflow_id=workflow.id,
                process_observation="dead", observed_identity=decision.observed_identity,
                repository={**decision.repository, "branch_name": "other"},
                control_state_fingerprint=decision.control_state_fingerprint,
                authority=decision.authority, detail=decision.detail)),
            ("changed_control", VerificationRecoveryDecision(workflow_id=workflow.id,
                process_observation="dead", observed_identity=decision.observed_identity,
                repository=decision.repository, control_state_fingerprint="f" * 64,
                authority=decision.authority, detail=decision.detail)),
        ):
            with self.subTest(observation=label):
                with self.assertRaises((ConflictFailure, ValidationFailure)):
                    self.store.finish_interrupted_verification_recovery(forged)
                self.assertIsNotNone(self.store._connection.execute(
                    "SELECT 1 FROM workspace_operation_leases WHERE lease_id=?",
                    (intent["lease_id"],)).fetchone())

    def test_corrupt_durable_recovery_linkages_fail_closed(self):
        corruptions = {
            "attempt": "UPDATE verification_attempts SET lease_id='other-lease'",
            "operation": "UPDATE operations SET related_record_id=NULL WHERE kind='verification'",
            "workflow": "UPDATE workflows SET status='human_attention'",
            "repository": "UPDATE workspace_operation_leases SET repository_key='other-key'",
            "lease_owner": "UPDATE workspace_operation_leases SET owner_instance_id='other-owner'",
            "authority": "UPDATE verification_attempts SET authority_sha256='" + "f" * 64 + "'",
            "child_identity": "UPDATE verification_command_results SET child_process_session=NULL",
            "missing_authority": "DELETE FROM task_implementation_states WHERE status='verifying'",
        }
        for label, statement in corruptions.items():
            with self.subTest(linkage=label):
                self.reset_fixture()
                workflow, intent = self.pending_attempt()
                decision = self.recovery_decision(workflow)
                self.store._connection.execute(statement)
                with self.assertRaises(ConflictFailure):
                    self.store.finish_interrupted_verification_recovery(decision)
                self.assertIsNotNone(self.store._connection.execute(
                    "SELECT 1 FROM workspace_operation_leases WHERE lease_id=?",
                    (intent["lease_id"],)).fetchone())

    def test_unknown_cannot_be_released_by_normal_or_generic_lease_api(self):
        workflow, intent = self.pending_attempt()
        context = self.store.active_verification_recovery_context(workflow.id)
        lease = context["lease"]
        with self.assertRaises(ConflictFailure):
            self.store.release_workspace_operation_lease(repository_key=lease["repository_key"],
                lease_id=lease["lease_id"], attempt_id=lease["attempt_id"],
                operation_id=lease["operation_id"], owner_instance_id=lease["owner_instance_id"])
        self.store._connection.execute("""UPDATE workspace_operation_leases
            SET operation_kind='implementation' WHERE lease_id=?""", (lease["lease_id"],))
        with self.assertRaises(ConflictFailure):
            self.store.release_workspace_operation_lease(repository_key=lease["repository_key"],
                lease_id=lease["lease_id"], attempt_id=lease["attempt_id"],
                operation_id=lease["operation_id"], owner_instance_id=lease["owner_instance_id"])
        self.store._connection.execute("""UPDATE workspace_operation_leases
            SET operation_kind='verification' WHERE lease_id=?""", (lease["lease_id"],))
        self.store.retain_verification_unknown(intent["attempt_id"], intent["lease_id"],
            owner_instance_id="recover-owner", final_inspection={"reason": "ambiguous"},
            detail="verification is unknown")
        with self.assertRaises(ConflictFailure):
            self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"],
                owner_instance_id="recover-owner", outcome="verified", final_inspection={})
        with self.assertRaises(ConflictFailure):
            self.store.release_workspace_operation_lease(repository_key=lease["repository_key"],
                lease_id=lease["lease_id"], attempt_id=lease["attempt_id"],
                operation_id=lease["operation_id"], owner_instance_id=lease["owner_instance_id"])
        with self.assertRaises(ConflictFailure):
            self.store.finish_interrupted_verification_recovery(self.recovery_decision(workflow))
        self.assertIsNotNone(self.store._connection.execute(
            "SELECT 1 FROM workspace_operation_leases WHERE lease_id=?",
            (intent["lease_id"],)).fetchone())

    def test_verification_child_identity_is_write_once_and_generic_api_cannot_mutate_it(self):
        workflow, intent = self.pending_attempt()
        before = tuple(self.store._connection.execute(
            "SELECT child_pid,child_process_start,child_process_group,child_process_session "
            "FROM workspace_operation_leases WHERE lease_id=?", (intent["lease_id"],)).fetchone())
        with self.assertRaises(ConflictFailure):
            self.store.finish_verification_attempt(intent["attempt_id"], intent["lease_id"],
                owner_instance_id="recover-owner", outcome="verification_failed",
                final_inspection={})
        with self.assertRaises(ConflictFailure):
            self.store.record_workspace_operation_child(intent["attempt_id"], intent["lease_id"],
                owner_instance_id="recover-owner", child_pid=9, child_process_start="other",
                child_process_group=9)
        command_id = self.store._connection.execute(
            "SELECT id FROM verification_command_results WHERE verification_attempt_id=?",
            (intent["attempt_id"],)).fetchone()[0]
        with self.assertRaises(ConflictFailure):
            self.store.record_verification_command_started(intent["attempt_id"], intent["lease_id"],
                command_id, owner_instance_id="recover-owner", child_pid=9,
                child_process_start="other", child_process_group=9,
                child_process_session=9, child_host_id="host", child_boot_id="boot")
        after = tuple(self.store._connection.execute(
            "SELECT child_pid,child_process_start,child_process_group,child_process_session "
            "FROM workspace_operation_leases WHERE lease_id=?", (intent["lease_id"],)).fetchone())
        self.assertEqual(after, before)

    def test_generic_workflow_mutations_cannot_bypass_unresolved_verification(self):
        workflow, intent = self.pending_attempt()
        with self.assertRaises(ConflictFailure):
            self.store.set_workflow_state(workflow.id, status=WorkflowStatus.RUNNING)
        with self.assertRaises(ConflictFailure):
            self.store.cancel_v2_workflow(workflow.id)
        row = self.store._connection.execute(
            "SELECT verification_attempts.plan_artifact_id,verification_attempts.plan_sha256,"
            "verification_attempts.task_contract_id,verification_attempts.task_contract_sha256,selected_at "
            "FROM verification_attempts JOIN task_implementation_states USING "
            "(workflow_id,plan_artifact_id,task_contract_id) WHERE verification_attempts.id=?",
            (intent["attempt_id"],)).fetchone()
        with self.assertRaises(ConflictFailure):
            self.store.put_task_implementation_state(workflow.id, row["plan_artifact_id"],
                row["plan_sha256"], row["task_contract_id"], row["task_contract_sha256"],
                "verified", selected_at=row["selected_at"])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.VERIFYING)
        self.assertIsNotNone(self.store._connection.execute(
            "SELECT 1 FROM workspace_operation_leases WHERE lease_id=?",
            (intent["lease_id"],)).fetchone())

    def test_every_audited_generic_mutation_surface_uses_the_unresolved_verification_guard(self):
        guarded = (
            "set_workflow_state", "cancel_v2_workflow", "create_generation_intent",
            "start_execution", "put_task_implementation_state", "create_implementation_intent",
            "finish_implementation_attempt", "request_plan_changes", "answer_clarification",
            "complete_generation", "import_task_plan", "create_task_cycle",
            "create_task_operation", "complete_task_operation", "record_task_test_evidence",
            "accept_task", "complete_task_cycle", "record_intervention", "pause_task",
            "fail_task_operation", "mark_task_operation_unknown", "fail_generation",
            "mark_operation_unknown", "record_approval", "create_scope",
            "record_lifecycle_state", "record_capability_result", "record_canonical_transition",
            "record_governance_decision", "migrate_historical_workflow",
        )
        for name in guarded:
            with self.subTest(api=name):
                source = inspect.getsource(getattr(WorkflowStore, name))
                self.assertIn("_require_no_unresolved_verification_unlocked", source)

    def test_unknown_is_sticky_and_later_recovery_classification_is_durable(self):
        workflow, intent = self.pending_attempt()
        original = {"identity": {"pid": 4242, "process_start": "start-1",
            "ownership_marker": "slice-3"}}
        self.store.retain_verification_unknown(intent["attempt_id"], intent["lease_id"],
            owner_instance_id="recover-owner", final_inspection=original,
            detail="Slice 3 could not prove process-group death")
        service = self.service(ProcessGroupObservation.DEAD)
        self.assertEqual(service.reconcile(workflow.id),
            VerificationRecoveryOutcome.PROCESS_DEAD_UNCHANGED)
        self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))
        attempt = self.store._connection.execute(
            "SELECT status,classification,final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()
        self.assertEqual(tuple(attempt[:2]), ("unknown", "verification_unknown"))
        retained = json.loads(attempt[2])
        self.assertEqual(retained["recovery_classification"], "process_dead_unchanged")
        self.assertEqual(retained["identity"]["ownership_marker"], "slice-3")
        self.assertEqual(self.service(ProcessGroupObservation.ALIVE_OWNED).reconcile(workflow.id),
            VerificationRecoveryOutcome.PROCESS_ALIVE_OWNED)
        retained = json.loads(self.store._connection.execute(
            "SELECT final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0])
        self.assertEqual(retained["recovery_classification"], "process_alive_owned")
        self.assertEqual([item["classification"] for item in retained["recovery_observations"]],
            ["process_dead_unchanged", "process_alive_owned"])
        self.assertEqual(retained["identity"]["ownership_marker"], "slice-3")
        self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))

    def test_crash_after_command_result_persistence_recovers_without_redispatch(self):
        workflow, intent = self.pending_attempt()
        self.complete_current_command(intent)
        observer = mock.Mock(side_effect=AssertionError("completed command must not be observed or rerun"))
        service = VerificationRecoveryService(self.store, identity=HostBootIdentity("host", "boot"),
            observer=observer)
        self.assertEqual(service.reconcile(workflow.id),
            VerificationRecoveryOutcome.PROCESS_DEAD_UNCHANGED)
        observer.assert_not_called()
        attempt = self.store._connection.execute(
            "SELECT status,classification FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()
        self.assertEqual(tuple(attempt), ("terminal", "interrupted_unchanged"))
        self.assertIsNone(self.store.active_verification_recovery_context(workflow.id))
        self.assertEqual(self.store._connection.execute(
            "SELECT count(*) FROM verification_command_results").fetchone()[0], 1)

    def test_between_command_crash_recovers_without_running_next_command(self):
        marker = self.root / "second-command-ran"
        workflow, intent = self.pending_attempt([["/bin/true"],
            ["/bin/sh", "-c", f"touch {marker}"]])
        self.complete_current_command(intent)
        service = VerificationRecoveryService(self.store, identity=HostBootIdentity("host", "boot"),
            observer=mock.Mock(side_effect=AssertionError("recovery must not execute or observe a completed child")))
        self.assertEqual(service.reconcile(workflow.id),
            VerificationRecoveryOutcome.PROCESS_DEAD_UNCHANGED)
        self.assertFalse(marker.exists())
        self.assertEqual(self.store._connection.execute(
            "SELECT count(*) FROM verification_command_results").fetchone()[0], 1)
        self.assertEqual(self.store._connection.execute(
            "SELECT classification FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0], "interrupted_unchanged")

    def test_corrupt_authoritative_command_evidence_is_unknown_and_retains_lease(self):
        corruptions = (
            ("command_id", "UPDATE verification_command_results SET command_id='wrong'"),
            ("ordinal", "UPDATE verification_command_results SET ordinal=2"),
            ("argv", "UPDATE verification_command_results SET argv_json='[\"/bin/false\"]'"),
            ("timeout", "UPDATE verification_command_results SET timeout_seconds=9"),
            ("canonical_hash", "UPDATE verification_command_results SET canonical_command_sha256='" + "f" * 64 + "'"),
        )
        for label, statement in corruptions:
            with self.subTest(field=label):
                if self.store is not None:
                    self.store.close(); self.store = None
                self.temp.cleanup(); self.setUp()
                workflow, intent = self.pending_attempt()
                self.store._connection.execute(statement)
                self.assertEqual(self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id),
                    VerificationRecoveryOutcome.STATE_INCONSISTENT)
                self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))
                attempt = self.store._connection.execute(
                    "SELECT status,classification FROM verification_attempts WHERE id=?",
                    (intent["attempt_id"],)).fetchone()
                self.assertEqual(tuple(attempt), ("unknown", "verification_unknown"))
                self.assertEqual(self.store.get_workflow(workflow.id).status,
                    WorkflowStatus.HUMAN_ATTENTION)

    def test_corrupt_prior_unknown_evidence_is_preserved_while_failing_closed(self):
        workflow, intent = self.pending_attempt()
        corrupt = '{"repository":'
        self.store._connection.execute("""UPDATE verification_attempts
            SET final_inspection_json=? WHERE id=?""", (corrupt, intent["attempt_id"]))
        self.assertEqual(self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id),
            VerificationRecoveryOutcome.STATE_INCONSISTENT)
        retained = json.loads(self.store._connection.execute(
            "SELECT final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0])
        self.assertEqual(retained["corrupt_prior_evidence_raw"], corrupt)
        self.assertEqual(retained["recovery_observations"][0]["classification"],
            "state_inconsistent")
        self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))
        self.assertEqual(self.store.get_workflow(workflow.id).status,
            WorkflowStatus.HUMAN_ATTENTION)

    def test_corrupt_feature_plan_approval_task_and_producer_authority_fails_closed(self):
        corruptions = {
            "feature": ("UPDATE artifacts SET sha256=? WHERE stage='intake'", ("f" * 64,)),
            "plan": ("UPDATE artifacts SET sha256=? WHERE stage='plan'", ("e" * 64,)),
            "approval": ("UPDATE approvals SET decision='rejected'", ()),
            "task": ("UPDATE task_implementation_states SET task_contract_sha256=?", ("d" * 64,)),
            "producer_operation": (
                "UPDATE operations SET status='unknown' WHERE kind='implementation'", ()),
            "producer_execution": ("""UPDATE executions SET lifecycle='unknown' WHERE id IN
                (SELECT execution_id FROM implementation_attempts)""", ()),
        }
        for label, (statement, parameters) in corruptions.items():
            with self.subTest(authority=label):
                self.reset_fixture()
                workflow, intent = self.pending_attempt()
                self.complete_current_command(intent)
                self.store._connection.execute(statement, parameters)
                self.assert_completed_evidence_fails_closed(workflow, intent)

    def test_completed_command_requires_complete_repository_inspection_evidence(self):
        corruptions = {
            "missing_repository": lambda value: value.pop("repository"),
            "malformed_repository": lambda value: value.update(repository={"fingerprint": "bad"}),
            "repository_snapshot_mismatch": self._replace_with_valid_mismatched_repository,
        }
        for label, corrupt in corruptions.items():
            with self.subTest(evidence=label):
                self.reset_fixture()
                workflow, intent = self.pending_attempt()
                self.complete_current_command(intent)
                row = self.store._connection.execute(
                    "SELECT id,post_command_inspection_json FROM verification_command_results").fetchone()
                inspection = json.loads(row[1]); corrupt(inspection)
                self.store._connection.execute(
                    "UPDATE verification_command_results SET post_command_inspection_json=? WHERE id=?",
                    (json.dumps(inspection, sort_keys=True, separators=(",", ":")), row[0]))
                self.assert_completed_evidence_fails_closed(workflow, intent)

    @staticmethod
    def _replace_with_valid_mismatched_repository(inspection):
        repository = dict(inspection["repository"])
        repository["branch_name"] = repository["branch_name"] + "-other"
        fields = {key: value for key, value in repository.items() if key != "fingerprint"}
        repository["fingerprint"] = hashlib.sha256(json.dumps(
            fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        inspection["repository"] = repository

    def test_completed_command_requires_matching_control_state_fingerprint(self):
        corruptions = {
            "missing": lambda value: value.pop("control_state_fingerprint"),
            "malformed": lambda value: value.update(control_state_fingerprint=17),
            "mismatch": lambda value: value.update(control_state_fingerprint="f" * 64),
        }
        for label, corrupt in corruptions.items():
            with self.subTest(evidence=label):
                self.reset_fixture()
                workflow, intent = self.pending_attempt()
                self.complete_current_command(intent)
                row = self.store._connection.execute(
                    "SELECT id,post_command_inspection_json FROM verification_command_results").fetchone()
                inspection = json.loads(row[1]); corrupt(inspection)
                self.store._connection.execute(
                    "UPDATE verification_command_results SET post_command_inspection_json=? WHERE id=?",
                    (json.dumps(inspection, sort_keys=True, separators=(",", ":")), row[0]))
                self.assert_completed_evidence_fails_closed(workflow, intent)

    def test_completed_command_requires_complete_current_host_boot_and_owner_identity(self):
        corruptions = {
            "host_mismatch": "UPDATE workspace_operation_leases SET owner_host_id='other-host'",
            "boot_mismatch": "UPDATE workspace_operation_leases SET owner_boot_id='other-boot'",
            "missing_host": "UPDATE workspace_operation_leases SET owner_host_id=''",
            "missing_boot": "UPDATE workspace_operation_leases SET owner_boot_id=''",
            "missing_owner": "UPDATE workspace_operation_leases SET owner_instance_id=''",
            "owner_chain": "UPDATE verification_command_results SET child_owner_instance_id='other-owner'",
        }
        for label, statement in corruptions.items():
            with self.subTest(identity=label):
                self.reset_fixture()
                workflow, intent = self.pending_attempt()
                self.complete_current_command(intent)
                self.store._connection.execute(statement)
                self.assert_completed_evidence_fails_closed(workflow, intent)

    def test_corrupt_recovery_lifecycle_state_fails_closed(self):
        corruptions = {
            "workflow": "UPDATE workflows SET status='task_verified'",
            "task": "UPDATE task_implementation_states SET status='verified'",
            "operation": "UPDATE operations SET status='completed' WHERE kind='verification'",
            "execution": "UPDATE executions SET lifecycle='completed' WHERE id IN "
                "(SELECT execution_id FROM verification_attempts)",
        }
        for label, statement in corruptions.items():
            with self.subTest(lifecycle=label):
                self.reset_fixture()
                workflow, intent = self.pending_attempt()
                self.complete_current_command(intent)
                self.store._connection.execute(statement)
                self.assert_completed_evidence_fails_closed(workflow, intent)

    def test_inconsistent_completed_result_classifications_fail_closed(self):
        corruptions = {
            "passed_nonzero": "UPDATE verification_command_results SET exit_code=2",
            "failed_zero": "UPDATE verification_command_results SET classification='failed'",
            "timeout_flag_missing": "UPDATE verification_command_results SET classification='timed_out'",
            "output_limit_flag_missing": "UPDATE verification_command_results SET classification='output_limited'",
            "spawn_blocked_with_exit": "UPDATE verification_command_results SET classification='spawn_blocked'",
            "repository_mutated_with_safe_snapshot":
                "UPDATE verification_command_results SET classification='repository_mutated'",
        }
        for label, statement in corruptions.items():
            with self.subTest(classification=label):
                self.reset_fixture()
                workflow, intent = self.pending_attempt()
                self.complete_current_command(intent)
                self.store._connection.execute(statement)
                self.assert_completed_evidence_fails_closed(workflow, intent)

    def test_dead_changed_becomes_unknown_and_retains_lease_and_evidence(self):
        workflow, intent = self.pending_attempt()
        (self.root / "source.py").write_text("changed during interrupted verification\n")
        service = self.service(ProcessGroupObservation.DEAD)
        self.assertEqual(service.reconcile(workflow.id), VerificationRecoveryOutcome.PROCESS_DEAD_CHANGED)
        self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))
        attempt = self.store._connection.execute(
            "SELECT status,classification,final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()
        self.assertEqual(tuple(attempt[:2]), ("unknown", "verification_unknown"))
        evidence = json.loads(attempt[2])
        self.assertEqual(evidence["recovery_classification"], "process_dead_changed")
        self.assertEqual(set(evidence["identity"]), {"pid", "process_start", "process_group",
            "process_session", "machine_id", "boot_id", "owner_instance_id", "owner_pid",
            "workflow_id", "attempt_id", "lease_id", "operation_id", "command_result_id"})
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        events = self.store._connection.execute(
            "SELECT count(*) FROM events WHERE type='verification.recovery.unknown_retained'").fetchone()[0]
        self.assertEqual(service.reconcile(workflow.id), VerificationRecoveryOutcome.PROCESS_DEAD_CHANGED)
        self.assertEqual(self.store._connection.execute(
            "SELECT count(*) FROM events WHERE type='verification.recovery.unknown_retained'").fetchone()[0], events)
        retained = json.loads(self.store._connection.execute(
            "SELECT final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0])
        self.assertEqual(len(retained["recovery_observations"]), 1)

    def test_unknown_history_preserves_repository_control_and_classification_evidence(self):
        workflow, intent = self.pending_attempt()
        original_repository = {"fingerprint": "original-unsafe-repository"}
        original_control = "a" * 64
        self.store.retain_verification_unknown(intent["attempt_id"], intent["lease_id"],
            owner_instance_id="recover-owner",
            final_inspection={"repository": original_repository,
                "control_state_fingerprint": original_control,
                "recovery_classification": "inspection_failure"},
            detail="original inspection could not establish safety")
        self.assertEqual(self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id),
            VerificationRecoveryOutcome.PROCESS_DEAD_UNCHANGED)
        retained = json.loads(self.store._connection.execute(
            "SELECT final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0])
        self.assertEqual(retained["repository"], original_repository)
        self.assertEqual(retained["control_state_fingerprint"], original_control)
        self.assertEqual(retained["original_unknown_evidence"]["classification"],
            "inspection_failure")
        history = retained["recovery_observations"]
        self.assertEqual([item["classification"] for item in history],
            ["process_dead_unchanged"])
        self.assertIn("repository", history[0])
        self.assertIn("control_state_fingerprint", history[0])
        before = json.dumps(retained, sort_keys=True)
        self.assertEqual(self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id),
            VerificationRecoveryOutcome.PROCESS_DEAD_UNCHANGED)
        after = self.store._connection.execute(
            "SELECT final_inspection_json FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0]
        self.assertEqual(json.dumps(json.loads(after), sort_keys=True), before)

    def test_identity_failures_fail_closed_without_signaling(self):
        cases = (
            (ProcessGroupObservation.PID_REUSED, VerificationRecoveryOutcome.PID_REUSED),
            (ProcessGroupObservation.IDENTITY_MISMATCH, VerificationRecoveryOutcome.IDENTITY_MISMATCH),
            (ProcessGroupObservation.DIFFERENT_MACHINE, VerificationRecoveryOutcome.DIFFERENT_MACHINE),
            (ProcessGroupObservation.DIFFERENT_BOOT, VerificationRecoveryOutcome.DIFFERENT_BOOT),
            (ProcessGroupObservation.INCOMPLETE_IDENTITY, VerificationRecoveryOutcome.INCOMPLETE_IDENTITY),
            (ProcessGroupObservation.INSPECTION_FAILURE, VerificationRecoveryOutcome.INSPECTION_FAILURE),
            (ProcessGroupObservation.AMBIGUOUS_OWNERSHIP, VerificationRecoveryOutcome.AMBIGUOUS_OWNERSHIP),
        )
        for observation, expected in cases:
            with self.subTest(observation=observation.value):
                if self.store is not None:
                    self.store.close(); self.store = None
                self.temp.cleanup(); self.setUp()
                workflow, _ = self.pending_attempt()
                with mock.patch("engineering_flow.process_identity.os.killpg") as signal_group:
                    self.assertEqual(self.service(observation).reconcile(workflow.id), expected)
                self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))
                self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
                signal_group.assert_not_called()

    def test_inconsistent_owner_linkage_fails_closed(self):
        workflow, _ = self.pending_attempt()
        self.store._connection.execute(
            "UPDATE verification_command_results SET child_owner_instance_id='other'")
        self.assertEqual(self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id),
            VerificationRecoveryOutcome.STATE_INCONSISTENT)
        self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))

    def test_inconsistent_operation_linkage_fails_closed_without_releasing(self):
        workflow, _ = self.pending_attempt()
        producer_operation = self.store._connection.execute(
            "SELECT producer_operation_id FROM verification_attempts").fetchone()[0]
        self.store._connection.execute(
            "UPDATE workspace_operation_leases SET operation_id=?", (producer_operation,))
        self.assertEqual(self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id),
            VerificationRecoveryOutcome.STATE_INCONSISTENT)
        self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)

    def test_inconsistent_linkage_exact_observation_is_deduplicated(self):
        workflow, intent = self.pending_attempt()
        evidence = {"linkage": "lease operation differs", "future_evidence": {"version": 1}}
        kwargs = {"workflow_id": workflow.id, "lease_id": intent["lease_id"],
            "attempt_id": intent["attempt_id"], "operation_id": intent["operation_id"],
            "owner_instance_id": "recover-owner", "evidence": evidence,
            "detail": "verification linkage is inconsistent"}
        self.store.retain_inconsistent_verification_lease(**kwargs)
        self.store.retain_inconsistent_verification_lease(**kwargs)
        events = self.store._connection.execute("""SELECT payload FROM events WHERE workflow_id=?
            AND type='verification.recovery.inconsistent_lease'""", (workflow.id,)).fetchall()
        self.assertEqual(len(events), 1)

    def test_inconsistent_linkage_distinct_observation_appends(self):
        workflow, intent = self.pending_attempt()
        base = {"workflow_id": workflow.id, "lease_id": intent["lease_id"],
            "attempt_id": intent["attempt_id"], "operation_id": intent["operation_id"],
            "owner_instance_id": "recover-owner", "detail": "verification linkage is inconsistent"}
        self.store.retain_inconsistent_verification_lease(**base,
            evidence={"linkage": "lease operation differs", "future_evidence": {"version": 1}})
        self.store.retain_inconsistent_verification_lease(**base,
            evidence={"linkage": "lease operation differs", "future_evidence": {"version": 2}})
        events = self.store._connection.execute("""SELECT payload FROM events WHERE workflow_id=?
            AND type='verification.recovery.inconsistent_lease' ORDER BY sequence ASC""", (workflow.id,)).fetchall()
        self.assertEqual(len(events), 2)
        self.assertEqual([json.loads(row["payload"])["identity"]["future_evidence"]["version"]
            for row in events], [1, 2])

    def test_recovery_event_projection_allowlists_safe_fields(self):
        event = mock.Mock()
        event.sequence, event.type, event.stage = 1, "verification.recovery.live_owned", None
        event.artifact_id, event.execution_id, event.created_at = None, None, "now"
        event.payload = {"attempt_id": "attempt-safe", "classification": "process_alive_owned",
            "reason": "raw diagnostic", "observation": {"pid": 4242, "raw_output": "secret",
                "environment": {"TOKEN": "secret"}, "owner_pid": 111,
                "process_start": "start", "process_group": 4242, "process_session": 4242,
                "machine_id": "host", "boot_id": "boot", "owner_instance_id": "owner",
                "future": "not safe"},
            "future_field": "not safe"}
        projected = _event_payload(event)["payload"]
        self.assertEqual(projected, {"attempt_id": "attempt-safe",
            "classification": "process_alive_owned", "lease_held": True})
        rendered = json.dumps(_event_payload(event), sort_keys=True)
        for sensitive in ("4242", "secret", "start", "host", "boot", "owner"):
            self.assertNotIn(sensitive, rendered)

    def test_recovery_event_projection_excludes_unknown_fields_but_preserves_other_events(self):
        recovery = mock.Mock()
        recovery.sequence, recovery.type, recovery.stage = 1, "verification.recovery.unknown_retained", None
        recovery.artifact_id, recovery.execution_id, recovery.created_at = None, None, "now"
        recovery.payload = {"attempt_id": "attempt-safe", "observation": {
            "classification": "process_dead_changed", "raw_output": "secret", "future": "not safe"},
            "new_top_level_evidence": "not safe"}
        self.assertEqual(_event_payload(recovery)["payload"], {"attempt_id": "attempt-safe",
            "classification": "process_dead_changed", "lease_held": True})
        future = mock.Mock()
        future.sequence, future.type, future.stage = 2, "verification.recovery.future", None
        future.artifact_id, future.execution_id, future.created_at = None, None, "now"
        future.payload = {"arbitrary_future_evidence": {"raw_output": "secret"}}
        self.assertEqual(_event_payload(future)["payload"], {})
        ordinary = mock.Mock()
        ordinary.sequence, ordinary.type, ordinary.stage = 3, "verification.command.completed", None
        ordinary.artifact_id, ordinary.execution_id, ordinary.created_at = None, None, "now"
        ordinary.payload = {"unchanged": {"future": "still present"}}
        self.assertEqual(_event_payload(ordinary)["payload"], ordinary.payload)

    def test_incomplete_persisted_identity_fails_closed(self):
        workflow, _ = self.pending_attempt()
        self.store._connection.execute(
            "UPDATE verification_command_results SET child_process_session=NULL")
        self.store._connection.execute(
            "UPDATE workspace_operation_leases SET child_process_session=NULL")
        service = VerificationRecoveryService(self.store, identity=HostBootIdentity("host", "boot"))
        self.assertEqual(service.reconcile(workflow.id),
            VerificationRecoveryOutcome.INCOMPLETE_IDENTITY)
        self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))

    def test_repository_inspection_failure_is_unknown_and_retains_lease(self):
        workflow, _ = self.pending_attempt()
        class BrokenInspector:
            def __init__(self, root): pass
            def capture(self): raise OSError("inspection unavailable")
        service = VerificationRecoveryService(self.store, identity=HostBootIdentity("host", "boot"),
            observer=lambda **kwargs: ProcessGroupObservation.DEAD, inspector_factory=BrokenInspector)
        self.assertEqual(service.reconcile(workflow.id),
            VerificationRecoveryOutcome.REPOSITORY_INSPECTION_FAILURE)
        self.assertIsNotNone(self.store.active_verification_recovery_context(workflow.id))

    def test_zero_matching_lease_fails_closed_without_observing_or_dispatching(self):
        workflow, intent = self.pending_attempt()
        self.store._connection.execute(
            "DELETE FROM workspace_operation_leases WHERE lease_id=?", (intent["lease_id"],))
        observer = mock.Mock(side_effect=AssertionError("ambiguous recovery must not observe"))
        service = VerificationRecoveryService(self.store,
            identity=HostBootIdentity("host", "boot"), observer=observer)
        self.assertEqual(service.reconcile(workflow.id),
            VerificationRecoveryOutcome.STATE_INCONSISTENT)
        observer.assert_not_called()
        self.assertEqual(self.store.get_workflow(workflow.id).status,
            WorkflowStatus.HUMAN_ATTENTION)
        self.assertIsNone(self.store._connection.execute(
            "SELECT result_at FROM verification_command_results").fetchone()[0])

    def test_multiple_lease_context_fails_closed_without_observing_or_releasing(self):
        workflow, intent = self.pending_attempt()
        self.store._connection.execute("""INSERT INTO operations
            (id,idempotency_key,kind,workflow_id,status,created_at,updated_at)
            VALUES ('ambiguous-op','ambiguous-op','verification',?,'pending','now','now')""",
            (workflow.id,))
        self.store._connection.execute("""INSERT INTO workspace_operation_leases
            (repository_key,lease_id,operation_kind,attempt_id,operation_id,workflow_id,
             canonical_root,owner_instance_id,owner_pid,owner_host_id,owner_boot_id,
             acquired_at,updated_at)
            VALUES ('ambiguous-key','ambiguous-lease','verification','ambiguous-attempt',
                    'ambiguous-op',?,'/ambiguous','ambiguous-owner',7,'host','boot','now','now')""",
            (workflow.id,))
        observer = mock.Mock(side_effect=AssertionError("ambiguous recovery must not observe"))
        service = VerificationRecoveryService(self.store,
            identity=HostBootIdentity("host", "boot"), observer=observer)
        self.assertEqual(service.reconcile(workflow.id),
            VerificationRecoveryOutcome.STATE_INCONSISTENT)
        observer.assert_not_called()
        self.assertEqual(self.store._connection.execute(
            "SELECT count(*) FROM workspace_operation_leases WHERE workflow_id=?",
            (workflow.id,)).fetchone()[0], 2)
        self.assertIsNone(self.store._connection.execute(
            "SELECT result_at FROM verification_command_results WHERE verification_attempt_id=?",
            (intent["attempt_id"],)).fetchone()[0])

    def test_unknown_recovery_persistence_failure_rolls_back_all_projections(self):
        workflow, intent = self.pending_attempt()
        before = self.recovery_rows(intent)
        self.store._connection.execute("""CREATE TRIGGER fail_recovery_unknown BEFORE INSERT ON events
            WHEN NEW.type='verification.recovery.unknown_retained'
            BEGIN SELECT RAISE(ABORT, 'fault injected'); END""")
        with self.assertRaises(DomainFailure):
            self.service(ProcessGroupObservation.PID_REUSED).reconcile(workflow.id)
        self.assertEqual(self.recovery_rows(intent), before)

    def test_inconsistent_lease_persistence_failure_rolls_back_all_projections(self):
        workflow, intent = self.pending_attempt()
        producer_operation = self.store._connection.execute(
            "SELECT producer_operation_id FROM verification_attempts WHERE id=?",
            (intent["attempt_id"],)).fetchone()[0]
        self.store._connection.execute(
            "UPDATE workspace_operation_leases SET operation_id=? WHERE lease_id=?",
            (producer_operation, intent["lease_id"]))
        before = self.recovery_rows(intent)
        self.store._connection.execute("""CREATE TRIGGER fail_inconsistent_recovery BEFORE INSERT ON events
            WHEN NEW.type='verification.recovery.inconsistent_lease'
            BEGIN SELECT RAISE(ABORT, 'fault injected'); END""")
        with self.assertRaises(DomainFailure):
            self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id)
        self.assertEqual(self.recovery_rows(intent), before)

    def test_dead_unchanged_terminal_failure_rolls_back_all_projections_and_lease_delete(self):
        workflow, intent = self.pending_attempt()
        before = self.recovery_rows(intent)
        self.store._connection.execute("""CREATE TRIGGER fail_verification_lease_delete
            BEFORE DELETE ON workspace_operation_leases
            WHEN OLD.lease_id='""" + intent["lease_id"] + """'
            BEGIN SELECT RAISE(ABORT, 'fault injected'); END""")
        with self.assertRaises(DomainFailure):
            self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id)
        self.assertEqual(self.recovery_rows(intent), before)

    def test_runtime_error_mid_terminal_projection_rolls_back_every_write(self):
        from engineering_flow import store as store_module
        workflow, intent = self.pending_attempt()
        before = self.recovery_rows(intent)
        real_json = store_module._json
        def fail_terminal_result_json(value):
            if value == {"classification": "interrupted_unchanged"}:
                raise RuntimeError("fault injected after attempt write")
            return real_json(value)
        with mock.patch("engineering_flow.store._json", side_effect=fail_terminal_result_json):
            with self.assertRaisesRegex(RuntimeError, "fault injected after attempt write"):
                self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id)
        self.assertEqual(self.recovery_rows(intent), before)
        self.assertFalse(self.store._connection.in_transaction)

    def test_runtime_error_after_terminal_event_persistence_rolls_back_every_write(self):
        workflow, intent = self.pending_attempt()
        before = self.recovery_rows(intent)
        real_event = self.store._event_unlocked
        def fail_after_event(*args, **kwargs):
            real_event(*args, **kwargs)
            raise RuntimeError("fault injected after terminal event")
        with mock.patch.object(self.store, "_event_unlocked", side_effect=fail_after_event):
            with self.assertRaisesRegex(RuntimeError, "fault injected after terminal event"):
                self.service(ProcessGroupObservation.DEAD).reconcile(workflow.id)
        self.assertEqual(self.recovery_rows(intent), before)
        self.assertFalse(self.store._connection.in_transaction)

    def test_real_identity_inspector_distinguishes_reuse_host_boot_incomplete_and_group_liveness(self):
        identity = HostBootIdentity("host", "boot")
        kwargs = dict(host_id="host", boot_id="boot", process_pid=42, process_start="10",
            process_group=42, process_session=42, identity=identity)
        self.assertEqual(observe_exact_process_group(**kwargs,
            record_reader=lambda pid: ("11", 42, 42, "S"), proc_lister=lambda: []),
            ProcessGroupObservation.PID_REUSED)
        self.assertEqual(observe_exact_process_group(**{**kwargs, "host_id": "elsewhere"},
            record_reader=lambda pid: None, proc_lister=lambda: []), ProcessGroupObservation.DIFFERENT_MACHINE)
        self.assertEqual(observe_exact_process_group(**{**kwargs, "boot_id": "old"},
            record_reader=lambda pid: None, proc_lister=lambda: []), ProcessGroupObservation.DIFFERENT_BOOT)
        self.assertEqual(observe_exact_process_group(**{**kwargs, "process_start": None},
            record_reader=lambda pid: None, proc_lister=lambda: []), ProcessGroupObservation.INCOMPLETE_IDENTITY)
        self.assertEqual(observe_exact_process_group(**kwargs,
            record_reader=lambda pid: None if pid == 42 else ("20", 42, 42, "S"),
            proc_lister=lambda: ["42", "43"]), ProcessGroupObservation.ALIVE_OWNED)
        self.assertEqual(observe_exact_process_group(**kwargs,
            record_reader=lambda pid: None, proc_lister=lambda: []), ProcessGroupObservation.DEAD)
        self.assertEqual(observe_exact_process_group(**kwargs,
            record_reader=lambda pid: ("10", 99, 42, "S"), proc_lister=lambda: []),
            ProcessGroupObservation.IDENTITY_MISMATCH)
        self.assertEqual(observe_exact_process_group(**kwargs,
            record_reader=lambda pid: (_ for _ in ()).throw(OSError("denied")), proc_lister=lambda: []),
            ProcessGroupObservation.INSPECTION_FAILURE)
        self.assertEqual(observe_exact_process_group(**kwargs,
            record_reader=lambda pid: None if pid == 42 else ("20", 42, 99, "S"),
            proc_lister=lambda: ["42", "43"]), ProcessGroupObservation.AMBIGUOUS_OWNERSHIP)


if __name__ == "__main__":
    unittest.main()
