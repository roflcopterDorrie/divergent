"""Load and validate divergent.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from divergent.gitutil import is_git_repo


class ConfigError(ValueError):
    """Invalid or missing configuration."""


@dataclass(frozen=True)
class Config:
    """Resolved configuration."""

    config_path: Path
    main_repo: Path
    variations: list[Path]


def default_config_path(main_repo: Path) -> Path:
    return main_repo / "divergent.toml"


def load_config(config_path: Path) -> Config:
    """
    Load *config_path* and validate variation repos.

    Paths in the config are resolved relative to the config file's directory.
    The main repo is the git toplevel containing (or equal to) that directory.
    """
    config_path = config_path.resolve()
    if not config_path.is_file():
        raise ConfigError(f"config not found: {config_path}")

    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {config_path}: {exc}") from exc

    raw_variations = data.get("variations")
    if raw_variations is None:
        raise ConfigError(f"{config_path}: missing required key 'variations'")
    if not isinstance(raw_variations, list) or not raw_variations:
        raise ConfigError(f"{config_path}: 'variations' must be a non-empty list of paths")
    if not all(isinstance(v, str) for v in raw_variations):
        raise ConfigError(f"{config_path}: 'variations' entries must be strings")

    base = config_path.parent
    variations: list[Path] = []
    for entry in raw_variations:
        path = Path(entry)
        if not path.is_absolute():
            path = (base / path).resolve()
        else:
            path = path.resolve()
        if not path.is_dir():
            raise ConfigError(f"variation path does not exist or is not a directory: {path}")
        if not is_git_repo(path):
            raise ConfigError(f"variation path is not a git repository: {path}")
        variations.append(path)

    from divergent.gitutil import toplevel

    try:
        main_repo = toplevel(base)
    except Exception as exc:
        raise ConfigError(f"config directory is not inside a git repository: {base}") from exc

    return Config(config_path=config_path, main_repo=main_repo, variations=variations)
