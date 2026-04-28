"""Tests for container_ref derivation logic."""

from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "integrations" / "claude-code" / "hooks"))

from common import derive_container_ref, _normalize_remote_url


class TestNormalizeRemoteUrl:
    def test_https_with_dot_git(self):
        assert _normalize_remote_url("https://github.com/user/repo.git") == "github.com/user/repo"

    def test_https_without_dot_git(self):
        assert _normalize_remote_url("https://github.com/user/repo") == "github.com/user/repo"

    def test_ssh_format(self):
        assert _normalize_remote_url("git@github.com:user/repo.git") == "github.com/user/repo"

    def test_ssh_without_dot_git(self):
        assert _normalize_remote_url("git@github.com:user/repo") == "github.com/user/repo"

    def test_uppercase_normalized(self):
        assert _normalize_remote_url("https://GitHub.com/User/Repo.git") == "github.com/user/repo"

    def test_trailing_slash_stripped(self):
        assert _normalize_remote_url("https://github.com/user/repo/") == "github.com/user/repo"


class TestDeriveContainerRef:
    @patch("common.subprocess.run")
    def test_with_remote(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/user/repo.git\n"
        )
        result = derive_container_ref("/some/path")
        assert result == "git:github.com/user/repo"

    @patch("common.subprocess.run")
    def test_no_remote_has_root_commit(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "get-url" in cmd:
                return MagicMock(returncode=128, stdout="")
            if "rev-list" in cmd:
                return MagicMock(returncode=0, stdout="abc123def456\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect
        result = derive_container_ref("/some/path")
        assert result == "repo:abc123def456"

    @patch("common.subprocess.run")
    def test_not_a_git_repo(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "get-url" in cmd:
                return MagicMock(returncode=128, stdout="")
            if "rev-list" in cmd:
                return MagicMock(returncode=128, stdout="")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect
        result = derive_container_ref("/some/path")
        assert result.startswith("path:")
        assert len(result) == len("path:") + 12

    @patch("common.subprocess.run")
    def test_ssh_remote(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="git@github.com:org/project.git\n"
        )
        result = derive_container_ref("/some/path")
        assert result == "git:github.com/org/project"

    @patch("common.subprocess.run")
    def test_git_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=3)
        result = derive_container_ref("/some/path")
        assert result.startswith("path:")

    @patch("common.subprocess.run")
    def test_git_not_installed(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        result = derive_container_ref("/some/path")
        assert result.startswith("path:")

    @patch("common.subprocess.run")
    def test_consistent_path_hash(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        result1 = derive_container_ref("/some/path")
        result2 = derive_container_ref("/some/path")
        assert result1 == result2

    @patch("common.subprocess.run")
    def test_different_paths_different_hashes(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        result1 = derive_container_ref("/path/one")
        result2 = derive_container_ref("/path/two")
        assert result1 != result2
