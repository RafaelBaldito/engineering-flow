"""Terminal presentation for verified CLI result documents.

This module is the only Rich boundary.  It consumes sanitized projections and
never decides workflow transitions or reads authoritative state.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any, Callable, Mapping, TextIO

from rich.console import Console
from rich.json import JSON
from rich.table import Table
from rich.text import Text


class OutputMode(str, Enum):
    HUMAN = "human"
    VERBOSE = "verbose"
    JSON = "json"


_SUCCESS = {"approved", "completed", "plan_approved", "ready", "success", "succeeded"}
_ATTENTION = {"awaiting_approval", "clarification", "human_attention", "needs_clarification", "pending"}
_FAILURE = {"failed", "interrupted", "rejected", "timed_out"}


def _is_terminal(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError):
        return False


def _color_disabled(*, stream: TextIO, no_color: bool, environ: Mapping[str, str]) -> bool:
    return (
        no_color
        or "NO_COLOR" in environ
        or environ.get("TERM", "").casefold() == "dumb"
        or not _is_terminal(stream)
    )


def build_console(
    stream: TextIO,
    *,
    no_color: bool = False,
    environ: Mapping[str, str] | None = None,
    width: int | None = None,
) -> Console:
    """Build an explicit console whose terminal behavior follows CLI policy."""

    environment = os.environ if environ is None else environ
    disabled = _color_disabled(stream=stream, no_color=no_color, environ=environment)
    return Console(
        file=stream,
        force_terminal=False if disabled else None,
        color_system=None if disabled else "auto",
        no_color=disabled,
        highlight=False,
        markup=False,
        emoji=False,
        soft_wrap=False,
        width=width,
    )


def _semantic_style(value: Any) -> str:
    normalized = str(value or "").casefold()
    if normalized in _SUCCESS:
        return "green"
    if normalized in _ATTENTION:
        return "yellow"
    if normalized in _FAILURE:
        return "red"
    return "cyan"


def _heading(console: Console, label: str) -> None:
    console.print(Text(label, style="bold cyan"))


def _rows(console: Console, rows: list[tuple[str, Any, str | None]]) -> None:
    table = Table.grid(padding=(0, 2), expand=False)
    table.add_column(style="bold")
    table.add_column(no_wrap=True, overflow="ignore")
    for label, value, style in rows:
        table.add_row(label, Text(str(value), style=style or ""))
    console.print(table)


def render_workflow_summary(console: Console, document: Mapping[str, Any]) -> None:
    stage = str(document.get("stage") or "unknown").upper()
    status = str(document.get("status") or "unknown").upper()
    _heading(console, "Workflow")
    _rows(console, [
        ("Stage", stage, "cyan"),
        ("Status", status, _semantic_style(document.get("status"))),
    ])

    # Until selected-workflow resolution is implemented, a newly created
    # workflow still needs to expose its ID so the existing explicit command
    # contract remains usable. Plan views suppress this routine identity.
    if document.get("command") == "run" and not document.get("plan") and document.get("workflow_id"):
        console.print(Text(f"workflow: {document['workflow_id']}", style="dim"))


def render_intake_summary(console: Console, intake: Mapping[str, Any]) -> None:
    console.print()
    outcome = str(intake.get("outcome") or "unknown").upper()
    console.print(Text(f"Intake: {outcome}", style=_semantic_style(intake.get("outcome"))))
    questions = intake.get("open_questions")
    if isinstance(questions, list) and questions:
        console.print()
        _heading(console, "Open questions:")
        for question in questions:
            console.print(Text(f"- {question}"))


def render_task_summary(console: Console, task: Mapping[str, Any]) -> None:
    task_id = str(task.get("id") or "?")
    objective = str(task.get("objective") or "")
    console.print(Text.assemble((f"  {task_id}  ", "bold cyan"), objective))
    metadata = [f"{task.get('complexity', 'unknown')} complexity", f"{task.get('risk', 'unknown')} risk"]
    dependencies = task.get("depends_on")
    if isinstance(dependencies, list) and dependencies:
        metadata.append(f"depends on {', '.join(str(item) for item in dependencies)}")
    console.print(Text(f"      {' · '.join(metadata)}", style="dim"))


def render_plan_summary(console: Console, document: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    details = plan.get("plan") if isinstance(plan.get("plan"), Mapping) else {}
    tasks = details.get("tasks") if isinstance(details, Mapping) else []
    if not isinstance(tasks, list):
        tasks = []

    console.print()
    _heading(console, "Plan")
    _rows(console, [
        ("Revision", plan.get("revision", "unknown"), None),
        ("Tasks", len(tasks), None),
        ("Approval", str(plan.get("approval_state") or "unknown").upper(),
         _semantic_style(plan.get("approval_state"))),
    ])
    if tasks:
        console.print()
        _heading(console, "Tasks")
        for index, task in enumerate(tasks):
            if isinstance(task, Mapping):
                if index:
                    console.print()
                render_task_summary(console, task)

    status = document.get("status")
    console.print()
    if status == "awaiting_approval":
        console.print(Text("Waiting for human approval.", style="yellow"))
    elif status == "plan_approved":
        console.print(Text("Plan approved.", style="green"))
        console.print("No implementation has started.")
    elif status == "rejected":
        console.print(Text("Plan rejected.", style="red"))
        if plan.get("decision_reason"):
            console.print("Rejection reason recorded.")


def _render_legacy_summary(console: Console, document: Mapping[str, Any]) -> None:
    artifacts = document.get("artifacts")
    tasks = document.get("tasks")
    if isinstance(artifacts, list):
        console.print()
        _heading(console, "Artifacts")
        _rows(console, [("Count", len(artifacts), None)])
    if isinstance(tasks, list) and tasks:
        console.print()
        _heading(console, "Tasks")
        for task in tasks:
            if isinstance(task, Mapping):
                label = task.get("key") or task.get("id") or "?"
                title = task.get("title") or ""
                console.print(Text.assemble((f"  {label}  ", "bold cyan"), str(title)))


def render_human(console: Console, document: Mapping[str, Any]) -> None:
    if document.get("command_result") == "error":
        code = document.get("error_code") or "workflow"
        message = document.get("message") or ""
        console.print(Text(f"error: {code}: {message}", style="red"))
        if document.get("workflow_id"):
            console.print(Text(f"workflow: {document['workflow_id']}", style="dim"))
        return

    if not document.get("stage") and not document.get("status"):
        if document.get("command") == "init":
            console.print(Text("Engineering Flow initialized.", style="green"))
            _rows(console, [
                ("Repository", document.get("repository_path", "unknown"), None),
                ("Workspace", document.get("application_path", "unknown"), None),
            ])
        else:
            console.print(Text("Command completed.", style="green"))
        return

    render_workflow_summary(console, document)
    intake = document.get("intake")
    if isinstance(intake, Mapping):
        render_intake_summary(console, intake)
    plan = document.get("plan")
    if isinstance(plan, Mapping):
        render_plan_summary(console, document, plan)
    elif not isinstance(intake, Mapping):
        _render_legacy_summary(console, document)

    events = document.get("events")
    if isinstance(events, list):
        console.print()
        _heading(console, "Events")
        for event in events:
            console.print(json.dumps(event, ensure_ascii=False, sort_keys=True))


def render_verbose(console: Console, document: Mapping[str, Any]) -> None:
    """Render the concise view followed by the complete sanitized projection."""

    render_human(console, document)
    console.print()
    _heading(console, "Verified projection")
    console.print(JSON.from_data(document, ensure_ascii=False, indent=2, sort_keys=True))


def render_result(
    document: Mapping[str, Any],
    *,
    mode: OutputMode,
    stream: TextIO,
    no_color: bool = False,
    environ: Mapping[str, str] | None = None,
    width: int | None = None,
) -> None:
    """Render one already-sanitized result document to the requested stream."""

    if mode is OutputMode.JSON:
        stream.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        return
    console = build_console(stream, no_color=no_color, environ=environ, width=width)
    if mode is OutputMode.VERBOSE:
        render_verbose(console, document)
    else:
        render_human(console, document)


def make_plan_progress_renderer(
    stream: TextIO,
    *,
    no_color: bool = False,
    environ: Mapping[str, str] | None = None,
) -> Callable[[Any], None] | None:
    """Preserve the existing Plan-only progress contract at the presentation boundary."""

    if not _is_terminal(stream):
        return None
    console = build_console(stream, no_color=no_color, environ=environ)

    def render(event: Any) -> None:
        if event.kind == "started":
            text, style = "→ PLAN started", "cyan"
        elif event.kind == "heartbeat":
            text, style = f"  Codex running... {event.elapsed_seconds:.0f}s", "cyan"
        elif event.kind == "activity":
            text, style = (f"  {event.message}" if event.message else ""), "cyan"
        elif event.kind == "completed":
            text, style = f"✓ PLAN completed ({event.elapsed_seconds:.1f}s)", "green"
        elif event.kind == "timed_out":
            text, style = f"✗ PLAN timed out ({event.elapsed_seconds:.1f}s)", "red"
        else:
            text, style = f"✗ PLAN failed ({event.elapsed_seconds:.1f}s)", "red"
        if text:
            console.print(Text(text, style=style))

    return render


__all__ = [
    "OutputMode",
    "build_console",
    "make_plan_progress_renderer",
    "render_human",
    "render_plan_summary",
    "render_result",
    "render_task_summary",
    "render_verbose",
    "render_workflow_summary",
]
