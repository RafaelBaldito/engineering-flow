"""Binary-safe Git checkout identity used by the bootstrap controller."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ).stdout


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture(root: Path) -> dict[str, str]:
    """Return the exact five-component aggregate proven by the technical spike."""
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    status = _git(root, "status", "--porcelain=v2", "-z", "--untracked-files=all")
    diff = _git(root, "diff", "--binary", "HEAD")
    untracked = [p for p in _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p]
    untracked.sort()
    untracked_manifest = b"".join(
        path + b"\0" + _sha((root / path.decode("utf-8", "surrogateescape")).read_bytes()).encode() + b"\0"
        for path in untracked
    )
    changed = set(p for p in _git(root, "diff", "--name-only", "-z", "HEAD").split(b"\0") if p)
    changed.update(untracked)
    changed_manifest = b"".join(path + b"\0" for path in sorted(changed))
    # The aggregate remains the spike's five-component identity.  This
    # additional map is deliberately retained for operation-local output
    # validation: aggregate hashes alone cannot say which file changed.
    tracked = [p for p in _git(root, "ls-files", "-z").split(b"\0") if p]
    paths = sorted(set(tracked) | set(untracked))
    path_hashes = {
        path.decode("utf-8", "surrogateescape"): _sha(
            (root / path.decode("utf-8", "surrogateescape")).read_bytes()
        )
        for path in paths
        if (root / path.decode("utf-8", "surrogateescape")).is_file()
    }
    identity = {
        "head": head,
        "status_hash": _sha(status),
        "diff_hash": _sha(diff),
        "untracked_hash": _sha(untracked_manifest),
        "changed_paths_hash": _sha(changed_manifest),
    }
    identity["fingerprint"] = _sha(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    identity["path_hashes"] = path_hashes
    return identity
