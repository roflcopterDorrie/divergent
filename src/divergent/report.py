"""Markdown report (optional / legacy). Prefer report_html for interactive use."""

from __future__ import annotations

from divergent.compare import CheckResult, FileStatus
from divergent.sync_cmd import render_sync_script, syncable_files, unsyncable_files


def render_markdown(result: CheckResult) -> str:
    short = result.commit[:12]
    lines: list[str] = [
        f"# Divergent check: `{short}`",
        "",
        f"- **Commit:** `{result.commit}`",
        f"- **Subject:** {result.subject}",
        f"- **Date:** {result.date}",
        f"- **Files changed:** {len(result.changes)}",
        f"- **Overall:** {'all syncable' if result.all_safe else 'action needed'}",
        "",
    ]

    if not result.changes:
        lines.append("_No files changed in this commit._")
        lines.append("")
        return "\n".join(lines)

    for var in result.variations:
        counts = var.counts
        safe = syncable_files(var)
        unsafe = unsyncable_files(var)
        lines.append(f"## {var.name}")
        lines.append("")
        lines.append(f"_Path: `{var.path}`_")
        lines.append("")
        if var.all_safe:
            lines.append("**Fully syncable**")
        elif safe:
            lines.append("**Partially syncable**")
        else:
            lines.append("**Not syncable**")
        lines.append("")
        lines.append(
            f"| syncable | diverged | missing | unexpected |\n"
            f"| ---: | ---: | ---: | ---: |\n"
            f"| {counts[FileStatus.SAFE]} | {counts[FileStatus.DIVERGED]} "
            f"| {counts[FileStatus.MISSING]} | {counts[FileStatus.UNEXPECTED]} |"
        )
        lines.append("")

        lines.append(f"### Syncable ({len(safe)})")
        lines.append("")
        if safe:
            lines.append("| path | change | note |")
            lines.append("| --- | --- | --- |")
            for f in safe:
                note = f.detail.replace("|", "\\|")
                lines.append(f"| `{f.path}` | {f.kind.value} | {note} |")
            lines.append("")
            lines.append("#### Copy command")
            lines.append("")
            lines.append("```bash")
            lines.append(render_sync_script(result, var).rstrip("\n"))
            lines.append("```")
            lines.append("")
        else:
            lines.append("_No syncable files for this site._")
            lines.append("")

        lines.append(f"### Unsyncable ({len(unsafe)})")
        lines.append("")
        if unsafe:
            lines.append("| path | change | status | note |")
            lines.append("| --- | --- | --- | --- |")
            for f in unsafe:
                note = f.detail.replace("|", "\\|")
                lines.append(
                    f"| `{f.path}` | {f.kind.value} | {f.status.value} | {note} |"
                )
            lines.append("")
        else:
            lines.append("_None — every changed path matches._")
            lines.append("")

    return "\n".join(lines)
