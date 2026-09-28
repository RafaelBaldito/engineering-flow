"""Deterministic Git evidence for the V2 implementation boundary.

This module deliberately has no runtime/provider dependency.  It is used both
before and after an injected writer so Git, rather than agent claims, is the
source of repository truth.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .domain import ValidationFailure


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def control_state_fingerprint(root: str | Path) -> str:
    """Hash control files, excluding per-attempt runtime outputs.

    This is detection evidence, not a sandbox.  If it cannot be collected the
    caller must treat the execution result as unsafe rather than ignore it.
    """
    control = Path(root).resolve() / ".engineering-flow"
    if not control.exists():
        return _sha(b"missing")
    rows: list[bytes] = []
    for path in sorted(control.rglob("*")):
        if (("implementation-runtime" in path.parts or "verification-runtime" in path.parts
             or "review-runtime" in path.parts) or not path.is_file()
                # SQLite/WAL bytes necessarily change as the parent persists
                # lifecycle evidence.  Authority rows are revalidated by the
                # store instead of pretending these volatile bytes are stable.
                or path.name.startswith("workflows.sqlite3")):
            continue
        relative = path.relative_to(control)
        rows.append(os.fsencode(str(relative)) + b"\0" + _sha(path.read_bytes()).encode())
    return _sha(b"\n".join(rows))


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    canonical_root: str
    git_toplevel: str
    git_dir: str
    git_common_dir: str
    head_sha: str
    branch_name: str
    detached: bool
    status_sha256: str
    diff_sha256: str
    untracked_manifest_sha256: str
    changed_paths: tuple[str, ...]
    changed_paths_sha256: str
    local_git_config_sha256: str
    fingerprint: str

    def as_payload(self) -> dict[str, object]:
        value = asdict(self)
        value["changed_paths"] = list(self.changed_paths)
        return value


class RepositoryInspector:
    """Inspect exactly one supported, existing Git worktree using argv calls."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _git(self, *args: str, check: bool = True) -> bytes:
        try:
            result = subprocess.run(("git", "-C", os.fspath(self.root), *args), shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        except OSError as exc:
            raise ValidationFailure(f"Git inspection unavailable: {exc}") from exc
        if check and result.returncode:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise ValidationFailure(f"unsupported target repository: {detail or 'git command failed'}")
        return result.stdout

    def _path(self, value: bytes) -> Path:
        path = Path(os.fsdecode(value.rstrip(b"\n")))
        return (path if path.is_absolute() else self.root / path).resolve()

    def _identity(self) -> tuple[Path, Path, Path, str, str]:
        if not self.root.is_dir():
            raise ValidationFailure("target repository root does not exist")
        bare = self._git("rev-parse", "--is-bare-repository").strip()
        if bare != b"false":
            raise ValidationFailure("target repository must be a non-bare Git worktree")
        top = self._path(self._git("rev-parse", "--show-toplevel"))
        if top != self.root:
            raise ValidationFailure("Git top-level does not equal workflow repository path")
        self._git("rev-parse", "--verify", "HEAD")
        branch = self._git("symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
        if not branch:
            raise ValidationFailure("target repository must have an attached local branch")
        git_dir = self._path(self._git("rev-parse", "--git-dir"))
        common = self._path(self._git("rev-parse", "--git-common-dir"))
        return top, git_dir, common, self._git("rev-parse", "HEAD").strip().decode(), branch.decode()

    def _validate_topology(self) -> None:
        if b"160000" in self._git("ls-files", "--stage", "-z"):
            raise ValidationFailure("registered gitlinks/submodules are unsupported")
        # Ignore the root marker itself; any lower .git boundary is unsupported.
        for base, dirs, files in os.walk(self.root, topdown=True):
            path = Path(base)
            if path == self.root:
                dirs[:] = [d for d in dirs if d != ".git"]
            elif ".git" in dirs or ".git" in files:
                raise ValidationFailure("nested Git repositories are unsupported")
            dirs[:] = [d for d in dirs if d not in {".git", ".engineering-flow"}]

    def _untracked_manifest(self, status: bytes) -> tuple[bytes, tuple[str, ...]]:
        # Porcelain v2 untracked records are '? path\\0'.  Git has already
        # applied ignore policy; hash files without following symlinks.
        paths = sorted({os.fsdecode(item[2:]) for item in status.split(b"\0") if item.startswith(b"? ")})
        rows: list[bytes] = []
        for text in paths:
            candidate = self.root / text
            try:
                stat = candidate.lstat()
                if os.path.islink(candidate):
                    evidence = b"symlink\0" + os.fsencode(os.readlink(candidate))
                elif os.path.isfile(candidate):
                    evidence = b"file\0" + candidate.read_bytes()
                else:
                    # Git normally reports individual files with --untracked-files=all;
                    # reject opaque special nodes rather than guess at their contents.
                    raise OSError("unsupported untracked filesystem node")
                rows.append(os.fsencode(text) + b"\0" + str(stat.st_mode).encode() + b"\0" + _sha(evidence).encode())
            except OSError as exc:
                raise ValidationFailure(f"cannot deterministically inspect untracked path {text!r}: {exc}") from exc
        return b"\n".join(rows), tuple(paths)

    def capture(self, *, require_clean: bool = False) -> RepositorySnapshot:
        top, git_dir, common, head, branch = self._identity()
        self._validate_topology()
        status = self._git("status", "--porcelain=v2", "-z", "--untracked-files=all", "--ignore-submodules=none")
        if require_clean and status:
            raise ValidationFailure("target repository is not clean; reconcile staged, tracked, conflict, or untracked changes before implementation")
        diff = self._git("diff", "--binary", "HEAD")
        manifest, untracked = self._untracked_manifest(status)
        changed = set(untracked)
        # Name-status includes index and worktree changes and is binary-safe with -z.
        names = self._git("diff", "--name-only", "-z", "HEAD").split(b"\0")
        changed.update(os.fsdecode(item) for item in names if item)
        # Git resolves linked-worktree configuration correctly; raw config
        # paths do not.  NUL form preserves unusual values byte-for-byte.
        config = self._git("config", "--local", "--null", "--list", check=False)
        fields = {
            "canonical_root": str(top), "git_toplevel": str(top), "git_dir": str(git_dir),
            "git_common_dir": str(common), "head_sha": head, "branch_name": branch,
            "detached": False, "status_sha256": _sha(status), "diff_sha256": _sha(diff),
            "untracked_manifest_sha256": _sha(manifest), "changed_paths": sorted(changed),
            "changed_paths_sha256": _sha(b"\0".join(os.fsencode(x) for x in sorted(changed))),
            "local_git_config_sha256": _sha(config),
        }
        fingerprint = _sha(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode())
        return RepositorySnapshot(**fields, fingerprint=fingerprint)  # type: ignore[arg-type]

    def repository_key(self) -> str:
        snapshot = self.capture()
        return _sha("\0".join((snapshot.canonical_root, snapshot.git_dir, snapshot.git_common_dir)).encode())
