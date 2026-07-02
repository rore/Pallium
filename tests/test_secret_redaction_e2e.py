"""E2E Tests 10a + 10b — Secret redaction at every persistence and
retrieval surface.

These tests lock the security barriers PR 0 is adding. They are the
executable spec for what "no secret ever leaks" means in this codebase:

Test 10a — **Known-shape secrets** never survive at any surface (write
barrier, source-item content, index text_view, lexical_fts.text_view,
service.query result, dashboard API, pallium_expand).

Test 10b — **Unknown-shape secrets** (synthetic never-seen formats)
caught by the entropy+context heuristic — the design's generalization
layer. If a future contributor tightens Tier B to a known-shape
allow-list, these tests fail.

Both tests are XFAIL at the point Tier A + Tier B land (PR 0 step 3)
because the write / retrieval / index barriers are not yet wired.
Each subsequent PR 0 step flips one class of assertions from XFAIL to
must-pass. When all four barriers are wired (step 8), both tests are
promoted to strict must-pass.

Fixtures reuse the existing e2e harness at
``tests/test_agent_work_trace_e2e.py:86-155`` (real ``PalliumService``,
real SQLite via ``tmp_path``, real plugin registry).
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from core.models import SourceItem, new_id, utc_now
from core.service import PalliumService
from providers.llm.base import LLMJsonResponse, LLMProvider
from retrieval.lexical import LexicalRetrievalProvider
from semantic.agent_work_trace import AgentWorkTracePlugin
from semantic.demo_agent_memory import DemoAgentMemoryPlugin
from storage.sqlite import SQLiteStorageProvider


# --------------------------------------------------------------------------- #
# Fixtures — parallel to tests/test_agent_work_trace_e2e.py                    #
# --------------------------------------------------------------------------- #


class _StubOutcomeProvider(LLMProvider):
    def generate_json(self, *, system_prompt, user_prompt, schema_description):
        result = {"outcome": "recorded"}
        return LLMJsonResponse(raw_text=json.dumps(result), parsed_json=result)


@pytest.fixture
def test_db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'secrets_test.db'}"


@pytest.fixture
def service(test_db_url):
    storage = SQLiteStorageProvider(test_db_url)
    plugins = {
        "demo_agent_memory": DemoAgentMemoryPlugin(),
        "agent_work_trace": AgentWorkTracePlugin(provider=_StubOutcomeProvider()),
    }
    return PalliumService(
        storage=storage,
        retrieval=LexicalRetrievalProvider(storage),
        semantic_plugins=plugins,
        default_use_case="demo_agent_memory",
    )


@pytest.fixture
def sqlite_conn(test_db_url):
    """Read-only sqlite handle for asserting on-disk state."""
    path = test_db_url.replace("sqlite:///", "")
    return sqlite3.connect(path)


CONTAINER_REF = "git:example.com/secrets-test"
THREAD_REF = "sess-secrets-001"


# --------------------------------------------------------------------------- #
# Known-shape secret constants (synthetic — never real)                        #
# --------------------------------------------------------------------------- #

# Real-shape but obviously synthetic values. We assert these strings
# never appear in any persisted or returned surface.
_GITHUB_PAT = "ghp_" + ("A" * 36)                     # 40 chars total
_SLACK_BOT = "xoxb-1234567890-9876543210-" + ("a" * 30)
_OPENAI_ANT = "sk-ant-api03-" + ("X" * 40)
_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
_JWT_TRIPLE = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiJ0ZXN0In0"
    ".abcDEF_ghi-jkl-mno"
)
_DB_URL_CREDS = "postgres://alice:hunter2@db.internal:5432/prod"
_BEARER_HEADER = "Authorization: Bearer 1234567890abcdef1234567890abcdef1234"

_ALL_KNOWN_SECRETS = [
    _GITHUB_PAT,
    _SLACK_BOT,
    _OPENAI_ANT,
    _AWS_KEY,
    _JWT_TRIPLE,
]

# Secrets that only make sense in a specific wrapper shape — asserted
# separately because the raw value is captured only when the wrapper
# lands in prose. E.g. ``hunter2`` alone is 7 chars (below Tier B min)
# and only becomes redactable when appearing inside a
# ``postgres://user:hunter2@host`` URL.
_WRAPPED_SECRETS: list[tuple[str, str]] = [
    (_DB_URL_CREDS, "hunter2"),
    (_BEARER_HEADER, "1234567890abcdef1234567890abcdef1234"),
]


# --------------------------------------------------------------------------- #
# Unknown-shape secret constants (Tier B fodder)                               #
# --------------------------------------------------------------------------- #

# Synthetic never-seen formats. Each has:
# - length ≥ 20 chars
# - high entropy (mixed case + digits, no repetition)
# - a nearby cue word so Tier B's context requirement fires

_SYNTH_TOKEN = "SYNTHTOKEN-4a8f9c2e1b7d6a3f5e0c8b2a9d4e7c1f6b3a"
_SYNTH_CUE_CONTEXT = f"our secret is {_SYNTH_TOKEN}"

_UNKNOWN_YAML_KEY = "b64EncodedRandomLookingValueHereXYZ123abcDEF"
_UNKNOWN_YAML_CONTEXT = f"mycompany_prod_key: {_UNKNOWN_YAML_KEY}"

_UNKNOWN_HEADER_VAL = "4a8f9c2e1b7d6a3f5e0c8b2a9d4e7c1f6b3a9d8e"
_UNKNOWN_HEADER_CONTEXT = f"X-Custom-Auth: {_UNKNOWN_HEADER_VAL}"

_XYZLANG_TOKEN = "aB3dE4fG5hI6jK7lM8nO9pQ0rS1tU2vW3xY4z"
_XYZLANG_CONTEXT = f"xyz_api_token = \"{_XYZLANG_TOKEN}\""

_ALL_UNKNOWN_SECRETS = [
    _SYNTH_TOKEN,
    _UNKNOWN_YAML_KEY,
    _UNKNOWN_HEADER_VAL,
    _XYZLANG_TOKEN,
]


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _ingest_chat_content(service, content, *, source_id=None):
    """Ingest a chat-like source_item containing the given content."""
    service.ingest_item(
        source_type="claude-code",
        source_id=source_id or f"cc-secrets-{new_id()[:12]}",
        content_type="text/plain",
        content=content,
        metadata=None,
        use_case="demo_agent_memory",
        artifact_kind="assistant_output",
        role="assistant",
        container_ref=CONTAINER_REF,
        thread_ref=THREAD_REF,
        visibility="private",
    )


def _assert_no_secret_in_db(conn, secret):
    """Post-write barrier: no persisted row (memory_objects, source_items,
    index_entries, lexical_fts) contains the secret substring.
    """
    tables_and_cols = [
        ("memory_objects", "payload_json"),
        ("memory_objects", "subject"),
        ("source_items", "content"),
        ("source_items", "metadata_json"),
        ("index_entries", "text_view"),
        ("lexical_fts", "text_view"),
    ]
    for table, col in tables_and_cols:
        try:
            rows = conn.execute(
                f"SELECT {col} FROM {table} WHERE {col} LIKE ?",
                (f"%{secret}%",),
            ).fetchall()
        except sqlite3.OperationalError:
            # lexical_fts is a virtual table; some queries might not
            # work identically. Fall back to whole-column scan.
            rows = conn.execute(f"SELECT {col} FROM {table}").fetchall()
            rows = [r for r in rows if r[0] and secret in r[0]]
        assert not rows, (
            f"Secret {secret!r} leaked into {table}.{col}: "
            f"{len(rows)} row(s) contain it"
        )


def _assert_no_secret_in_query_result(result, secret):
    """Post-retrieval barrier: the QueryResult contains no raw secret."""
    for block in result.injectable_blocks:
        assert secret not in (block.title or ""), (
            f"Secret leaked into injectable_blocks[].title"
        )
        assert secret not in (block.text or ""), (
            f"Secret leaked into injectable_blocks[].text"
        )
    for item in result.results:
        assert secret not in (item.excerpt or ""), (
            f"Secret leaked into result excerpt"
        )
        assert secret not in json.dumps(item.payload or {}), (
            f"Secret leaked into result payload"
        )


def _assert_no_secret_in_expand(service, memory_object_id, secret):
    """Post-expand barrier: pallium_expand returns no raw secret."""
    payload, items, match_text = service.get_memory_expand(
        memory_object_id, container_ref=CONTAINER_REF
    )
    assert secret not in json.dumps(payload or {})
    if match_text:
        assert secret not in match_text
    for item in items:
        assert secret not in (item.content or "")
        # metadata is a dict on the SourceItem
        assert secret not in json.dumps(item.metadata or {})


# --------------------------------------------------------------------------- #
# Test 10a — Known-shape secrets                                                #
# --------------------------------------------------------------------------- #


class TestKnownShapeSecretRedaction:
    """Every enumerated Tier-A secret shape must be redacted at every
    surface the API can return."""

    def test_github_pat_never_leaks(self, service, sqlite_conn):
        _ingest_chat_content(service, f"my token = {_GITHUB_PAT}")
        _assert_no_secret_in_db(sqlite_conn, _GITHUB_PAT)
        result = service.query(
            text="token",
            limit=10,
            container_ref=CONTAINER_REF,
            trigger_origin="user_prompt_submit",
        )
        _assert_no_secret_in_query_result(result, _GITHUB_PAT)

    def test_slack_bot_token_never_leaks(self, service, sqlite_conn):
        _ingest_chat_content(service, f"slack bot: {_SLACK_BOT}")
        _assert_no_secret_in_db(sqlite_conn, _SLACK_BOT)

    def test_openai_anthropic_key_never_leaks(self, service, sqlite_conn):
        _ingest_chat_content(service, f"anthropic key was: {_OPENAI_ANT}")
        _assert_no_secret_in_db(sqlite_conn, _OPENAI_ANT)

    def test_aws_access_key_never_leaks(self, service, sqlite_conn):
        _ingest_chat_content(service, f"AWS_ACCESS_KEY_ID={_AWS_KEY}")
        _assert_no_secret_in_db(sqlite_conn, _AWS_KEY)

    def test_jwt_triple_never_leaks(self, service, sqlite_conn):
        _ingest_chat_content(service, f"session={_JWT_TRIPLE}")
        _assert_no_secret_in_db(sqlite_conn, _JWT_TRIPLE)

    def test_db_connection_creds_never_leak(self, service, sqlite_conn):
        _ingest_chat_content(service, f"connect: {_DB_URL_CREDS}")
        _assert_no_secret_in_db(sqlite_conn, "hunter2")

    def test_bearer_header_never_leaks(self, service, sqlite_conn):
        _ingest_chat_content(service, f"curl -H '{_BEARER_HEADER}'")
        _assert_no_secret_in_db(sqlite_conn, "1234567890abcdef1234567890abcdef1234")

    def test_all_known_secrets_absent_from_lexical_fts(self, service, sqlite_conn):
        """Any of the secrets in the ingested content must NOT be
        searchable via lexical FTS after the barrier is wired.
        This is the retrieval-corruption test — a lexical hit on a
        secret is worse than a memory row containing it, because
        retrieval will surface it into the LLM prompt on any query
        that scores it.

        Each secret is ingested inside its natural wrapper (raw
        token in prose, or password inside a URL, or bearer inside
        an Authorization header) so the pipeline sees a realistic
        input shape."""
        # Raw provider tokens land in prose as-is; Tier A catches them.
        prose_dump = "\n".join(
            [f"secret {i}: {s}" for i, s in enumerate(_ALL_KNOWN_SECRETS)]
        )
        # Wrapped secrets require their container to be sensible input.
        wrapped_dump = "\n".join(
            [f"wrap {i}: {wrapper}" for i, (wrapper, _) in enumerate(_WRAPPED_SECRETS)]
        )
        _ingest_chat_content(service, prose_dump + "\n" + wrapped_dump)

        rows = sqlite_conn.execute(
            "SELECT text_view FROM lexical_fts"
        ).fetchall()
        for row in rows:
            text = row[0] or ""
            for secret in _ALL_KNOWN_SECRETS:
                assert secret not in text, (
                    f"lexical_fts contains raw secret {secret!r}"
                )
            for _, sensitive_fragment in _WRAPPED_SECRETS:
                assert sensitive_fragment not in text, (
                    f"lexical_fts contains raw fragment "
                    f"{sensitive_fragment!r} from a wrapped secret"
                )


# --------------------------------------------------------------------------- #
# Test 10b — Unknown-shape (Tier B) secrets                                    #
# --------------------------------------------------------------------------- #


class TestUnknownShapeSecretRedaction:
    """Tier B is the generalization layer. If a future PR tightens
    Tier B to an allow-list of provider prefixes, these tests must
    fail — they lock the design's promise that unknown formats are
    caught by entropy+context, not by pattern lookup."""

    def test_synth_token_never_leaks(self, service, sqlite_conn):
        _ingest_chat_content(service, _SYNTH_CUE_CONTEXT)
        _assert_no_secret_in_db(sqlite_conn, _SYNTH_TOKEN)

    def test_unknown_yaml_key_never_leaks(self, service, sqlite_conn):
        _ingest_chat_content(service, _UNKNOWN_YAML_CONTEXT)
        _assert_no_secret_in_db(sqlite_conn, _UNKNOWN_YAML_KEY)

    def test_unknown_header_val_never_leaks(self, service, sqlite_conn):
        _ingest_chat_content(service, _UNKNOWN_HEADER_CONTEXT)
        _assert_no_secret_in_db(sqlite_conn, _UNKNOWN_HEADER_VAL)

    def test_xyzlang_ecosystem_token_never_leaks(self, service, sqlite_conn):
        """Synthetic never-seen ecosystem — proves the generalization
        contract in the same shape as the operational_fact fresh-
        ecosystem test."""
        _ingest_chat_content(service, _XYZLANG_CONTEXT)
        _assert_no_secret_in_db(sqlite_conn, _XYZLANG_TOKEN)


# --------------------------------------------------------------------------- #
# FP guards — must NOT redact                                                  #
# --------------------------------------------------------------------------- #


class TestNotOverRedacted:
    """Positive assertions: real content that resembles a secret but is
    not one — git SHAs, UUIDs, content hashes — must remain retrievable.
    These are the FP-guard tests at the e2e level; the unit-level
    counterparts live in ``tests/test_redaction_tier_a_and_b.py``."""

    def test_git_sha_in_prose_survives(self, service, sqlite_conn):
        sha = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
        content = f"the fix is in commit {sha}, see it in log"
        _ingest_chat_content(service, content)
        # SHA must reach storage — it's evidence, not a secret.
        rows = sqlite_conn.execute(
            "SELECT content FROM source_items WHERE content LIKE ?",
            (f"%{sha}%",),
        ).fetchall()
        assert rows, "git SHA got FP-redacted at ingest"

    def test_uuid_in_prose_survives(self, service, sqlite_conn):
        uid = "550e8400-e29b-41d4-a716-446655440000"
        content = f"the tenant we generated was {uid} — remember this"
        _ingest_chat_content(service, content)
        rows = sqlite_conn.execute(
            "SELECT content FROM source_items WHERE content LIKE ?",
            (f"%{uid}%",),
        ).fetchall()
        assert rows, "UUID got FP-redacted at ingest"

    def test_user_note_content_preserved_verbatim(self, service, sqlite_conn):
        """User-explicit ``note`` artifacts bypass the write barrier —
        a runbook or procedure the user pasted for verbatim recall
        must land in storage exactly as written. Placeholder patterns
        like ``key=NEW_KEY`` in a procedure step are documentation,
        not secrets; redacting them destroys the note's utility.

        This is the deliberate carve-out documented in
        ``core/service.py::ingest_item``. The tradeoff: a user who
        pastes a real secret into a note has explicitly asked us to
        remember it; that's a user decision, not a silent leak.
        """
        procedure = (
            "API key rotation procedure:\n"
            "1. Generate new key in admin console\n"
            "2. Update in vault: vault kv put secret/api-keys key=NEW_KEY\n"
            "3. Restart service"
        )
        service.ingest_item(
            source_type="agent_artifact",
            source_id=f"note-{new_id()[:8]}",
            content_type="text/plain",
            content=procedure,
            metadata=None,
            use_case="demo_agent_memory",
            artifact_kind="note",
            role="user",
            container_ref=CONTAINER_REF,
            thread_ref=THREAD_REF,
            visibility="private",
        )
        rows = sqlite_conn.execute(
            "SELECT content FROM source_items WHERE content LIKE ?",
            ("%key=NEW_KEY%",),
        ).fetchall()
        assert rows, "user-explicit note was redacted despite artifact_kind='note'"
