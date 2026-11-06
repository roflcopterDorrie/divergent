"""Self-contained HTML report."""

from __future__ import annotations

import difflib
import html
from pathlib import Path

from divergent.compare import (
    CheckResult,
    FileDiff,
    FileResult,
    FileStatus,
    VariationResult,
)
from divergent.sync_cmd import render_sync_script

_STATUS_LABEL = {
    FileStatus.SAFE: "syncable",
    FileStatus.DIVERGED: "diverged",
    FileStatus.MISSING: "missing",
    FileStatus.UNEXPECTED: "unexpected",
}


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _is_binary(data: bytes | None) -> bool:
    if data is None:
        return False
    if b"\0" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _decode(data: bytes | None) -> str | None:
    if data is None:
        return None
    return data.decode("utf-8")


def _lines_for_diff(data: bytes | None) -> list[str]:
    text = _decode(data)
    if text is None:
        return []
    # HtmlDiff expects a list of lines without requiring keepends.
    return text.splitlines()


def format_unified_diff(diff: FileDiff) -> tuple[str, bool]:
    """
    Return (plain unified diff text, is_binary).

    Kept for tests and plain-text consumers; the HTML report uses
    ``render_diff_html`` instead.
    """
    if _is_binary(diff.left) or _is_binary(diff.right):
        return ("Binary file content — text diff not shown.", True)

    left_lines = [f"{line}\n" for line in _lines_for_diff(diff.left)]
    right_lines = [f"{line}\n" for line in _lines_for_diff(diff.right)]

    if diff.left is None and diff.right is None:
        return ("(both sides absent)", False)

    ud = difflib.unified_diff(
        left_lines,
        right_lines,
        fromfile=diff.left_label,
        tofile=diff.right_label,
        lineterm="",
    )
    return ("\n".join(ud) or "(no differences in text representation)", False)


def render_diff_html(diff: FileDiff) -> tuple[str, bool]:
    """
    Return (HTML fragment, is_binary) — a side-by-side red/green diff.
    """
    if _is_binary(diff.left) or _is_binary(diff.right):
        return ('<p class="note">Binary file content — text diff not shown.</p>', True)

    if diff.left is None and diff.right is None:
        return ('<p class="note">(both sides absent)</p>', False)

    left_lines = _lines_for_diff(diff.left)
    right_lines = _lines_for_diff(diff.right)

    # HtmlDiff escapes fromdesc/todesc itself — pass raw labels.
    table = difflib.HtmlDiff(tabsize=4, wrapcolumn=88).make_table(
        left_lines,
        right_lines,
        fromdesc=diff.left_label,
        todesc=diff.right_label,
        context=True,
        numlines=4,
    )
    legend = (
        '<p class="diff-legend">'
        '<span class="pill del">removed / only in left</span> '
        '<span class="pill add">added / only in right</span> '
        '<span class="pill chg">changed</span>'
        "</p>"
    )
    return (f'<div class="diff-view">{legend}{table}</div>', False)


def _css() -> str:
    return """
:root {
  --bg: #f6f5f1;
  --surface: #ffffff;
  --ink: #1c1b19;
  --muted: #5c5954;
  --line: #d9d5cc;
  --safe: #1f6b4a;
  --safe-bg: #e5f3ec;
  --warn: #8a4b12;
  --warn-bg: #f8eedf;
  --bad: #8b1e2d;
  --bad-bg: #f8e6e9;
  --code: #f0ece4;
  --accent: #245b6b;
  --mono: "IBM Plex Mono", "Consolas", "Liberation Mono", monospace;
  --sans: "IBM Plex Sans", "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: var(--sans);
  color: var(--ink);
  background:
    radial-gradient(1200px 500px at 10% -10%, #e7eef1 0%, transparent 55%),
    radial-gradient(900px 400px at 100% 0%, #efe8de 0%, transparent 50%),
    var(--bg);
  line-height: 1.45;
}
main { max-width: 1100px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
h1 { font-size: 1.6rem; margin: 0 0 0.35rem; letter-spacing: -0.02em; }
h2 { font-size: 1.25rem; margin: 2rem 0 0.75rem; }
h3 { font-size: 1.05rem; margin: 1.25rem 0 0.5rem; }
.meta { color: var(--muted); margin: 0 0 1.5rem; }
.meta code { font-family: var(--mono); font-size: 0.9em; }
.banner {
  display: inline-block;
  padding: 0.2rem 0.55rem;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 600;
}
.banner.ok { background: var(--safe-bg); color: var(--safe); }
.banner.bad { background: var(--bad-bg); color: var(--bad); }
.banner.warn { background: var(--warn-bg); color: var(--warn); }
.warnings {
  background: var(--warn-bg);
  border: 1px solid #e6d2a8;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  margin: 0 0 1.25rem;
}
.warnings h2 { margin: 0 0 0.5rem; font-size: 1rem; color: var(--warn); }
.warnings ul { margin: 0; padding-left: 1.2rem; }
.warnings li { margin: 0.25rem 0; }
.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 1rem 1.1rem;
  margin: 0.75rem 0 1.25rem;
}
table { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
th, td { text-align: left; padding: 0.45rem 0.5rem; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }
code, pre { font-family: var(--mono); }
code.path { font-size: 0.9em; }
.status {
  display: inline-block;
  padding: 0.1rem 0.45rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 600;
}
.status.safe { background: var(--safe-bg); color: var(--safe); }
.status.diverged, .status.unexpected { background: var(--bad-bg); color: var(--bad); }
.status.missing { background: var(--warn-bg); color: var(--warn); }
.file-list { list-style: none; padding: 0; margin: 0; }
.file-list li { padding: 0.35rem 0; border-bottom: 1px solid var(--line); }
.file-list li:last-child { border-bottom: 0; }
.kind { color: var(--muted); font-size: 0.85rem; margin-left: 0.5rem; }
.sync-wrap { position: relative; }
.sync-wrap pre {
  margin: 0;
  padding: 0.85rem 1rem;
  background: var(--code);
  border-radius: 6px;
  overflow-x: auto;
  font-size: 0.82rem;
  white-space: pre;
}
button.copy {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--accent);
  border-radius: 4px;
  padding: 0.25rem 0.55rem;
  font: inherit;
  font-size: 0.8rem;
  cursor: pointer;
}
button.copy:hover { border-color: var(--accent); }
details.diff { margin: 0.5rem 0 1rem; }
details.diff summary {
  cursor: pointer;
  color: var(--accent);
  font-weight: 600;
}
.diff-view {
  margin-top: 0.65rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: auto;
  background: #faf9f6;
}
.diff-legend {
  margin: 0;
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--line);
  font-size: 0.8rem;
  color: var(--muted);
}
.diff-legend .pill {
  display: inline-block;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  margin-right: 0.35rem;
  font-weight: 600;
}
.diff-legend .pill.del { background: #f8d7da; color: #8b1e2d; }
.diff-legend .pill.add { background: #d1e7dd; color: #0f5132; }
.diff-legend .pill.chg { background: #fff3cd; color: #664d03; }
.diff-view table.diff {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--mono);
  font-size: 0.78rem;
  line-height: 1.4;
}
.diff-view table.diff td,
.diff-view table.diff th {
  padding: 0.15rem 0.45rem;
  border: none;
  border-bottom: 1px solid #ece8e0;
  vertical-align: top;
  white-space: pre-wrap;
  word-break: break-word;
}
.diff-view table.diff th {
  background: #efece5;
  color: var(--ink);
  font-weight: 600;
  text-transform: none;
  letter-spacing: 0;
  position: sticky;
  top: 0;
}
.diff-view table.diff .diff_next {
  background: #efece5;
  width: 1.5rem;
}
.diff-view table.diff .diff_header {
  background: #e7e3da;
  color: var(--muted);
  width: 2.5rem;
  text-align: right;
  user-select: none;
}
.diff-view table.diff .diff_add { background: #d1e7dd; color: #0f5132; }
.diff-view table.diff .diff_sub { background: #f8d7da; color: #8b1e2d; }
.diff-view table.diff .diff_chg { background: #fff3cd; color: #664d03; }
.diff-view table.diff span.diff_add { background: #a3cfbb; }
.diff-view table.diff span.diff_sub { background: #f1aeb5; }
.diff-view table.diff span.diff_chg { background: #ffe69c; }
.note { color: var(--muted); font-size: 0.9rem; }
.legend { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0 0 1.5rem; }
footer { margin-top: 2.5rem; color: var(--muted); font-size: 0.85rem; }
""".strip()


def _js() -> str:
    return """
async function copyScript(id, btn) {
  const el = document.getElementById(id);
  if (!el) return;
  try {
    await navigator.clipboard.writeText(el.textContent);
    btn.textContent = "Copied";
    setTimeout(() => { btn.textContent = "Copy"; }, 1500);
  } catch (err) {
    btn.textContent = "Select & copy manually";
  }
}
""".strip()


def _render_file_row(f: FileResult, idx: str) -> str:
    status_class = f.status.value
    label = _STATUS_LABEL[f.status]
    rows = [
        "<tr>",
        f"<td><code class='path'>{_esc(f.path)}</code></td>",
        f"<td>{_esc(f.kind.value)}</td>",
        f"<td><span class='status {status_class}'>{_esc(label)}</span></td>",
        f"<td class='note'>{_esc(f.detail)}</td>",
        "</tr>",
    ]
    body = "\n".join(rows)
    if f.status == FileStatus.SAFE or f.diff is None:
        return body

    diff_html, is_binary = render_diff_html(f.diff)
    title = "Binary note" if is_binary else "Show side-by-side diff"
    # Open by default so the coloured diff is visible immediately.
    open_attr = "" if is_binary else " open"
    extra = (
        f"<tr><td colspan='4'>"
        f"<details class='diff'{open_attr}><summary>{_esc(title)}</summary>"
        f"{diff_html}</details>"
        f"</td></tr>"
    )
    return body + "\n" + extra


def _render_variation(result: CheckResult, var: VariationResult, index: int) -> str:
    branch_label = var.current_branch if var.current_branch else "detached HEAD"
    parts: list[str] = [
        f"<section class='panel' id='var-{index}'>",
        f"<h2>{_esc(var.name)}</h2>",
        f"<p class='meta'><code>{_esc(str(var.path))}</code><br>"
        f"comparing against <code>{_esc(var.compare_ref)}</code> · "
        f"checked out: <code>{_esc(branch_label)}</code></p>",
    ]

    for warning in var.warnings:
        parts.append(f"<p><span class='banner warn'>Warning</span> {_esc(warning)}</p>")

    if not result.changes:
        parts.append("<p class='note'>No files changed in this commit.</p>")
        parts.append("</section>")
        return "\n".join(parts)

    if var.all_safe:
        parts.append("<p><span class='banner ok'>Fully syncable</span></p>")
        script = render_sync_script(result, var)
        script_id = f"sync-{index}"
        parts.append("<h3>Sync command</h3>")
        parts.append(
            "<p class='note'>Read-only tool: this script is for you to copy and run. "
            "Divergent will not execute it. It creates the same feature branch as main "
            f"from <code>{_esc(result.variation_base_branch)}</code>, then copies files.</p>"
        )
        parts.append('<div class="sync-wrap">')
        parts.append(
            f'<button type="button" class="copy" onclick="copyScript(\'{script_id}\', this)">Copy</button>'
        )
        parts.append(f"<pre id='{script_id}'>{_esc(script)}</pre>")
        parts.append("</div>")
    else:
        parts.append("<p><span class='banner bad'>Not syncable — manual update needed</span></p>")

    counts = var.counts
    parts.append(
        "<p class='note'>"
        f"syncable {counts[FileStatus.SAFE]} · "
        f"diverged {counts[FileStatus.DIVERGED]} · "
        f"missing {counts[FileStatus.MISSING]} · "
        f"unexpected {counts[FileStatus.UNEXPECTED]}"
        "</p>"
    )

    parts.append("<table>")
    parts.append("<thead><tr><th>Path</th><th>Change</th><th>Status</th><th>Note</th></tr></thead>")
    parts.append("<tbody>")
    for i, f in enumerate(var.files):
        parts.append(_render_file_row(f, f"{index}-{i}"))
    parts.append("</tbody></table>")
    parts.append("</section>")
    return "\n".join(parts)


def render_html(result: CheckResult) -> str:
    short = result.commit[:12]
    overall = "all syncable" if result.all_safe else "action needed"
    overall_class = "ok" if result.all_safe else "bad"

    change_items = []
    for c in result.changes:
        change_items.append(
            f"<li><code class='path'>{_esc(c.path)}</code>"
            f"<span class='kind'>{_esc(c.kind.value)}</span></li>"
        )
    if not change_items:
        changed_block = "<p class='note'>No files changed in this commit.</p>"
    else:
        changed_block = "<ul class='file-list'>" + "\n".join(change_items) + "</ul>"

    var_blocks = "\n".join(
        _render_variation(result, var, i) for i, var in enumerate(result.variations)
    )

    main_branch_label = result.main_branch if result.main_branch else "detached HEAD"
    warnings = result.all_warnings
    if warnings:
        warning_items = "\n".join(f"<li>{_esc(w)}</li>" for w in warnings)
        warnings_block = (
            '<section class="warnings"><h2>Branch warnings</h2>'
            f"<ul>{warning_items}</ul></section>"
        )
    else:
        warnings_block = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Divergent check {_esc(short)}</title>
<style>{_css()}</style>
</head>
<body>
<main>
  <h1>Divergent check</h1>
  <p class="meta">
    Commit <code>{_esc(result.commit)}</code><br>
    {_esc(result.subject)}<br>
    {_esc(result.date)} · main <code>{_esc(str(result.main_repo))}</code><br>
    main branch <code>{_esc(main_branch_label)}</code> ·
    comparing variations against <code>{_esc(result.variation_base_branch)}</code>
  </p>
  <p><span class="banner {overall_class}">{_esc(overall)}</span></p>
  {warnings_block}
  <div class="legend">
    <span class="status safe">syncable</span>
    <span class="status diverged">diverged</span>
    <span class="status missing">missing</span>
    <span class="status unexpected">unexpected</span>
  </div>

  <section class="panel">
    <h2>Files changed by commit</h2>
    {changed_block}
  </section>

  {var_blocks}

  <footer>
    Generated by divergent (view/analyse only — does not commit, push, or modify repos).
  </footer>
</main>
<script>{_js()}</script>
</body>
</html>
"""
