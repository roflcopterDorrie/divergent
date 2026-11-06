"""Tests for WSL-aware report opening helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from divergent import open_report


def test_on_windows_mount() -> None:
    assert open_report.on_windows_mount(Path("/mnt/c/Users/x/Temp/a.html"))
    assert open_report.on_windows_mount(Path("/mnt/d/tmp/a.html"))
    assert not open_report.on_windows_mount(Path("/home/dylan/report.html"))
    assert not open_report.on_windows_mount(Path("/tmp/report.html"))


def test_copy_to_windows_temp(tmp_path: Path) -> None:
    source = tmp_path / "src.html"
    source.write_text("<html>hi</html>\n", encoding="utf-8")
    dest_dir = tmp_path / "win-temp"
    dest_dir.mkdir()

    copied = open_report.copy_to_windows_temp(source, dest_dir=dest_dir)
    assert copied is not None
    assert copied.parent == dest_dir
    assert copied.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_open_html_report_non_wsl_uses_webbrowser(tmp_path: Path, monkeypatch) -> None:
    report = tmp_path / "r.html"
    report.write_text("<html></html>\n", encoding="utf-8")
    monkeypatch.setattr(open_report, "is_wsl", lambda: False)

    called: list[str] = []

    def fake_open(url: str) -> bool:
        called.append(url)
        return True

    monkeypatch.setattr(open_report.webbrowser, "open", fake_open)
    ok, path, warning = open_report.open_html_report(report)
    assert ok
    assert path == report.resolve()
    assert warning is None
    assert called and called[0].startswith("file:")


def test_open_html_report_wsl_copies_and_launches_explorer(
    tmp_path: Path, monkeypatch
) -> None:
    report = tmp_path / "linux-only.html"
    report.write_text("<html>x</html>\n", encoding="utf-8")
    win_temp = tmp_path / "mnt-c-temp"
    win_temp.mkdir()

    monkeypatch.setattr(open_report, "is_wsl", lambda: True)
    monkeypatch.setattr(open_report, "windows_temp_dir", lambda: win_temp)
    monkeypatch.setattr(
        open_report,
        "wsl_to_windows_path",
        lambda p: f"C:\\\\Temp\\\\{p.name}",
    )

    launched: list[list[str]] = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            launched.append(list(args))

    monkeypatch.setattr(open_report.subprocess, "Popen", FakePopen)

    ok, path, warning = open_report.open_html_report(report)
    assert ok
    assert path.parent == win_temp
    assert path.read_text(encoding="utf-8") == "<html>x</html>\n"
    assert warning is not None and "Windows Temp" in warning
    assert launched and launched[0][0] == "explorer.exe"


def test_default_report_path_prefers_windows_temp(tmp_path: Path, monkeypatch) -> None:
    win_temp = tmp_path / "win"
    win_temp.mkdir()
    monkeypatch.setattr(open_report, "is_wsl", lambda: True)
    monkeypatch.setattr(open_report, "windows_temp_dir", lambda: win_temp)
    path = open_report.default_report_path()
    assert path.parent == win_temp
    assert path.suffix == ".html"
