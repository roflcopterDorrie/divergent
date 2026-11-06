"""CLI integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from divergent.cli import EXIT_DIVERGED, EXIT_ERROR, EXIT_OK
from divergent.cli import main as cli_main


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


def test_cli_check_safe(
    sibling_repos: dict[str, Path], tmp_path: Path, capsys, monkeypatch
) -> None:
    main_repo = sibling_repos["main"]
    _write(main_repo, "shared.txt", "hello world\n")
    _commit(main_repo, "update shared")

    out_file = tmp_path / "out.html"
    monkeypatch.chdir(main_repo)
    with pytest.raises(SystemExit) as exc:
        cli_main(["check", "--no-open", "-o", str(out_file)])
    assert exc.value.code == EXIT_OK

    out = capsys.readouterr().out
    assert "report:" in out
    assert "all syncable" in out
    assert "main branch: feature/123" in out


def test_cli_check_diverged(
    sibling_repos: dict[str, Path], tmp_path: Path, capsys, monkeypatch
) -> None:
    main_repo = sibling_repos["main"]
    v1 = sibling_repos["v1"]
    _write(v1, "shared.txt", "drifted\n")
    _commit(v1, "drift")
    _write(main_repo, "shared.txt", "hello world\n")
    _commit(main_repo, "update shared")

    out_file = tmp_path / "out.html"
    monkeypatch.chdir(main_repo)
    with pytest.raises(SystemExit) as exc:
        cli_main(["check", "--no-open", "-o", str(out_file)])
    assert exc.value.code == EXIT_DIVERGED

    out = capsys.readouterr().out
    assert "action needed" in out


def test_cli_bad_config(sibling_repos: dict[str, Path], capsys, monkeypatch) -> None:
    main_repo = sibling_repos["main"]
    bad = main_repo / "missing.toml"
    monkeypatch.chdir(main_repo)
    with pytest.raises(SystemExit) as exc:
        cli_main(["check", "--config", str(bad), "--no-open"])
    assert exc.value.code == EXIT_ERROR

    err = capsys.readouterr().err
    assert "config not found" in err


def test_cli_write_output_file(
    sibling_repos: dict[str, Path], tmp_path: Path, monkeypatch
) -> None:
    main_repo = sibling_repos["main"]
    _write(main_repo, "shared.txt", "hello world\n")
    _commit(main_repo, "update shared")

    out_file = tmp_path / "report.html"
    monkeypatch.chdir(main_repo)
    with pytest.raises(SystemExit) as exc:
        cli_main(["check", "-o", str(out_file), "--no-open"])
    assert exc.value.code == EXIT_OK

    text = out_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text
    assert "shared.txt" in text
    assert "Fully syncable" in text
    assert "git commit -F -" in text
    assert "git switch -c" in text
    assert "feature/123" in text
