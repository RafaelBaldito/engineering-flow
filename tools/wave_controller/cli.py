"""JSON CLI for a Codex Wave Host; it never spawns or manages children."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from .core import Controller, ControllerError

def main() -> int:
    parser = argparse.ArgumentParser(prog="wave-controller")
    parser.add_argument("--root", default="."); parser.add_argument("--wave", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status"); sub.add_parser("reconcile"); sub.add_parser("next")
    sub.add_parser("register-tasks")
    begin = sub.add_parser("begin-operation"); begin.add_argument("--operation-id"); begin.add_argument("--child-task-name")
    complete = sub.add_parser("complete-operation"); complete.add_argument("--envelope", required=True, help="path to JSON envelope")
    authority = sub.add_parser("record-authority")
    authority.add_argument("--gate", required=True); authority.add_argument("--decision", required=True)
    authority.add_argument("--actor", required=True); authority.add_argument("--evidence", required=True, help="path to JSON evidence list")
    authority.add_argument("--authority-wave", required=True)
    for name in ("approve", "authorize", "revoke", "supersede"):
        command = sub.add_parser(name)
        command.add_argument("--gate", required=True); command.add_argument("--actor", required=True)
        command.add_argument("--authority-wave", required=True)
        if name in {"approve", "supersede"}:
            command.add_argument("--evidence", required=True, help="path to JSON evidence list")
        if name in {"revoke", "supersede"}: command.add_argument("--target", required=True)
    args = parser.parse_args(); controller = Controller(Path(args.root), args.wave)
    try:
        if args.command == "status": result = controller.status()
        elif args.command == "reconcile": result = controller.reconcile()
        elif args.command == "next": result = controller.next()
        elif args.command == "register-tasks": result = controller.register_tasks()
        elif args.command == "begin-operation": result = controller.begin_operation(args.operation_id, args.child_task_name)
        elif args.command == "complete-operation": result = controller.complete_operation(json.loads(Path(args.envelope).read_text(encoding="utf-8")))
        elif args.command == "record-authority": result = controller.record_authority(args.gate, args.decision, args.actor,
                                                                                         json.loads(Path(args.evidence).read_text(encoding="utf-8")), args.authority_wave)
        elif args.command == "approve": result = controller.approve(args.gate, args.actor, json.loads(Path(args.evidence).read_text(encoding="utf-8")), args.authority_wave)
        elif args.command == "authorize": result = controller.authorize(args.gate, args.actor, json.loads(Path(args.evidence).read_text(encoding="utf-8")), args.authority_wave)
        elif args.command == "revoke": result = controller.revoke(args.gate, args.actor, args.target, args.authority_wave)
        else: result = controller.supersede(args.gate, args.actor, json.loads(Path(args.evidence).read_text(encoding="utf-8")), args.target, args.authority_wave)
    except (ControllerError, OSError, json.JSONDecodeError) as exc: result = {"status": "INVALID", "reason": str(exc)}
    print(json.dumps(result, sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())
