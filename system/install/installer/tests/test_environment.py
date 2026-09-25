"""Tests for making sure every subprocess the installer runs can use flakes.

A stock ISO's `nix.conf` does not enable `flakes` or `nix-command`.
`--extra-experimental-features` on the `nix run` that starts the installer
only covers that one process. Everything the installer runs afterwards
(`nix eval`, `nix build`, `nixos-install --flake`, `disko --flake`) is a fresh
process, and needs the same features through `NIX_CONFIG` instead, or it fails
the same way a bare `nix eval` does on a fresh ISO: "experimental Nix feature
... is disabled".
"""

from __future__ import annotations

from nixos_installer.proc import ensure_experimental_features, merged_nix_config


class TestMergedNixConfig:
    def test_adds_the_line_when_there_is_no_config_at_all(self):
        assert merged_nix_config("") == "experimental-features = flakes nix-command"

    def test_extends_an_existing_experimental_features_line(self):
        result = merged_nix_config("experimental-features = ca-derivations")
        assert "ca-derivations" in result
        assert "flakes" in result
        assert "nix-command" in result

    def test_does_not_duplicate_features_already_present(self):
        result = merged_nix_config("experimental-features = flakes nix-command")
        assert result.count("flakes") == 1
        assert result.count("nix-command") == 1

    def test_leaves_unrelated_settings_untouched(self):
        result = merged_nix_config("substituters = https://cache.nixos.org")
        assert "substituters = https://cache.nixos.org" in result
        assert "flakes" in result


class TestEnsureExperimentalFeatures:
    def test_sets_nix_config_from_nothing(self):
        env: dict[str, str] = {}
        ensure_experimental_features(env)
        assert "flakes" in env["NIX_CONFIG"]
        assert "nix-command" in env["NIX_CONFIG"]

    def test_extends_rather_than_overwrites(self):
        env = {"NIX_CONFIG": "substituters = https://cache.nixos.org"}
        ensure_experimental_features(env)
        assert "substituters = https://cache.nixos.org" in env["NIX_CONFIG"]
        assert "flakes" in env["NIX_CONFIG"]
