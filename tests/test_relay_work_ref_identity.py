import json
from pathlib import Path

import pytest

from core.work_ref import readable_work_ref, validate_work_ref_key
from integrations.codex.hooks import common as codex_common
from integrations.codex.hooks.common import canonical_git_remote, roadmap_scope_ref, structural_work_refs_payload, WorkRefDiscovery


def test_golden_vectors_and_nfc():
    ref = readable_work_ref("roadmap:v1:git:github.com/rore/pallium#roadmap", "feature:add-relay-session-work-associations")
    assert ref.key == "work:v1:4e012e357683c4d5202c658947097e4a1effcf0c4f0e075d450874f89f40b652"
    assert (
        readable_work_ref("tracker:v1:jira.example.test#pallium", "ticket:PAL-412").key
        == "work:v1:50123c19c18153c5f77c954a37ef6257b27b57b11660e62f9e0980ab73132616"
    )
    assert readable_work_ref("e\u0301", "x").key == readable_work_ref("é", "x").key


def test_case_and_unicode_are_preserved():
    assert readable_work_ref("Scope", "\U0001f600").local_ref == "\U0001f600"
    assert readable_work_ref("Scope", "Ä").key != readable_work_ref("Scope", "ä").key
    assert readable_work_ref("Scope", "\U0001f600").local_ref == "\U0001f600"


@pytest.mark.parametrize("value", ["", " x", "x ", "x\x00y", "x\x1fy", "x\x80y", "x\u2028y", "[REDACTED]", "password=sk-ant-api03-" + "x" * 40, "a\ud800"])
def test_rejects_unsafe_parts(value):
    with pytest.raises(ValueError):
        readable_work_ref(value, "local")


def test_bounds_and_advanced_key():
    readable_work_ref("s", "a" * 128)
    readable_work_ref("é" * 256, "local")
    with pytest.raises(ValueError):
        readable_work_ref("s", "a" * 129)
    with pytest.raises(ValueError):
        readable_work_ref("s", "😀" * 129)
    with pytest.raises(ValueError):
        readable_work_ref("é" * 257, "local")
    key = readable_work_ref("s", "l").key
    assert validate_work_ref_key(key) == key
    for bad in [key.upper(), key[:-1], key + "0", "work:v1:" + "g" * 64]:
        with pytest.raises(ValueError):
            validate_work_ref_key(bad)

@pytest.mark.parametrize("remote, expected", [
    ("https://github.com/User/Repo.git", "git:github.com/user/repo"),
    ("ssh://git@git.example.test:22/team/Repo.git", "git:git.example.test/team/Repo"),
    ("ssh://git@git.example.test:2222/team/Repo.git", "git:git.example.test:2222/team/Repo"),
    ("git@github.com:User/Repo.git", "git:github.com/user/repo"),
    ("https://git.example.test/Team/Repo.git", "git:git.example.test/Team/Repo"),
])
def test_canonical_git_remote_vectors(remote, expected):
    assert canonical_git_remote(remote) == expected


@pytest.mark.parametrize("remote", [
    "file:///tmp/repo", "https://user:password@example.test/repo.git",
    "https://example.test:0/repo.git", "https://example.test:65536/repo.git",
    "https://example.test/repo.git?token=secret", "not a remote",
])
def test_canonical_git_remote_rejects_unsafe_or_malformed(remote):
    assert canonical_git_remote(remote) is None


def test_roadmap_root_is_normalized_and_structural_scopes_are_distinct(monkeypatch):
    repo = "git:github.com/owner/repo"
    assert roadmap_scope_ref(repo, r"roadmap\é space") == "roadmap:v1:git:github.com/owner/repo#roadmap/%C3%A9%20space"
    assert roadmap_scope_ref(repo, ".") == "roadmap:v1:git:github.com/owner/repo#."
    monkeypatch.setattr(codex_common, "repository_scope_ref", lambda _cwd: repo)
    payload = structural_work_refs_payload(
        "git:wrong/container",
        WorkRefDiscovery(("git-branch:feature/x", "agent-workflow:item")),
        "checkout",
    )
    assert payload == [
        {"scope_ref": repo, "local_ref": "git-branch:feature/x"},
        {"scope_ref": roadmap_scope_ref(repo), "local_ref": "agent-workflow:item"},
    ]


@pytest.mark.parametrize("root", ["", "/roadmap", "a/../b", "a//b", "C:/roadmap"])
def test_roadmap_root_rejects_non_repository_paths(root):
    with pytest.raises(ValueError):
        roadmap_scope_ref("git:example.test/repo", root)

def test_shared_repository_and_roadmap_vectors():
    vectors = json.loads(
        (Path(__file__).parent / "fixtures" / "relay_work_identity_vectors.json").read_text(
            encoding="utf-8"
        )
    )
    for row in vectors["canonical_remotes"]:
        assert canonical_git_remote(row["input"]) == row["expected"]
    for remote in vectors["invalid_remotes"]:
        assert canonical_git_remote(remote) is None
    repository = "git:github.com/owner/repo"
    for row in vectors["roadmap_roots"]:
        assert roadmap_scope_ref(repository, row["input"]) == (
            f"roadmap:v1:{repository}#{row['expected']}"
        )
    for root in vectors["invalid_roadmap_roots"]:
        with pytest.raises(ValueError):
            roadmap_scope_ref(repository, root)
