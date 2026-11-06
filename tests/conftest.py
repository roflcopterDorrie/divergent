"""Shared fixtures: temporary main + variation git repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(repo: Path, *args: str, input_text: str | None = None) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        input=input_text.encode() if input_text is not None else None,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    # Avoid depending on the host default branch name.
    _git(path, "checkout", "-b", "main")
    return path


def _write(repo: Path, rel: str, content: str) -> None:
    file_path = repo / rel
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def sibling_repos(tmp_path: Path) -> dict[str, Path]:
    """
    Parent directory with main + two variations sharing an identical shared.txt.

    - main checked out on feature/123
    - variations have a develop branch and are checked out on develop
    """
    parent = tmp_path
    main = _init_repo(parent / "main")
    v1 = _init_repo(parent / "variation-1")
    v2 = _init_repo(parent / "variation-2")

    for repo in (main, v1, v2):
        _write(repo, "shared.txt", "hello\n")
        _write(repo, "keep.txt", "unchanged\n")
        _commit_all(repo, "initial")

    _git(main, "checkout", "-b", "feature/123")
    for repo in (v1, v2):
        _git(repo, "branch", "develop")
        _git(repo, "checkout", "develop")

    config = main / "divergent.toml"
    config.write_text(
        'variations = ["../variation-1", "../variation-2"]\n'
        'variation_base_branch = "develop"\n'
        'main_branch_pattern = "^feature/.+"\n',
        encoding="utf-8",
    )

    return {"parent": parent, "main": main, "v1": v1, "v2": v2, "config": config}
