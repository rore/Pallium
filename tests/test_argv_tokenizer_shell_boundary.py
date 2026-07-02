"""E2E test for PR 2 — argv-tokenizer scope fix.

Test 3 from the operational_fact redesign plan: heredoc source
content must never be captured as an operational_fact artifact.

Pre-PR-2 the extractor scanned the entire ``cmd`` field, including
heredoc bodies. A command like:

    cat > file.py <<'EOF'
    import sys
    sys.path.insert(0, "{WP}/wp-content/functions.php")
    EOF

produced an "artifact" of ``{WP}/wp-content/functions.php`` because
the URL regex ran over the Python source content buried in the
heredoc. PR 2 fixes this by truncating the ``cmd`` at the first
unquoted shell-word boundary (``<<``, ``>``, ``|``, ``;``, ``&&``,
``||``) before extraction runs.
"""

from __future__ import annotations

from semantic.operational_fact import (
    _extract_artifact_tokens,
    _iter_argv_head,
    _shell_word_head,
)


# --------------------------------------------------------------------------- #
# _shell_word_head — pure function, exhaustive coverage                        #
# --------------------------------------------------------------------------- #


class TestShellWordHead:
    def test_no_boundary_returns_original(self):
        s = "python --version /repo/foo"
        assert _shell_word_head(s) == s

    def test_heredoc_boundary(self):
        s = "cat > file.py <<'EOF'\nimport sys\nprint('leak: /etc/passwd')\nEOF"
        # Truncation happens at the FIRST boundary. Here the ``>``
        # redirect precedes the ``<<`` heredoc marker, so the argv
        # slice returned is just ``cat ``. Either way, the heredoc
        # body ("import sys" etc.) is excluded — that's the load-
        # bearing invariant.
        head = _shell_word_head(s)
        assert "import sys" not in head
        assert "/etc/passwd" not in head
        assert head.startswith("cat")

    def test_redirect_single(self):
        s = "python -m app.main > /tmp/out.log"
        assert _shell_word_head(s) == "python -m app.main "

    def test_redirect_double(self):
        s = "echo test >> /var/log/pallium.log"
        assert _shell_word_head(s) == "echo test "

    def test_pipe(self):
        s = "ls /repo | grep test | wc -l"
        assert _shell_word_head(s) == "ls /repo "

    def test_semicolon(self):
        s = "cd /repo; python test.py; echo done"
        assert _shell_word_head(s) == "cd /repo"

    def test_and_then(self):
        s = "cd /repo && python test.py && echo ok"
        assert _shell_word_head(s) == "cd /repo "

    def test_or_else(self):
        s = "python test.py || echo failed"
        assert _shell_word_head(s) == "python test.py "

    def test_quote_protects_semicolon(self):
        # Semicolon INSIDE quotes is not a boundary — it's a literal.
        s = 'python -c "for x in a; b: print(x)"'
        assert _shell_word_head(s) == s

    def test_quote_protects_pipe(self):
        s = "grep 'foo|bar' file"
        assert _shell_word_head(s) == s

    def test_quote_protects_heredoc(self):
        # A quoted ``<<`` inside a string is not a heredoc marker.
        s = "echo 'the << operator' foo"
        assert _shell_word_head(s) == s

    def test_empty_string(self):
        assert _shell_word_head("") == ""


# --------------------------------------------------------------------------- #
# _iter_argv_head — respects new boundary                                      #
# --------------------------------------------------------------------------- #


class TestIterArgvHead:
    def test_argv_head_stops_before_heredoc(self):
        argv = _iter_argv_head(
            "cat > /tmp/foo.py <<'EOF'\nimport sys\nfrom os import path\nEOF"
        )
        # Only pre-``<<`` tokens: cat, >, /tmp/foo.py — the redirect
        # itself is a boundary so ``>`` is dropped. Contract: nothing
        # from inside the heredoc body appears here.
        for tok in argv:
            assert "import" not in tok
            assert "from" not in tok
            assert "path" not in tok

    def test_argv_head_stops_before_pipe(self):
        argv = _iter_argv_head("git log --oneline | grep secret_ref")
        assert "grep" not in argv
        assert "secret_ref" not in argv

    def test_argv_head_preserves_quoted_special_chars(self):
        argv = _iter_argv_head("python -c 'print(a<b)'")
        # The ``<`` inside quotes is not a boundary.
        assert argv == ("python", "-c", "print(a<b)")


# --------------------------------------------------------------------------- #
# _extract_artifact_tokens — end-to-end for the motivating failure             #
# --------------------------------------------------------------------------- #


class TestArtifactTokensNoHeredocLeak:
    def test_heredoc_body_never_extracted(self):
        # The exact failure mode PR 2 fixes: a Python source-content
        # URL/path buried in a heredoc must NOT emerge as an artifact.
        cmd = (
            "cat > /tmp/build.py <<'EOF'\n"
            "import sys\n"
            'sys.path.insert(0, "{WP}/wp-content/themes/twentyfifteen/functions.php")\n'
            'print("http://internal.example.com/should-not-leak")\n'
            "EOF"
        )
        tokens = _extract_artifact_tokens(cmd, output_tail="")
        joined = " ".join(tokens)
        assert "{WP}" not in joined
        assert "wp-content" not in joined
        assert "functions.php" not in joined
        assert "http://internal.example.com" not in joined
        assert "should-not-leak" not in joined

    def test_pipe_tail_never_extracted(self):
        # Similar failure via pipe: a URL in the second command of a
        # pipeline must not become an artifact of the first.
        cmd = "cat /repo/config.toml | curl -X POST https://api.example.com/upload"
        tokens = _extract_artifact_tokens(cmd, output_tail="")
        joined = " ".join(tokens)
        assert "api.example.com" not in joined

    def test_redirect_target_not_extracted_as_argv_artifact(self):
        # ``> /tmp/out.log`` — the redirect target is a shell control,
        # not an argv token of the LEFT command. It should NOT appear
        # as an artifact.
        cmd = "python -m pytest > /tmp/pytest.log"
        tokens = _extract_artifact_tokens(cmd, output_tail="")
        joined = " ".join(tokens)
        assert "/tmp/pytest.log" not in joined

    def test_argv_before_heredoc_still_extracted(self):
        # Regression pin: the pre-``<<`` slice must STILL produce
        # legitimate argv artifacts. Otherwise the fix is too broad.
        cmd = "python /repo/scripts/run.py <<'EOF'\nirrelevant\nEOF"
        tokens = _extract_artifact_tokens(cmd, output_tail="")
        assert any("run.py" in t for t in tokens)

    def test_url_before_pipe_still_extracted(self):
        # URL in the first command of a pipeline IS a legitimate
        # artifact of that command.
        cmd = "curl http://localhost:8000/health | jq ."
        tokens = _extract_artifact_tokens(cmd, output_tail="")
        assert any("http://localhost:8000/health" in t for t in tokens)

    def test_output_tail_still_scanned_after_fix(self):
        # PR 2 only tightens the ``cmd`` scan; ``output_tail`` is a
        # separate signal and continues to be scanned in full for
        # URLs and paths. Regression pin.
        cmd = "curl -sI https://example.com/health"
        output_tail = "HTTP/2 200\nlocation: https://cdn.example.com/asset.js\n"
        tokens = _extract_artifact_tokens(cmd, output_tail=output_tail)
        joined = " ".join(tokens)
        # Both the argv URL and the header URL survive.
        assert "https://example.com/health" in joined
        assert "https://cdn.example.com/asset.js" in joined


# --------------------------------------------------------------------------- #
# Regression: the specific offenders from the 2026-07-02 live-DB survey       #
# --------------------------------------------------------------------------- #


class TestLiveCorpusHeredocOffenders:
    def test_zarim_check_layout_heredoc(self):
        # Reproduction of the ``{WP}/wp-content/themes/twentyfifteen/
        # functions.php`` operational_fact that motivated PR 2.
        cmd = (
            "cat > C:/Dev/roni_linder_articles/zarim_check_layout.py <<'PYEOF'\n"
            "import sys\n"
            'sys.path.insert(0, "{WP}/wp-content/themes/twentyfifteen/functions.php")\n'
            'sftp.close()\n'
            "paramiko.SSHClient()\n"
            "PYEOF"
        )
        tokens = _extract_artifact_tokens(cmd, output_tail="")
        joined = " ".join(tokens)
        # None of the heredoc-body Python source lines become artifacts.
        # This is the load-bearing invariant PR 2 establishes.
        assert "sys.path.insert" not in joined
        assert "sftp.close" not in joined
        assert "paramiko.SSHClient" not in joined
        assert "{WP}/wp-content" not in joined
        # The zarim script path itself is the redirect TARGET of a
        # ``cat > path`` write — it is not "invoked" by this command,
        # only written to. Correct behavior post-PR-2: the redirect
        # target is out of scope for argv extraction. If future
        # capture logic wants to record file-creation as an artifact,
        # that belongs on the ``files_modified`` signal, not on the
        # command-argv extraction path.
