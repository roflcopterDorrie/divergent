"""
Full scenario matrix: every classify outcome we expect in practice.

Syncable
  - Added     (new on main, absent on variation)
  - Removed   (deleted on main, matching content on variation)
  - Modified  (updated on main, matching pre-commit on variation)

Unsyncable
  - Diverged modified  (both sides changed from the shared baseline)
  - Missing modified   (changed on main; path never existed on variation)
  - Unexpected add     (added on main, but path already on variation)
  - Diverged delete    (deleted on main, different content on variation)
  - Diverged prior delete (absent on variation because it deleted the path earlier)

Also covered
  - Rename             (safe delete of old path + safe add of new path)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from divergent.compare import FileStatus, run_check
from divergent.config import load_config
from divergent.report_html import _note_label, render_html


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


def _file_map(result, variation_name: str) -> dict[str, object]:
    var = next(v for v in result.variations if v.name == variation_name)
    return {f.path: f for f in var.files}


def _prepare_matrix(sibling_repos: dict[str, Path]) -> str:
    """
    Build one main commit that exercises every scenario against variation-1.

    variation-2 is left matching so those paths stay syncable there.
    """
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]

    # Shared baseline files on main + both variations.
    # unsync_missing.txt is only on main/v2 (never existed on v1).
    for repo in (main, sibling_repos["v2"]):
        _write(repo, "unsync_missing.txt", "only-main-will-keep\n")
    for repo in (main, v1, sibling_repos["v2"]):
        _write(repo, "sync_modified.txt", "base\n")
        _write(repo, "sync_removed.txt", "delete-me\n")
        _write(repo, "unsync_diverged.txt", "base\n")
        _write(repo, "unsync_del_diverged.txt", "delete-base\n")
        _write(repo, "unsync_del_missing.txt", "already-gone\n")
        _write(repo, "rename_me.txt", "rename-base\n")
    _commit(main, "matrix baseline on main")
    _commit(v1, "matrix baseline on v1")
    _commit(sibling_repos["v2"], "matrix baseline on v2")

    # Variation-1 drifts / special cases on develop.
    _write(v1, "unsync_diverged.txt", "v1-drift\n")
    _write(v1, "unsync_del_diverged.txt", "v1-different\n")
    (v1 / "unsync_del_missing.txt").unlink()
    _write(v1, "unsync_unexpected.txt", "already-on-v1\n")
    _commit(v1, "v1 matrix drifts")

    # Main feature commit covering every change kind.
    _write(main, "sync_added.txt", "brand-new\n")
    _write(main, "sync_modified.txt", "updated\n")
    (main / "sync_removed.txt").unlink()
    _write(main, "unsync_diverged.txt", "main-updated\n")
    _write(main, "unsync_missing.txt", "main-updated-missing-on-v1\n")
    _write(main, "unsync_unexpected.txt", "main-adds-existing\n")
    (main / "unsync_del_diverged.txt").unlink()
    (main / "unsync_del_missing.txt").unlink()
    _git(main, "mv", "rename_me.txt", "renamed.txt")
    return _commit(main, "matrix commit")


def test_scenario_matrix_statuses(sibling_repos: dict[str, Path]) -> None:
    commit = _prepare_matrix(sibling_repos)
    result = run_check(load_config(sibling_repos["config"]), commit)
    files = _file_map(result, "variation-1")

    expected = {
        # Syncable
        "sync_added.txt": FileStatus.SAFE,
        "sync_modified.txt": FileStatus.SAFE,
        "sync_removed.txt": FileStatus.SAFE,
        # Unsyncable
        "unsync_diverged.txt": FileStatus.DIVERGED,
        "unsync_missing.txt": FileStatus.MISSING,
        "unsync_unexpected.txt": FileStatus.UNEXPECTED,
        "unsync_del_diverged.txt": FileStatus.DIVERGED,
        # Existed on v1 then deleted → divergent (not merely missing).
        "unsync_del_missing.txt": FileStatus.DIVERGED,
        # Rename = safe delete + safe add
        "rename_me.txt": FileStatus.SAFE,
        "renamed.txt": FileStatus.SAFE,
    }
    assert {path: files[path].status for path in expected} == expected  # type: ignore[attr-defined]

    notes = {
        path: _note_label(files[path], compare_ref="develop")  # type: ignore[arg-type]
        for path in expected
    }
    assert notes == {
        "sync_added.txt": "Safe to add",
        "sync_modified.txt": "Safe to update",
        "sync_removed.txt": "Safe to delete",
        "unsync_diverged.txt": "Divergent",
        "unsync_missing.txt": "Missing on variant/develop",
        "unsync_unexpected.txt": "Already exists",
        "unsync_del_diverged.txt": "Divergent",
        "unsync_del_missing.txt": "Divergent",
        "rename_me.txt": "Safe to delete",
        "renamed.txt": "Safe to rename",
    }

    # variation-2 never drifted: every path that exists there should be syncable.
    v2 = _file_map(result, "variation-2")
    for path, status in {
        "sync_added.txt": FileStatus.SAFE,
        "sync_modified.txt": FileStatus.SAFE,
        "sync_removed.txt": FileStatus.SAFE,
        "unsync_diverged.txt": FileStatus.SAFE,
        "unsync_missing.txt": FileStatus.SAFE,
        "unsync_unexpected.txt": FileStatus.SAFE,
        "unsync_del_diverged.txt": FileStatus.SAFE,
        "unsync_del_missing.txt": FileStatus.SAFE,
        "rename_me.txt": FileStatus.SAFE,
        "renamed.txt": FileStatus.SAFE,
    }.items():
        assert v2[path].status == status  # type: ignore[attr-defined]


def test_scenario_matrix_html_labels_and_defaults(
    sibling_repos: dict[str, Path],
) -> None:
    commit = _prepare_matrix(sibling_repos)
    result = run_check(load_config(sibling_repos["config"]), commit)
    html = render_html(result)

    # Variation tabs present.
    assert "variation-1" in html
    assert "variation-2" in html
    assert "selectTab" in html

    # Note column labels for every scenario.
    for label in (
        "Safe to add",
        "Safe to update",
        "Safe to delete",
        "Safe to rename",
        "Divergent",
        "Missing on",
        "Already exists",
        "branch-pill",
    ):
        assert label in html

    assert "variant/develop" in html
    assert "Safe" in html
    assert "Review" in html
    assert "force-sync" in html
    assert "ignore-sync" in html
    assert "Copy command" in html
    assert "Files changed by commit" not in html
    assert "<h3>Stage</h3>" in html
    assert "<h3>Commit message</h3>" in html

    # Defaults: syncable files start with Sync checked; unsyncable with Ignore.
    v1 = next(v for v in result.variations if v.name == "variation-1")
    for f in v1.files:
        path = f.path
        if f.status == FileStatus.SAFE:
            assert (
                f'data-path="{path}" checked' in html
                or f"data-path='{path}' checked" in html
                or f'data-path="{path}"' in html
            )
            # Sync checkbox appears before Ignore for each row; safe rows have
            # the sync input checked and ignore unchecked.
            sync_marker = (
                f'class="force-sync" data-var="0" data-path="{path}" checked'
            )
            ignore_marker = (
                f'class="ignore-sync" data-var="0" data-path="{path}" '
            )
            assert sync_marker in html
            assert ignore_marker in html
            # Ignore should not be checked for syncable defaults.
            assert (
                f'class="ignore-sync" data-var="0" data-path="{path}" checked'
                not in html
            )
        else:
            assert (
                f'class="ignore-sync" data-var="0" data-path="{path}" checked'
                in html
            )
            assert (
                f'class="force-sync" data-var="0" data-path="{path}" checked'
                not in html
            )
