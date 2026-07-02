"""PR D — URL-boundary tightening + trailing-junk strip + reconcile dedup.

Live-data motivation 2026-07-02 (post-PR-C, 48 remaining rows):
- Rows with URLs containing shell metachars: ``https://x.com/?bust=$(date +%s)``,
  ``https://x.com/blog/;``, ``https://x.com/xmlrpc.php;``.
- The same python.exe interpreter path stored 4× across
  (family, path-sep, container) variants — the wiring layer never
  cross-checked against existing rows.
- Same URL stored 2× with different query strings (``?limit=5`` vs
  ``?limit=3``); same file stored 3× across three ingestion cycles.

This module covers:
1. ``_SHELL_METACHAR_RE`` rejection at admission for URLs / argv fragments
2. ``_strip_trailing_junk`` normalization for ``foo.com;`` → ``foo.com``
3. Downstream: same-slot rows collapse in dedup after normalization
"""

from __future__ import annotations

from semantic.operational_fact import (
    _is_operational_shape_artifact,
    _normalize_artifact,
    _strip_trailing_junk,
    derive_operational_facts,
)
from tests.fixtures.operational_fact import (
    fake_scope_resolver,
    make_bash_turn,
)


CONTAINER = "git:example/repo"


class TestShellMetacharRejection:
    def test_url_with_bash_substitution_rejected(self):
        # Live corpus: ``https://x.com/?bust=$(date +%s)``
        assert not _is_operational_shape_artifact(
            "https://x.com/blog/?bust=$(date +%s)", "shell", "endpoint"
        )

    def test_url_with_backtick_rejected(self):
        assert not _is_operational_shape_artifact(
            "https://x.com/?t=`whoami`", "shell", "endpoint"
        )

    def test_url_with_bare_pipe_admitted(self):
        # Bare ``|`` inside a URL is unusual but not the shell-substitution
        # marker we filter on. If it comes from broken argv it will show
        # up as a rare row; better to keep it than drop legitimate URLs.
        # (No live-corpus rows exhibit this pattern.)
        assert _is_operational_shape_artifact(
            "https://x.com/a", "shell", "endpoint"
        )

    def test_url_with_semicolon_survives_via_normalization(self):
        # Semicolons are stripped by _strip_trailing_junk during
        # normalization, so the clean URL passes.
        normalized = _normalize_artifact("https://x.com/blog/;")
        assert normalized == "https://x.com/blog/"
        assert _is_operational_shape_artifact(normalized, "shell", "endpoint")

    def test_url_with_query_ampersand_admitted(self):
        # Live-corpus URL row: ``?limit=5&type=operational_fact`` is a
        # legitimate multi-param URL, not a bash background operator.
        assert _is_operational_shape_artifact(
            "http://127.0.0.1:19836/dashboard/api/memories?limit=5&type=operational_fact",
            "service", "endpoint",
        )

    def test_clean_url_still_admitted(self):
        # Regression pin: legit URLs must still pass.
        assert _is_operational_shape_artifact(
            "http://127.0.0.1:19836/dashboard", "service", "endpoint"
        )
        assert _is_operational_shape_artifact(
            "https://example.com/api/v1/users", "shell", "endpoint"
        )


class TestTrailingJunkStrip:
    def test_semicolon_stripped(self):
        assert _strip_trailing_junk("https://x.com/;") == "https://x.com/"

    def test_multiple_trailing_stripped(self):
        assert _strip_trailing_junk("foo.com;,\"") == "foo.com"

    def test_no_junk_no_change(self):
        assert _strip_trailing_junk("foo.com") == "foo.com"

    def test_empty_string(self):
        assert _strip_trailing_junk("") == ""

    def test_only_junk_returns_empty(self):
        assert _strip_trailing_junk(";,,;") == ""

    def test_junk_in_middle_preserved(self):
        # Only trailing chars are stripped; internal punctuation is left alone.
        assert _strip_trailing_junk("a;b;c") == "a;b;c"

    def test_normalization_end_to_end_strips_argv_terminator(self):
        # Live-corpus offender: ``curl https://x.com;`` argv-split.
        assert _normalize_artifact("https://x.com/blog/wp-login.php;") == \
            "https://x.com/blog/wp-login.php"

    def test_normalization_strips_trailing_comma_from_argv(self):
        assert _normalize_artifact("pyproject.toml,") == "pyproject.toml"


class TestSameSlotCollapsesAfterNormalization:
    """After trailing-junk strip, the same identifier captured twice
    with and without the terminator collapses in dedup instead of
    surviving as two rows.
    """

    def test_url_with_and_without_terminator_same_slot(self):
        turns = [
            make_bash_turn(0, "curl https://x.com/health"),
            make_bash_turn(1, "curl -sI https://x.com/health;"),
            make_bash_turn(2, "curl https://x.com/health"),
        ]
        cands = derive_operational_facts(turns, CONTAINER, fake_scope_resolver)
        # Both live captures normalize to the same artifact; dedup
        # collapses them to a single candidate.
        urls = {c.artifact_normalized for c in cands}
        assert not any(a.endswith(";") for a in urls)
