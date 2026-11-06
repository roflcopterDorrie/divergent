"""Markdown report (optional / legacy). Prefer report_html for interactive use."""

from __future__ import annotations

from divergent.compare import CheckResult, FileStatus


def render_markdown(result: CheckResult) -> str:
    short = result.commit[:12]
    lines: list[str] = [
        f"# Divergent check: `{short}`",
        "",
        f"- **Commit:** `{result.commit}`",
        f"- **Subject:** {result.subject}",
        f"- **Date:** {result.date}",
        f"- **Files changed:** {len(result.changes)}",
        f"- **Overall:** {'all safe' if result.all_safe else 'action needed'}",
        "",
    ]

    if not result.changes:
        lines.append("_No files changed in this commit._")
        lines.append("")
        return "\n".join(lines)

    for var in result.variations:
        counts = var.counts
        lines.append(f"## {var.name}")
        lines.append("")
        lines.append(f"_Path: `{var.path}`_")
        lines.append("")
        lines.append(
            f"| safe | diverged | missing | unexpected |\n"
            f"| ---: | ---: | ---: | ---: |\n"
            f"| {counts[FileStatus.SAFE]} | {counts[FileStatus.DIVERGED]} "
            f"| {counts[FileStatus.MISSING]} | {counts[FileStatus.UNEXPECTED]} |"
        )
        lines.append("")

        by_status: dict[FileStatus, list] = {s: [] for s in FileStatus}
        for f in var.files:
            by_status[f.status].append(f)

        order = (
            FileStatus.SAFE,
            FileStatus.DIVERGED,
            FileStatus.MISSING,
            FileStatus.UNEXPECTED,
        )
        for status in order:
            files = by_status[status]
            if not files:
                continue
            lines.append(f"### {status.value}")
            lines.append("")
            lines.append("| path | change | note |")
            lines.append("| --- | --- | --- |")
            for f in files:
                note = f.detail.replace("|", "\\|")
                lines.append(f"| `{f.path}` | {f.kind.value} | {note} |")
            lines.append("")

    return "\n".join(lines)
