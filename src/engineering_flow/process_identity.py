"""Small Linux/WSL process-identity helpers for IMPLEMENT ownership.

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
    return result


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
