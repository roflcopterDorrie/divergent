"""Compare main-repo commit changes against variation repos."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from divergent import gitutil
from divergent.config import Config


class ChangeKind(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class FileStatus(str, Enum):
    SAFE = "safe"
    DIVERGED = "diverged"
    MISSING = "missing"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class FileChange:
    """A single path change introduced by the commit (post-rename expansion)."""

    kind: ChangeKind
    path: str
    """Path in the relevant tree (new path for adds/modifies; deleted path for deletes)."""
    old_path: str | None = None
    """Set when this add came from a rename/copy (the previous path)."""


@dataclass(frozen=True)
class FileDiff:
    """Byte contents for a two-sided comparison shown in the report."""

    left_label: str
    right_label: str
    left: bytes | None
    right: bytes | None


@dataclass(frozen=True)
class FileResult:
    path: str
    kind: ChangeKind
    status: FileStatus
    detail: str = ""
    diff: FileDiff | None = None


@dataclass
class VariationResult:
    name: str
    path: Path
    compare_ref: str
    current_branch: str | None = None
    files: list[FileResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[FileStatus, int]:
        out = {s: 0 for s in FileStatus}
        for f in self.files:
            out[f.status] += 1
        return out

    @property
    def all_safe(self) -> bool:
        return all(f.status == FileStatus.SAFE for f in self.files)


@dataclass
class CheckResult:
    commit: str
    parent: str
    subject: str
    message: str
    date: str
    main_repo: Path
    main_branch: str | None
    variation_base_branch: str
    changes: list[FileChange]
    variations: list[VariationResult]
    warnings: list[str] = field(default_factory=list)

    @property
    def all_safe(self) -> bool:
        return all(v.all_safe for v in self.variations)

    @property
    def all_warnings(self) -> list[str]:
        out = list(self.warnings)
        for var in self.variations:
            out.extend(var.warnings)
        return out


def expand_changes(entries: list[tuple[str, str, str | None]]) -> list[FileChange]:
    """
    Turn git name-status entries into FileChange records.

    Renames become a DELETED on the old path plus an ADDED on the new path
    (so each side is compared with the correct rule).
    """
    changes: list[FileChange] = []
    for status, path, old_path in entries:
        if status == "A":
            changes.append(FileChange(ChangeKind.ADDED, path))
        elif status == "M" or status == "T":
            changes.append(FileChange(ChangeKind.MODIFIED, path))
        elif status == "D":
            changes.append(FileChange(ChangeKind.DELETED, path))
        elif status in ("R", "C"):
            assert old_path is not None
            if status == "R":
                changes.append(FileChange(ChangeKind.DELETED, old_path))
            changes.append(FileChange(ChangeKind.ADDED, path, old_path=old_path))
        else:
            changes.append(FileChange(ChangeKind.MODIFIED, path))
    return changes


def classify(
    kind: ChangeKind,
    pre_bytes: bytes | None,
    var_bytes: bytes | None,
) -> tuple[FileStatus, str]:
    """
    Classify one path for one variation.

    *pre_bytes*: content in main at C^ (None if path did not exist).
    *var_bytes*: content in variation at the base branch (None if path does not exist).
    """
    if kind == ChangeKind.ADDED:
        if var_bytes is None:
            return FileStatus.SAFE, "path absent on base branch; safe to add"
        return FileStatus.UNEXPECTED, "path already exists on base branch"

    if pre_bytes is None:
        if var_bytes is None:
            return FileStatus.SAFE, "path absent on both sides"
        return FileStatus.UNEXPECTED, "no pre-commit content in main but path exists on base branch"

    if var_bytes is None:
        return FileStatus.MISSING, "path missing on base branch"

    if pre_bytes == var_bytes:
        if kind == ChangeKind.DELETED:
            return FileStatus.SAFE, "pre-commit content matches base branch; safe to delete"
        return FileStatus.SAFE, "pre-commit content matches base branch; safe to update"

    return FileStatus.DIVERGED, "pre-commit content differs from base branch"


def _build_diff(
    status: FileStatus,
    variation_name: str,
    compare_ref: str,
    parent: str,
    commit: str,
    pre: bytes | None,
    post: bytes | None,
    var: bytes | None,
) -> FileDiff | None:
    parent_short = parent[:12] if parent != gitutil.EMPTY_TREE_SHA else "empty-tree"
    commit_short = commit[:12]
    if status == FileStatus.DIVERGED:
        return FileDiff(
            left_label=f"{variation_name}:{compare_ref}",
            right_label=f"main:{parent_short} (pre-commit)",
            left=var,
            right=pre,
        )
    if status == FileStatus.UNEXPECTED:
        return FileDiff(
            left_label=f"{variation_name}:{compare_ref}",
            right_label=f"main:{commit_short} (incoming)",
            left=var,
            right=post,
        )
    if status == FileStatus.MISSING:
        return FileDiff(
            left_label=f"{variation_name}:{compare_ref} (missing)",
            right_label=f"main:{parent_short} (pre-commit)",
            left=None,
            right=pre,
        )
    return None


def list_commit_changes(main_repo: Path, commit: str) -> list[FileChange]:
    parent = gitutil.parent_tree(main_repo, commit)
    entries = gitutil.name_status(main_repo, parent, commit)
    return expand_changes(entries)


def check_variation(
    main_repo: Path,
    parent: str,
    commit: str,
    variation: Path,
    changes: list[FileChange],
    compare_ref: str,
) -> VariationResult:
    name = variation.name
    warnings: list[str] = []
    current = gitutil.current_branch(variation)

    if not gitutil.ref_exists(variation, compare_ref):
        raise gitutil.GitError(
            f"variation {name!r} has no branch/ref {compare_ref!r} to compare against"
        )

    if current is None:
        warnings.append(
            f"{name}: checked out in detached HEAD state "
            f"(expected branch {compare_ref!r}; still comparing against {compare_ref!r})"
        )
    elif current != compare_ref:
        warnings.append(
            f"{name}: currently on branch {current!r}, expected {compare_ref!r} "
            f"(still comparing against {compare_ref!r})"
        )

    results: list[FileResult] = []
    for change in changes:
        if change.kind == ChangeKind.ADDED:
            pre = None
        else:
            pre = gitutil.blob_at(main_repo, parent, change.path)

        if change.kind == ChangeKind.DELETED:
            post = None
        else:
            post = gitutil.blob_at(main_repo, commit, change.path)

        var = gitutil.blob_at(variation, compare_ref, change.path)
        status, detail = classify(change.kind, pre, var)
        diff = _build_diff(status, name, compare_ref, parent, commit, pre, post, var)
        results.append(
            FileResult(
                path=change.path,
                kind=change.kind,
                status=status,
                detail=detail,
                diff=diff,
            )
        )
    return VariationResult(
        name=name,
        path=variation,
        compare_ref=compare_ref,
        current_branch=current,
        files=results,
        warnings=warnings,
    )


def run_check(config: Config, commit_ref: str = "HEAD") -> CheckResult:
    """Run the diverge check for *commit_ref* against all configured variations."""
    main = config.main_repo
    commit = gitutil.rev_parse(main, commit_ref)
    parent = gitutil.parent_tree(main, commit)
    subject = gitutil.commit_subject(main, commit)
    message = gitutil.commit_message(main, commit)
    date = gitutil.commit_date(main, commit)
    changes = list_commit_changes(main, commit)
    main_branch = gitutil.current_branch(main)
    base = config.variation_base_branch

    warnings: list[str] = []
    if main_branch is None:
        warnings.append(
            "main repo is in detached HEAD state "
            f"(expected a branch matching /{config.main_branch_pattern}/)"
        )
    elif not config.main_branch_regex.match(main_branch):
        warnings.append(
            f"main repo is on branch {main_branch!r}, "
            f"expected a name matching /{config.main_branch_pattern}/"
        )

    variations = [
        check_variation(main, parent, commit, var_path, changes, base)
        for var_path in config.variations
    ]
    return CheckResult(
        commit=commit,
        parent=parent,
        subject=subject,
        message=message,
        date=date,
        main_repo=main,
        main_branch=main_branch,
        variation_base_branch=base,
        changes=changes,
        variations=variations,
        warnings=warnings,
    )
