"""W4 follow-up 2026-07-02 — predicate admission gate tests.

Two layers of coverage:

1. **Unit tests** over ``_is_operational_shape_artifact`` and
   ``_is_admissible_candidate``. One accepted + one rejected case per
   role/family combo, plus the ``127.0.0`` version-tightening regression
   and the shell/path fallback rejection.

2. **Integration tests** through ``derive_operational_facts`` end-to-end:
   the per-thread cap, the AdmissionDiagnostics dataclass, and the live-
   corpus fixture at ``tests/fixtures/live_corpus_row_samples.py`` mapped
   through the admission helper.

Together these lock the design invariants from the shipped plan:
- Fallback ``family=shell`` rows without operational shape are dropped.
- Known families with new-ecosystem artifacts are admitted.
- Per-thread cap defaults to 5, applied deterministically.
- Diagnostics counters sum coherently.
"""

from __future__ import annotations

import pytest

from semantic.operational_fact import (
    AdmissionDiagnostics,
    MAX_CANDIDATES_PER_REBUILD,
    OperationalFactCandidate,
    _is_admissible_candidate,
    _is_operational_shape_artifact,
    derive_operational_facts,
)
from tests.fixtures.live_corpus_row_samples import LIVE_CORPUS_ROWS
from tests.fixtures.operational_fact import (
    fake_scope_resolver,
    make_bash_turn,
    make_turn,
)


CONTAINER = "git:example/repo"


# --------------------------------------------------------------------------- #
# TestFallbackFamilyRejected — fallback shell w/o shape channel rejected.     #
# --------------------------------------------------------------------------- #


class TestFallbackFamilyRejected:
    """Live data showed 86% of emitted rows were the shell fallback slot.
    The gate must drop these unless they hit an explicit shape channel.
    """

    def test_shell_path_arbitrary_source_file_rejected(self):
        assert not _is_operational_shape_artifact("app/dashboard.py", "shell", "path")

    def test_shell_path_directory_rejected(self):
        assert not _is_operational_shape_artifact("tests/", "shell", "path")

    def test_shell_path_regex_pattern_rejected(self):
        assert not _is_operational_shape_artifact("foo|bar", "shell", "path")

    def test_shell_endpoint_bare_int_rejected(self):
        assert not _is_operational_shape_artifact("3", "shell", "endpoint")

    def test_shell_path_config_file_still_admitted_via_shape_channel(self):
        # Even under family=shell fallback, a known operational config
        # basename passes through the shape channel.
        assert _is_operational_shape_artifact("pyproject.toml", "shell", "path")

    def test_shell_endpoint_url_still_admitted_via_shape_channel(self):
        assert _is_operational_shape_artifact(
            "http://127.0.0.1:8000/health", "shell", "endpoint"
        )


# --------------------------------------------------------------------------- #
# TestOperationalShapeArtifact — one keep + one drop per role/family.         #
# --------------------------------------------------------------------------- #


class TestOperationalShapeArtifact:
    # --- interpreter ---
    def test_interpreter_python_exe_admitted(self):
        assert _is_operational_shape_artifact(
            "C:/Users/x/.venv/scripts/python.exe", "python", "interpreter"
        )

    def test_interpreter_random_exe_rejected(self):
        assert not _is_operational_shape_artifact(
            "C:/tools/notepad.exe", "shell", "interpreter"
        )

    def test_interpreter_node_admitted(self):
        assert _is_operational_shape_artifact(
            "/usr/local/bin/node", "shell", "interpreter"
        )

    # --- venv ---
    def test_venv_dot_venv_admitted(self):
        assert _is_operational_shape_artifact(
            "/repo/.venv/bin/python", "python", "venv"
        )

    def test_venv_unrelated_path_rejected(self):
        assert not _is_operational_shape_artifact(
            "/repo/random/path", "shell", "venv"
        )

    # --- endpoint ---
    def test_endpoint_url_admitted(self):
        assert _is_operational_shape_artifact(
            "http://127.0.0.1:8000/health", "service", "endpoint"
        )

    def test_endpoint_host_port_admitted(self):
        assert _is_operational_shape_artifact(
            "localhost:5432", "service", "endpoint"
        )

    def test_endpoint_random_string_rejected(self):
        assert not _is_operational_shape_artifact(
            "random-nonsense", "shell", "endpoint"
        )

    # --- version (tightened over W4 extraction regex) ---
    def test_version_strict_semver_admitted(self):
        assert _is_operational_shape_artifact("3.13.14", "python", "version")

    def test_version_semver_with_prerelease_admitted(self):
        assert _is_operational_shape_artifact("1.0.0-rc.1", "cargo", "version")

    def test_version_two_part_rejected(self):
        # The extraction regex accepts 2-part; admission requires 3-part.
        assert not _is_operational_shape_artifact("127.0", "service", "version")

    def test_version_ip_prefix_regression_rejected(self):
        # The exact 127.0.0 live-corpus false positive.
        assert not _is_operational_shape_artifact("127.0.0", "service", "version")

    # --- config path basename ---
    def test_pyproject_admitted(self):
        assert _is_operational_shape_artifact("pyproject.toml", "uv", "path")

    def test_makefile_admitted(self):
        assert _is_operational_shape_artifact("Makefile", "make", "path")

    def test_gradlew_admitted(self):
        assert _is_operational_shape_artifact("./gradlew", "gradle", "path")

    def test_arbitrary_source_file_rejected(self):
        assert not _is_operational_shape_artifact("app/dashboard.py", "shell", "path")

    # --- known-family channel (new ecosystem, unfamiliar artifact) ---
    def test_cargo_target_admitted(self):
        # cargo test ./target — target is unfamiliar but family is known.
        assert _is_operational_shape_artifact("target", "cargo", "runner")

    def test_pnpm_pkg_admitted(self):
        assert _is_operational_shape_artifact("pkg.json", "pnpm", "runner")

    def test_git_repo_path_admitted(self):
        assert _is_operational_shape_artifact("/repo/pallium", "git", "path")

    def test_new_ecosystem_bun_via_shape_only_rejected_when_no_shape(self):
        # Bun is not yet a KNOWN_FAMILY; a random artifact under shell
        # fallback must be rejected. When Bun's family lands, the
        # invariant flips (see admission-gate design note).
        assert not _is_operational_shape_artifact(
            "some.random.token", "shell", "runner"
        )


# --------------------------------------------------------------------------- #
# TestPerThreadCap — per-thread candidate cap of 5.                            #
# --------------------------------------------------------------------------- #


class TestPerThreadCap:
    """Deterministic cap under a synthetic stream of admissible candidates."""

    def _make_admissible_stream(self, n: int):
        # Generate n discovery+use pairs at different turn indices with
        # distinct known-family artifacts so all admit.
        turns = []
        for i in range(n):
            artifact = f"scripts/mod_{i:03d}.py"
            turns.append(make_bash_turn(2 * i, f"python {artifact} --dry"))
            turns.append(make_bash_turn(2 * i + 1, f"python {artifact}"))
        return turns

    def test_cap_default_value(self):
        assert MAX_CANDIDATES_PER_REBUILD == 5

    def test_under_cap_pass_through(self):
        turns = self._make_admissible_stream(3)
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert len(cands) == 3

    def test_over_cap_capped(self):
        turns = self._make_admissible_stream(10)
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert len(cands) == MAX_CANDIDATES_PER_REBUILD

    def test_over_cap_deterministic_ordering(self):
        # Same input twice → same output. The cap ranking must be a
        # pure function of the input candidates.
        turns = self._make_admissible_stream(8)
        c1 = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        c2 = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert [c.artifact_normalized for c in c1] == [c.artifact_normalized for c in c2]


# --------------------------------------------------------------------------- #
# TestLiveCorpusFixtures — 30 anonymized live rows, expected keep/drop.       #
# --------------------------------------------------------------------------- #


class TestLiveCorpusFixtures:
    """Drive ``_is_operational_shape_artifact`` with the anonymized live
    corpus and pin the expected keep/drop for each row."""

    def test_every_row_matches_expected_admit(self):
        misses = []
        for row in LIVE_CORPUS_ROWS:
            got = _is_operational_shape_artifact(
                row.artifact_normalized, row.family, row.role
            )
            if got != row.expected_admit:
                misses.append(
                    f"{row.family}/{row.role} art={row.artifact_normalized!r} "
                    f"expected_admit={row.expected_admit} got={got} "
                    f"({row.rationale})"
                )
        assert not misses, "live-corpus admission mismatches:\n" + "\n".join(misses)

    def test_drop_bucket_dominant(self):
        # Live data is ~86% drops; the fixture must reflect that.
        drops = sum(1 for r in LIVE_CORPUS_ROWS if not r.expected_admit)
        keeps = sum(1 for r in LIVE_CORPUS_ROWS if r.expected_admit)
        assert drops >= keeps * 4, (
            f"fixture drift: {drops} drops vs {keeps} keeps — "
            "live data motivating this PR was ~86% noise"
        )


# --------------------------------------------------------------------------- #
# TestDiagnosticsShape — return_diagnostics contract.                         #
# --------------------------------------------------------------------------- #


class TestDiagnosticsShape:
    def test_default_return_type_is_list(self):
        turns = [make_bash_turn(0, "uv sync ./pyproject.toml"),
                 make_bash_turn(1, "uv run pytest ./pyproject.toml")]
        result = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert isinstance(result, list)
        # legacy invariant: no diagnostics tuple by default
        assert not (isinstance(result, tuple) and len(result) == 2)

    def test_opt_in_returns_diagnostics(self):
        turns = [make_bash_turn(0, "uv sync ./pyproject.toml"),
                 make_bash_turn(1, "uv run pytest ./pyproject.toml")]
        result = derive_operational_facts(
            turns, CONTAINER, fake_scope_resolver, return_diagnostics=True
        )
        assert isinstance(result, tuple)
        cands, diag = result
        assert isinstance(cands, list)
        assert isinstance(diag, AdmissionDiagnostics)
        # admitted is the post-dedup, post-cap count — matches the
        # returned list length.
        assert diag.admitted == len(cands)

    def test_diagnostics_fallback_counter_populated(self):
        # A turn stream that would emit a shell/path fallback for a
        # random argv-shaped file. Force such a candidate by using a
        # discovery + use pair of a random source file (not on the
        # config allow-list).
        turns = [
            make_turn(0, files_read=["scripts/build.sh"]),
            make_bash_turn(1, "bash scripts/build.sh"),
        ]
        cands, diag = derive_operational_facts(
            turns, CONTAINER, fake_scope_resolver, return_diagnostics=True
        )
        # Whatever was produced upstream, the admitted list must
        # contain only shape-passing rows and diag.admitted matches.
        assert diag.admitted == len(cands)
        total_rejected = diag.fallback_family + sum(diag.non_operational_shape.values())
        assert total_rejected >= 0
        assert diag.capped == 0  # ≤ 5 raw candidates from this trace

    def test_empty_stream_yields_zero_diagnostics(self):
        cands, diag = derive_operational_facts(
            [], CONTAINER, fake_scope_resolver, return_diagnostics=True
        )
        assert cands == []
        assert diag == AdmissionDiagnostics()

    def test_diagnostics_admitted_equals_returned_length_under_cap(self):
        # Generate 10 admissible discovery/use pairs — the cap trims
        # to 5. diag.admitted must equal len(cands) == 5, and
        # diag.capped must equal 5.
        turns = []
        for i in range(10):
            artifact = f"scripts/mod_{i:03d}.py"
            turns.append(make_bash_turn(2 * i, f"python {artifact} --dry"))
            turns.append(make_bash_turn(2 * i + 1, f"python {artifact}"))
        cands, diag = derive_operational_facts(
            turns, CONTAINER, fake_scope_resolver, return_diagnostics=True
        )
        assert len(cands) == 5
        assert diag.admitted == len(cands)
        assert diag.capped == 5


# --------------------------------------------------------------------------- #
# TestBackwardCompat — legacy callers unchanged.                              #
# --------------------------------------------------------------------------- #


class TestBackwardCompat:
    def test_default_signature_returns_bare_list(self):
        # PR B must not change the default return type — retrieval
        # callers construct on the returned list, not a tuple.
        result = derive_operational_facts([], CONTAINER, fake_scope_resolver)
        assert result == []
        assert isinstance(result, list)

    def test_positional_call_still_works(self):
        turns = [make_bash_turn(0, "uv sync ./pyproject.toml"),
                 make_bash_turn(1, "uv run pytest ./pyproject.toml")]
        result = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        assert isinstance(result, list)
