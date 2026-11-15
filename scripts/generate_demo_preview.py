#!/usr/bin/env python3
"""Rebuild demo-repos/ and demo-report.html with the full scenario matrix."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo-repos"
REPORT = ROOT / "demo-report.html"

# Long enough that side-by-side diffs show several changed hunks.
_SYNC_MODIFIED_BASE = """\
line 01 shared baseline
line 02 shared baseline
line 03 shared baseline
line 04 shared baseline
line 05 shared baseline
line 06 shared baseline
line 07 shared baseline
line 08 shared baseline
line 09 shared baseline
line 10 shared baseline
line 11 shared baseline
line 12 shared baseline
"""

_SYNC_MODIFIED_MAIN = """\
line 01 shared baseline
line 02 UPDATED on main
line 03 shared baseline
line 04 shared baseline
line 05 shared baseline
line 06 REMOVED next two on main
line 09 shared baseline
line 10 shared baseline
line 11 ALSO UPDATED on main
line 12 shared baseline
"""

_DIVERGED_BASE = """\
div 01 shared
div 02 shared
div 03 shared
div 04 shared
div 05 shared
div 06 shared
div 07 shared
div 08 shared
div 09 shared
div 10 shared
div 11 shared
div 12 shared
"""

_DIVERGED_V1 = """\
div 01 shared
div 02 DRIFTED on variation-1
div 03 shared
div 04 shared
div 05 shared
div 06 gone on v1
div 09 shared
div 10 shared
div 11 also drifted on v1
div 12 shared
"""

_DIVERGED_MAIN = """\
div 01 shared
div 02 UPDATED on main
div 03 shared
div 04 shared
div 05 shared
div 06 REMOVED on main next
div 09 shared
div 10 shared
div 11 ALSO UPDATED on main
div 12 shared
"""


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
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "demo@example.com")
    _git(path, "config", "user.name", "Demo")
    _git(path, "checkout", "-b", "main")
    return path


def build_demo() -> Path:
    if DEMO.exists():
        shutil.rmtree(DEMO)

    main = _init_repo(DEMO / "main")
    v1 = _init_repo(DEMO / "variation-1")
    v2 = _init_repo(DEMO / "variation-2")

    # Identical starting point on all three repos.
    # unsync_missing.txt is never created on variation-1 (true Missing case).
    for repo in (main, v1, v2):
        _write(repo, "keep.txt", "untouched\n")
        _write(repo, "sync_modified.txt", _SYNC_MODIFIED_BASE)
        _write(repo, "sync_removed.txt", "delete me when matched\n")
        _write(repo, "unsync_diverged.txt", _DIVERGED_BASE)
        _write(repo, "unsync_del_diverged.txt", "delete baseline\n")
        _write(repo, "unsync_del_missing.txt", "will vanish on v1\n")
        # Main will modify this; v1 will delete it → divergent prior-delete.
        _write(repo, "unsync_mod_deleted.txt", "modify-vs-deleted baseline\n")
        _write(repo, "rename_me.txt", "rename baseline\n")
        if repo is not v1:
            _write(repo, "unsync_missing.txt", "exists on main only later\n")
        _commit(repo, "initial baseline")

    # Main: develop first, then feature from develop (default merge-base check).
    _git(main, "branch", "develop")
    _git(main, "checkout", "-b", "feature/demo-matrix")
    for repo in (v1, v2):
        _git(repo, "branch", "develop")
        _git(repo, "checkout", "develop")

    # variation-1: create every unsyncable situation on develop (with history).
    _write(v1, "unsync_diverged.txt", _DIVERGED_V1)
    _commit(v1, "variation-1 first drift on unsync_diverged")
    _write(v1, "unsync_diverged.txt", _DIVERGED_V1.replace("also drifted", "second drift"))
    _write(v1, "unsync_del_diverged.txt", "different content on v1\n")
    (v1 / "unsync_del_missing.txt").unlink()
    (v1 / "unsync_mod_deleted.txt").unlink()
    _write(v1, "unsync_unexpected.txt", "already present on v1\n")
    _commit(v1, "variation-1 deleted paths and other unsyncable demos")

    # One commit per change on the feature branch.
    _write(main, "sync_added.txt", "brand new file\n")
    _commit(main, "demo: add sync_added.txt")

    _write(main, "sync_modified.txt", _SYNC_MODIFIED_MAIN)
    _commit(main, "demo: update sync_modified.txt")

    (main / "sync_removed.txt").unlink()
    _commit(main, "demo: remove sync_removed.txt")

    _write(main, "unsync_diverged.txt", _DIVERGED_MAIN)
    _commit(main, "demo: update unsync_diverged.txt")

    _write(main, "unsync_missing.txt", "updated on main (never on v1)\n")
    _commit(main, "demo: update unsync_missing.txt")

    _write(main, "unsync_mod_deleted.txt", "updated on main (deleted on v1)\n")
    _commit(main, "demo: update unsync_mod_deleted.txt")

    _write(main, "unsync_unexpected.txt", "added on main but already on v1\n")
    _commit(main, "demo: add unsync_unexpected.txt")

    (main / "unsync_del_diverged.txt").unlink()
    _commit(main, "demo: delete unsync_del_diverged.txt")

    (main / "unsync_del_missing.txt").unlink()
    _commit(main, "demo: delete unsync_del_missing.txt")

    _git(main, "mv", "rename_me.txt", "renamed.txt")
    _commit(main, "demo: rename rename_me.txt to renamed.txt")

    config = main / "divergent.toml"
    config.write_text(
        'variations = ["../variation-1", "../variation-2"]\n'
        'variation_base_branch = "develop"\n'
        'main_base_branch = "develop"\n'
        'main_branch_pattern = "^feature/.+"\n',
        encoding="utf-8",
    )
    # Keep config untracked so it is not part of the feature range.
    return main


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from divergent.compare import run_check
    from divergent.config import load_config
    from divergent.open_report import open_html_report
    from divergent.report_html import render_html

    main_repo = build_demo()
    # Default check: merge-base(develop)..HEAD (all feature commits).
    result = run_check(load_config(main_repo / "divergent.toml"))
    REPORT.write_text(render_html(result), encoding="utf-8")

    print(f"Wrote {REPORT}")
    print(f"Repos under {DEMO}")
    print(f"Feature commits in range: {len(result.commits)}")
    print(
        "Scenarios on variation-1: "
        "Added, Removed, Modified, Diverged, Missing (never existed), "
        "Modified-but-deleted-on-variant, Unexpected, rename"
    )
    print(
        "variation-2 stays matching → those same paths are Syncable there "
        "(except Unexpected add is just Added)."
    )

    ok, opened, warning = open_html_report(REPORT)
    if warning:
        print(warning)
    if ok:
        print(f"Opened {opened}")
    else:
        print(f"Could not open report automatically; open {REPORT} manually.")

    return 0 if result.all_safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
