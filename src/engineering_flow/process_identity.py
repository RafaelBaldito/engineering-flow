"""Small Linux/WSL process-identity helpers for durable process ownership.

PIDs are recyclable.  The kernel start-time field in ``/proc/<pid>/stat`` is
therefore persisted with the PID and is required before observing or signaling
a previous writer.
"""
from __future__ import annotations

import os
import signal
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class HostBootIdentity:
    host_id: str
    boot_id: str


class ProcessObservation(Enum):
    ALIVE = "alive"
    GONE = "gone"
    AMBIGUOUS = "ambiguous"


class ProcessGroupObservation(Enum):
    """Recovery-safe classification of a persisted process group/session."""

    ALIVE_OWNED = "alive_owned"
    DEAD = "dead"
    PID_REUSED = "pid_reused"
    IDENTITY_MISMATCH = "identity_mismatch"
    DIFFERENT_MACHINE = "different_machine"
    DIFFERENT_BOOT = "different_boot"
    INCOMPLETE_IDENTITY = "incomplete_identity"
    INSPECTION_FAILURE = "inspection_failure"
    AMBIGUOUS_OWNERSHIP = "ambiguous_ownership"


def _read_required(path: str) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise OSError(f"empty identity source: {path}")
    return value


def local_host_boot_identity() -> HostBootIdentity:
    """Return stable Linux machine and boot IDs, or raise instead of guessing."""
    return HostBootIdentity(_read_required("/etc/machine-id"),
                            _read_required("/proc/sys/kernel/random/boot_id"))


def process_start_token(pid: int) -> str | None:
    """Linux ``/proc`` starttime (field 22), safe around spaces in comm."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        closing = raw.rfind(")")
        if closing < 0:
            return None
        # Fields following ')' start at field 3; starttime is field 22.
        fields = raw[closing + 2:].split()
        return fields[19] if len(fields) > 19 and fields[19].isdigit() else None
    except OSError:
        return None


def observe_exact_process(*, host_id: str | None, boot_id: str | None,
                          provider_pid: int | None, provider_process_start: str | None,
                          identity: HostBootIdentity | None = None,
                          token_reader: Callable[[int], str | None] = process_start_token) -> ProcessObservation:
    """Observe a persisted writer without treating PID existence as ownership."""
    try:
        current = identity or local_host_boot_identity()
    except OSError:
        return ProcessObservation.AMBIGUOUS
    if not host_id or not boot_id or host_id != current.host_id or boot_id != current.boot_id:
        return ProcessObservation.AMBIGUOUS
    if type(provider_pid) is not int or provider_pid <= 0 or not provider_process_start:
        return ProcessObservation.AMBIGUOUS
    token = token_reader(provider_pid)
    if token is None:
        # Only a missing proc directory proves death.  A present but unreadable
        # stat file may be permissions or a process-table failure, never a
        # license to release ownership.
        try:
            return (ProcessObservation.GONE if not Path(f"/proc/{provider_pid}").exists()
                    else ProcessObservation.AMBIGUOUS)
        except OSError:
            return ProcessObservation.AMBIGUOUS
    if token != provider_process_start:
        return ProcessObservation.AMBIGUOUS
    return ProcessObservation.ALIVE


def owned_process_evidence(pid: int) -> dict[str, object]:
    """Evidence captured immediately after Popen; unavailable evidence is null."""
    result: dict[str, object] = {"pid": pid, "process_start": process_start_token(pid)}
    try:
        result["process_group"] = os.getpgid(pid)
    except OSError:
        result["process_group"] = None
    try:
        result["process_session"] = os.getsid(pid)
    except OSError:
        result["process_session"] = None
    return result


def _process_record(pid: int) -> tuple[str, int, int, str] | None:
    """Return start token, process group, session, and state; None means gone."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeError(f"cannot inspect process {pid}") from exc
    closing = raw.rfind(")")
    fields = raw[closing + 2:].split()
    if closing < 0 or len(fields) <= 19 or not fields[19].isdigit():
        raise RuntimeError(f"malformed process identity for {pid}")
    try:
        return fields[19], int(fields[2]), int(fields[3]), fields[0]
    except (ValueError, IndexError) as exc:
        raise RuntimeError(f"malformed process identity for {pid}") from exc


def observe_exact_process_group(*, host_id: str | None, boot_id: str | None,
                                process_pid: int | None, process_start: str | None,
                                process_group: int | None, process_session: int | None,
                                identity: HostBootIdentity | None = None,
                                record_reader: Callable[[int], tuple[str, int, int, str] | None] = _process_record,
                                proc_lister: Callable[[], list[str]] = lambda: os.listdir("/proc"),
                                ) -> ProcessGroupObservation:
    """Classify a persisted Linux process identity without signaling it.

    A missing leader is not sufficient proof of death: surviving members of
    its process group or session are inspected before DEAD is returned.
    """
    try:
        current = identity or local_host_boot_identity()
    except OSError:
        return ProcessGroupObservation.INSPECTION_FAILURE
    if not host_id or not boot_id:
        return ProcessGroupObservation.INCOMPLETE_IDENTITY
    if host_id != current.host_id:
        return ProcessGroupObservation.DIFFERENT_MACHINE
    if boot_id != current.boot_id:
        return ProcessGroupObservation.DIFFERENT_BOOT
    if (type(process_pid) is not int or process_pid <= 0 or not process_start
            or type(process_group) is not int or process_group <= 0
            or type(process_session) is not int or process_session <= 0):
        return ProcessGroupObservation.INCOMPLETE_IDENTITY
    # Verification uses start_new_session=True, so all three identifiers are
    # initially the leader PID.  Any other persisted shape is not ours.
    if process_group != process_pid or process_session != process_pid:
        return ProcessGroupObservation.IDENTITY_MISMATCH
    try:
        leader = record_reader(process_pid)
    except Exception:
        return ProcessGroupObservation.INSPECTION_FAILURE
    if leader is not None:
        start, group, session, state = leader
        if start != process_start:
            return ProcessGroupObservation.PID_REUSED
        if group != process_group or session != process_session:
            return ProcessGroupObservation.IDENTITY_MISMATCH
        if state not in {"Z", "X"}:
            return ProcessGroupObservation.ALIVE_OWNED
    try:
        for entry in proc_lister():
            if not entry.isdecimal() or int(entry) == process_pid:
                continue
            try:
                member = record_reader(int(entry))
            except FileNotFoundError:
                continue
            if member is None:
                continue
            _, group, session, state = member
            if state not in {"Z", "X"} and (group == process_group or session == process_session):
                # A live session bearing the persisted session ID cannot be a
                # recycled unrelated session while one of its members exists.
                return (ProcessGroupObservation.ALIVE_OWNED if session == process_session
                        else ProcessGroupObservation.AMBIGUOUS_OWNERSHIP)
    except Exception:
        return ProcessGroupObservation.INSPECTION_FAILURE
    return ProcessGroupObservation.DEAD


def signal_owned_group(*, process_group: int | None, provider_pid: int | None,
                       provider_process_start: str | None, host_id: str | None,
                       boot_id: str | None, sig: signal.Signals,
                       identity: HostBootIdentity | None = None,
                       token_reader: Callable[[int], str | None] = process_start_token,
                       signal_sender: Callable[[int, signal.Signals], None] = os.killpg) -> bool:
    """Signal only a currently exact process in its persisted process group."""
    if observe_exact_process(host_id=host_id, boot_id=boot_id, provider_pid=provider_pid,
                             provider_process_start=provider_process_start, identity=identity,
                             token_reader=token_reader) is not ProcessObservation.ALIVE:
        return False
    if type(process_group) is not int or process_group <= 0:
        return False
    try:
        if os.getpgid(provider_pid) != process_group:  # type: ignore[arg-type]
            return False
        signal_sender(process_group, sig)
        return True
    except OSError:
        return False
