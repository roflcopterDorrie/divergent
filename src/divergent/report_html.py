"""Self-contained HTML report."""

from __future__ import annotations

import difflib
import html
import json

from divergent.compare import (
    ChangeKind,
    CheckResult,
    FileDiff,
    FileResult,
    FileStatus,
    VariationResult,
    main_branch_label,
    variant_branch_label,
)
from divergent.sync_cmd import (
    assemble_commit_message_text,
    assemble_stage_commands,
    assemble_sync_script,
    default_ignored_paths,
    default_synced_paths,
    sync_script_data,
)


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


def _note_label(f: FileResult, *, compare_ref: str = "develop") -> str:
    """Short scannable note for the collapsed file row (plain text)."""
    if f.status == FileStatus.MISSING:
        return f"Missing on {variant_branch_label(compare_ref)}"
    if f.status == FileStatus.DIVERGED:
        return "Divergent"
    if f.status == FileStatus.UNEXPECTED:
        return "Already exists"
    # Syncable: no deviation from the variation base.
    if f.kind == ChangeKind.ADDED and f.old_path:
        return "Safe to rename"
    return {
        ChangeKind.ADDED: "Safe to add",
        ChangeKind.MODIFIED: "Safe to update",
        ChangeKind.DELETED: "Safe to delete",
    }[f.kind]


def _branch_pill(label: str) -> str:
    return f'<span class="branch-pill">{_esc(label)}</span>'


def _pillify_branches(text: str, *branch_labels: str) -> str:
    """Escape *text*, then wrap known branch labels in pills."""
    out = _esc(text)
    for label in sorted({b for b in branch_labels if b}, key=len, reverse=True):
        esc = _esc(label)
        out = out.replace(esc, _branch_pill(label))
    return out


def _syncability_label(f: FileResult) -> tuple[str, str]:
    if f.status == FileStatus.SAFE:
        return ("Safe", "safe")
    return ("Review", "unsafe")


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
.meta { color: var(--muted); margin: 0 0 0.75rem; }
.panel > h2:first-child { margin-top: 0; }
main > .panel:first-of-type { margin-top: 0.5rem; }
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
.status.unsafe { background: var(--bad-bg); color: var(--bad); }
.branch-pill {
  display: inline-block;
  padding: 0.05rem 0.4rem;
  border-radius: 999px;
  background: #e7eef1;
  color: var(--accent);
  font-family: var(--mono);
  font-size: 0.84em;
  font-weight: 600;
  white-space: nowrap;
}
.note { color: var(--muted); font-size: 0.9rem; }
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  border-bottom: 1px solid var(--line);
  margin: 0 0 1rem;
  padding: 0;
}
.tabs button {
  border: 1px solid transparent;
  border-bottom: none;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-weight: 600;
  font-size: 0.92rem;
  padding: 0.55rem 0.85rem;
  cursor: pointer;
  border-radius: 6px 6px 0 0;
  margin-bottom: -1px;
}
.tabs button:hover { color: var(--ink); background: #f0ece4; }
.tabs button.active {
  color: var(--ink);
  background: var(--surface);
  border-color: var(--line);
}
.tab-panel { display: none; }
.tab-panel.active { display: block; }
.file-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.92rem;
}
.file-table thead th {
  text-align: left;
  padding: 0.4rem 0.5rem;
  color: var(--muted);
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--line);
}
.file-table thead th.col-check { width: 4.5rem; text-align: center; }
.file-row {
  border-bottom: 1px solid var(--line);
}
.file-row > summary {
  list-style: none;
  cursor: pointer;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(11rem, 0.9fr) 7rem 4.5rem 4.5rem;
  gap: 0.35rem;
  align-items: center;
  padding: 0.45rem 0.35rem;
}
.file-row > summary::-webkit-details-marker { display: none; }
.file-row .cell-name {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}
.file-row .cell-name::before {
  content: "▸";
  color: var(--muted);
  font-size: 0.75rem;
  width: 0.9rem;
  flex-shrink: 0;
}
.file-row[open] .cell-name::before { content: "▾"; }
.file-row .cell-name code {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-row .cell-note {
  color: var(--muted);
  font-size: 0.82rem;
  line-height: 1.3;
}
.file-row .cell-check {
  text-align: center;
}
.file-row .cell-check input {
  margin: 0;
  accent-color: var(--accent);
  cursor: pointer;
}
.file-row .cell-check label {
  display: inline-flex;
  cursor: pointer;
}
.file-body {
  padding: 0 0.5rem 0.85rem 1.4rem;
}
.file-body .detail { margin: 0 0 0.5rem; }
.variant-history {
  margin: 0 0 0.75rem;
  padding: 0;
  list-style: none;
  font-size: 0.85rem;
}
.variant-history li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.65rem 1rem;
  padding: 0.2rem 0;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
}
.variant-history li:last-child { border-bottom: 0; }
.variant-history .sha {
  flex: 0 0 auto;
  font-family: var(--mono);
  color: var(--accent);
}
.variant-history .action {
  flex: 0 0 auto;
  font-weight: 600;
  color: var(--ink);
}
.variant-history li > span:last-child {
  flex: 1 1 12rem;
  min-width: 0;
}
.variant-history h4 {
  margin: 0 0 0.35rem;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted);
}
.feature-name-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
  margin: 0 0 0.65rem;
}
.feature-name-row label {
  font-size: 0.9rem;
  color: var(--muted);
  white-space: nowrap;
}
.feature-name-row input {
  flex: 1 1 14rem;
  min-width: 0;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
  color: var(--ink);
  font: inherit;
  font-size: 0.95rem;
}
.feature-name-row input:focus {
  outline: 2px solid color-mix(in srgb, var(--accent) 35%, transparent);
  border-color: var(--accent);
}
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
.diff-view table.diff .diff_next { background: #efece5; width: 1.5rem; }
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
.files-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(11rem, 0.9fr) 7rem 4.5rem 4.5rem;
  gap: 0.35rem;
  padding: 0 0.35rem 0.35rem 1.25rem;
  color: var(--muted);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--line);
  margin-bottom: 0.15rem;
}
.files-header span:nth-child(4),
.files-header span:nth-child(5) { text-align: center; }
.files { margin-bottom: 1rem; }
@media (max-width: 720px) {
  .files-header { display: none; }
  .file-row > summary {
    grid-template-columns: minmax(0, 1fr) 4rem 4rem;
    grid-template-areas:
      "name name"
      "note status"
      "sync ignore";
  }
  .file-row .cell-name { grid-area: name; }
  .file-row .cell-note { grid-area: note; }
  .file-row .cell-status { grid-area: status; }
  .file-row .cell-sync { grid-area: sync; }
  .file-row .cell-ignore { grid-area: ignore; }
}
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

function selectTab(index) {
  document.querySelectorAll(".tabs button").forEach((btn, i) => {
    btn.classList.toggle("active", i === index);
  });
  document.querySelectorAll(".tab-panel").forEach((panel, i) => {
    panel.classList.toggle("active", i === index);
  });
}

function selectedPaths(varIndex, selector) {
  return new Set(
    Array.from(
      document.querySelectorAll(
        selector + '[data-var="' + varIndex + '"]:checked'
      )
    ).map((el) => el.dataset.path)
  );
}

function onSyncActionToggle(el, event) {
  if (event) event.stopPropagation();
  const varIndex = el.dataset.var;
  if (el.checked) {
    const wrap = el.closest(".file-row");
    if (wrap) {
      const otherSel = el.classList.contains("force-sync")
        ? "input.ignore-sync"
        : "input.force-sync";
      const other = wrap.querySelector(otherSel);
      if (other) other.checked = false;
    }
  }
  rebuildSyncScript(varIndex);
}

function shellQuote(path) {
  if (/^[A-Za-z0-9_./@%+=:,-]+$/.test(path)) return path;
  return "'" + String(path).replace(/'/g, "'\\''") + "'";
}

function shellQuoteMessage(text) {
  return "'" + String(text).replace(/'/g, "'\\''") + "'";
}

function commitMessageBody(data) {
  const subjects = data.subjects || [];
  if (subjects.length <= 1) {
    return (data.commit_message || subjects[0] || "").replace(/\\n$/, "");
  }
  return subjects.map((s) => "- " + s).join("\\n");
}

function rebuildStageBox(varIndex, data, synced) {
  const pre = document.getElementById("stage-" + varIndex);
  if (!pre) return;
  const adds = [];
  const rms = [];
  for (const f of data.files) {
    if (!synced.has(f.path)) continue;
    if (f.kind === "deleted") rms.push(f.path);
    else adds.push(f.path);
  }
  const lines = [];
  if (adds.length) {
    lines.push("git add -- " + adds.map(shellQuote).join(" "));
  }
  if (rms.length) {
    lines.push("git rm -- " + rms.map(shellQuote).join(" "));
  }
  pre.textContent = lines.length
    ? lines.join("\\n") + "\\n"
    : "# No Sync-checked files to stage.\\n";
}

function rebuildMessageBox(varIndex, data) {
  const pre = document.getElementById("msg-" + varIndex);
  if (!pre) return;
  const input = document.getElementById("feature-name-" + varIndex);
  const feature = ((input && input.value) || "").trim() || "Feature name";
  const body = commitMessageBody(data);
  const full = body ? feature + "\\n\\n" + body : feature;
  pre.textContent = "git commit -m " + shellQuoteMessage(full) + "\\n";
}

function onFeatureNameInput(varIndex) {
  const dataEl = document.getElementById("sync-data-" + varIndex);
  if (!dataEl) return;
  rebuildMessageBox(varIndex, JSON.parse(dataEl.textContent));
}

function rebuildSyncScript(varIndex) {
  const dataEl = document.getElementById("sync-data-" + varIndex);
  const pre = document.getElementById("sync-" + varIndex);
  if (!dataEl || !pre) return;
  const data = JSON.parse(dataEl.textContent);
  const synced = selectedPaths(varIndex, "input.force-sync");
  const ignored = selectedPaths(varIndex, "input.ignore-sync");
  rebuildStageBox(varIndex, data, synced);
  rebuildMessageBox(varIndex, data);
  const toSync = data.files.filter((f) => synced.has(f.path));
  if (!toSync.length) {
    const pending = data.files.filter(
      (f) => !synced.has(f.path) && !ignored.has(f.path)
    );
    if (!pending.length && data.files.length) {
      pre.textContent = "# All paths ignored; nothing to copy.\\n";
      return;
    }
    pre.textContent =
      "# Select Sync on at least one file to build a sync script.\\n";
    return;
  }
  const lines = data.header.slice();
  lines.push("");
  const pending = data.files.filter(
    (f) => !synced.has(f.path) && !ignored.has(f.path)
  );
  const ignoredEntries = data.files.filter(
    (f) => ignored.has(f.path) && !synced.has(f.path)
  );
  if (pending.length) {
    lines.push("# Partial sync — skipped (not syncable; often regenerated):");
    for (const s of pending) {
      lines.push("#   " + s.status + " " + s.path);
    }
    lines.push("");
  }
  if (ignoredEntries.length) {
    lines.push("# Ignored (acknowledged, not synced):");
    for (const s of ignoredEntries) {
      lines.push("#   " + s.status + " " + s.path);
    }
    lines.push("");
  }
  lines.push(...data.branch);
  lines.push("");
  for (const f of toSync) {
    lines.push(...f.lines);
    lines.push("");
  }
  pre.textContent = lines.join("\\n") + "\\n";
}
""".strip()


def _render_file_row(
    f: FileResult,
    *,
    var_index: int,
    compare_ref: str,
    main_branch: str | None,
) -> str:
    base = main_branch_label(main_branch)
    variant = variant_branch_label(compare_ref)
    note = _note_label(f, compare_ref=compare_ref)
    note_html = _pillify_branches(note, base, variant)
    status_label, status_class = _syncability_label(f)
    sync_checked = " checked" if f.status == FileStatus.SAFE else ""
    ignore_checked = "" if f.status == FileStatus.SAFE else " checked"
    path_attr = _esc(f.path)
    detail_html = _pillify_branches(f.detail, base, variant)

    body_parts = [
        f'<p class="detail note">{detail_html}</p>',
    ]
    if f.variant_history:
        hist = ['<div class="variant-history-wrap"><h4>Variant history since divergence</h4><ul class="variant-history">']
        for entry in f.variant_history:
            hist.append(
                "<li>"
                f'<span class="sha">{_esc(entry.commit)}</span>'
                f'<span class="action">{_esc(entry.action)}</span>'
                f"<span>{_esc(entry.subject)}</span>"
                "</li>"
            )
        hist.append("</ul></div>")
        body_parts.append("".join(hist))
    if f.diff is not None:
        diff_html, _is_binary_diff = render_diff_html(f.diff)
        body_parts.append(diff_html)

    return (
        f'<details class="file-row">'
        f"<summary>"
        f'<span class="cell-name"><code class="path">{path_attr}</code></span>'
        f'<span class="cell-note">{note_html}</span>'
        f'<span class="cell-status"><span class="status {status_class}">'
        f"{_esc(status_label)}</span></span>"
        f'<span class="cell-check cell-sync">'
        f'<label title="Sync" onclick="event.stopPropagation()">'
        f'<input type="checkbox" class="force-sync" '
        f'data-var="{var_index}" data-path="{path_attr}"'
        f"{sync_checked} "
        f'onclick="event.stopPropagation()" '
        f'onchange="onSyncActionToggle(this, event)">'
        f"</label></span>"
        f'<span class="cell-check cell-ignore">'
        f'<label title="Ignore" onclick="event.stopPropagation()">'
        f'<input type="checkbox" class="ignore-sync" '
        f'data-var="{var_index}" data-path="{path_attr}"'
        f"{ignore_checked} "
        f'onclick="event.stopPropagation()" '
        f'onchange="onSyncActionToggle(this, event)">'
        f"</label></span>"
        f"</summary>"
        f'<div class="file-body">{"".join(body_parts)}</div>'
        f"</details>"
    )


def _render_file_list(
    files: list[FileResult],
    *,
    var_index: int,
    compare_ref: str,
    main_branch: str | None,
) -> list[str]:
    parts = [
        '<div class="files-header" aria-hidden="true">'
        "<span>File</span><span>Note</span><span>Status</span>"
        "<span>Sync</span><span>Ignore</span>"
        "</div>",
        '<div class="files">',
    ]
    for f in files:
        parts.append(
            _render_file_row(
                f,
                var_index=var_index,
                compare_ref=compare_ref,
                main_branch=main_branch,
            )
        )
    parts.append("</div>")
    return parts


def _copy_pre(pre_id: str, text: str) -> list[str]:
    return [
        '<div class="sync-wrap">',
        f'<button type="button" class="copy" '
        f"onclick=\"copyScript('{pre_id}', this)\">Copy</button>",
        f"<pre id='{pre_id}'>{_esc(text)}</pre>",
        "</div>",
    ]


def _render_sync_block(result: CheckResult, var: VariationResult, index: int) -> list[str]:
    data = sync_script_data(result, var)
    synced = default_synced_paths(var)
    ignored = default_ignored_paths(var)
    script = assemble_sync_script(data, synced, ignored)
    if script is None:
        script = "# Select Sync on at least one file to build a sync script.\n"
    stage = assemble_stage_commands(data, synced)
    message = assemble_commit_message_text(data)
    script_id = f"sync-{index}"
    stage_id = f"stage-{index}"
    msg_id = f"msg-{index}"
    data_id = f"sync-data-{index}"
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    parts = [
        "<h3>Copy command</h3>",
        f'<script type="application/json" id="{data_id}">{payload}</script>',
    ]
    parts.extend(_copy_pre(script_id, script))
    parts.append("<h3>Stage</h3>")
    parts.append(
        "<p class='note'>Git add/rm for files currently marked Sync.</p>"
    )
    parts.extend(_copy_pre(stage_id, stage))
    feature_id = f"feature-name-{index}"
    parts.append("<h3>Commit message</h3>")
    parts.append(
        '<div class="feature-name-row">'
        f'<label for="{feature_id}">Feature name</label>'
        f'<input type="text" id="{feature_id}" '
        f'placeholder="Feature name" autocomplete="off" '
        f"oninput=\"onFeatureNameInput({index})\">"
        "</div>"
    )
    parts.extend(_copy_pre(msg_id, message))
    return parts


def _render_variation_panel(
    result: CheckResult, var: VariationResult, index: int, *, active: bool
) -> str:
    active_cls = " active" if active else ""
    parts: list[str] = [
        f'<section class="tab-panel{active_cls}" id="var-{index}" role="tabpanel">',
        '<div class="panel">',
    ]

    for warning in var.warnings:
        parts.append(
            f"<p><span class='banner warn'>Warning</span> {_esc(warning)}</p>"
        )

    if not result.changes:
        parts.append("<p class='note'>No files changed in this commit.</p>")
        parts.append("</div></section>")
        return "\n".join(parts)

    if var.files:
        parts.extend(
            _render_file_list(
                var.files,
                var_index=index,
                compare_ref=var.compare_ref,
                main_branch=result.main_branch,
            )
        )
        parts.extend(_render_sync_block(result, var, index))
    else:
        parts.append("<p class='note'>No files changed in this commit.</p>")

    parts.append("</div></section>")
    return "\n".join(parts)


def render_html(result: CheckResult) -> str:
    short = result.commit[:12]

    tab_buttons: list[str] = []
    tab_panels: list[str] = []
    for i, var in enumerate(result.variations):
        cls = ' class="active"' if i == 0 else ""
        tab_buttons.append(
            f'<button type="button" role="tab"{cls} '
            f"onclick=\"selectTab({i})\">{_esc(var.name)}</button>"
        )
        tab_panels.append(
            _render_variation_panel(result, var, i, active=(i == 0))
        )

    tabs_block = (
        f'<div class="tabs" role="tablist">{"".join(tab_buttons)}</div>'
        + "\n".join(tab_panels)
        if result.variations
        else "<p class='note'>No variations configured.</p>"
    )

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
    {_branch_pill(main_branch_label(result.main_branch))}
    compared against
    {_branch_pill(variant_branch_label(result.variation_base_branch))}
  </p>
  {warnings_block}

  <h2>Variations</h2>
  {tabs_block}

</main>
<script>{_js()}</script>
</body>
</html>
"""
