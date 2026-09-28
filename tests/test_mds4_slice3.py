import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from engineering_flow.domain import (ApprovalDecision, ApprovalState, DomainFailure,
    LifecycleVersion, Stage, VerificationOutcome, WorkflowStatus)
from engineering_flow.repository import RepositoryInspector
from engineering_flow.store import WorkflowStore
from engineering_flow.verification import (DeterministicVerificationOrchestrator,
    DeterministicVerificationPreflight, VerificationCommandRunner)
from engineering_flow.process_identity import local_host_boot_identity


def git(root, *args):
    return subprocess.run(("git", "-C", str(root), *args), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


class Mds4Slice3RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"; self.root.mkdir()
        git(self.root, "init", "-q"); git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "Test")
        (self.root / ".gitignore").write_text(".engineering-flow/workflows.sqlite3*\n.engineering-flow/verification-runtime/\n")
        (self.root / "source.py").write_text("before\n")
        self.store = None

    def tearDown(self):
        if self.store:
            self.store.close()
        self.temp.cleanup()

    def prepare(self, commands, *, output_limit=65536):
        manifest = self.root / ".engineering-flow" / "verification" / "manifest-v1.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"version": 1, "commands": [
            {"id": f"c{index}", "argv": command, "timeout_seconds": 1}
            for index, command in enumerate(commands, 1)]}))
        git(self.root, "add", "."); git(self.root, "commit", "-qm", "initial")
        self.store = WorkflowStore(self.root / ".engineering-flow" / "workflows.sqlite3")
        workflow = self.store.create_workflow(self.root, provider="fake", lifecycle_version=LifecycleVersion.V2, stage=Stage.INTAKE)
        feature_intent = self.store.create_generation_intent(workflow.id, Stage.INTAKE, request_hash="feature", provider="fake", role="intake", revision=1, artifact_path=self.store.feature_contract_path(workflow.id, 1))
        feature = self.store.complete_generation(feature_intent.operation.idempotency_key,
            content=json.dumps({"outcome":"READY", "feature":{"id":workflow.id,"goal":"g","requirements":["r"],"acceptance_criteria":["a"],"constraints":[],"out_of_scope":[],"assumptions":[],"open_questions":[]}}),
            artifact_path=self.store.feature_contract_path(workflow.id, 1), stage=Stage.INTAKE, revision=1,
            workflow_stage=Stage.INTAKE, workflow_status=WorkflowStatus.READY, approval_state=ApprovalState.NOT_REQUIRED)
        plan_intent = self.store.create_generation_intent(workflow.id, Stage.PLAN, request_hash="plan", provider="fake", role="planner", revision=1, artifact_path=self.store.plan_path(workflow.id, 1))
        task = {"id":"T1", "objective":"one", "context":{"relevant_files":["source.py"],"existing_patterns":[]}, "requirements":["r"], "acceptance_criteria":["a"], "verification":["test"], "constraints":[], "depends_on":[], "complexity":"low", "risk":"low"}
        plan = self.store.complete_generation(plan_intent.operation.idempotency_key,
            content=json.dumps({"plan":{"id":f"{workflow.id}:plan:r1", "workflow_id":workflow.id, "revision":1, "feature_contract":{"artifact_id":feature.id,"sha256":feature.sha256}, "strategy":"s", "assumptions":[], "verification_strategy":["test"], "tasks":[task]}}),
            artifact_path=self.store.plan_path(workflow.id, 1), stage=Stage.PLAN, revision=1,
            workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.AWAITING_APPROVAL)
        self.store.record_approval(workflow.id, plan.id, ApprovalDecision.APPROVED, actor="human", workflow_stage=Stage.PLAN, workflow_status=WorkflowStatus.PLAN_APPROVED)
        contract = self.store.load_approved_v2_plan_authority(workflow.id).plan.tasks[0]
        inspector = RepositoryInspector(self.root)
        implementation = self.store.create_implementation_intent(workflow.id, repository_key=inspector.repository_key(), canonical_root=str(self.root), task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), request_hash="i" * 64, baseline=inspector.capture().as_payload(), owner_instance_id="implement", owner_pid=os.getpid(), owner_host_id="host")
        (self.root / "source.py").write_text("implemented\n")
        self.store.finish_implementation_attempt(implementation["attempt_id"], implementation["lease_id"], status="succeeded", classification="completed_changed", final=inspector.capture().as_payload(), workspace_changed=True, owner_instance_id="implement")
        preflight = DeterministicVerificationPreflight(self.root, self.store.load_approved_v2_plan_authority, self.store.load_successful_implementation_producer).validate(workflow.id, task_contract_id=contract.id, task_contract_sha256=contract.payload_sha256(), producer_operation_id=implementation["operation_id"])
        return workflow, preflight, DeterministicVerificationOrchestrator(self.store, self.root, runner=VerificationCommandRunner(self.root, output_limit_bytes=output_limit), owner_instance_id="runner")

    def run_commands(self, commands, **kwargs):
        workflow, preflight, orchestrator = self.prepare(commands, **kwargs)
        return workflow, orchestrator.run(preflight)

    def test_successful_multi_command_execution_is_sequential_and_releases_lease(self):
        log = Path(self.temp.name) / "order"
        commands = [[sys.executable, "-c", f"from pathlib import Path; Path({str(log)!r}).write_text('one')"],
                    [sys.executable, "-c", f"from pathlib import Path; assert Path({str(log)!r}).read_text() == 'one'; Path({str(log)!r}).write_text('one two')"]]
        workflow, outcome = self.run_commands(commands)
        self.assertEqual(outcome, VerificationOutcome.VERIFIED); self.assertEqual(log.read_text(), "one two")
        rows = self.store._connection.execute("SELECT ordinal,result_at FROM verification_command_results ORDER BY ordinal").fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2]); self.assertTrue(all(row[1] for row in rows))
        self.assertIsNone(self.store.active_workspace_operation_lease(RepositoryInspector(self.root).repository_key()))
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.TASK_VERIFIED)

    def test_nonzero_stops_after_first_command(self):
        marker = self.root / "should-not-run"
        workflow, outcome = self.run_commands([[sys.executable, "-c", "import sys; sys.exit(3)"], [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('bad')"]])
        self.assertEqual(outcome, VerificationOutcome.VERIFICATION_FAILED); self.assertFalse(marker.exists())
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM verification_command_results").fetchone()[0], 1)
    def test_timeout_stops_execution(self):
        workflow, outcome = self.run_commands([[sys.executable, "-c", "import time; time.sleep(3)"]])
        self.assertEqual(outcome, VerificationOutcome.VERIFICATION_FAILED)
        row = self.store._connection.execute("SELECT timed_out FROM verification_command_results").fetchone()
        self.assertEqual(row[0], 1)

    def test_stdout_stderr_and_bounded_output_are_captured(self):
        runner = VerificationCommandRunner(self.root, output_limit_bytes=5)
        from engineering_flow.verification import VerificationCommand
        result = runner.run(VerificationCommand("out", (sys.executable, "-c", "import sys; print('abcdefgh'); print('ijklmnop', file=sys.stderr)"), 1), runtime_directory=Path(self.temp.name) / "runtime")
        self.assertIn(b"abcde", result.stdout); self.assertIn(b"ijklm", result.stderr)
        self.assertTrue(result.output_truncated); self.assertGreater(result.output_bytes, len(result.stdout) + len(result.stderr))

    def test_protected_repository_mutation_is_unknown_and_result_is_persisted(self):
        workflow, outcome = self.run_commands([[sys.executable, "-c", "from pathlib import Path; Path('source.py').write_text('mutated')"]])
        self.assertEqual(outcome, VerificationOutcome.VERIFICATION_UNKNOWN)
        row = self.store._connection.execute("SELECT result_at,classification FROM verification_command_results").fetchone()
        self.assertTrue(row[0]); self.assertEqual(row[1], "repository_mutated")
        self.assertIsNotNone(self.store.active_workspace_operation_lease(
            RepositoryInspector(self.root).repository_key()))
        self.assertEqual(self.store.get_workflow(workflow.id).status,
            WorkflowStatus.HUMAN_ATTENTION)

    def test_baseline_inspection_failure_is_unknown_and_retains_lease(self):
        workflow, preflight, orchestrator = self.prepare([[sys.executable, "-c", "pass"]])
        real_capture = RepositoryInspector.capture
        calls = 0
        def fail_second_capture(inspector):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("baseline unavailable")
            return real_capture(inspector)
        with mock.patch.object(RepositoryInspector, "capture", fail_second_capture):
            self.assertEqual(orchestrator.run(preflight),
                VerificationOutcome.VERIFICATION_UNKNOWN)
        self.assertIsNotNone(self.store.active_workspace_operation_lease(
            RepositoryInspector(self.root).repository_key()))
        self.assertEqual(self.store.get_workflow(workflow.id).status,
            WorkflowStatus.HUMAN_ATTENTION)

    def test_generic_runner_exception_is_unknown_and_retains_lease(self):
        class BrokenRunner(VerificationCommandRunner):
            def run(self, command, **kwargs):
                raise RuntimeError("runner ambiguity")
        workflow, preflight, orchestrator = self.prepare([[sys.executable, "-c", "pass"]])
        orchestrator.runner = BrokenRunner(self.root)
        self.assertEqual(orchestrator.run(preflight),
            VerificationOutcome.VERIFICATION_UNKNOWN)
        self.assertIsNotNone(self.store.active_workspace_operation_lease(
            RepositoryInspector(self.root).repository_key()))
        self.assertEqual(self.store.get_workflow(workflow.id).status,
            WorkflowStatus.HUMAN_ATTENTION)

    def test_command_intent_exists_before_process_execution(self):
        class InspectingRunner(VerificationCommandRunner):
            def run(inner, command, **kwargs):
                row = self.store._connection.execute("SELECT intent_at,result_at FROM verification_command_results").fetchone()
                self.assertTrue(row[0]); self.assertIsNone(row[1])
                return super().run(command, **kwargs)
        workflow, preflight, orchestrator = self.prepare([[sys.executable, "-c", "pass"]])
        orchestrator.runner = InspectingRunner(self.root)
        self.assertEqual(orchestrator.run(preflight), VerificationOutcome.VERIFIED)

    def test_leader_exit_with_live_descendant_is_terminated_before_return(self):
        from engineering_flow.verification import VerificationCommand
        pid_file = Path(self.temp.name) / "descendant.pid"
        code = ("import os,subprocess,sys; p=subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(30)']); open(sys.argv[1], 'w').write(str(os.getpgrp()))")
        result = VerificationCommandRunner(self.root).run(VerificationCommand("child", (sys.executable, "-c", code, str(pid_file)), 1), runtime_directory=Path(self.temp.name) / "runtime-child")
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(VerificationCommandRunner._live_group_members(int(pid_file.read_text())))

    def test_descendant_holding_pipes_has_bounded_completion_and_cleanup(self):
        from engineering_flow.verification import VerificationCommand
        pid_file = Path(self.temp.name) / "pipe-descendant.pid"
        code = ("import os,subprocess,sys; p=subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(30)']); open(sys.argv[1], 'w').write(str(os.getpgrp()))")
        started = time.monotonic()
        result = VerificationCommandRunner(self.root).run(VerificationCommand("pipe", (sys.executable, "-c", code, str(pid_file)), 1), runtime_directory=Path(self.temp.name) / "runtime-pipe")
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(VerificationCommandRunner._live_group_members(int(pid_file.read_text())))

    def test_on_started_persistence_failure_terminates_group(self):
        from engineering_flow.verification import VerificationCommand
        groups = []
        code = "import time; time.sleep(30)"
        def fail_started(evidence):
            groups.append(evidence["process_group"])
            raise RuntimeError("persistence unavailable")
        with self.assertRaisesRegex(RuntimeError, "persistence unavailable"):
            VerificationCommandRunner(self.root).run(VerificationCommand("started", (sys.executable, "-c", code), 30), runtime_directory=Path(self.temp.name) / "runtime-started", on_started=fail_started)
        self.assertFalse(VerificationCommandRunner._live_group_members(groups[0]))

    def test_existing_unresolved_attempt_does_not_execute(self):
        workflow, preflight, orchestrator = self.prepare([[sys.executable, "-c", "raise SystemExit(99)"]])
        inspector = RepositoryInspector(self.root)
        first = self.store.create_verification_intent(workflow.id, repository_key=inspector.repository_key(), canonical_root=str(self.root), producer_operation_id=preflight.producer.operation_id, task_contract_id=preflight.producer.task_contract_id, task_contract_sha256=preflight.producer.task_contract_sha256, authority_sha256=preflight.authority_sha256, request_hash=preflight.request_hash, manifest_binding={}, baseline=inspector.capture().as_payload(), owner_instance_id="other", owner_pid=os.getpid(), owner_host_id="host")
        self.assertEqual(orchestrator.run(preflight), VerificationOutcome.VERIFICATION_BLOCKED)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM verification_command_results").fetchone()[0], 0)
        self.assertEqual(self.store.active_workspace_operation_lease(inspector.repository_key())["lease_id"], first["lease_id"])

    def test_unresolved_command_intent_does_not_reexecute(self):
        workflow, preflight, orchestrator = self.prepare([[sys.executable, "-c", "raise SystemExit(99)"]])
        inspector = RepositoryInspector(self.root)
        first = self.store.create_verification_intent(workflow.id, repository_key=inspector.repository_key(), canonical_root=str(self.root), producer_operation_id=preflight.producer.operation_id, task_contract_id=preflight.producer.task_contract_id, task_contract_sha256=preflight.producer.task_contract_sha256, authority_sha256=preflight.authority_sha256, request_hash=preflight.request_hash, manifest_binding={}, baseline=inspector.capture().as_payload(), owner_instance_id="other", owner_pid=os.getpid(), owner_host_id="host")
        self.store.record_verification_command_intent(first["attempt_id"], first["lease_id"], owner_instance_id="other", ordinal=1, command_id="c1", canonical_command_sha256=orchestrator._command_hash(preflight.manifest_binding.manifest.commands[0]), argv=preflight.manifest_binding.manifest.commands[0].argv, timeout_seconds=1)
        self.assertEqual(orchestrator.run(preflight), VerificationOutcome.VERIFICATION_BLOCKED)
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM verification_command_results").fetchone()[0], 1)

    def test_runtime_environment_paths_are_outside_repository(self):
        from engineering_flow.verification import VerificationCommand
        destination = Path(self.temp.name) / "environment.json"
        code = "import json,os,sys; open(sys.argv[1], 'w').write(json.dumps({k:os.environ[k] for k in ('HOME','TMPDIR','XDG_CACHE_HOME','PIP_CACHE_DIR','PYTHONPYCACHEPREFIX')}))"
        external_runtime = Path(self.temp.name) / "runtime-env"
        VerificationCommandRunner(self.root).run(VerificationCommand("env", (sys.executable, "-c", code, str(destination)), 1), runtime_directory=external_runtime)
        for value in json.loads(destination.read_text()).values():
            self.assertFalse(Path(value).resolve().is_relative_to(self.root))

    def test_inspection_is_after_confirmed_group_death(self):
        pid_file = Path(self.temp.name) / "inspection-child.pid"
        code = ("import os,subprocess,sys; p=subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(30)']); open(sys.argv[1], 'w').write(str(os.getpgrp()))")
        workflow, outcome = self.run_commands([[sys.executable, "-c", code, str(pid_file)]])
        self.assertEqual(outcome, VerificationOutcome.VERIFIED)
        self.assertFalse(VerificationCommandRunner._live_group_members(int(pid_file.read_text())))

    def test_child_identity_is_preserved_in_command_evidence(self):
        workflow, outcome = self.run_commands([[sys.executable, "-c", "pass"]])
        self.assertEqual(outcome, VerificationOutcome.VERIFIED)
        row = self.store._connection.execute("""SELECT child_pid,child_process_start,child_process_group,
            child_process_session,child_host_id,child_boot_id,child_owner_instance_id
            FROM verification_command_results""").fetchone()
        identity = local_host_boot_identity()
        self.assertIsInstance(row[0], int); self.assertTrue(row[1]); self.assertEqual(row[2], row[0])
        self.assertEqual(row[3], row[0])
        self.assertEqual((row[4], row[5], row[6]), (identity.host_id, identity.boot_id, "runner"))

    def test_unproven_group_death_retains_lease_and_unresolved_command_evidence(self):
        from engineering_flow.verification import VerificationProcessGroupDeathUnknown
        class UnprovenRunner(VerificationCommandRunner):
            @classmethod
            def _terminate_group(cls, process_group):
                raise VerificationProcessGroupDeathUnknown("test cannot prove group death")
        workflow, preflight, orchestrator = self.prepare([[sys.executable, "-c", "pass"]])
        orchestrator.runner = UnprovenRunner(self.root)
        self.assertEqual(orchestrator.run(preflight), VerificationOutcome.VERIFICATION_UNKNOWN)
        key = RepositoryInspector(self.root).repository_key()
        lease = self.store.active_workspace_operation_lease(key)
        self.assertIsNotNone(lease)
        self.assertTrue(lease["child_pid"]); self.assertTrue(lease["child_process_start"])
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.HUMAN_ATTENTION)
        attempt = self.store._connection.execute(
            "SELECT status,classification,final_inspection_json FROM verification_attempts").fetchone()
        self.assertEqual(tuple(attempt[:2]), ("unknown", "verification_unknown"))
        identity_evidence = json.loads(attempt[2])["identity"]
        self.assertEqual(set(identity_evidence), {"pid", "process_start", "process_group",
            "process_session", "machine_id", "boot_id", "owner_instance_id", "owner_pid",
            "workflow_id", "attempt_id", "lease_id", "operation_id", "command_result_id"})
        command = self.store._connection.execute("SELECT argv_json,intent_at,result_at,child_pid,child_process_start FROM verification_command_results").fetchone()
        self.assertIn(sys.executable, command[0]); self.assertTrue(command[1]); self.assertIsNone(command[2])
        self.assertTrue(command[3]); self.assertTrue(command[4])
        self.assertEqual(self.store._connection.execute("SELECT count(*) FROM events WHERE type='verification.attempt.terminal'").fetchone()[0], 0)

    def test_unknown_retention_persistence_failure_rolls_back_every_projection(self):
        from engineering_flow.verification import VerificationProcessGroupDeathUnknown
        class UnprovenRunner(VerificationCommandRunner):
            @classmethod
            def _terminate_group(cls, process_group):
                raise VerificationProcessGroupDeathUnknown("test cannot prove group death")
        workflow, preflight, orchestrator = self.prepare([[sys.executable, "-c", "pass"]])
        orchestrator.runner = UnprovenRunner(self.root)
        self.store._connection.execute("""CREATE TRIGGER fail_unknown_event BEFORE INSERT ON events
            WHEN NEW.type='verification.attempt.unknown_retained'
            BEGIN SELECT RAISE(ABORT, 'fault injected'); END""")
        with self.assertRaises(DomainFailure):
            orchestrator.run(preflight)
        attempt = self.store._connection.execute(
            "SELECT status,classification,final_inspection_json FROM verification_attempts").fetchone()
        self.assertEqual(tuple(attempt), ("verifying", None, None))
        self.assertEqual(self.store.get_workflow(workflow.id).status, WorkflowStatus.VERIFYING)
        self.assertEqual(self.store._connection.execute(
            "SELECT status FROM operations WHERE kind='verification'").fetchone()[0], "pending")
        self.assertIsNotNone(self.store.active_workspace_operation_lease(
            RepositoryInspector(self.root).repository_key()))

    def test_retained_unknown_lease_blocks_a_successor_operation(self):
        from engineering_flow.verification import VerificationProcessGroupDeathUnknown
        from engineering_flow.store import ConflictFailure
        class UnprovenRunner(VerificationCommandRunner):
            @classmethod
            def _terminate_group(cls, process_group):
                raise VerificationProcessGroupDeathUnknown("test cannot prove group death")
        workflow, preflight, orchestrator = self.prepare([[sys.executable, "-c", "pass"]])
        orchestrator.runner = UnprovenRunner(self.root)
        self.assertEqual(orchestrator.run(preflight), VerificationOutcome.VERIFICATION_UNKNOWN)
        inspector = RepositoryInspector(self.root)
        with self.assertRaises(ConflictFailure):
            self.store.create_implementation_intent(workflow.id, repository_key=inspector.repository_key(),
                canonical_root=str(self.root), task_contract_id=preflight.producer.task_contract_id,
                task_contract_sha256=preflight.producer.task_contract_sha256, request_hash="z" * 64,
                baseline=inspector.capture().as_payload(), owner_instance_id="successor", owner_pid=os.getpid(),
                owner_host_id="host")
