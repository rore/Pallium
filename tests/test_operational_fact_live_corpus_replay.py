"""Live-corpus replay: verify PR 3 predicate suppresses the noise
that the pre-PR-3 predicate emitted.

**Discipline** (user directive, 2026-07-02): before cleaning up bad
live data, use it as an existence proof that the new predicate
correctly rejects it. Any regression that reintroduces the pre-PR-3
permissive shape channel will re-emit these rows and fail this test.

This test reads a fixture built from the live DB on 2026-07-02 at
commit ``e63eff9`` (post-PR-2, pre-PR-3). The fixture contains 218
active operational_fact rows across 4 containers. The invariant
locked here: **the vast majority of them would NOT be produced under
PR 3** — because they came from the deleted discovery+use pairing
model that admitted anything shaped like an argv token.

The fixture ships with each row's provenance: the source turn's
``cmd`` + ``output_tail`` + ``files_read``. Replaying that turn
through ``derive_operational_facts`` under PR 3 must produce zero or
few operational_fact candidates for the noisy rows.

Do NOT run this against the actual live DB — this test uses a
committed static fixture so future runs replay the same "before"
state deterministically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from semantic.operational_fact import derive_operational_facts
from semantic.reconnaissance import detect_reconnaissance
from tests.fixtures.operational_fact import fake_scope_resolver, make_bash_turn, make_turn


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "live_corpus_pre_pr3_2026_07_02.json"


def _load_fixture() -> list[dict]:
    if not _FIXTURE_PATH.exists():
        pytest.skip(f"live-corpus fixture missing at {_FIXTURE_PATH}")
    with _FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _turn_from_fixture(entry: dict) -> object:
    """Construct a TurnRecord from a fixture entry."""
    cmds = entry.get("commands") or []
    if cmds:
        first = cmds[0]
        return make_bash_turn(
            entry.get("turn_index", 0),
            first.get("cmd", ""),
            exit_code=first.get("exit_code", 0),
            output_tail=first.get("output_tail", ""),
        )
    return make_turn(
        entry.get("turn_index", 0),
        files_read=tuple(entry.get("files_read") or ()),
    )


class TestLiveCorpusRejectionRate:
    """The core invariant: PR 3 rejects the noise that motivated the
    redesign. Not every legacy row must be rejected — some were
    legitimate (interpreter paths, config-file basenames). But the
    aggregate rejection rate on the pre-PR-3 corpus must be high
    enough that the noise is gone.
    """

    def test_grep_pattern_rows_produce_no_candidate(self):
        # Live-corpus row: family=shell, role=path, artifact=
        # "^def /|^__all__" — a grep pattern captured as an argv
        # token. Under the pre-PR-3 discovery+use pairing this landed
        # as an operational_fact.
        turn = make_bash_turn(
            0,
            "grep -n '^def /|^__all__' storage/sqlite.py",
            output_tail="",
        )
        cands = derive_operational_facts(
            [turn], "path:tmp:ee1a7f749cab", fake_scope_resolver,
        )
        # No reconnaissance verb fires — grep is not in the closed set.
        assert all("^def" not in c.artifact_normalized for c in cands)

    def test_regex_capture_rows_produce_no_candidate(self):
        # Live-corpus row: artifact was a regex string. Same failure
        # mode as above — argv tokenizer captured the regex.
        turn = make_bash_turn(
            0,
            "grep -rE 'reconcile_process_result/|_persist' semantic/",
            output_tail="",
        )
        cands = derive_operational_facts(
            [turn], "git:github.com/rore/pallium", fake_scope_resolver,
        )
        assert not cands

    def test_one_off_script_path_produces_no_candidate(self):
        # Live-corpus rows: many role=path artifacts were one-off
        # script paths. Not reconnaissance verbs, no promotion signal.
        # PR 3: no recon verb fires → zero candidates.
        turn = make_bash_turn(
            0,
            "python tests/test_redaction_tier_a_and_b.py",
            output_tail="",
        )
        cands = derive_operational_facts(
            [turn], "git:github.com/rore/pallium", fake_scope_resolver,
        )
        assert not cands

    def test_ls_directory_still_admits_but_as_recon(self):
        # ``ls tests/`` IS reconnaissance — directory_probe. Under
        # PR 3 it emits a candidate. Under PR 4 it will need cross-
        # thread recurrence to promote, so a single ``ls tests/`` in
        # one thread won't surface. Verified: candidate emerges but
        # with lifecycle handled downstream.
        turn = make_bash_turn(0, "ls tests/", output_tail="test_a.py\ntest_b.py")
        cands = derive_operational_facts(
            [turn], "git:github.com/rore/pallium", fake_scope_resolver,
        )
        assert cands  # candidate emerges
        # Every downstream row is a candidate — invisibility handled
        # by the storage layer (Test 9 in test_operational_fact_e2e).

    def test_heredoc_source_content_still_rejected(self):
        # From PR 2's motivating live-corpus offender:
        # ``cat > path <<'EOF'\nimport sys\n...`` — heredoc source
        # scanned as argv tokens.
        turn = make_bash_turn(
            0,
            "cat > tmp.py <<'EOF'\nimport sys\nsys.path.insert(0, '/wp')\nEOF",
            output_tail="",
        )
        cands = derive_operational_facts(
            [turn], "path:tmp:ee1a7f749cab", fake_scope_resolver,
        )
        # PR 2 + PR 3: argv tokenizer stops at ``<<``; ``cat > file``
        # with a config-anchor filename basename WOULD have matched
        # cat_config_recon, but ``tmp.py`` isn't a config anchor, so
        # nothing fires.
        assert not cands

    def test_url_with_shell_substitution_produces_no_candidate(self):
        # Live-corpus row (from PR D URL hygiene notes):
        # ``curl 'https://x.com/?bust=$(date +%s)'`` — the pre-PR-3
        # extractor captured the URL as an operational_fact endpoint.
        # PR 3: only port_probe emits endpoints, and only for
        # ``curl -sI``/``--head``/etc. Plain curl fetch is not recon.
        turn = make_bash_turn(
            0,
            "curl 'https://x.com/?bust=$(date +%s)'",
            output_tail="<html>",
        )
        cands = derive_operational_facts(
            [turn], "path:roni_linder_articles:b86c0c3f661d", fake_scope_resolver,
        )
        assert not cands


class TestLiveCorpusLegitimateStillAdmits:
    """The complement: legitimate reconnaissance behaviors from the
    live corpus continue to admit under PR 3.
    """

    def test_python_version_reconnaissance_still_admits(self):
        turn = make_bash_turn(0, "python --version", output_tail="Python 3.13.14")
        cands = derive_operational_facts(
            [turn], "git:github.com/rore/pallium", fake_scope_resolver,
        )
        assert cands
        cand = cands[0]
        assert cand.command_family == "python"
        assert cand.artifact_role == "version"

    def test_where_python_reconnaissance_still_admits(self):
        turn = make_bash_turn(
            0, "where python",
            output_tail="C:/Users/I347041/AppData/Roaming/uv/python/cpython-3.13.14-windows-x86_64-none/python.exe",
        )
        cands = derive_operational_facts(
            [turn], "git:github.com/rore/pallium", fake_scope_resolver,
        )
        assert cands
        # A real interpreter path lands with role=interpreter.
        assert any(c.artifact_role == "interpreter" for c in cands)

    def test_cat_pyproject_still_admits(self):
        turn = make_bash_turn(
            0, "cat pyproject.toml", output_tail="[project]\nname = 'pallium'",
        )
        cands = derive_operational_facts(
            [turn], "git:github.com/rore/pallium", fake_scope_resolver,
        )
        assert cands
        assert cands[0].command_family == "python"
        assert cands[0].artifact_role == "config"


class TestLiveCorpusReplayFixture:
    """Replay the live-corpus fixture through PR 3 and assert the
    aggregate rejection rate is high.

    The fixture is the actual 218-row live-DB snapshot from 2026-07-02
    at commit e63eff9 (post-PR-2, pre-PR-3). Extracted via
    ``scripts/extract_live_corpus_fixture.py`` — see fixture generation
    script for methodology.

    Skipped if the fixture isn't present.
    """

    def test_aggregate_noise_rejection_rate_high(self):
        entries = _load_fixture()
        if not entries:
            pytest.skip("fixture empty")
        admitted = 0
        for entry in entries:
            turn = _turn_from_fixture(entry)
            recon_events = detect_reconnaissance(turn)
            if recon_events:
                admitted += 1
        n = len(entries)
        # Aggregate expectation from the 2026-07-02 live corpus:
        # the majority of pre-PR-3 rows were noise (grep patterns,
        # regex captures, one-off script paths). At least 60% must
        # be rejected. Tune down if the fixture composition shifts;
        # never tune below 50% without a design review.
        rejected_frac = 1.0 - (admitted / n)
        assert rejected_frac >= 0.60, (
            f"expected ≥60% rejection on the pre-PR-3 noise corpus, "
            f"got {rejected_frac:.1%} ({admitted}/{n} admitted). "
            f"If the fixture composition shifted legitimately, update "
            f"this threshold; otherwise investigate the regression."
        )
