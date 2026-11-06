"""Thin wrappers around the git CLI (read-only).

This module never runs mutating git commands (commit, push, checkout, add, …).
All calls go through an allowlist enforced in ``run_git``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Well-known SHA of the empty tree; avoids calling hash-object.
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# Only these git subcommands may be invoked. Keep this list tight.
_READ_ONLY_SUBCOMMANDS = frozenset(
    {
        "rev-parse",
        "log",
        "rev-list",
        "diff-tree",
        "cat-file",
        "show",
    }
)


class GitError(RuntimeError):
    """Raised when a git command fails unexpectedly."""


def _subcommand(args: tuple[str, ...]) -> str:
    """Return the git subcommand (first non-option argument)."""
    for arg in args:
        if arg.startswith("-"):
            continue
        return arg
    raise GitError(f"no git subcommand in args: {args!r}")


def run_git(
    repo: Path,
    *args: str,
    check: bool = True,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """
    Run a read-only git command in *repo*.

    Rejects any subcommand not on the allowlist so mutating operations cannot
    be introduced accidentally.
    """
    sub = _subcommand(args)
    if sub not in _READ_ONLY_SUBCOMMANDS:
        raise GitError(
            f"refusing to run mutating or non-allowlisted git command: {sub!r} "
            f"(allowed: {', '.join(sorted(_READ_ONLY_SUBCOMMANDS))})"
        )

    cmd = ["git", "-C", str(repo), *args]
    result = subprocess.run(
        cmd,
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed in {repo}: {stderr}")
    return result


def rev_parse(repo: Path, ref: str) -> str:
    """Resolve *ref* to a full commit SHA."""
    return run_git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").stdout.decode().strip()


def commit_subject(repo: Path, commit: str) -> str:
    return run_git(repo, "log", "-1", "--format=%s", commit).stdout.decode().rstrip("\n")


def commit_message(repo: Path, commit: str) -> str:
    """Return the full commit message body (%B), trailing newlines stripped once."""
    return run_git(repo, "log", "-1", "--format=%B", commit).stdout.decode().rstrip("\n") + "\n"


def commit_date(repo: Path, commit: str) -> str:
    return run_git(repo, "log", "-1", "--format=%ci", commit).stdout.decode().rstrip("\n")


def parent_tree(repo: Path, commit: str) -> str:
    """Return the parent commit SHA, or the empty-tree SHA for a root commit."""
    result = run_git(repo, "rev-list", "--parents", "-n", "1", commit)
    parts = result.stdout.decode().strip().split()
    if len(parts) < 2:
        return EMPTY_TREE_SHA
    return parts[1]


def name_status(repo: Path, parent: str, commit: str) -> list[tuple[str, str, str | None]]:
    """
    List changes between *parent* and *commit*.

    Each item: (status, path, old_path)
      - status: 'A' | 'M' | 'D' | 'R' | 'C' | 'T' | ...
      - path: the path in the new tree (or deleted path for D)
      - old_path: set for R/C, else None
    """
    result = run_git(
        repo,
        "diff-tree",
        "--find-renames",
        "-r",
        "--name-status",
        "-z",
        parent,
        commit,
    )
    raw = result.stdout
    if not raw:
        return []

    entries: list[tuple[str, str, str | None]] = []
    parts = raw.split(b"\0")
    i = 0
    while i < len(parts):
        status_b = parts[i]
        if status_b == b"":
            i += 1
            continue
        status_s = status_b.decode()
        letter = status_s[0]
        i += 1
        if i >= len(parts):
            break
        if letter in ("R", "C"):
            old_path = parts[i].decode()
            i += 1
            if i >= len(parts):
                break
            new_path = parts[i].decode()
            i += 1
            entries.append((letter, new_path, old_path))
        else:
            path = parts[i].decode()
            i += 1
            entries.append((letter, path, None))
    return entries


def blob_at(repo: Path, rev: str, path: str) -> bytes | None:
    """
    Return blob bytes for *path* at *rev*, or None if the path does not exist.
    *rev* may be a commit SHA or a tree-ish (including empty tree SHA).
    """
    result = run_git(repo, "cat-file", "-e", f"{rev}:{path}", check=False)
    if result.returncode != 0:
        return None
    return run_git(repo, "show", f"{rev}:{path}").stdout


def path_exists_at(repo: Path, rev: str, path: str) -> bool:
    result = run_git(repo, "cat-file", "-e", f"{rev}:{path}", check=False)
    return result.returncode == 0


def is_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    result = run_git(path, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.decode().strip() == "true"


def toplevel(path: Path) -> Path:
    out = run_git(path, "rev-parse", "--show-toplevel").stdout.decode().strip()
    return Path(out)
