"""HTML report and sync script tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from divergent.compare import FileStatus, run_check
from divergent.config import load_config
from divergent.report_html import format_unified_diff, render_diff_html, render_html
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


def test_html_syncable_includes_script(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared\n\nMore detail.\n")

    result = run_check(load_config(sibling_repos["config"]), commit)
    html = render_html(result)

    assert "Fully syncable" in html
    assert "update shared" in html
    assert "More detail." in html
    assert str(main.resolve()) in html or "git -C" in html
    assert "git commit -F -" in html
    script = render_sync_script(result, result.variations[0])
    assert "shared.txt" in script
    assert "set -euo pipefail" in script


def test_html_diverged_includes_diff(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]
    _write(v1, "shared.txt", "drifted line\n")
    _commit(v1, "drift")
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    html = render_html(result)

    assert "Not syncable" in html
    assert "Show side-by-side diff" in html
    assert "diff-view" in html
    assert "diff_add" in html or "diff_sub" in html or "diff_chg" in html
    # HtmlDiff encodes spaces as &nbsp;
    assert "drifted" in html
    assert "hello" in html  # pre-commit content in diff

    v1_result = next(v for v in result.variations if v.name == "variation-1")
    file_result = next(f for f in v1_result.files if f.path == "shared.txt")
    assert file_result.status == FileStatus.DIVERGED
    assert file_result.diff is not None
    text, binary = format_unified_diff(file_result.diff)
    assert not binary
    assert "drifted line" in text
    frag, frag_binary = render_diff_html(file_result.diff)
    assert not frag_binary
    assert "diff_add" in frag or "diff_sub" in frag or "diff_chg" in frag
    assert "drifted&nbsp;line" in frag or "drifted line" in frag


def test_html_escapes_xss(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _write(main, "shared.txt", "hello <script>alert(1)</script>\n")
    commit = _commit(main, "update <script>alert(1)</script>")

    result = run_check(load_config(sibling_repos["config"]), commit)
    html = render_html(result)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
