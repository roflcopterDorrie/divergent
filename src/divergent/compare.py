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
class VariantFileCommit:
    """A variation commit that touched a divergent path after drift began."""

    commit: str
    subject: str
    action: str


@dataclass(frozen=True)
class FileResult:
    path: str
    kind: ChangeKind
    status: FileStatus
    detail: str = ""
    diff: FileDiff | None = None
    old_path: str | None = None
    """Set when this add came from a rename/copy (the previous path)."""
    variant_history: list[VariantFileCommit] = field(default_factory=list)
    """Populated only when status is DIVERGED."""


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
    """Tip (post) commit SHA of the compared range."""
    parent: str
    """Start (pre / fork) commit SHA of the compared range."""
    subject: str
    message: str
    date: str
    main_repo: Path
    main_branch: str | None
    variation_base_branch: str
    changes: list[FileChange]
    variations: list[VariationResult]
    warnings: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    """SHAs in the range, oldest first."""
    subjects: list[str] = field(default_factory=list)
    """Subjects for commits in the range, oldest first."""

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


def main_branch_label(main_branch: str | None) -> str:
    """Display label for the main repo branch, e.g. ``base/feature/123``."""
    if main_branch:
        return f"base/{main_branch}"
    return "base/(detached HEAD)"


def variant_branch_label(compare_ref: str) -> str:
    """Display label for the variation compare ref, e.g. ``variant/develop``."""
    return f"variant/{compare_ref}"


def classify(
    kind: ChangeKind,
    pre_bytes: bytes | None,
    var_bytes: bytes | None,
    *,
    compare_ref: str = "base branch",
    main_branch: str | None = None,
    old_path: str | None = None,
) -> tuple[FileStatus, str]:
    """
    Classify one path for one variation.

    *pre_bytes*: content in main at the range start / fork (None if path did not exist).
    *var_bytes*: content in variation at the base branch (None if path does not exist).
    *compare_ref*: variation branch/ref name used in messages.
    *main_branch*: main repo branch name used in ``base/…`` messages.
    *old_path*: previous path when this add came from a rename/copy.
    """
    base = main_branch_label(main_branch)
    variant = variant_branch_label(compare_ref)

    if kind == ChangeKind.ADDED:
        if var_bytes is None:
            if old_path:
                return (
                    FileStatus.SAFE,
                    f"Safe to rename — {old_path} → this path; "
                    f"not on {variant} yet.",
                )
            return (
                FileStatus.SAFE,
                f"Safe to add — this path is not on {variant} yet.",
            )
        return (
            FileStatus.UNEXPECTED,
            f"Already exists on {variant}. {base} is adding this path, "
            "but the variation already has a file there.",
        )

    if pre_bytes is None:
        if var_bytes is None:
            return (
                FileStatus.SAFE,
                "Path is absent on both sides.",
            )
        return (
            FileStatus.UNEXPECTED,
            f"Unexpected on {variant}. {base} had no prior version of this "
            "path, but the variation already has one.",
        )

    if var_bytes is None:
        # Provisional: check_variation refines never-existed vs deleted-on-variant.
        if kind == ChangeKind.DELETED:
            return (
                FileStatus.MISSING,
                f"{base} had the file and deleted it; "
                f"{variant} does not have this path.",
            )
        return (
            FileStatus.MISSING,
            f"{base} had the file and modified it; "
            f"{variant} does not have this path.",
        )

    if pre_bytes == var_bytes:
        if kind == ChangeKind.DELETED:
            return (
                FileStatus.SAFE,
                f"Safe to delete — {variant} still matches "
                f"{base}'s version from before this commit.",
            )
        return (
            FileStatus.SAFE,
            f"Safe to update — {variant} still matches "
            f"{base}'s version from before this commit.",
        )

    if kind == ChangeKind.DELETED:
        return (
            FileStatus.DIVERGED,
            f"{base} is trying to delete this file from {variant}, "
            "but the file is divergent.",
        )
    return (
        FileStatus.DIVERGED,
        f"{base} is trying to update this file on {variant}, "
        "but the file is divergent.",
    )


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
            right_label=f"main:{parent_short} (fork)",
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
            right_label=f"main:{parent_short} (fork)",
            left=None,
            right=pre,
        )
    return None


def list_range_changes(main_repo: Path, start: str, end: str) -> list[FileChange]:
    """Net path changes between *start* and *end* trees."""
    entries = gitutil.name_status(main_repo, start, end)
    return expand_changes(entries)


def list_commit_changes(main_repo: Path, commit: str) -> list[FileChange]:
    parent = gitutil.parent_tree(main_repo, commit)
    return list_range_changes(main_repo, parent, commit)


def resolve_compare_range(
    main_repo: Path,
    commit_ref: str | None,
    main_base_branch: str,
) -> tuple[str, str, list[str], list[str]]:
    """
    Resolve (*start*, *end*, commit_shas oldest-first, subjects).

    *commit_ref* None → merge-base(HEAD, main_base_branch)..HEAD
    ``A..B`` → explicit range
    single ref → parent(ref)..ref
    """
    if commit_ref is None:
        tip = gitutil.rev_parse(main_repo, "HEAD")
        if not gitutil.ref_exists(main_repo, main_base_branch):
            raise gitutil.GitError(
                f"main base branch {main_base_branch!r} not found "
                f"(needed to find where the feature forked)"
            )
        fork = gitutil.merge_base(main_repo, tip, main_base_branch)
        commits = gitutil.commits_in_range(main_repo, fork, tip)
        subjects = gitutil.log_subjects(main_repo, fork, tip)
        return fork, tip, commits, subjects

    if ".." in commit_ref:
        left, right = commit_ref.split("..", 1)
        if not left or not right:
            raise gitutil.GitError(f"invalid revision range: {commit_ref!r}")
        start = gitutil.rev_parse(main_repo, left)
        end = gitutil.rev_parse(main_repo, right)
        commits = gitutil.commits_in_range(main_repo, start, end)
        subjects = gitutil.log_subjects(main_repo, start, end)
        return start, end, commits, subjects

    tip = gitutil.rev_parse(main_repo, commit_ref)
    parent = gitutil.parent_tree(main_repo, tip)
    commits = [tip]
    subjects = [gitutil.commit_subject(main_repo, tip)]
    return parent, tip, commits, subjects


def _history_entries_to_commits(
    entries: list[gitutil.PathCommitEntry],
) -> list[VariantFileCommit]:
    return [
        VariantFileCommit(
            commit=e.commit[:12],
            subject=e.subject,
            action=e.action,
        )
        for e in entries
    ]


def divergent_path_history(
    variation: Path,
    compare_ref: str,
    path: str,
    fork_blob: bytes | None,
) -> list[VariantFileCommit]:
    """
    Variation commits that touched *path* after content diverged from *fork_blob*.

    Newest-first log is walked; commits after the last match to *fork_blob*
    are returned oldest-first for display. If never matched, all path commits.
    """
    entries = gitutil.path_log_with_status(variation, compare_ref, path)
    if not entries:
        return []

    # entries are newest first
    cutoff = len(entries)  # default: all are post-divergence
    if fork_blob is not None:
        for i, entry in enumerate(entries):
            blob = gitutil.blob_at(variation, entry.commit, path)
            if blob == fork_blob:
                cutoff = i
                break

    post = entries[:cutoff]  # still newest first
    post.reverse()  # oldest first for display
    return _history_entries_to_commits(post)


def history_since_variant_deletion(
    entries: list[gitutil.PathCommitEntry],
) -> list[VariantFileCommit]:
    """
    Commits from the newest deletion of *path* onward (oldest-first).

    *entries* must be newest-first from ``path_log_with_status``.
    """
    if not entries:
        return []
    cutoff = 0
    for i, entry in enumerate(entries):
        if entry.action == "deleted":
            cutoff = i
            break
    else:
        # Touched before but no delete status (e.g. renamed away): show all.
        cutoff = len(entries) - 1
    post = entries[: cutoff + 1]
    post.reverse()
    return _history_entries_to_commits(post)


def refine_missing_on_variant(
    *,
    kind: ChangeKind,
    compare_ref: str,
    main_branch: str | None,
    variation: Path,
    path: str,
) -> tuple[FileStatus, str, list[VariantFileCommit]]:
    """
    When the path is absent on the variation tip, distinguish:

    - never existed on the branch → MISSING
    - existed then deleted → DIVERGED, with history since that deletion
    """
    base = main_branch_label(main_branch)
    variant = variant_branch_label(compare_ref)
    entries = gitutil.path_log_with_status(variation, compare_ref, path)

    if not entries:
        if kind == ChangeKind.DELETED:
            detail = (
                f"{base} had the file and deleted it; "
                f"{variant} never had this path."
            )
        else:
            detail = (
                f"{base} had the file and modified it; "
                f"{variant} never had this path."
            )
        return FileStatus.MISSING, detail, []

    history = history_since_variant_deletion(entries)
    if kind == ChangeKind.DELETED:
        detail = (
            f"{base} is trying to delete this file from {variant}, "
            "but the variation already deleted it earlier."
        )
    else:
        detail = (
            f"{base} is trying to update this file on {variant}, "
            "but the variation deleted it earlier."
        )
    return FileStatus.DIVERGED, detail, history


def check_variation(
    main_repo: Path,
    parent: str,
    commit: str,
    variation: Path,
    changes: list[FileChange],
    compare_ref: str,
    main_branch: str | None = None,
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
        status, detail = classify(
            change.kind,
            pre,
            var,
            compare_ref=compare_ref,
            main_branch=main_branch,
            old_path=change.old_path,
        )
        history: list[VariantFileCommit] = []
        if status == FileStatus.MISSING:
            status, detail, history = refine_missing_on_variant(
                kind=change.kind,
                compare_ref=compare_ref,
                main_branch=main_branch,
                variation=variation,
                path=change.path,
            )
        elif status == FileStatus.DIVERGED:
            history = divergent_path_history(
                variation, compare_ref, change.path, pre
            )
        diff = _build_diff(status, name, compare_ref, parent, commit, pre, post, var)
        results.append(
            FileResult(
                path=change.path,
                kind=change.kind,
                status=status,
                detail=detail,
                diff=diff,
                old_path=change.old_path,
                variant_history=history,
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


def run_check(config: Config, commit_ref: str | None = None) -> CheckResult:
    """
    Run the diverge check against all configured variations.

    *commit_ref*:
      - None: merge-base(HEAD, main_base_branch)..HEAD
      - ``A..B``: explicit range
      - single ref: that commit vs its parent
    """
    main = config.main_repo
    parent, commit, commits, subjects = resolve_compare_range(
        main, commit_ref, config.main_base_branch
    )
    if commits:
        subject = subjects[-1] if subjects else gitutil.commit_subject(main, commit)
        date = gitutil.commit_date(main, commit)
        if len(commits) == 1:
            message = gitutil.commit_message(main, commit)
        else:
            # Multi-commit: bullet list of subjects for the message box /
            # sync script body.
            message = "\n".join(f"- {s}" for s in subjects) + "\n"
    else:
        subject = "(no commits in range)"
        message = ""
        date = ""

    changes = list_range_changes(main, parent, commit) if commits else []
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
        check_variation(
            main, parent, commit, var_path, changes, base, main_branch
        )
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
        commits=commits,
        subjects=subjects,
    )
