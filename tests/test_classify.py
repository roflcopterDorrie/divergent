"""Unit tests for classify()."""

from __future__ import annotations

from divergent.compare import ChangeKind, FileStatus, classify


def test_added_absent() -> None:
    status, _ = classify(ChangeKind.ADDED, None, None)
    assert status == FileStatus.SAFE


def test_added_present() -> None:
    status, _ = classify(ChangeKind.ADDED, None, b"x")
    assert status == FileStatus.UNEXPECTED


def test_modified_match() -> None:
    status, _ = classify(ChangeKind.MODIFIED, b"a", b"a")
    assert status == FileStatus.SAFE


def test_modified_mismatch() -> None:
    status, _ = classify(ChangeKind.MODIFIED, b"a", b"b")
    assert status == FileStatus.DIVERGED


def test_modified_missing() -> None:
    status, detail = classify(
        ChangeKind.MODIFIED,
        b"a",
        None,
        compare_ref="develop",
        main_branch="feature/demo-matrix",
    )
    assert status == FileStatus.MISSING
    assert "base/feature/demo-matrix" in detail
    assert "variant/develop" in detail
    assert "modified it" in detail
    assert "does not have this path" in detail


def test_deleted_match() -> None:
    status, detail = classify(
        ChangeKind.DELETED, b"a", b"a", compare_ref="develop"
    )
    assert status == FileStatus.SAFE
    assert detail.startswith("Safe to delete")
    assert "variant/develop" in detail


def test_deleted_mismatch() -> None:
    status, detail = classify(
        ChangeKind.DELETED,
        b"a",
        b"b",
        compare_ref="develop",
        main_branch="feature/demo-matrix",
    )
    assert status == FileStatus.DIVERGED
    assert "trying to delete" in detail
    assert "base/feature/demo-matrix" in detail
    assert "variant/develop" in detail
    assert "divergent" in detail


def test_modified_mismatch_detail() -> None:
    status, detail = classify(
        ChangeKind.MODIFIED,
        b"a",
        b"b",
        compare_ref="develop",
        main_branch="feature/123",
    )
    assert status == FileStatus.DIVERGED
    assert "trying to update" in detail
    assert "base/feature/123" in detail
    assert "variant/develop" in detail
    assert "divergent" in detail


def test_deleted_missing() -> None:
    status, detail = classify(
        ChangeKind.DELETED,
        b"a",
        None,
        compare_ref="develop",
        main_branch="feature/demo-matrix",
    )
    assert status == FileStatus.MISSING
    assert "deleted it" in detail
    assert "does not have this path" in detail
    assert "base/feature/demo-matrix" in detail
    assert "variant/develop" in detail


def test_added_detail_messages() -> None:
    _, absent = classify(ChangeKind.ADDED, None, None, compare_ref="develop")
    _, present = classify(
        ChangeKind.ADDED,
        None,
        b"x",
        compare_ref="develop",
        main_branch="feature/123",
    )
    assert absent.startswith("Safe to add")
    assert "variant/develop" in absent
    assert "Already exists on variant/develop" in present
    assert "base/feature/123" in present


def test_rename_add_detail() -> None:
    status, detail = classify(
        ChangeKind.ADDED,
        None,
        None,
        compare_ref="develop",
        old_path="rename_me.txt",
    )
    assert status == FileStatus.SAFE
    assert detail.startswith("Safe to rename")
    assert "rename_me.txt" in detail


def test_modified_match_detail() -> None:
    _, detail = classify(
        ChangeKind.MODIFIED,
        b"a",
        b"a",
        compare_ref="develop",
        main_branch="feature/123",
    )
    assert detail.startswith("Safe to update")
    assert "variant/develop" in detail
    assert "base/feature/123" in detail
