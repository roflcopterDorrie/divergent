"""HTML report and sync script tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from divergent.compare import FileStatus, run_check
from divergent.config import load_config
from divergent.report_html import format_unified_diff, render_diff_html, render_html
from divergent.sync_cmd import (
    assemble_commit_message_text,
    assemble_stage_commands,
    assemble_sync_script,
    default_synced_paths,
    optional_sync_files,
    render_sync_script,
    sync_script_data,
)


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

    assert "Copy command" in html
    assert "update shared" in html
    assert "More detail." in html
    assert "role=\"tablist\"" in html or "role='tablist'" in html
    assert "force-sync" in html
    assert "ignore-sync" in html
    assert "Safe" in html
    assert str(main.resolve()) in html or "git -C" in html
    assert "git switch -c" in html
    script = render_sync_script(result, result.variations[0])
    assert "shared.txt" in script
    assert "set -euo pipefail" in script
    assert 'git switch -c "${BRANCH}" "${BASE}"' in script
    assert "feature/123" in script
    assert "develop" in script
    assert "Partial sync" not in script
    assert "git add" not in script
    assert "git rm" not in script
    assert "git commit" not in script
    assert "git -C" in script


def test_html_has_variation_tabs(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")
    result = run_check(load_config(sibling_repos["config"]), commit)
    html = render_html(result)
    assert "variation-1" in html
    assert "variation-2" in html
    assert "selectTab(0)" in html
    assert "selectTab(1)" in html
    assert 'class="tab-panel active"' in html or "class='tab-panel active'" in html


def test_html_diverged_includes_diff(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]
    _write(v1, "shared.txt", "drifted line\n")
    _commit(v1, "drift")
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    html = render_html(result)

    assert "Divergent" in html
    assert "Review" in html
    assert "diff-view" in html
    assert "diff_add" in html or "diff_sub" in html or "diff_chg" in html
    assert "drifted" in html
    assert "hello" in html
    assert "file-row" in html

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


def test_html_partial_sync_defaults_ignore_unsyncable(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]
    _write(v1, "dist.txt", "site-a build\n")
    _commit(v1, "site dist")
    _write(main, "shared.txt", "hello world\n")
    _write(main, "dist.txt", "main build\n")
    commit = _commit(main, "update shared and dist")

    result = run_check(load_config(sibling_repos["config"]), commit)
    html = render_html(result)

    assert "Copy command" in html
    assert "shared.txt" in html
    assert "dist.txt" in html
    assert "Ignored (acknowledged, not synced)" in html

    v1_result = next(v for v in result.variations if v.name == "variation-1")
    script = render_sync_script(result, v1_result)
    assert "shared.txt" in script
    assert "#   unexpected dist.txt" in script
    assert "Ignored (acknowledged, not synced)" in script
    for line in script.splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert "dist.txt" not in line


def test_html_escapes_xss(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    _write(main, "shared.txt", "hello <script>alert(1)</script>\n")
    commit = _commit(main, "update <script>alert(1)</script>")

    result = run_check(load_config(sibling_repos["config"]), commit)
    html = render_html(result)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_missing_never_existed_defaults_to_ignore(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    _write(main, "main_only.txt", "only on main\n")
    _commit(main, "add main_only")
    _write(main, "main_only.txt", "hello world\n")
    commit = _commit(main, "update main_only")

    result = run_check(load_config(sibling_repos["config"]), commit)
    v1_result = next(v for v in result.variations if v.name == "variation-1")
    missing = next(f for f in v1_result.files if f.path == "main_only.txt")
    assert missing.status == FileStatus.MISSING
    assert "never had this path" in missing.detail
    assert optional_sync_files(v1_result)

    html = render_html(result)
    assert "Missing on" in html
    assert "variant/develop" in html
    assert "branch-pill" in html
    assert "never had this path" in html
    assert "force-sync" in html
    assert "ignore-sync" in html
    assert "rebuildSyncScript" in html
    assert "Copy command" in html
    assert "sync-data-" in html

    script = render_sync_script(result, v1_result, include=list(v1_result.files))
    assert "main_only.txt" in script
    assert "git -C" in script
    assert "git add" not in script


def test_html_deleted_on_variant_shows_divergent_history(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]
    (v1 / "shared.txt").unlink()
    _commit(v1, "remove shared from develop")
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    v1_result = next(v for v in result.variations if v.name == "variation-1")
    shared = next(f for f in v1_result.files if f.path == "shared.txt")
    assert shared.status == FileStatus.DIVERGED
    assert "deleted it earlier" in shared.detail
    assert [e.subject for e in shared.variant_history] == [
        "remove shared from develop"
    ]

    html = render_html(result)
    assert "Divergent" in html
    assert "Variant history since divergence" in html
    assert "remove shared from develop" in html


def test_html_diverged_can_force_sync(sibling_repos: dict[str, Path]) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]
    _write(v1, "shared.txt", "drifted line\n")
    _commit(v1, "drift")
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    v1_result = next(v for v in result.variations if v.name == "variation-1")
    assert v1_result.files[0].status == FileStatus.DIVERGED
    assert optional_sync_files(v1_result)

    html = render_html(result)
    assert "force-sync" in html
    assert "ignore-sync" in html
    assert "Copy command" in html

    script = render_sync_script(result, v1_result, include=list(v1_result.files))
    assert "shared.txt" in script
    assert "git add" not in script
    assert "git commit" not in script
    for line in script.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if "shared.txt" in line:
            break
    else:
        raise AssertionError("shared.txt not in active sync commands")


def test_ignored_path_listed_separately_in_script(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]
    _write(v1, "dist.txt", "site-a build\n")
    _commit(v1, "site dist")
    _write(main, "shared.txt", "hello world\n")
    _write(main, "dist.txt", "main build\n")
    commit = _commit(main, "update shared and dist")

    result = run_check(load_config(sibling_repos["config"]), commit)
    v1_result = next(v for v in result.variations if v.name == "variation-1")
    data = sync_script_data(result, v1_result)
    script = assemble_sync_script(data, {"shared.txt"}, {"dist.txt"})
    assert script is not None
    assert "Ignored (acknowledged, not synced):" in script
    assert "#   unexpected dist.txt" in script or "#   diverged dist.txt" in script
    assert "Partial sync — skipped" not in script
    assert "shared.txt" in script


def test_html_has_stage_and_message_boxes_not_files_panel(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    _write(main, "shared.txt", "hello world\n")
    commit = _commit(main, "update shared\n\nBody line.\n")

    result = run_check(load_config(sibling_repos["config"]), commit)
    html = render_html(result)

    assert "Files changed by commit" not in html
    assert "changed-files" not in html
    assert "<h3>Stage</h3>" in html
    assert "<h3>Commit message</h3>" in html
    assert "id='stage-0'" in html or 'id="stage-0"' in html
    assert "id='msg-0'" in html or 'id="msg-0"' in html
    assert "rebuildStageBox" in html
    assert "rebuildMessageBox" in html
    assert "git add --" in html
    assert "git commit -m" in html
    assert "feature-name-0" in html
    assert "update shared" in html
    assert "Body line." in html

    v0 = result.variations[0]
    data = sync_script_data(result, v0)
    stage = assemble_stage_commands(data, default_synced_paths(v0))
    assert "git add --" in stage
    assert "shared.txt" in stage
    msg = assemble_commit_message_text(data, "My feature")
    assert msg.startswith("git commit -m ")
    assert "My feature" in msg
    assert "update shared" in msg
    assert "Body line." in msg


def test_html_multi_commit_message_uses_subjects(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    _write(main, "a.txt", "a\n")
    _commit(main, "add a")
    _write(main, "b.txt", "b\n")
    _commit(main, "add b")

    result = run_check(load_config(sibling_repos["config"]))
    html = render_html(result)
    assert "- add a" in html
    assert "- add b" in html
    assert "git commit -m" in html

    data = sync_script_data(result, result.variations[0])
    msg = assemble_commit_message_text(data, "Ship it")
    assert msg.startswith("git commit -m ")
    assert "Ship it" in msg
    assert "- add a" in msg
    assert "- add b" in msg


def test_html_divergent_history_rendered(
    sibling_repos: dict[str, Path],
) -> None:
    main = sibling_repos["main"]
    v1 = sibling_repos["v1"]
    _write(v1, "shared.txt", "drift-one\n")
    _commit(v1, "v1 drift one")
    _write(v1, "shared.txt", "drift-two\n")
    _commit(v1, "v1 drift two")
    _write(main, "shared.txt", "main update\n")
    commit = _commit(main, "update shared")

    result = run_check(load_config(sibling_repos["config"]), commit)
    html = render_html(result)
    assert "Variant history since divergence" in html
    assert "v1 drift one" in html
    assert "v1 drift two" in html
    assert "variant-history" in html
