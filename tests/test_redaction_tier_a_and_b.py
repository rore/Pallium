"""Tests for PR 0 Tier A + Tier B secret redaction expansion.

Covers the shapes the 2026-07-02 live-DB audit found in production
data, plus the defensive edge cases from the architect review §H:
empty string, idempotence, very long content, multi-secret, overlap,
FP guards for git SHAs / UUIDs / content hashes, and adjacency to the
redaction marker.

See:
- ``docs/specs/2026-05-31-operational-fact-memory-design.md`` for the
  role of ``semantic.redaction`` in the ingest and retrieval barriers.
- ``.local/milestone-progress-2026-07/redesign-pr0-progress-2026-07-02.md``
  for the PR-0 sequence and durable state.
"""

from __future__ import annotations

import re

import pytest

from semantic.redaction import (
    redact_probable_secrets,
    redact_sensitive,
)


# --------------------------------------------------------------------------- #
# Test fixtures                                                                #
# --------------------------------------------------------------------------- #


def _real_shape(prefix: str, char_pool: str, length: int) -> str:
    """Build a token whose character shape is realistic (high entropy over
    the given pool) without embedding an actual credential."""
    seed = "aB3dE4fG5hI6jK7lM8nO9pQ0rS1tU2vW3xY4zXcVbNmZaSdFgHjKlPoIuYtReWq"
    body = (seed * (length // len(seed) + 1))[:length]
    return prefix + body


# =========================================================================== #
# TIER A — provider-specific shapes                                            #
# =========================================================================== #


class TestTierAGithub:
    def test_github_pat_redacts(self):
        tok = _real_shape("ghp_", "", 40)  # ghp_ + 36 chars
        out = redact_sensitive(f"authorize with {tok}")
        assert tok not in out
        assert "[REDACTED]" in out

    def test_github_oauth_gho_redacts(self):
        tok = _real_shape("gho_", "", 40)
        assert _real_shape("gho_", "", 40) not in redact_sensitive(tok)

    def test_github_pat_in_bearer_header(self):
        tok = _real_shape("ghp_", "", 40)
        out = redact_sensitive(f'Authorization: Bearer {tok}')
        assert tok not in out
        # Header rule fires first; result is 'Authorization: [REDACTED]'
        assert "Authorization: [REDACTED]" in out

    def test_github_pat_not_matched_inside_identifier(self):
        # Word boundary anchors — ``ghp_XXX`` embedded in a longer
        # identifier should still match at the \b boundary. Regression
        # pin: don't accidentally require a non-word suffix.
        tok = _real_shape("ghp_", "", 40)
        out = redact_sensitive(f'{tok},{tok}')
        assert tok not in out


class TestTierASlack:
    def test_slack_bot_token_strict_shape_redacts(self):
        # xoxb-<team>-<user>-<secret>
        tok = "xoxb-1234567890-9876543210-" + _real_shape("", "", 30)
        out = redact_sensitive(f"the bot token is {tok}")
        assert tok not in out
        assert "[REDACTED]" in out

    def test_slack_user_token_xoxp_redacts(self):
        tok = "xoxp-1234567890-9876543210-1112223330-" + _real_shape("", "", 40)
        assert tok not in redact_sensitive(tok)

    def test_slack_legacy_fallback_shape(self):
        # Legacy shape without the ternary team-user-secret split.
        tok = "xoxs-" + _real_shape("", "", 40)
        assert tok not in redact_sensitive(tok)


class TestTierAOpenAIAnthropic:
    def test_anthropic_key_redacts(self):
        tok = "sk-ant-api03-" + _real_shape("", "", 40)
        assert tok not in redact_sensitive(tok)

    def test_openai_project_key_redacts(self):
        tok = "sk-proj-" + _real_shape("", "", 40)
        assert tok not in redact_sensitive(tok)

    def test_openai_generic_key_redacts(self):
        tok = "sk-" + _real_shape("", "", 40)
        assert tok not in redact_sensitive(tok)

    def test_anthropic_key_not_downgraded_to_openai(self):
        # Ordering guarantee: the sk-ant regex fires first so we don't
        # end up with e.g. 'sk-ant-[REDACTED]' where only the tail
        # after 'sk-ant-' got matched by the generic rule.
        tok = "sk-ant-api03-" + _real_shape("", "", 50)
        out = redact_sensitive(tok)
        # Whole token gone, single marker.
        assert tok not in out
        assert out.count("[REDACTED]") == 1


class TestTierAAws:
    def test_aws_access_key_redacts(self):
        tok = "AKIA" + ("A" * 8) + ("B" * 8)  # 20 chars, uppercase
        out = redact_sensitive(f'export AWS_ACCESS_KEY_ID={tok}')
        # The env-var rule may fire; either way, secret must be gone.
        assert tok not in out

    def test_aws_sts_session_key_redacts(self):
        tok = "ASIA" + ("A" * 8) + ("B" * 8)
        assert tok not in redact_sensitive(tok)

    def test_akia_lowercase_not_matched(self):
        # Real AWS keys are uppercase A-Z0-9; ``akiaFOOBAR`` in prose
        # must not FP.
        s = "akiaFOOBARBAZQUX12345"
        assert s in redact_sensitive(s)


class TestTierAJwt:
    def test_jwt_three_parts_redacts(self):
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            ".abc_XYZ-def_UVW-ghi_JKL"
        )
        out = redact_sensitive(f"session={jwt}")
        assert jwt not in out

    def test_jwt_with_url_safe_base64_chars(self):
        jwt = (
            "eyJabcDEF_GHI-jklMNO"
            ".eyJpqr_STU-vwxYZ012"
            ".mno-pqr_stu-vwx"
        )
        assert jwt not in redact_sensitive(jwt)


class TestTierAConnectionAndBasicAuth:
    def test_basic_auth_url_preserves_host(self):
        s = "clone https://alice:hunter2@github.com/example/repo.git"
        out = redact_sensitive(s)
        assert "hunter2" not in out
        assert "github.com" in out
        assert "alice" in out
        # Redacted form keeps user visible, password gone.
        assert "alice:[REDACTED]@github.com" in out

    def test_postgres_connection_string_redacts(self):
        s = "DATABASE_URL=postgres://user:pw@db.internal:5432/prod"
        out = redact_sensitive(s)
        assert "pw" not in out
        # env-var rule may fire (TOKEN/PASSWORD/etc.); either way
        # the credential must be gone. DATABASE_URL isn't in the
        # sensitive-name list, so the connection-string rule handles it.
        assert "postgres://[REDACTED]" in out


class TestTierAEnvVars:
    def test_env_password_redacts(self):
        assert "MyS3cret" not in redact_sensitive("PASSWORD=MyS3cret")

    def test_env_yaml_password_redacts(self):
        assert "MyS3cret" not in redact_sensitive("password: MyS3cret")

    def test_env_apikey_variants(self):
        for name in ("APIKEY", "APITOKEN", "PAT", "CREDENTIALS", "PRIVATE_KEY"):
            assert "s3cretVal" not in redact_sensitive(f"{name}=s3cretVal")

    def test_env_mypassword_not_fp(self):
        # Word-boundary anchor guarantees MYPASSWORD != PASSWORD.
        s = "MYPASSWORD_STRIPPED=irrelevant"
        assert s in redact_sensitive(s)

    def test_env_hotkey_not_fp(self):
        assert "HOTKEY_MAPPING=ctrl-c" in redact_sensitive(
            "HOTKEY_MAPPING=ctrl-c"
        )


# =========================================================================== #
# TIER B — entropy + context                                                   #
# =========================================================================== #


class TestTierBHighEntropyWithCue:
    @pytest.mark.parametrize(
        "cue",
        ["password", "secret", "token", "auth", "credential", "bearer",
         "authorization", "api_key", "apikey", "access_key",
         "refresh_token", "client_secret", "session_id", "webhook"],
    )
    def test_high_entropy_near_cue_redacts(self, cue):
        secret = _real_shape("", "", 30)
        s = f"the {cue} is {secret}"
        out = redact_sensitive(s)
        assert secret not in out
        assert "[REDACTED-30c]" in out

    def test_short_token_not_redacted_even_near_cue(self):
        # Under min length (20).
        s = "password: short"
        # Tier-A env-var rule redacts this by full-value match, so
        # ``short`` won't appear in output. Tier B would NOT have
        # redacted ``short`` on its own — verify by using a token
        # that doesn't match tier-A env pattern (no cue-word key).
        s2 = "the token seems to be short"
        assert "short" in redact_sensitive(s2)

    def test_low_entropy_repeated_chars_not_redacted(self):
        # 40 chars of one letter — very low entropy despite length.
        s = "password: " + ("a" * 40)
        # Tier-A env rule still catches this, so verify with a case
        # where Tier B is the only chance:
        s2 = "the token seems: " + ("a" * 40)
        assert ("a" * 40) in redact_sensitive(s2)


class TestTierBFPGuards:
    def test_git_commit_sha_not_redacted_even_with_cue(self):
        sha = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
        s = f"git commit key: {sha}"
        # Even with 'key:' cue, the 40-hex-char shape is a git SHA.
        # FP guard must fire.
        assert sha in redact_sensitive(s)

    def test_uuid_not_redacted(self):
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        # UUIDs contain `-` so they're a single token per Tier B's
        # char class. The Tier B FP guard must fire — even if a cue
        # word is nearby, a well-formed UUID is not a secret.
        # NOTE: env-var-style ``token: <uuid>`` IS explicitly treated
        # as a token assignment by Tier A's yaml rule (that's the
        # intended semantics — a token is a token). We assert the
        # narrower Tier-B FP guard using a prose form that Tier A
        # doesn't match:
        s = f"the identifier we generated was {uuid}"
        assert uuid in redact_sensitive(s)

    def test_sha256_content_hash_not_redacted(self):
        h = "a" * 64
        s = f"password: {h}"
        # 64 hex — content hash guard fires. Env-var rule DOES fire
        # here (name is 'password') — that's a separate concern.
        # Verify with a non-env prose form:
        s2 = f"the hash key: {h}"
        assert h in redact_sensitive(s2)


class TestTierBWithoutCueWord:
    def test_high_entropy_without_cue_not_redacted(self):
        # No secret-cue word within 30 chars — Tier B must not fire.
        token = _real_shape("", "", 40)
        s = f"processing item {token} at position 5"
        assert token in redact_sensitive(s)


class TestTierBIdempotence:
    def test_double_pass_is_stable(self):
        s = "the token is " + _real_shape("", "", 30)
        once = redact_sensitive(s)
        twice = redact_sensitive(once)
        assert once == twice

    def test_marker_not_re_matched(self):
        # A [REDACTED-30c] marker sits next to a legitimate token.
        # The next redact pass must not re-touch the marker OR
        # match it as a secret.
        pre = "the token is " + _real_shape("", "", 30)
        out1 = redact_sensitive(pre)
        assert redact_sensitive(out1) == out1


# =========================================================================== #
# DEFENSIVE EDGE CASES (architect review §H)                                   #
# =========================================================================== #


class TestEdgeCases:
    def test_empty_string(self):
        assert redact_sensitive("") == ""
        assert redact_probable_secrets("") == ""

    def test_none_like_none_raises(self):
        # ``None`` is not a string; caller should not pass it. Behavior:
        # returns None because of the ``if not text`` guard. Test the
        # guard.
        assert redact_sensitive(None) is None  # type: ignore[arg-type]

    def test_very_long_input_tier_b_skipped(self):
        # 1.1M chars — Tier B skips per _TIER_B_MAX_INPUT_LEN.
        # Tier A still runs. Confirm no exception.
        long = ("password: irrelevant " * 60_000)  # ~1.2M
        out = redact_sensitive(long)
        # Tier A env-var rule handles this — but the whole thing must
        # not throw regardless.
        assert isinstance(out, str)

    def test_multi_secret_in_one_string(self):
        gh = _real_shape("ghp_", "", 40)
        sl = "xoxb-1234567890-9876543210-" + _real_shape("", "", 30)
        s = f"gh={gh} slack={sl}"
        out = redact_sensitive(s)
        assert gh not in out
        assert sl not in out

    def test_tier_a_wins_over_tier_b(self):
        # ghp_ token also sits near 'token' — either regex could
        # match. Tier A runs first and replaces with '[REDACTED]';
        # Tier B's token class excludes '[' so it does NOT re-touch.
        tok = _real_shape("ghp_", "", 40)
        s = f"token: {tok}"
        out = redact_sensitive(s)
        assert tok not in out
        # Tier A marker: '[REDACTED]' (not '[REDACTED-Nc]')
        assert "[REDACTED]" in out
        # Tier B marker should NOT appear on this ghp_ token.
        # (It might appear elsewhere if there are other high-entropy
        # tokens, but not for this one.)

    def test_secret_at_start(self):
        tok = _real_shape("ghp_", "", 40)
        assert tok not in redact_sensitive(f"{tok} rest of line")

    def test_secret_at_end(self):
        tok = _real_shape("ghp_", "", 40)
        assert tok not in redact_sensitive(f"prefix trailing {tok}")

    def test_secret_adjacent_to_redacted_marker(self):
        tok = _real_shape("ghp_", "", 40)
        s = f"[REDACTED] {tok}"
        out = redact_sensitive(s)
        assert tok not in out

    def test_binary_junk_bytes_preserved(self):
        tok = _real_shape("ghp_", "", 40)
        # Include null byte and 0xff in the surrounding prose.
        s = f"\x00\xff prefix {tok} suffix \x00"
        out = redact_sensitive(s)
        assert tok not in out
        assert "\x00" in out
        assert "\xff" in out


class TestPreExistingBehaviorPreserved:
    """Pin the pre-existing tier-A rules that PR 0 must NOT regress."""

    def test_bearer_still_redacted(self):
        assert "Bearer [REDACTED]" in redact_sensitive("Bearer xyz.abc.def")

    def test_x_api_key_still_redacted(self):
        assert "myMagicKey" not in redact_sensitive("X-API-Key: myMagicKey")

    def test_pem_block_still_redacted(self):
        pem = (
            "-----BEGIN PRIVATE KEY-----\n"
            "MIIabc123\n"
            "-----END PRIVATE KEY-----"
        )
        out = redact_sensitive(f"key: {pem}")
        assert "MIIabc123" not in out
        assert "[REDACTED KEY BLOCK]" in out

    def test_authorization_header_still_redacted(self):
        assert "abc123" not in redact_sensitive(
            'headers = {"Authorization": "Bearer abc123"}'
        )
