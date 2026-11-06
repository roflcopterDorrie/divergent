# divergent

Check whether files changed by a commit in a **main** git repo are still identical
(at their pre-commit content) across sibling **variation** repos.

If they match, it is safe to copy the post-commit versions across. If not, the
variations have diverged and need a manual update.

**No install required.** Needs only `python3` and `git`.

## Setup

1. Copy this project into (or alongside) your main repo, or keep it checked out somewhere reachable.
2. Copy [`divergent.example.toml`](divergent.example.toml) to `divergent.toml` at
   the main repo root and list your variation paths:

```toml
variations = [
  "../variation-1",
  "../variation-2",
]
variation_base_branch = "develop"
main_branch_pattern = "^feature/.+"
```

## Usage

From inside the main repo:

```bash
python3 /path/to/divergent/run.py check
python3 /path/to/divergent/run.py check abc1234
python3 /path/to/divergent/run.py check --no-open
python3 /path/to/divergent/run.py check -o report.html
```

Or, if this repo is the cwd during development:

```bash
python3 run.py check
```

This writes an HTML report and opens it in your browser (unless `--no-open`).

On **WSL**, the report is written under Windows Temp (or copied there when you
pass `-o` to a Linux path) and opened with `explorer.exe`, so Windows can open
it even when `\\wsl$` paths do not work.

### Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | All changed files are syncable for every variation |
| 1 | At least one divergence, missing path, or unexpected path |
| 2 | Usage, config, or git error |

## How comparison works

Main is expected on a branch like `feature/123` (configurable regex). Each
variation is compared against its **`develop`** branch (configurable), not
whatever happens to be checked out. A warning is shown if a variation is not
currently on `develop`, or if main’s branch does not match the pattern.

For commit `C` in main, each changed path is compared as follows against each
variation’s base branch (default `develop`):

| Change in `C` | Safe when |
| --- | --- |
| Modified | `main:C^:path` equals `variation:develop:path` |
| Added | path does not exist on `develop` |
| Deleted | `main:C^:path` equals `variation:develop:path` |
| Renamed | treated as delete of the old path + add of the new path |

When a variation is fully syncable, the HTML sync script creates the **same
feature branch name as main** from `develop`, switches to it, then copies files
and commits.

## Read-only guarantee

This tool **only views and analyses**. It does not commit, push, checkout,
stage, merge, or otherwise modify any repository. Git calls go through a
subcommand allowlist (`rev-parse`, `log`, `rev-list`, `diff-tree`, `cat-file`,
`show`).

When a variation is fully syncable, the HTML report shows a **copy-paste shell
script** you can run yourself. Divergent never executes that script.

## Development tests (optional)

```bash
uv venv .venv
uv pip install -e ".[dev]"
.venv/bin/pytest
```
