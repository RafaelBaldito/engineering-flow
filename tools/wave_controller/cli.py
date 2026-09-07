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
    begin = sub.add_parser("begin-operation"); begin.add_argument("--operation-id"); begin.add_argument("--child-task-name")
    complete = sub.add_parser("complete-operation"); complete.add_argument("--envelope", required=True, help="path to JSON envelope")
    args = parser.parse_args(); controller = Controller(Path(args.root), args.wave)
    try:
        if args.command == "status": result = controller.status()
        elif args.command == "reconcile": result = controller.reconcile()
        elif args.command == "next": result = controller.next()
        elif args.command == "begin-operation": result = controller.begin_operation(args.operation_id, args.child_task_name)
        else: result = controller.complete_operation(json.loads(Path(args.envelope).read_text(encoding="utf-8")))
    except (ControllerError, OSError, json.JSONDecodeError) as exc: result = {"status": "INVALID", "reason": str(exc)}
    print(json.dumps(result, sort_keys=True)); return 0

if __name__ == "__main__": raise SystemExit(main())
