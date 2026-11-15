"""Config loading tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from divergent.config import ConfigError, load_config


def test_load_valid_config(sibling_repos: dict[str, Path]) -> None:
    config = load_config(sibling_repos["config"])
    assert config.main_repo == sibling_repos["main"].resolve()
    assert config.variations == [
        sibling_repos["v1"].resolve(),
        sibling_repos["v2"].resolve(),
    ]
    assert config.main_base_branch == "develop"
    assert config.variation_base_branch == "develop"


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config not found"):
        load_config(tmp_path / "nope.toml")


def test_missing_variations_key(sibling_repos: dict[str, Path]) -> None:
    path = sibling_repos["main"] / "bad.toml"
    path.write_text("other = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="missing required key"):
        load_config(path)


def test_empty_variations_list(sibling_repos: dict[str, Path]) -> None:
    path = sibling_repos["main"] / "bad.toml"
    path.write_text("variations = []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="non-empty list"):
        load_config(path)


def test_variation_path_missing(sibling_repos: dict[str, Path]) -> None:
    path = sibling_repos["main"] / "bad.toml"
    path.write_text('variations = ["../does-not-exist"]\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(path)


def test_variation_not_a_git_repo(sibling_repos: dict[str, Path], tmp_path: Path) -> None:
    plain = tmp_path / "plain-dir"
    plain.mkdir()
    path = sibling_repos["main"] / "bad.toml"
    # Use absolute path so it resolves correctly from main
    path.write_text(f'variations = ["{plain}"]\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="not a git repository"):
        load_config(path)
