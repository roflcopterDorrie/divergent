"""Open HTML reports in a browser, with WSL → Windows Temp support."""

from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path


def is_wsl() -> bool:
    """Return True when running under Windows Subsystem for Linux."""
    if Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists():
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def on_windows_mount(path: Path) -> bool:
    """True if *path* is under a Windows drive mount (/mnt/c, /mnt/d, …)."""
    parts = path.resolve().parts
    return len(parts) >= 3 and parts[1] == "mnt" and len(parts[2]) == 1


def windows_temp_dir() -> Path | None:
    """
    Resolve a writable Windows Temp directory via /mnt/c.

    Prefers ``cmd.exe %TEMP%``, then common fallbacks.
    """
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", "echo", "%TEMP%"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        win_temp = (result.stdout or "").strip().splitlines()
        win_temp_s = win_temp[0].strip() if win_temp else ""
        if win_temp_s and win_temp_s.upper() != "%TEMP%":
            converted = subprocess.run(
                ["wslpath", "-u", win_temp_s],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if converted.returncode == 0:
                candidate = Path(converted.stdout.strip())
                if candidate.is_dir() and os.access(candidate, os.W_OK):
                    return candidate
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass

    for candidate in (
        Path("/mnt/c/Windows/Temp"),
        *_user_local_temps(),
    ):
        if candidate.is_dir() and os.access(candidate, os.W_OK):
            return candidate
    return None


def _user_local_temps() -> list[Path]:
    users = Path("/mnt/c/Users")
    if not users.is_dir():
        return []
    found: list[Path] = []
    try:
        entries = sorted(users.iterdir())
    except OSError:
        return []
    for user_dir in entries:
        if not user_dir.is_dir():
            continue
        name = user_dir.name
        if name in ("Public", "Default", "Default User", "All Users"):
            continue
        temp = user_dir / "AppData" / "Local" / "Temp"
        if temp.is_dir():
            found.append(temp)
    return found


def wsl_to_windows_path(path: Path) -> str | None:
    """Convert a Linux path to a Windows path string via ``wslpath -w``."""
    try:
        result = subprocess.run(
            ["wslpath", "-w", str(path.resolve())],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    win = result.stdout.strip()
    return win or None


def copy_to_windows_temp(source: Path, dest_dir: Path | None = None) -> Path | None:
    """Copy *source* into Windows Temp; return the new path, or None on failure."""
    dest_dir = dest_dir or windows_temp_dir()
    if dest_dir is None:
        return None
    dest = dest_dir / f"divergent-report-{os.getpid()}.html"
    try:
        shutil.copy2(source, dest)
    except OSError:
        return None
    return dest


def default_report_path() -> Path:
    """
    Choose where to write the report when ``-o`` is not given.

    On WSL, prefer Windows Temp so Explorer can open it directly.
    """
    if is_wsl():
        win_temp = windows_temp_dir()
        if win_temp is not None:
            return win_temp / f"divergent-report-{os.getpid()}.html"
    import tempfile

    fd, name = tempfile.mkstemp(prefix="divergent-report-", suffix=".html")
    os.close(fd)
    return Path(name)


def open_html_report(path: Path) -> tuple[bool, Path, str | None]:
    """
    Open *path* in the desktop browser.

    On WSL, copies onto a Windows drive if needed and launches ``explorer.exe``.

    Returns ``(ok, opened_path, warning)``.
    """
    path = path.resolve()
    warning: str | None = None
    open_path = path

    if is_wsl():
        if not on_windows_mount(open_path):
            copied = copy_to_windows_temp(open_path)
            if copied is None:
                return (
                    False,
                    path,
                    "could not copy report to Windows Temp; open the Linux path manually",
                )
            open_path = copied
            warning = f"copied to Windows Temp for Explorer: {open_path}"

        win_path = wsl_to_windows_path(open_path)
        if win_path is None:
            return False, open_path, "wslpath failed; open the report manually"

        try:
            # explorer.exe often returns a non-zero status even when it succeeds.
            subprocess.Popen(
                ["explorer.exe", win_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return False, open_path, f"explorer.exe failed: {exc}"
        return True, open_path, warning

    opened = webbrowser.open(open_path.as_uri())
    if not opened:
        return False, open_path, "webbrowser.open returned false"
    return True, open_path, None
