"""Unit tests for the canonical container_ref helper (per-type discipline)."""
from __future__ import annotations

from core.container_ref import canonicalize_container_ref


def test_github_owner_repo_is_lowercased() -> None:
    assert canonicalize_container_ref("git:github.com/rore/Pallium") == "git:github.com/rore/pallium"
    assert canonicalize_container_ref("git:github.com/RORE/PALLIUM") == "git:github.com/rore/pallium"


def test_github_trailing_git_and_slash_normalized() -> None:
    assert canonicalize_container_ref("git:github.com/Rore/Pallium.git") == "git:github.com/rore/pallium"
    assert canonicalize_container_ref("git:github.com/Rore/Pallium/") == "git:github.com/rore/pallium"


def test_idempotent() -> None:
    once = canonicalize_container_ref("git:github.com/rore/Pallium")
    assert canonicalize_container_ref(once) == once


def test_none_safe() -> None:
    assert canonicalize_container_ref(None) is None


def test_non_github_schemes_pass_through_unchanged() -> None:
    # PER-TYPE: only github owner/repo is normalized. Everything else is
    # returned verbatim — path/repo/other hosts can be case-sensitive.
    for value in (
        "path:MyProject:abc123",              # filesystem path — case may matter
        "repo:ABCDEF0123",                    # commit-hash id — already stable
        "git:gitlab.com/Group/Sub/Repo",      # GitLab paths ARE case-sensitive
        "git:github.com/rore/Pallium/extra",  # not a 2-segment github ref
        "github:rore/Pallium",                # different scheme prefix
        "chat:Room-A",                        # arbitrary scope
    ):
        assert canonicalize_container_ref(value) == value
