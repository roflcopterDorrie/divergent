"""Branch / develop comparison behaviour."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from divergent.compare import FileStatus, run_check
from divergent.config import load_config
from divergent.gitutil import GitError
from divergent.sync_cmd import render_sync_script


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


def test_compares_against_develop_not_other_branch(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]

    # Drift only on a side branch; develop stays identical to main's pre-commit.
    _git(v1, "checkout", "-b", "side")
    _write(v1, "shared.txt", "only on side\n")
    _commit(v1, "side drift")
    # Leave variation checked out on side (should warn), but develop still matches.

    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    v1_result = next(v for v in result.variations if v.name == "variation-1")
    assert v1_result.files[0].status == FileStatus.SAFE
    assert any("expected 'develop'" in w for w in v1_result.warnings)
    assert result.all_safe


def test_warns_when_main_not_on_feature_branch(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _git(main, "checkout", "-b", "not-a-feature")
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    assert any("not-a-feature" in w for w in result.warnings)
    assert any("feature" in w for w in result.warnings)


def test_errors_when_develop_missing(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]
    _git(v1, "checkout", "main")
    _git(v1, "branch", "-D", "develop")

    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")

    with pytest.raises(GitError, match="develop"):
        run_check(load_config(sibling_repos["config"]), commit)


def test_sync_script_creates_feature_from_develop(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")
    result = run_check(load_config(sibling_repos["config"]), commit)
    script = render_sync_script(result, result.variations[0])
    assert "BRANCH=feature/123" in script or 'BRANCH="feature/123"' in script
    assert "BASE=develop" in script or 'BASE="develop"' in script
    assert 'git switch -c "${BRANCH}" "${BASE}"' in script
