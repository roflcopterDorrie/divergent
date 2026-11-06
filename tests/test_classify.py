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
    status, _ = classify(ChangeKind.MODIFIED, b"a", None)
    assert status == FileStatus.MISSING


def test_deleted_match() -> None:
    status, _ = classify(ChangeKind.DELETED, b"a", b"a")
    assert status == FileStatus.SAFE


def test_deleted_mismatch() -> None:
    status, _ = classify(ChangeKind.DELETED, b"a", b"b")
    assert status == FileStatus.DIVERGED
