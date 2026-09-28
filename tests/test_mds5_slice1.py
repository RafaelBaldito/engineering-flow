import json
import unittest
from unittest import mock

from engineering_flow.domain import ValidationFailure
from engineering_flow.review import (ReviewPreflightResolver, parse_reviewer_result,
                                     validate_repository_relative_path)
from engineering_flow.verification import DeterministicVerificationOrchestrator
from tests import test_mds4_slice3 as mds4


class Mds5Slice1Tests(unittest.TestCase):
    setUp = mds4.Mds4Slice3RunnerTests.setUp
    tearDown = mds4.Mds4Slice3RunnerTests.tearDown
    prepare = mds4.Mds4Slice3RunnerTests.prepare

    def verified(self):
        workflow, preflight, orchestrator = self.prepare([["/bin/true"]])
        self.assertEqual(orchestrator.run(preflight).value, "verified")
        return workflow, preflight

    def resolver(self):
        return ReviewPreflightResolver(self.store.load_approved_v2_plan_authority,
            self.store.load_successful_implementation_producer, self.store.load_verified_review_evidence)

    def test_resolves_exact_verified_authority_and_hashes_deterministically_without_execution_or_writes(self):
        workflow, verification = self.verified()
        before = self.store._connection.total_changes
        with mock.patch.object(DeterministicVerificationOrchestrator, "run", side_effect=AssertionError("dispatch")):
            first = self.resolver().resolve(workflow.id, task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
            second = self.resolver().resolve(workflow.id, task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(first.request_hash, second.request_hash)
        self.assertEqual(first.authority_sha256, second.authority_sha256)
        self.assertEqual(len(first.request_hash), 64)
        self.assertEqual(self.store._connection.total_changes, before)

    def test_rejects_stale_mismatched_and_incomplete_verified_evidence(self):
        workflow, verification = self.verified()
        args = dict(task_contract_id=verification.producer.task_contract_id,
            task_contract_sha256=verification.producer.task_contract_sha256)
        self.store._connection.execute("UPDATE verification_attempts SET authority_sha256=?", ("0" * 64,))
        with self.assertRaisesRegex(ValidationFailure, "stale|inconsistent"):
            self.resolver().resolve(workflow.id, **args)
        self.store._connection.execute("UPDATE verification_attempts SET authority_sha256=?", (verification.authority_sha256,))
        self.store._connection.execute("DELETE FROM verification_command_results")
        with self.assertRaisesRegex(ValidationFailure, "incomplete"):
            self.resolver().resolve(workflow.id, **args)

    def test_rejects_verified_attempt_with_mismatched_implement_producer(self):
        workflow, verification = self.verified()
        self.store._connection.execute("UPDATE verification_attempts SET producer_operation_id=operation_id")
        with self.assertRaisesRegex(ValidationFailure, "missing|producer"):
            self.resolver().resolve(workflow.id, task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)

    def test_rejects_nonverified_projection_before_any_provider_boundary(self):
        workflow, verification = self.verified()
        self.store._connection.execute("UPDATE workflows SET status='verification_failed' WHERE id=?", (workflow.id,))
        calls = []
        resolver = ReviewPreflightResolver(lambda _: calls.append("authority") or self.store.load_approved_v2_plan_authority(workflow.id),
            lambda *args: calls.append("producer"), lambda *args: calls.append("evidence"))
        with self.assertRaises(ValidationFailure):
            resolver.resolve(workflow.id, task_contract_id=verification.producer.task_contract_id,
                task_contract_sha256=verification.producer.task_contract_sha256)
        self.assertEqual(calls, ["authority"])

    def test_strict_reviewer_payload_and_hash(self):
        valid = {"outcome": "CHANGES_REQUESTED", "summary": "Fix the guard.", "findings": [{
            "id": "R-1", "severity": "blocking", "category": "correctness",
            "description": "A boundary is missing.", "path": "src/engineering_flow/review.py",
            "line": 1, "requirement_reference": "acceptance 1"}]}
        parsed = parse_reviewer_result(json.dumps(valid))
        self.assertEqual(parsed.sha256(), parse_reviewer_result(valid).sha256())
        invalid = [
            {**valid, "extra": True},
            {**valid, "outcome": "REVIEW_PASSED"},
            {**valid, "findings": [{**valid["findings"][0], "severity": "fatal"}]},
            {**valid, "findings": [{**valid["findings"][0], "line": 0}]},
            {**valid, "findings": [{**valid["findings"][0], "id": ""}]},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValidationFailure): parse_reviewer_result(value)
        with self.assertRaises(ValidationFailure):
            parse_reviewer_result('{"outcome":"REVIEW_PASSED","outcome":"REVIEW_PASSED","summary":"ok","findings":[]}')

    def test_invalid_finding_paths_fail_closed(self):
        for path in ("/etc/passwd", "../secret", "src/../../secret", "src\\secret", "", "."):
            with self.subTest(path=path), self.assertRaises(ValidationFailure):
                validate_repository_relative_path(path)
