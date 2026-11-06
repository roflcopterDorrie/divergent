"""Comparison logic tests against fixture repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

from divergent.compare import FileStatus, run_check
from divergent.config import load_config


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _write(repo: Path, rel: str, content: str) -> None:
    (repo / rel).write_text(content, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _statuses(result, variation_name: str) -> dict[str, FileStatus]:
    var = next(v for v in result.variations if v.name == variation_name)
    return {f.path: f.status for f in var.files}


def test_modified_identical_is_safe(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    assert result.all_safe
    assert _statuses(result, "variation-1")["shared.txt"] == FileStatus.SAFE
    assert _statuses(result, "variation-2")["shared.txt"] == FileStatus.SAFE


def test_modified_diverged(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]

    # Drift variation-1 away from the shared baseline
    _write(v1, "shared.txt", "drifted\n")
    _commit(v1, "drift shared")

    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    assert not result.all_safe
    assert _statuses(result, "variation-1")["shared.txt"] == FileStatus.DIVERGED
    assert _statuses(result, "variation-2")["shared.txt"] == FileStatus.SAFE


def test_add_absent_is_safe(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _write(main, "new.txt", "brand new\n")
    commit = _commit(main, "add new")

    result = run_check(load_config(sibling_repos["config"]), commit)
    assert result.all_safe
    assert _statuses(result, "variation-1")["new.txt"] == FileStatus.SAFE


def test_add_already_present_is_unexpected(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]

    _write(v1, "new.txt", "already here\n")
    _commit(v1, "add new in v1")

    _write(main, "new.txt", "brand new\n")
    commit = _commit(main, "add new")

    result = run_check(load_config(sibling_repos["config"]), commit)
    assert not result.all_safe
    assert _statuses(result, "variation-1")["new.txt"] == FileStatus.UNEXPECTED
    assert _statuses(result, "variation-2")["new.txt"] == FileStatus.SAFE


def test_delete_matching_is_safe(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    (main / "shared.txt").unlink()
    commit = _commit(main, "delete shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    assert result.all_safe
    assert _statuses(result, "variation-1")["shared.txt"] == FileStatus.SAFE


def test_delete_diverged(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    v2 = sibling_repos["v2"]

    _write(v2, "shared.txt", "different\n")
    _commit(v2, "change shared in v2")

    (main / "shared.txt").unlink()
    commit = _commit(main, "delete shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    assert not result.all_safe
    assert _statuses(result, "variation-1")["shared.txt"] == FileStatus.SAFE
    assert _statuses(result, "variation-2")["shared.txt"] == FileStatus.DIVERGED


def test_delete_missing_in_variation(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]

    (v1 / "shared.txt").unlink()
    _commit(v1, "already deleted in v1")

    (main / "shared.txt").unlink()
    commit = _commit(main, "delete shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    assert _statuses(result, "variation-1")["shared.txt"] == FileStatus.MISSING
    assert _statuses(result, "variation-2")["shared.txt"] == FileStatus.SAFE


def test_rename_safe(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _git(main, "mv", "shared.txt", "renamed.txt")
    commit = _commit(main, "rename shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    statuses = _statuses(result, "variation-1")
    # Old path must match to delete; new path must be absent to add
    assert statuses["shared.txt"] == FileStatus.SAFE
    assert statuses["renamed.txt"] == FileStatus.SAFE
    assert result.all_safe
