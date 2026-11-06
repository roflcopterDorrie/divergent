"""Ensure git helpers refuse mutating commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from divergent.gitutil import GitError, run_git


@pytest.mark.parametrize(
    "args",
    [
        ("commit", "-m", "nope"),
        ("push", "origin", "main"),
        ("add", "file.txt"),
        ("checkout", "main"),
        ("reset", "--hard", "HEAD~1"),
        ("merge", "other"),
        ("rebase", "main"),
        ("tag", "v1"),
        ("stash", "push"),
    ],
)
def test_refuses_mutating_git_commands(tmp_path: Path, args: tuple[str, ...]) -> None:
    with pytest.raises(GitError, match="refusing to run"):
        run_git(tmp_path, *args)


def test_allows_read_only_subcommand_lookup(tmp_path: Path) -> None:
    # Not a repo — still gets past the allowlist, then git fails normally.
    with pytest.raises(GitError, match="failed"):
        run_git(tmp_path, "rev-parse", "HEAD")
