import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from engineering_flow.domain import (  # noqa: E402
    ApprovalDecision,
    ArtifactCorruptionFailure,
    ConflictFailure,
    ValidationFailure,
    Stage,
    CanonicalStage,
    HumanAttentionOutcome,
    LifecycleVersion,
    ScopeKind,
    WorkflowStatus,
    GovernanceDecision,
    GovernanceDecisionType,
)
from engineering_flow.store import WorkflowStore  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "workflows.sqlite3"
        self.store = WorkflowStore(self.db_path, secret_values=("TOP-SECRET",))

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_schema_enables_wal_foreign_keys_and_required_tables(self):
        self.assertEqual(self.store._connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        self.assertEqual(self.store._connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        names = {
            row[0] for row in self.store._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue({"workflows", "artifacts", "approvals", "sessions", "executions", "operations", "events"} <= names)

    def test_generation_intent_and_approval_replay_are_idempotent(self):
        workflow = self.store.create_workflow("/repo", configuration_snapshot={"secret": "TOP-SECRET"})
        first = self.store.create_generation_intent(workflow.id, Stage.PRD, request_hash="request-hash")
        replay = self.store.create_generation_intent(workflow.id, Stage.PRD, request_hash="request-hash")
        self.assertTrue(replay.reused)
        self.assertEqual(first.execution.id, replay.execution.id)

        artifact = self.store.complete_generation(
            first.operation.idempotency_key,
            content="# PRD\n",
            artifact_path=Path(self.temp_dir.name) / "workflows" / workflow.id / "artifacts" / "001-prd.md",
            stage=Stage.PRD,
            revision=1,
        )
        replay_after_completion = self.store.create_generation_intent(
            workflow.id, Stage.PRD, request_hash="request-hash"
        )
        self.assertTrue(replay_after_completion.reused)
        approval = self.store.record_approval(
            workflow.id, artifact.id, ApprovalDecision.APPROVED, actor="human", reason="TOP-SECRET"
        )
        self.assertEqual(approval.id, self.store.record_approval(
            workflow.id, artifact.id, ApprovalDecision.APPROVED, actor="human", reason="ignored"
        ).id)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0], 1)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], 1)

    def test_generation_completion_matches_intent_binding(self):
        workflow = self.store.create_workflow("/repo")
        intent = self.store.create_generation_intent(workflow.id, Stage.PRD, request_hash="request-hash")
        with self.assertRaises(ValidationFailure):
            self.store.complete_generation(
                intent.operation.idempotency_key,
                content="# TECHSPEC\n",
                artifact_path=Path(self.temp_dir.name) / "arbitrary-name.md",
                stage=Stage.TECHSPEC,
                revision=17,
            )
        with self.assertRaises(ValidationFailure):
            self.store.complete_generation(
                intent.operation.idempotency_key,
                content="# PRD\n",
                artifact_path=Path(self.temp_dir.name)
                / "workflows"
                / workflow.id
                / "artifacts"
                / "001-prd.md",
                stage=Stage.PRD,
                revision=17,
            )
        with self.assertRaises(ValidationFailure):
            self.store.complete_generation(
                intent.operation.idempotency_key,
                content="# PRD\n",
                artifact_path=Path(self.temp_dir.name) / "arbitrary-name.md",
                stage=Stage.PRD,
                revision=1,
            )

        artifact = self.store.complete_generation(
            intent.operation.idempotency_key,
            content="# PRD\n",
            artifact_path=Path(self.temp_dir.name)
            / "workflows"
            / workflow.id
            / "artifacts"
            / "001-prd.md",
            stage=Stage.PRD,
            revision=1,
        )
        self.assertEqual(artifact.stage, Stage.PRD)

    def test_artifact_is_revisioned_immutable_and_hash_verified(self):
        workflow = self.store.create_workflow("/repo")
        intent = self.store.create_generation_intent(workflow.id, Stage.PRD, request_hash="hash")
        path = Path(self.temp_dir.name) / "workflows" / workflow.id / "artifacts" / "001-prd.md"
        artifact = self.store.complete_generation(intent.operation.idempotency_key, content="stable", artifact_path=path,
                                                  stage=Stage.PRD, revision=1)
        self.assertEqual(artifact.sha256, hashlib.sha256(b"stable").hexdigest())
        self.assertEqual(self.store.read_artifact(artifact.id), "stable")
        path.write_text("modified", encoding="utf-8")
        with self.assertRaises(ArtifactCorruptionFailure):
            self.store.read_artifact(artifact.id)
        second = self.store.create_generation_intent(
            workflow.id, Stage.PRD, request_hash="hash-2", artifact_path=path
        )
        with self.assertRaises(ConflictFailure):
            self.store.complete_generation(second.operation.idempotency_key, content="x", artifact_path=path,
                                           stage=Stage.PRD, revision=2)

    def test_events_are_monotonic_and_sanitized(self):
        workflow = self.store.create_workflow(
            "/repo",
            configuration_snapshot={
                "api_token": "TOP-SECRET",
                "environment": {"PATH": "C:/sensitive-runtime-path"},
            },
        )
        self.store.append_event(
            workflow.id,
            "diagnostic.environment",
            payload={
                "env": {"PATH": "C:/event-path"},
                "nested": {"ENVIRONMENT": {"HOME": "C:/event-home"}},
                "input_tokens": 101,
            },
        )
        intent = self.store.create_generation_intent(
            workflow.id,
            Stage.PRD,
            request_hash="hash",
            capability_report={
                "password": "TOP-SECRET",
                "environment": {"HOME": "C:/capability-home"},
                "cached_input_tokens": 202,
            },
        )
        self.store.complete_generation(intent.operation.idempotency_key, content="content", stage=Stage.PRD,
                                       revision=1, artifact_path=Path(self.temp_dir.name) / "workflows" / workflow.id
                                       / "artifacts" / "001-prd.md",
            terminal_result={
                "stderr": "token=TOP-SECRET",
                "env": {"SHELL": "C:/terminal-shell"},
                "nested": {"environment": {"TEMP": "C:/terminal-temp"}},
                "output_tokens": 303,
            })
        events = self.store.list_events(workflow.id)
        self.assertEqual([event.sequence for event in events], list(range(1, len(events) + 1)))
        encoded = json.dumps([event.payload for event in events])
        self.assertNotIn("TOP-SECRET", encoded)
        for environment_value in (
            "C:/event-path",
            "C:/event-home",
            "C:/capability-home",
            "C:/terminal-shell",
            "C:/terminal-temp",
        ):
            self.assertNotIn(environment_value, encoded)
        self.assertNotIn('"env"', encoded)
        self.assertNotIn('"ENVIRONMENT"', encoded)
        self.assertNotIn('"environment"', encoded)
        self.assertNotIn("environment", json.dumps(intent.execution.capability_report))
        self.assertNotIn("C:/capability-home", json.dumps(intent.execution.capability_report))
        execution = self.store.get_execution(intent.execution.id)
        self.assertNotIn("env", json.dumps(execution.terminal_result))
        self.assertNotIn("environment", json.dumps(execution.terminal_result))
        self.assertNotIn("C:/terminal-shell", json.dumps(execution.terminal_result))
        diagnostic_event = next(event for event in events if event.type == "diagnostic.environment")
        self.assertEqual(diagnostic_event.payload["input_tokens"], 101)
        self.assertEqual(intent.execution.capability_report["cached_input_tokens"], 202)
        self.assertEqual(execution.terminal_result["output_tokens"], 303)
        self.assertEqual(self.store.get_workflow(workflow.id).configuration_snapshot["api_token"], "[REDACTED]")
        self.assertNotIn("environment", self.store.get_workflow(workflow.id).configuration_snapshot)
        self.assertNotIn("C:/sensitive-runtime-path", json.dumps(
            self.store.get_workflow(workflow.id).configuration_snapshot
        ))

    def test_foreign_keys_reject_orphan_records(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._connection.execute(
                "INSERT INTO artifacts (id, workflow_id, stage, revision, path, sha256, approval_state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("a", "missing", "prd", 1, "x", "0" * 64, "pending", "now"),
            )

    def test_canonical_lifecycle_scope_evidence_and_operation_replay_are_durable(self):
        workflow = self.store.create_workflow("/repo")
        scope = self.store.create_scope(workflow.id, ScopeKind.WAVE, "3")
        fingerprint = hashlib.sha256(b"request").hexdigest()
        state = self.store.record_lifecycle_state(
            workflow.id, lifecycle_version=LifecycleVersion.CANONICAL_V1,
            stage=CanonicalStage.TASK_PLAN, status=WorkflowStatus.RUNNING,
            operation_key="lifecycle:1", request_fingerprint=fingerprint, scope_id=scope.id,
        )
        self.assertEqual(state.lifecycle_version, LifecycleVersion.CANONICAL_V1)
        replay = self.store.record_lifecycle_state(
            workflow.id, lifecycle_version=LifecycleVersion.CANONICAL_V1,
            stage=CanonicalStage.TASK_PLAN, status=WorkflowStatus.RUNNING,
            operation_key="lifecycle:1", request_fingerprint=fingerprint, scope_id=scope.id,
        )
        self.assertEqual(replay.created_at, state.created_at)
        with self.assertRaises(ConflictFailure):
            self.store.record_lifecycle_state(workflow.id, lifecycle_version=LifecycleVersion.CANONICAL_V1,
                                              stage=CanonicalStage.TASK_PLAN, status=WorkflowStatus.RUNNING,
                                              operation_key="lifecycle:1", request_fingerprint="0" * 64)
        result = self.store.record_capability_result(
            workflow.id, operation_key="capability:1", request_fingerprint=fingerprint,
            result={"decision": "recorded"}, scope_id=scope.id, evidence_reference="docs/evidence.md",
            evidence_sha256=hashlib.sha256(b"evidence").hexdigest(),
        )
        self.assertEqual(result.status.value, "completed")
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM evidence_references").fetchone()[0], 1)

    def test_migration_records_explicit_canonical_contract_and_replays(self):
        workflow = self.store.create_workflow("/repo")
        receipt = self.store.migrate_historical_workflow(
            workflow.id, operation_key="migration:success", canonical_stage=CanonicalStage.PRD,
        )
        self.assertEqual(receipt.outcome.value, "completed")
        state = self.store.get_lifecycle_state(workflow.id)
        self.assertEqual((state.lifecycle_version, state.stage, state.status),
                         (LifecycleVersion.CANONICAL_V1, CanonicalStage.PRD, WorkflowStatus.CREATED))
        self.assertEqual(receipt.id, self.store.migrate_historical_workflow(
            workflow.id, operation_key="migration:success", canonical_stage=CanonicalStage.PRD,
        ).id)
        with self.assertRaises(ConflictFailure):
            self.store.migrate_historical_workflow(
                workflow.id, operation_key="migration:success", canonical_stage=CanonicalStage.TECHSPEC,
            )

    def test_migration_attention_outcomes_preserve_historical_workflow(self):
        workflow = self.store.create_workflow("/repo")
        receipt = self.store.migrate_historical_workflow(
            workflow.id, operation_key="migration:1", valid=False,
            attention_outcome=HumanAttentionOutcome.AMBIGUOUS_MIGRATION,
            detail="ambiguous legacy input",
        )
        self.assertEqual(receipt.outcome.value, "ambiguous")
        self.assertEqual(self.store.get_workflow(workflow.id).stage, Stage.PRD)
        state = self.store.get_lifecycle_state(workflow.id)
        self.assertEqual((state.lifecycle_version, state.status),
                         (LifecycleVersion.HISTORICAL, WorkflowStatus.HUMAN_ATTENTION))
        self.assertEqual(receipt.id, self.store.migrate_historical_workflow(
            workflow.id, operation_key="migration:1", valid=False,
            attention_outcome=HumanAttentionOutcome.AMBIGUOUS_MIGRATION,
            detail="ambiguous legacy input",
        ).id)
        for attention_outcome, expected in (
            (HumanAttentionOutcome.PARTIAL_MIGRATION, "partial"),
            (HumanAttentionOutcome.MIGRATION_FAILED, "failed"),
        ):
            additional = self.store.create_workflow("/repo")
            self.assertEqual(self.store.migrate_historical_workflow(
                additional.id, operation_key=f"migration:{expected}", valid=False,
                attention_outcome=attention_outcome,
            ).outcome.value, expected)
        unknown = self.store.record_capability_result(
            workflow.id, operation_key="capability:unknown", request_fingerprint=hashlib.sha256(b"unknown").hexdigest(),
            result=None, attention_outcome=HumanAttentionOutcome.UNKNOWN_OUTCOME,
        )
        self.assertEqual(unknown.status.value, "unknown")

    def _governance_fingerprint(self, workflow_id, scope_id, decision_type, decision, actor, evidence,
                                predecessors=(), affected=()):
        contract = {
            "workflow_id": workflow_id, "scope_id": scope_id, "lifecycle_version": "canonical-v1",
            "decision_type": decision_type.value, "decision": decision.value, "actor": actor,
            "evidence": tuple(sorted(evidence.items())), "predecessor_ids": tuple(predecessors),
            "affected_ids": tuple(affected),
        }
        return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _record_governance_evidence(self, workflow_id, reference, digest, *, scope_id=None):
        self.store.record_capability_result(
            workflow_id,
            operation_key=f"evidence:{reference}:{scope_id or 'workflow'}",
            request_fingerprint=hashlib.sha256(
                f"{reference}:{digest}:{scope_id}".encode()
            ).hexdigest(),
            result={"evidence": "recorded"},
            scope_id=scope_id,
            evidence_reference=reference,
            evidence_sha256=digest,
        )

    def test_governance_facts_are_complete_exact_and_replay_safe(self):
        workflow = self.store.create_workflow("/repo")
        scope = self.store.create_scope(workflow.id, ScopeKind.WAVE, "3")
        evidence = {"docs/wave-review.md": hashlib.sha256(b"review").hexdigest()}
        self._record_governance_evidence(workflow.id, *next(iter(evidence.items())), scope_id=scope.id)
        fingerprint = self._governance_fingerprint(
            workflow.id, scope.id, GovernanceDecisionType.WAVE_ACCEPTANCE,
            GovernanceDecision.ACCEPTED, "reviewer:42", evidence,
        )
        record = self.store.record_governance_decision(
            workflow.id, scope_id=scope.id, lifecycle_version=LifecycleVersion.CANONICAL_V1,
            operation_key="decision:wave:accept", request_fingerprint=fingerprint,
            decision_type=GovernanceDecisionType.WAVE_ACCEPTANCE,
            decision=GovernanceDecision.ACCEPTED, actor="reviewer:42", evidence=evidence,
        )
        self.assertEqual(record.evidence, tuple(sorted(evidence.items())))
        self.assertEqual(record.id, self.store.record_decision(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", operation_key="decision:wave:accept",
            request_fingerprint=fingerprint, decision_type="wave_acceptance", decision="accepted",
            actor="reviewer:42", evidence=evidence,
        ).id)
        self.assertTrue(self.store.active_authority(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", decision_type="wave_acceptance"
        ).active)
        duplicate_fingerprint = self._governance_fingerprint(
            workflow.id, scope.id, GovernanceDecisionType.WAVE_ACCEPTANCE,
            GovernanceDecision.ACCEPTED, "reviewer:43", evidence,
        )
        self.store.record_decision(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", operation_key="decision:wave:accept:2",
            request_fingerprint=duplicate_fingerprint, decision_type="wave_acceptance", decision="accepted",
            actor="reviewer:43", evidence=evidence,
        )
        duplicate = self.store.active_authority(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", decision_type="wave_acceptance"
        )
        self.assertFalse(duplicate.active)
        self.assertTrue(duplicate.attention_required)
        with self.assertRaises(ValidationFailure):
            self.store.record_decision(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", operation_key="bad",
                request_fingerprint="0" * 64, decision_type="delivery_authorization", decision="authorized",
                actor="operator", evidence={},
            )

    def test_revocation_invalidates_only_dependent_authority_and_preserves_history(self):
        workflow = self.store.create_workflow("/repo")
        wave = self.store.create_scope(workflow.id, ScopeKind.WAVE, "3")
        release = self.store.create_scope(workflow.id, ScopeKind.RELEASE, "r1")
        wave_evidence = {"docs/wave-evidence.md": hashlib.sha256(b"wave evidence").hexdigest()}
        release_evidence = {"docs/release-evidence.md": hashlib.sha256(b"release evidence").hexdigest()}
        self._record_governance_evidence(
            workflow.id, *next(iter(wave_evidence.items())), scope_id=wave.id
        )
        self._record_governance_evidence(
            workflow.id, *next(iter(release_evidence.items())), scope_id=release.id
        )

        def record(key, scope, kind, decision, evidence, predecessors=(), affected=()):
            return self.store.record_decision(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", operation_key=key,
                request_fingerprint=self._governance_fingerprint(workflow.id, scope.id, kind, decision, "human:1", evidence, predecessors, affected),
                decision_type=kind, decision=decision, actor="human:1", evidence=evidence,
                predecessor_ids=predecessors, affected_ids=affected,
            )
        acceptance = record("accept", wave, GovernanceDecisionType.WAVE_ACCEPTANCE, GovernanceDecision.ACCEPTED, wave_evidence)
        authorization = record("authorize", release, GovernanceDecisionType.DELIVERY_AUTHORIZATION,
                               GovernanceDecision.AUTHORIZED, release_evidence, (acceptance.id,))
        unrelated = record("unrelated", release, GovernanceDecisionType.APPROVAL, GovernanceDecision.APPROVED, release_evidence)
        record("revoke", wave, GovernanceDecisionType.REVOCATION, GovernanceDecision.REVOKED,
               wave_evidence, affected=(acceptance.id,))
        self.assertFalse(self.store.active_authority(workflow.id, scope_id=wave.id, lifecycle_version="canonical-v1", decision_type="wave_acceptance").active)
        self.assertFalse(self.store.active_authority(workflow.id, scope_id=release.id, lifecycle_version="canonical-v1", decision_type="delivery_authorization").active)
        self.assertTrue(self.store.active_authority(workflow.id, scope_id=release.id, lifecycle_version="canonical-v1", decision_type="approval").active)
        self.assertEqual(len(self.store.list_governance_decisions(workflow.id)), 4)
        self.assertIn("governance.decision.recorded", [event.type for event in self.store.list_events(workflow.id)])

    def test_invalid_supersession_does_not_withdraw_valid_authority(self):
        workflow = self.store.create_workflow("/repo")
        scope = self.store.create_scope(workflow.id, ScopeKind.WAVE, "3")
        evidence = {"docs/wave-review.md": hashlib.sha256(b"review").hexdigest()}
        self._record_governance_evidence(
            workflow.id, *next(iter(evidence.items())), scope_id=scope.id
        )

        acceptance = self.store.record_decision(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1",
            operation_key="accept", request_fingerprint=self._governance_fingerprint(
                workflow.id, scope.id, GovernanceDecisionType.WAVE_ACCEPTANCE,
                GovernanceDecision.ACCEPTED, "reviewer:42", evidence,
            ), decision_type="wave_acceptance", decision="accepted", actor="reviewer:42",
            evidence=evidence,
        )
        invalid_evidence = {"not-recorded.md": "0" * 64}
        self.store.record_decision(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1",
            operation_key="supersede", request_fingerprint=self._governance_fingerprint(
                workflow.id, scope.id, GovernanceDecisionType.SUPERSESSION,
                GovernanceDecision.SUPERSEDED, "reviewer:42", invalid_evidence,
                affected=(acceptance.id,),
            ), decision_type="supersession", decision="superseded", actor="reviewer:42",
            evidence=invalid_evidence, affected_ids=(acceptance.id,),
        )

        authority = self.store.active_authority(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1",
            decision_type="wave_acceptance",
        )
        self.assertTrue(authority.active)
        self.assertEqual(authority.record.id, acceptance.id)

    def test_revoked_or_superseded_predecessor_cannot_authorize_new_downstream_fact(self):
        workflow = self.store.create_workflow("/repo")
        wave = self.store.create_scope(workflow.id, ScopeKind.WAVE, "3")
        release = self.store.create_scope(workflow.id, ScopeKind.RELEASE, "r1")
        wave_evidence = {"docs/wave-evidence.md": hashlib.sha256(b"wave evidence").hexdigest()}
        release_evidence = {"docs/release-evidence.md": hashlib.sha256(b"release evidence").hexdigest()}
        self._record_governance_evidence(workflow.id, *next(iter(wave_evidence.items())), scope_id=wave.id)
        self._record_governance_evidence(workflow.id, *next(iter(release_evidence.items())), scope_id=release.id)

        def record(key, scope, kind, decision, evidence, predecessors=(), affected=()):
            return self.store.record_decision(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", operation_key=key,
                request_fingerprint=self._governance_fingerprint(
                    workflow.id, scope.id, kind, decision, "human:1", evidence, predecessors, affected,
                ),
                decision_type=kind, decision=decision, actor="human:1", evidence=evidence,
                predecessor_ids=predecessors, affected_ids=affected,
            )

        for action, decision in (("revoke", GovernanceDecision.REVOKED), ("supersede", GovernanceDecision.SUPERSEDED)):
            acceptance = record(
                f"accept:{action}", wave, GovernanceDecisionType.WAVE_ACCEPTANCE,
                GovernanceDecision.ACCEPTED, wave_evidence,
            )
            record(
                action, wave,
                GovernanceDecisionType.REVOCATION if action == "revoke" else GovernanceDecisionType.SUPERSESSION,
                decision, wave_evidence, affected=(acceptance.id,),
            )
            record(
                f"authorize:{action}", release, GovernanceDecisionType.DELIVERY_AUTHORIZATION,
                GovernanceDecision.AUTHORIZED, release_evidence, predecessors=(acceptance.id,),
            )
            authority = self.store.active_authority(
                workflow.id, scope_id=release.id, lifecycle_version="canonical-v1",
                decision_type="delivery_authorization",
            )
            self.assertFalse(authority.active)

    def test_active_authority_requires_recorded_matching_completed_evidence(self):
        workflow = self.store.create_workflow("/repo")
        scope = self.store.create_scope(workflow.id, ScopeKind.WAVE, "3")
        digest = hashlib.sha256(b"review").hexdigest()
        evidence = {"docs/wave-review.md": digest}
        self._record_governance_evidence(workflow.id, *next(iter(evidence.items())), scope_id=scope.id)

        def record(key, supplied_evidence):
            self.store.record_decision(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", operation_key=key,
                request_fingerprint=self._governance_fingerprint(
                    workflow.id, scope.id, GovernanceDecisionType.WAVE_ACCEPTANCE,
                    GovernanceDecision.ACCEPTED, "reviewer:42", supplied_evidence,
                ),
                decision_type="wave_acceptance", decision="accepted", actor="reviewer:42",
                evidence=supplied_evidence,
            )

        record("decision:missing-evidence", {"missing/evidence.md": "0" * 64})
        evaluation = self.store.active_authority(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", decision_type="wave_acceptance",
        )
        self.assertFalse(evaluation.active)
        self.assertTrue(evaluation.attention_required)
        self.assertEqual(evaluation.reason, "invalid authority evidence")

        # A stored reference with a different digest is not interchangeable evidence.
        record("decision:mismatched-evidence", {"docs/wave-review.md": "0" * 64})
        evaluation = self.store.active_authority(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", decision_type="wave_acceptance",
        )
        self.assertFalse(evaluation.active)
        self.assertTrue(evaluation.attention_required)

    def test_active_authority_fails_closed_for_mixed_validity_evidence(self):
        workflow = self.store.create_workflow("/repo")
        scope = self.store.create_scope(workflow.id, ScopeKind.WAVE, "3")
        evidence = {"docs/wave-review.md": hashlib.sha256(b"review").hexdigest()}
        self._record_governance_evidence(workflow.id, *next(iter(evidence.items())), scope_id=scope.id)

        def record(key, supplied_evidence):
            self.store.record_decision(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", operation_key=key,
                request_fingerprint=self._governance_fingerprint(
                    workflow.id, scope.id, GovernanceDecisionType.WAVE_ACCEPTANCE,
                    GovernanceDecision.ACCEPTED, "reviewer:42", supplied_evidence,
                ),
                decision_type="wave_acceptance", decision="accepted", actor="reviewer:42",
                evidence=supplied_evidence,
            )

        record("decision:valid-evidence", evidence)
        record("decision:missing-evidence", {"missing/evidence.md": "0" * 64})
        evaluation = self.store.active_authority(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", decision_type="wave_acceptance",
        )
        self.assertFalse(evaluation.active)
        self.assertTrue(evaluation.attention_required)
        self.assertEqual(evaluation.reason, "invalid authority evidence")

    def test_active_authority_fails_closed_for_mixed_validity_lineage(self):
        workflow = self.store.create_workflow("/repo")
        scope = self.store.create_scope(workflow.id, ScopeKind.WAVE, "3")
        evidence = {"docs/wave-review.md": hashlib.sha256(b"review").hexdigest()}
        self._record_governance_evidence(workflow.id, *next(iter(evidence.items())), scope_id=scope.id)

        def record(key, decision_type, decision, predecessors=()):
            return self.store.record_decision(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", operation_key=key,
                request_fingerprint=self._governance_fingerprint(
                    workflow.id, scope.id, decision_type, decision, "reviewer:42", evidence, predecessors,
                ),
                decision_type=decision_type, decision=decision, actor="reviewer:42", evidence=evidence,
                predecessor_ids=predecessors,
            )

        predecessor = record("decision:predecessor", GovernanceDecisionType.APPROVAL, GovernanceDecision.APPROVED)
        record("decision:invalid-lineage", GovernanceDecisionType.WAVE_ACCEPTANCE,
               GovernanceDecision.ACCEPTED, (predecessor.id,))
        record("decision:valid-lineage", GovernanceDecisionType.WAVE_ACCEPTANCE,
               GovernanceDecision.ACCEPTED)
        # Simulate legacy/inconsistent persisted eligibility: evaluation must
        # still fail closed rather than return the valid sibling.
        with self.store._transaction() as connection:
            connection.execute(
                "UPDATE governance_eligibility SET eligible = 0 WHERE decision_id = ?", (predecessor.id,)
            )
        evaluation = self.store.active_authority(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", decision_type="wave_acceptance",
        )
        self.assertFalse(evaluation.active)
        self.assertTrue(evaluation.attention_required)
        self.assertEqual(evaluation.reason, "invalid authority lineage")

    def test_active_authority_requires_evidence_at_the_exact_scope(self):
        workflow = self.store.create_workflow("/repo")
        scope = self.store.create_scope(workflow.id, ScopeKind.WAVE, "3")
        workflow_evidence = {"docs/workflow-review.md": hashlib.sha256(b"workflow review").hexdigest()}
        self._record_governance_evidence(workflow.id, *next(iter(workflow_evidence.items())))

        def record(key, evidence):
            self.store.record_decision(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", operation_key=key,
                request_fingerprint=self._governance_fingerprint(
                    workflow.id, scope.id, GovernanceDecisionType.WAVE_ACCEPTANCE,
                    GovernanceDecision.ACCEPTED, "reviewer:42", evidence,
                ),
                decision_type="wave_acceptance", decision="accepted", actor="reviewer:42",
                evidence=evidence,
            )

        record("decision:workflow-evidence", workflow_evidence)
        evaluation = self.store.active_authority(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", decision_type="wave_acceptance",
        )
        self.assertFalse(evaluation.active)
        self.assertTrue(evaluation.attention_required)
        self.assertEqual(evaluation.reason, "invalid authority evidence")

        scoped_evidence = {"docs/wave-review.md": hashlib.sha256(b"wave review").hexdigest()}
        self._record_governance_evidence(
            workflow.id, *next(iter(scoped_evidence.items())), scope_id=scope.id
        )
        record("decision:wave-evidence", scoped_evidence)
        evaluation = self.store.active_authority(
            workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", decision_type="wave_acceptance",
        )
        self.assertFalse(evaluation.active)
        self.assertTrue(evaluation.attention_required)
        self.assertEqual(evaluation.reason, "invalid authority evidence")

    def test_governance_decision_type_requires_its_matching_status(self):
        workflow = self.store.create_workflow("/repo")
        scope = self.store.create_scope(workflow.id, ScopeKind.WAVE, "3")
        evidence = {"docs/governance.md": hashlib.sha256(b"governance").hexdigest()}
        self._record_governance_evidence(workflow.id, *next(iter(evidence.items())), scope_id=scope.id)

        permitted = {
            GovernanceDecisionType.APPROVAL: GovernanceDecision.APPROVED,
            GovernanceDecisionType.REJECTION: GovernanceDecision.REJECTED,
            GovernanceDecisionType.WAVE_ACCEPTANCE: GovernanceDecision.ACCEPTED,
            GovernanceDecisionType.RELEASE_ACCEPTANCE: GovernanceDecision.ACCEPTED,
            GovernanceDecisionType.WAVE_START_AUTHORIZATION: GovernanceDecision.AUTHORIZED,
            GovernanceDecisionType.DELIVERY_AUTHORIZATION: GovernanceDecision.AUTHORIZED,
        }
        records = {}
        for index, (decision_type, decision) in enumerate(permitted.items()):
            records[decision_type] = self.store.record_decision(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1",
                operation_key=f"decision:valid:{index}",
                request_fingerprint=self._governance_fingerprint(
                    workflow.id, scope.id, decision_type, decision, "human:1", evidence,
                ),
                decision_type=decision_type, decision=decision, actor="human:1", evidence=evidence,
            )
        for decision_type in permitted:
            evaluation = self.store.active_authority(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", decision_type=decision_type,
            )
            self.assertEqual(evaluation.active, decision_type is not GovernanceDecisionType.REJECTION)
        for decision_type in (
            GovernanceDecisionType.REVOCATION, GovernanceDecisionType.SUPERSESSION,
        ):
            decision = (GovernanceDecision.REVOKED if decision_type is GovernanceDecisionType.REVOCATION
                        else GovernanceDecision.SUPERSEDED)
            record = self.store.record_decision(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1",
                operation_key=f"decision:valid:{decision_type.value}",
                request_fingerprint=self._governance_fingerprint(
                    workflow.id, scope.id, decision_type, decision, "human:1", evidence,
                    affected=(records[GovernanceDecisionType.APPROVAL].id,),
                ),
                decision_type=decision_type, decision=decision, actor="human:1", evidence=evidence,
                affected_ids=(records[GovernanceDecisionType.APPROVAL].id,),
            )
            self.assertEqual(record.decision, decision)

        active_types = set(permitted) - {
            GovernanceDecisionType.APPROVAL, GovernanceDecisionType.REJECTION,
        }
        for decision_type in permitted:
            evaluation = self.store.active_authority(
                workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1", decision_type=decision_type,
            )
            self.assertEqual(evaluation.active, decision_type in active_types)

        valid_pairs = {
            **permitted,
            GovernanceDecisionType.REVOCATION: GovernanceDecision.REVOKED,
            GovernanceDecisionType.SUPERSESSION: GovernanceDecision.SUPERSEDED,
        }
        for index, (decision_type, valid_decision) in enumerate(valid_pairs.items()):
            invalid_decision = next(decision for decision in GovernanceDecision if decision is not valid_decision)
            count = len(self.store.list_governance_decisions(workflow.id))
            with self.assertRaisesRegex(ValidationFailure, "must match its decision type"):
                self.store.record_decision(
                    workflow.id, scope_id=scope.id, lifecycle_version="canonical-v1",
                    operation_key=f"decision:invalid:{index}",
                    request_fingerprint=self._governance_fingerprint(
                        workflow.id, scope.id, decision_type, invalid_decision, "human:1", evidence,
                    ),
                    decision_type=decision_type, decision=invalid_decision, actor="human:1", evidence=evidence,
                )
            self.assertEqual(len(self.store.list_governance_decisions(workflow.id)), count)


if __name__ == "__main__":
    unittest.main()
