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


def test_delete_already_deleted_on_variation_is_diverged(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]

    (v1 / "shared.txt").unlink()
    _commit(v1, "already deleted in v1")

    (main / "shared.txt").unlink()
    commit = _commit(main, "delete shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    v1_files = next(v for v in result.variations if v.name == "variation-1").files
    shared = next(f for f in v1_files if f.path == "shared.txt")
    assert shared.status == FileStatus.DIVERGED
    assert "deleted it earlier" in shared.detail
    assert [e.subject for e in shared.variant_history] == ["already deleted in v1"]
    assert _statuses(result, "variation-2")["shared.txt"] == FileStatus.SAFE


def test_modified_never_existed_on_variation_is_missing(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    _write(main, "main_only.txt", "only on main\n")
    _commit(main, "add main_only")
    _write(main, "main_only.txt", "updated on main\n")
    commit = _commit(main, "update main_only")

    result = run_check(load_config(sibling_repos["config"]), commit)
    statuses = _statuses(result, "variation-1")
    assert statuses["main_only.txt"] == FileStatus.MISSING
    v1 = next(v for v in result.variations if v.name == "variation-1")
    missing = next(f for f in v1.files if f.path == "main_only.txt")
    assert "never had this path" in missing.detail
    assert missing.variant_history == []


def test_modified_deleted_on_variation_is_diverged_with_history(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]
    (v1 / "shared.txt").unlink()
    _commit(v1, "v1 removed shared")
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    v1_result = next(v for v in result.variations if v.name == "variation-1")
    shared = next(f for f in v1_result.files if f.path == "shared.txt")
    assert shared.status == FileStatus.DIVERGED
    assert "deleted it earlier" in shared.detail
    assert [e.subject for e in shared.variant_history] == ["v1 removed shared"]
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


def test_default_check_is_fork_to_head(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _write(main, "a.txt", "first\n")
    _commit(main, "add a")
    _write(main, "b.txt", "second\n")
    _commit(main, "add b")

    result = run_check(load_config(sibling_repos["config"]))
    paths = {c.path for c in result.changes}
    assert "a.txt" in paths
    assert "b.txt" in paths
    assert len(result.subjects) == 2
    assert result.subjects == ["add a", "add b"]
    assert len(result.commits) == 2
    assert result.all_safe


def test_explicit_range_and_single_sha(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _write(main, "a.txt", "first\n")
    sha_a = _commit(main, "add a")
    _write(main, "b.txt", "second\n")
    sha_b = _commit(main, "add b")

    parent_a = subprocess.run(
        ["git", "-C", str(main), "rev-parse", f"{sha_a}^"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    ranged = run_check(load_config(sibling_repos["config"]), f"{parent_a}..{sha_b}")
    assert {c.path for c in ranged.changes} == {"a.txt", "b.txt"}
    assert ranged.subjects == ["add a", "add b"]

    single = run_check(load_config(sibling_repos["config"]), sha_b)
    assert {c.path for c in single.changes} == {"b.txt"}
    assert single.subjects == ["add b"]
    assert len(single.commits) == 1


def test_divergent_history_lists_post_drift_only(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]

    _write(v1, "shared.txt", "drift-one\n")
    _commit(v1, "v1 drift one")
    _write(v1, "shared.txt", "drift-two\n")
    _commit(v1, "v1 drift two")

    _write(main, "shared.txt", "main update\n")
    _write(main, "keep.txt", "still unchanged\n")
    commit = _commit(main, "update shared and keep")

    result = run_check(load_config(sibling_repos["config"]), commit)
    v1_result = next(v for v in result.variations if v.name == "variation-1")
    shared = next(f for f in v1_result.files if f.path == "shared.txt")
    keep = next(f for f in v1_result.files if f.path == "keep.txt")

    assert shared.status == FileStatus.DIVERGED
    assert [e.subject for e in shared.variant_history] == [
        "v1 drift one",
        "v1 drift two",
    ]
    assert keep.status == FileStatus.SAFE
    assert keep.variant_history == []
