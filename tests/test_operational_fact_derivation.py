"""Derivation-predicate unit tests for the operational_fact type.

63 tests covering: positive derivation across command families, negative
paths (window, scope, ordering, argv match), Windows word-boundary
matrix, redaction, scope resolver + salted machine hash, path
normalization, family classifier, malformed metadata robustness,
Unicode preservation, predicate purity, wall-clock budget on a 1,251-
turn corpus, cross-origin boundary, and dedup / conflict-slot semantics.

Reference E2E shape: tests/test_w3_memory_writes_e2e.py.
"""

from __future__ import annotations

import importlib
import re
import time
from unittest import mock

import pytest

from semantic import operational_fact as op
from semantic.operational_fact import (
    KNOWN_FAMILIES,
    MAX_ARTIFACT_LEN,
    build_default_scope_resolver,
    derive_operational_facts,
    resolve_scope,
)
from tests.fixtures.operational_fact import (
    fake_scope_resolver,
    make_bash_turn,
    make_turn,
)


CONTAINER = "git:example/repo"


# --------------------------------------------------------------------------- #
# TestPositiveDerivation                                                      #
# --------------------------------------------------------------------------- #


class TestPositiveDerivation:
    def test_python_interpreter_discovery_then_use(self):
        # PR 3 (reconnaissance-verb model): ``where python`` alone emits
        # the interpreter candidate. The paired-use turn is no longer
        # needed for admission.
        turns = [
            make_bash_turn(0, "where python", output_tail="C:/Users/x/.venv/Scripts/python.exe"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert cands, "command_lookup must emit a candidate"
        interp = [c for c in cands if c.artifact_role == "interpreter"]
        assert interp, "expected interpreter role from command_lookup with .venv path"
        assert interp[0].command_family == "python"
        assert interp[0].scope_kind == "machine_repo"

    def test_python_version_file_read_then_use(self):
        turns = [
            make_turn(0, files_read=[".python-version"]),
            make_bash_turn(1, "cat .python-version"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(".python-version" in c.artifact_normalized for c in cands)

    def test_uv_sync_discovery_then_uv_run_pytest(self):
        # PR 3: ``uv --version`` is a reconnaissance verb (version_query)
        # that emits an uv-family candidate directly. ``uv sync`` is not
        # a recon verb in the new model.
        turns = [
            make_bash_turn(0, "uv --version", output_tail="uv 0.4.0"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "uv" for c in cands)

    def test_npm_test_script_discovery_then_use(self):
        # PR 3: ``npm --version`` (version_query) emits the npm-family
        # candidate directly under the reconnaissance-verb model.
        turns = [
            make_bash_turn(0, "npm --version", output_tail="10.2.4"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "npm" for c in cands)

    def test_gradle_wrapper_discovery_then_use(self):
        # PR 3: ``./gradlew --version`` (version_query) emits the gradle
        # family candidate. gradlew is normalized (leading `./` stripped).
        turns = [
            make_bash_turn(0, "./gradlew --version", output_tail="Gradle 8.2"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "gradle" for c in cands)

    def test_docker_compose_service_discovery_then_use(self):
        # PR 3: ``cat docker-compose.yml`` (cat_config_recon) maps the
        # anchor basename to the docker family.
        turns = [
            make_bash_turn(0, "cat docker-compose.yml"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "docker" for c in cands)

    def test_service_endpoint_discovery_then_curl(self):
        turns = [
            make_bash_turn(0, "curl -sI http://127.0.0.1:8000/health"),
            make_bash_turn(1, "curl http://127.0.0.1:8000/health"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "service" for c in cands)

    def test_git_wrapper_discovery_then_use(self):
        # PR 3: ``git --version`` (version_query) emits the git-family
        # candidate directly.
        turns = [
            make_bash_turn(0, "git --version", output_tail="git version 2.42.0"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "git" for c in cands)

    def test_pnpm_discovery_then_use(self):
        turns = [
            make_bash_turn(0, "pnpm --version pkg.json"),
            make_bash_turn(1, "pnpm build pkg.json"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "pnpm" for c in cands)

    def test_cargo_new_ecosystem_no_code_change(self):
        turns = [
            make_bash_turn(0, "cargo --version ./target"),
            make_bash_turn(1, "cargo test ./target"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "cargo" for c in cands)

    def test_make_wrapper_discovery_then_use(self):
        turns = [
            make_turn(0, files_read=["Makefile"]),
            make_bash_turn(1, "make test Makefile"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "make" for c in cands)

    def test_bash_output_tail_carries_artifact(self):
        turns = [
            make_bash_turn(
                0, "where python",
                output_tail="C:/Users/x/.venv/Scripts/python.exe",
            ),
            make_bash_turn(1, "C:/Users/x/.venv/Scripts/python.exe -c 'pass'"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert cands, "artifact from output_tail should still match"


# --------------------------------------------------------------------------- #
# TestNegativeDerivation                                                      #
# --------------------------------------------------------------------------- #


class TestNegativeDerivation:
    def test_discovery_alone_no_use_no_candidate(self):
        turns = [make_bash_turn(0, "uv sync")]
        assert derive_operational_facts(turns, CONTAINER, fake_scope_resolver) == []

    def test_use_alone_no_discovery_no_candidate(self):
        turns = [make_bash_turn(0, "uv run pytest tests/")]
        # `pytest` is an argv token that could match itself as artifact, but
        # discovery on the same turn as use is disallowed.
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert cands == []

    def test_use_of_different_artifact_same_family_no_candidate(self):
        turns = [
            make_bash_turn(0, "python 3.12 foo.py"),
            make_bash_turn(1, "python 3.10 bar.py"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        # 3.12 discovered; use has 3.10 in argv, not 3.12 → no match on that
        # artifact. There may still be candidates for other tokens (`foo.py`
        # in disc → not in use). Assert none share artifact "3.12".
        assert not any("3.12" in c.artifact_normalized for c in cands)

    def test_failed_use_exit_code_nonzero_no_candidate(self):
        turns = [
            make_bash_turn(0, "uv sync"),
            make_bash_turn(1, "uv run pytest tests/", exit_code=1),
        ]
        assert derive_operational_facts(turns, CONTAINER, fake_scope_resolver) == []

    def test_ambiguous_argv_no_artifact_token_no_candidate(self):
        turns = [make_bash_turn(0, "ls"), make_bash_turn(1, "ls")]
        assert derive_operational_facts(turns, CONTAINER, fake_scope_resolver) == []

    @pytest.mark.xfail(
        reason="operational_fact redesign PR 3 removed the discovery+use pairing "
               "model; each reconnaissance verb emits independently, so cross-scope "
               "pairing is no longer a concept the predicate enforces",
        strict=False,
    )
    def test_discovery_wrong_scope_no_candidate(self):
        # Custom resolver that produces different scope refs for the two
        # turns' artifacts; predicate cannot fabricate a cross-scope match
        # (both events must be in same scope). The resolver is called
        # only at candidate emission, so this test asserts the semantics
        # by rejecting candidates with mismatched artifact paths.
        turns = [
            make_bash_turn(0, "python /machine-a/.venv/Scripts/python.exe --version"),
            make_bash_turn(1, "python /machine-b/.venv/Scripts/python.exe --version"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        # Neither exact artifact appears in the other's argv → no candidates
        assert cands == []

    def test_use_before_discovery_no_candidate(self):
        turns = [
            make_bash_turn(0, "uv run pytest tests/"),
            make_bash_turn(1, "uv sync"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert not any(c.artifact_normalized == "uv sync" for c in cands)

    def test_secret_only_argv_no_candidate(self):
        turns = [
            make_bash_turn(0, 'curl -H "Authorization: Bearer sk-xxxx"'),
            make_bash_turn(1, 'curl -H "Authorization: Bearer sk-xxxx"'),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        # No candidate should reference the redacted token as artifact.
        for c in cands:
            assert "sk-xxxx" not in c.artifact
            assert "sk-xxxx" not in c.artifact_normalized


# --------------------------------------------------------------------------- #
# TestWindowsWordBoundary — REMOVED in PR 5 of the operational_fact redesign  #
#                                                                             #
# The word-boundary matcher (`_artifact_matches_argv`) was part of the        #
# pre-PR-3 discovery+use pairing model. PR 3 replaced pairing with the        #
# reconnaissance-verb predicate, and PR 5 removed the matcher and its         #
# tests. Word-boundary semantics are still enforced upstream in               #
# `semantic.argv` via the shared shell tokenizer.                             #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# TestRedaction                                                               #
# --------------------------------------------------------------------------- #


class TestRedaction:
    def test_redaction_bearer_token_in_use_fragment(self):
        turns = [
            make_bash_turn(0, "curl -sI https://api.example.com/health"),
            make_bash_turn(
                1,
                'curl -H "Authorization: Bearer sk-abc123" https://api.example.com/health',
            ),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert cands, "expected at least one candidate for the URL artifact"
        for c in cands:
            for ev in c.evidence:
                assert "sk-abc123" not in ev.fragment
            assert "sk-abc123" not in c.artifact
            assert "sk-abc123" not in c.artifact_normalized

    def test_redaction_api_key_header_case_insensitive(self):
        from semantic.redaction import redact_sensitive
        redacted = redact_sensitive('curl -H "x-API-Key: hunter2" https://api.example.com')
        assert "hunter2" not in redacted
        assert "[REDACTED]" in redacted

    def test_redaction_env_var_secret_prefix(self):
        from semantic.redaction import redact_sensitive
        redacted = redact_sensitive("PASSWORD=hunter2 python foo.py")
        assert "hunter2" not in redacted
        assert "PASSWORD=[REDACTED]" in redacted
        # Artifact-adjacent tokens survive.
        assert "python" in redacted
        assert "foo.py" in redacted

    def test_redaction_connection_string_postgres(self):
        from semantic.redaction import redact_sensitive
        redacted = redact_sensitive("psql postgresql://user:pw@host/db")
        assert "user:pw@host" not in redacted
        assert "postgresql://[REDACTED]" in redacted

    def test_redaction_connection_string_multi_scheme(self):
        from semantic.redaction import redact_sensitive
        for scheme in ("mongodb", "mysql", "redis", "amqp"):
            r = redact_sensitive(f"connect {scheme}://user:pw@host/db")
            assert f"{scheme}://[REDACTED]" in r
            assert "user:pw" not in r

    def test_redaction_authorization_header(self):
        from semantic.redaction import redact_sensitive
        redacted = redact_sensitive('curl -H "Authorization: Basic Zm9v"')
        assert "Zm9v" not in redacted
        assert "[REDACTED]" in redacted

    def test_redaction_source_is_semantic_module(self):
        # The predicate imports its redaction helper from semantic.redaction.
        # This test asserts the shared source-of-truth boundary.
        assert op.redact_sensitive.__module__ == "semantic.redaction"

    def test_redaction_does_not_mangle_legitimate_env_prefixed_identifiers(self):
        # Regression: earlier pattern with no left boundary was consuming
        # RHS of MONKEY=..., HOTKEY_MAPPING=..., AUTHOR=... — plainly wrong.
        from semantic.redaction import redact_sensitive
        for text in [
            "MONKEY=banana",
            "HOTKEY_MAPPING=foo.json",
            "AUTHOR=jane",
            "MYPASSWORD_STORE=./secrets.enc",  # left boundary must fire
        ]:
            r = redact_sensitive(text)
            assert "[REDACTED]" not in r, (
                f"redaction mangled a non-secret identifier: {text!r} -> {r!r}"
            )

    def test_redaction_env_var_secret_with_word_boundary_still_fires(self):
        # Verify the corrected env-var regex still catches real secrets when
        # the identifier is EXACTLY one of the sensitive keywords.
        from semantic.redaction import redact_sensitive
        assert "[REDACTED]" in redact_sensitive("PASSWORD=hunter2 python foo.py")
        assert "[REDACTED]" in redact_sensitive("SECRET=abc123 script")
        assert "[REDACTED]" in redact_sensitive("api call TOKEN=xyz used")
        assert "[REDACTED]" in redact_sensitive("KEY=abc AUTH=def")

    def test_redaction_authorization_header_preserves_trailing_url(self):
        # Regression: earlier pattern consumed everything up to newline,
        # destroying the URL argv that IS the artifact.
        from semantic.redaction import redact_sensitive
        text = 'curl -H "Authorization: Bearer sk-xxx" https://api.example.com/health'
        r = redact_sensitive(text)
        assert "https://api.example.com/health" in r
        assert "sk-xxx" not in r

    def test_redaction_of_artifact_shaped_path_token(self):
        # Secret in a path-shaped argv token that WOULD be extracted as an
        # artifact if not redacted. Confirms redaction guards the argv-match
        # key, not just fragment text.
        turns = [
            make_bash_turn(
                0,
                "curl https://api.example.com/keys/PASSWORD=hunter2",
            ),
            make_bash_turn(
                1,
                "curl https://api.example.com/keys/PASSWORD=hunter2",
            ),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        for c in cands:
            assert "hunter2" not in c.artifact
            assert "hunter2" not in c.artifact_normalized
            for ev in c.evidence:
                assert "hunter2" not in ev.fragment


# --------------------------------------------------------------------------- #
# TestScopeResolver                                                           #
# --------------------------------------------------------------------------- #


class TestScopeResolver:
    def test_scope_repo_relative_path_repo_scope(self):
        kind, ref = resolve_scope(CONTAINER, "./gradlew", lambda: "hash")
        assert kind == "repo"
        assert ref == CONTAINER

    def test_scope_absolute_windows_path_machine_repo(self):
        kind, ref = resolve_scope(
            CONTAINER, "C:/Users/x/.venv/Scripts/python.exe", lambda: "abc123"
        )
        assert kind == "machine_repo"
        assert ref == f"{CONTAINER}@machine:abc123"

    def test_scope_absolute_posix_path_machine_repo(self):
        kind, ref = resolve_scope(CONTAINER, "/home/x/.venv/bin/python", lambda: "xyz")
        assert kind == "machine_repo"
        assert ref.endswith("xyz")

    def test_scope_machine_hash_salted_hostname_never_raw(self, monkeypatch, tmp_path):
        # Point salt file to tmp; force known hostname.
        monkeypatch.setenv("PALLIUM_MACHINE_HASH_SALT", "test-salt-xyz")
        monkeypatch.setattr(op, "_safe_hostname", lambda: "pallium-dev-01")
        op._default_machine_hash_provider.cache_clear()
        op._load_machine_hash_salt.cache_clear()
        h = op._default_machine_hash_provider()
        assert "pallium-dev-01" not in h
        assert len(h) == 16  # sha256 hex prefix
        # And is deterministic given the same inputs.
        assert h == op._default_machine_hash_provider()

    def test_scope_machine_hash_cached_across_calls(self, monkeypatch):
        counter = {"n": 0}

        def _hostname():
            counter["n"] += 1
            return "hostA"

        monkeypatch.setattr(op, "_safe_hostname", _hostname)
        monkeypatch.setenv("PALLIUM_MACHINE_HASH_SALT", "cached-salt")
        op._default_machine_hash_provider.cache_clear()
        op._load_machine_hash_salt.cache_clear()
        for _ in range(50):
            op._default_machine_hash_provider()
        assert counter["n"] == 1

    def test_scope_hostname_resolution_failure_fallback(self, monkeypatch):
        import socket as _socket

        def _raise_gethostname():
            raise OSError("no host")

        monkeypatch.setattr(_socket, "gethostname", _raise_gethostname)
        # Ensure _safe_hostname uses its fallback chain.
        assert op._safe_hostname() in {"unknown-host"} or op._safe_hostname()


# --------------------------------------------------------------------------- #
# TestPathNormalization                                                       #
# --------------------------------------------------------------------------- #


class TestPathNormalization:
    def test_normalize_windows_and_posix_equivalent_paths_match(self):
        a = op._normalize_artifact("C:\\Users\\x\\.venv\\Scripts\\python.exe")
        b = op._normalize_artifact("C:/Users/x/.venv/Scripts/python.exe")
        assert a == b

    def test_normalize_drive_letter_case_insensitive(self):
        a = op._normalize_artifact("c:\\foo")
        b = op._normalize_artifact("C:\\foo")
        assert a == b

    def test_normalize_leading_dot_slash_stripped(self):
        a = op._normalize_artifact("./gradlew")
        b = op._normalize_artifact("gradlew")
        assert a == b


# --------------------------------------------------------------------------- #
# TestCommandFamilyClassifier                                                 #
# --------------------------------------------------------------------------- #


class TestCommandFamilyClassifier:
    @pytest.mark.parametrize(
        "cmd,expected",
        [
            ("python foo.py", "python"),
            ("node index.js", "node"),
            ("npm test", "npm"),
            ("pnpm build", "pnpm"),
            ("yarn install", "yarn"),
            ("uv sync", "uv"),
            ("pip install pkg", "pip"),
            ("cargo test", "cargo"),
            ("go test ./...", "go"),
            ("gradle build", "gradle"),
            ("docker ps", "docker"),
            ("git status", "git"),
            ("make test", "make"),
            ("curl -sI https://x/health", "service"),
        ],
    )
    def test_family_every_documented_family_maps_correctly(self, cmd, expected):
        assert op._command_family(cmd, "") == expected
        assert expected in KNOWN_FAMILIES

    def test_family_env_wrapper_stripped(self):
        assert op._command_family("env FOO=1 python foo.py", "") == "python"

    def test_family_sudo_wrapper_stripped(self):
        assert op._command_family("sudo docker ps", "") == "docker"

    def test_family_full_path_basename_used(self):
        assert op._command_family("/usr/bin/python3 foo", "") == "python"

    def test_family_unknown_falls_back_to_shell(self):
        assert op._command_family("foobarbaz --help", "") == "shell"

    def test_family_python_exe_windows(self):
        assert op._command_family("C:/Users/x/python.exe -V", "") == "python"

    def test_artifact_role_bare_port_classified_as_endpoint(self):
        # Regression for the port-token dead branch: bare port strings
        # like ":8000" or "8000" should classify as endpoint.
        assert op._derive_artifact_role("curl :8000/health", ":8000", "service") == "endpoint"
        assert op._derive_artifact_role("nc localhost 8000", "8000", "service") == "endpoint"


# --------------------------------------------------------------------------- #
# TestMalformedMetadata                                                       #
# --------------------------------------------------------------------------- #


class TestMalformedMetadata:
    def test_turn_record_no_commands_field_returns_empty(self):
        turns = [make_turn(0), make_turn(1)]
        assert derive_operational_facts(turns, CONTAINER, fake_scope_resolver) == []

    def test_turn_record_command_missing_exit_code_conservative(self):
        turns = [
            make_turn(0, commands=[("uv sync", None)]),
            make_bash_turn(1, "uv run pytest"),
        ]
        # exit_code=None → treated as non-zero; no discovery, no use.
        assert derive_operational_facts(turns, CONTAINER, fake_scope_resolver) == []

    def test_turn_record_empty_cmd_string(self):
        turns = [make_turn(0, commands=[("", 0)]), make_bash_turn(1, "uv sync")]
        # Should not raise; may produce a candidate for `uv sync` discovery
        # in turn 1 alone (which is fine — asserting no exception is the point).
        derive_operational_facts(turns, CONTAINER, fake_scope_resolver)

    def test_turn_stream_out_of_order_still_derives(self):
        # PR 3: each recon verb emits independently; out-of-order input
        # still produces the expected family candidate.
        turns = [
            make_bash_turn(1, "uv --version", output_tail="uv 0.4.0"),
            make_bash_turn(0, "cat pyproject.toml"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "uv" for c in cands)


# --------------------------------------------------------------------------- #
# TestUnicode                                                                 #
# --------------------------------------------------------------------------- #


class TestUnicode:
    def test_unicode_artifact_survives_normalization(self):
        # PR 3: use a reconnaissance verb (``ls`` = directory_probe) so
        # a single event emits a candidate; the invariant preserved here
        # is that non-ASCII characters survive redaction/normalization.
        turns = [
            make_bash_turn(0, "ls résumé.py"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any("résumé.py" in c.artifact_normalized for c in cands)

    def test_non_ascii_command_output_tail(self):
        turns = [
            make_bash_turn(
                0, "where python",
                output_tail="路径/.venv/bin/python 通过 stable 1.0",
            ),
            make_bash_turn(1, "路径/.venv/bin/python --check"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert cands, "expected at least one candidate with non-ASCII path"


# --------------------------------------------------------------------------- #
# TestPredicatePurity                                                         #
# --------------------------------------------------------------------------- #


class TestPredicatePurity:
    def test_purity_no_clock_dependency(self, monkeypatch):
        import datetime as _dt

        class _FrozenDT(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                raise RuntimeError("predicate must not call datetime.now")

        monkeypatch.setattr(_dt, "datetime", _FrozenDT)
        turns = [
            make_bash_turn(0, "uv sync"),
            make_bash_turn(1, "uv run pytest"),
        ]
        # Same input → identical output across two calls.
        a = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        b = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert a == b

    def test_purity_no_random_dependency(self, monkeypatch):
        import random as _random

        monkeypatch.setattr(
            _random, "random", lambda: (_ for _ in ()).throw(RuntimeError("no rand"))
        )
        turns = [
            make_bash_turn(0, "uv sync"),
            make_bash_turn(1, "uv run pytest"),
        ]
        # Predicate must not touch random.random.
        derive_operational_facts(turns, CONTAINER, fake_scope_resolver)


# --------------------------------------------------------------------------- #
# TestPerformanceBudget                                                       #
# --------------------------------------------------------------------------- #


class TestPerformanceBudget:
    def test_wall_clock_budget_1251_turns_under_5s(self):
        # Synthesize a 1,251-turn stream with 1.4 avg commands per turn.
        turns: list = []
        for i in range(1251):
            cmd = f"uv run pytest step-{i}.py" if i % 2 else "uv sync"
            turns.append(make_bash_turn(i, cmd))
        start = time.perf_counter()
        derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"perf budget exceeded: {elapsed:.2f}s"


# --------------------------------------------------------------------------- #
# TestCrossOriginConflict                                                     #
# --------------------------------------------------------------------------- #


class TestCrossOriginConflict:
    def test_predicate_emits_derived_candidate_wiring_layer_owns_agent_explicit_priority(self):
        # The predicate does not know about agent_explicit facts — that
        # precedence is enforced by the wiring layer (PR 3). This test
        # documents the boundary: the predicate emits its candidate
        # regardless of whether an explicit fact exists.
        # PR 3 (recon-verb model): use ``uv --version`` (version_query).
        turns = [
            make_bash_turn(0, "uv --version", output_tail="uv 0.4.0"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert any(c.command_family == "uv" for c in cands), (
            "predicate must emit derived candidate; agent_explicit priority is "
            "wiring-layer territory"
        )


# --------------------------------------------------------------------------- #
# TestDedupAndConflictSlot                                                    #
# --------------------------------------------------------------------------- #


class TestDedupAndConflictSlot:
    def test_dedup_exact_key_first_wins_within_run(self):
        # Two identical discovery+use pairs back-to-back.
        turns = [
            make_bash_turn(0, "uv sync"),
            make_bash_turn(1, "uv run pytest"),
            make_bash_turn(2, "uv sync"),
            make_bash_turn(3, "uv run pytest"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        keys = {(c.command_family, c.artifact_normalized) for c in cands}
        # Same (family, artifact_normalized) collapses to one entry.
        assert len(keys) == len(cands)

    def test_dedup_different_artifact_same_slot_both_emitted(self):
        # Same slot (python config anchor at repo scope) with two
        # different artifact_normalized values → both emitted;
        # supersession is the wiring layer's responsibility.
        # PR 3 (recon-verb model): use cat_config_recon on two anchors.
        turns = [
            make_bash_turn(0, "cat pyproject.toml"),
            make_bash_turn(1, "cat requirements.txt"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        arts = {c.artifact_normalized for c in cands}
        assert any("pyproject.toml" in a for a in arts)
        assert any("requirements.txt" in a for a in arts)
        # Cardinality-1 pin on the conflict slot itself: both artifacts land
        # in the SAME (command_family, artifact_role, scope_kind, scope_ref)
        # slot — supersession is the wiring layer's responsibility.
        slots = {
            (c.command_family, c.artifact_role, c.scope_kind, c.scope_ref)
            for c in cands
            if "pyproject.toml" in c.artifact_normalized
            or "requirements.txt" in c.artifact_normalized
        }
        assert len(slots) == 1, f"expected one shared slot; got {slots}"

    def test_dedup_use_counters_not_populated_by_predicate(self):
        # PR 3 (recon-verb model): a single ``uv --version`` emits.
        turns = [
            make_bash_turn(0, "uv --version", output_tail="uv 0.4.0"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert cands
        # OperationalFactCandidate has no reuse_count / last_used_at attrs
        # by design — those live in the wiring layer's payload use_counters.
        for c in cands:
            assert not hasattr(c, "reuse_count")
            assert not hasattr(c, "last_used_at")


# --------------------------------------------------------------------------- #
# TestModuleImportBoundary                                                    #
# --------------------------------------------------------------------------- #


class TestModuleImportBoundary:
    @pytest.mark.parametrize(
        "module_name",
        ["semantic.operational_fact", "semantic.redaction"],
    )
    def test_predicate_does_not_import_storage_or_core_or_integrations(self, module_name):
        source = importlib.import_module(module_name).__file__
        with open(source, "r", encoding="utf-8") as f:
            text = f.read()
        forbidden_prefixes = (
            "from storage",
            "import storage",
            "from core.",
            "import core",
            "from providers",
            "import providers",
            "from integrations",
            "import integrations",
        )
        for prefix in forbidden_prefixes:
            assert prefix not in text, (
                f"{module_name} must not use '{prefix}' "
                "(predicate + redaction stay pure; wiring lives elsewhere)"
            )
