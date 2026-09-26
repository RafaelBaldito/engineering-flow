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
from rich.live import Live
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
    current = intake.get("current_clarification")
    if isinstance(current, Mapping) and current.get("question"):
        console.print()
        _heading(console, "Open questions:")
        console.print(Text(f"- {current['question']}"))
        if current.get("answered"):
            console.print(Text("Answer persisted; Intake recovery is available.", style="yellow"))
        else:
            console.print("Continue with: engineering-flow resume --answer \"...\"")
    elif outcome == "READY":
        console.print(Text("Clarification accepted. Requirements are ready.", style="green"))


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
    elif status == "changes_requested":
        console.print(Text("Changes requested. Replacement Plan pending.", style="yellow"))
    elif status == "plan_approved":
        console.print(Text("Plan approved.", style="green"))
        console.print("No implementation has started.")
    elif status == "rejected":
        console.print(Text("Plan rejected.", style="red"))
        if plan.get("decision_reason"):
            console.print("Rejection reason recorded.")
    elif status == "cancelled":
        console.print(Text("Workflow cancelled.", style="yellow"))

    markdown_path = plan.get("plan_markdown_path")
    if markdown_path:
        console.print()
        _heading(console, "Review")
        console.print(Text(str(markdown_path)))
    if plan.get("projection_error"):
        console.print(Text("Plan view could not be regenerated from canonical JSON.", style="yellow"))


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
    if document.get("recovery_instruction"):
        console.print()
        console.print("Plan is awaiting approval.", style="yellow")
        console.print("Run `engineering-flow approve` or `engineering-flow reject --reason \"...\"`.")


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


def interactive_prompt_eligible(input_stream: TextIO, output_stream: TextIO, error_stream: TextIO) -> bool:
    """Return whether reading a human decision is safe for this invocation."""

    return _is_terminal(input_stream) and _is_terminal(output_stream) and _is_terminal(error_stream)


def prompt_for_plan_decision(
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    no_color: bool = False,
    environ: Mapping[str, str] | None = None,
    revised: bool = False,
    allow_changes: bool = True,
) -> tuple[str, str | None] | None:
    """Read one explicit Plan decision at the presentation boundary.

    ``None`` means EOF before a complete decision.  Empty input approves only
    at the decision prompt.  ``n`` requests a non-empty revision instruction;
    terminal rejection remains an explicit command rather than an interactive
    shortcut.
    """

    console = build_console(output_stream, no_color=no_color, environ=environ)
    while True:
        console.print("Approve this revised plan? [Y/n]" if revised else "Approve this plan? [Y/n]", end=" ")
        answer = input_stream.readline()
        if answer == "":
            return None
        normalized = answer.strip().casefold()
        if normalized in {"", "y", "yes"}:
            return "approve", None
        if normalized in {"n", "no"}:
            if not allow_changes:
                return "changes_unavailable", None
            console.print("What should be changed?")
            while True:
                console.print(">", end=" ")
                feedback = input_stream.readline()
                if feedback == "":
                    return None
                feedback = feedback.strip()
                if feedback:
                    return "request_changes", feedback
                console.print("Please enter non-empty feedback.", style="yellow")
        console.print("Please enter y or n.", style="yellow")


def prompt_for_clarification(
    question: str,
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    no_color: bool = False,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Read one non-empty clarification answer at the human boundary.

    ``None`` is reserved for EOF.  Blank input is not an answer, but unlike
    EOF it is safe to explain and reprompt without changing durable state.
    """

    console = build_console(output_stream, no_color=no_color, environ=environ)
    console.print(Text(f"? {question}", style="cyan"))
    while True:
        console.print(">", end=" ")
        answer = input_stream.readline()
        if answer == "":
            return None
        answer = answer.strip()
        if answer:
            return answer
        console.print("Please enter a non-empty answer.", style="yellow")


def render_recovery_instruction(output_stream: TextIO, *, no_color: bool = False,
                                environ: Mapping[str, str] | None = None) -> None:
    console = build_console(output_stream, no_color=no_color, environ=environ)
    console.print("Plan is awaiting approval.", style="yellow")
    console.print("Run `engineering-flow approve` or `engineering-flow reject --reason \"...\"`.")


def render_plan_revision_limit_instruction(output_stream: TextIO, *, no_color: bool = False,
                                           environ: Mapping[str, str] | None = None) -> None:
    """Explain the local Planner-call boundary without changing workflow state."""

    console = build_console(output_stream, no_color=no_color, environ=environ)
    console.print("Planner-call limit reached; the current Plan remains awaiting approval.", style="yellow")
    console.print("Approve it now, or run `engineering-flow resume` to request more changes.")


def render_clarification_recovery_instruction(output_stream: TextIO, *, no_color: bool = False,
                                              environ: Mapping[str, str] | None = None) -> None:
    """Render the bounded recovery seam for an unanswered clarification."""

    console = build_console(output_stream, no_color=no_color, environ=environ)
    console.print("Clarification remains unanswered.", style="yellow")
    console.print("Run `engineering-flow resume --answer \"...\"`.")


def render_plan_decision_result(output_stream: TextIO, decision: str, *, no_color: bool = False,
                                environ: Mapping[str, str] | None = None) -> None:
    console = build_console(output_stream, no_color=no_color, environ=environ)
    if decision == "approve":
        console.print("✓ Plan approved.", style="green")
        console.print("Implementation has not started.")
    else:
        console.print("Plan rejected.", style="red")


class ProgressRenderer:
    """Render the deliberately small, provider-neutral progress vocabulary.

    The renderer is a best-effort sink: orchestration owns lifecycle state and
    may safely ignore any presentation failure.  It deliberately accepts only
    fixed event kinds and stages, never provider payloads.
    """

    _terminal_kinds = frozenset({"completed", "failed", "timed_out", "interrupted"})
    _known_kinds = _terminal_kinds | {"started", "activity", "heartbeat"}

    def __init__(
        self,
        stream: TextIO,
        *,
        no_color: bool = False,
        environ: Mapping[str, str] | None = None,
        live_factory: Callable[..., Live] = Live,
    ) -> None:
        self._stream = stream
        self._console = build_console(stream, no_color=no_color, environ=environ)
        self._interactive = _is_terminal(stream)
        self._live_factory = live_factory
        self._live: Live | None = None

    @staticmethod
    def _stage(event: Any) -> str | None:
        stage = getattr(event, "stage", None)
        value = getattr(stage, "value", stage)
        return str(value).upper() if isinstance(value, str) and value else None

    @staticmethod
    def _elapsed(event: Any) -> float:
        value = getattr(event, "elapsed_seconds", 0.0)
        return value if isinstance(value, (int, float)) and value >= 0 else 0.0

    def _live_text(self, stage: str, event: Any) -> Text:
        elapsed = self._elapsed(event)
        message = "Agent running"
        if getattr(event, "kind", None) == "activity" and getattr(event, "message", None) == "Agent session started":
            message = "Agent running"
        return Text(f"⠋ {stage} · {message} · {elapsed:.0f}s", style="cyan")

    def _stop_live(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def close(self) -> None:
        """Restore a live terminal after an external cancellation."""

        try:
            self._stop_live()
        except Exception:
            # Presentation cleanup must never mask the original interruption.
            pass

    def __call__(self, event: Any) -> None:
        try:
            kind = getattr(event, "kind", None)
            stage = self._stage(event)
            if kind not in self._known_kinds or stage is None:
                return
            elapsed = self._elapsed(event)
            if not self._interactive:
                if kind == "started":
                    self._console.print(Text(f"{stage} started", style="cyan"))
                elif kind in self._terminal_kinds:
                    verb = {"completed": "completed", "failed": "failed", "timed_out": "timed out", "interrupted": "interrupted"}[kind]
                    style = "green" if kind == "completed" else "red"
                    self._console.print(Text(f"{stage} {verb} duration={elapsed:.1f}s", style=style))
                return
            if kind in {"started", "activity", "heartbeat"}:
                if self._live is None:
                    self._live = self._live_factory(
                        self._live_text(stage, event), console=self._console,
                        transient=True, redirect_stdout=False, redirect_stderr=False,
                    )
                    self._live.start()
                else:
                    self._live.update(self._live_text(stage, event), refresh=True)
                return
            self._stop_live()
            verb = {"completed": "completed", "failed": "failed", "timed_out": "timed out", "interrupted": "interrupted"}[kind]
            style = "green" if kind == "completed" else "red"
            self._console.print(Text(f"{'✓' if kind == 'completed' else '✗'} {stage} {verb} · {elapsed:.1f}s", style=style))
        except Exception:
            # A terminal is not an execution dependency.
            return


def create_progress_renderer(
    stream: TextIO,
    *,
    no_color: bool = False,
    environ: Mapping[str, str] | None = None,
) -> Callable[[Any], None]:
    """Create one stage-neutral human progress sink for stderr."""

    return ProgressRenderer(stream, no_color=no_color, environ=environ)


__all__ = [
    "OutputMode",
    "build_console",
    "ProgressRenderer",
    "create_progress_renderer",
    "interactive_prompt_eligible",
    "prompt_for_clarification",
    "prompt_for_plan_decision",
    "render_plan_decision_result",
    "render_plan_revision_limit_instruction",
    "render_recovery_instruction",
    "render_clarification_recovery_instruction",
    "render_human",
    "render_plan_summary",
    "render_result",
    "render_task_summary",
    "render_verbose",
    "render_workflow_summary",
]
