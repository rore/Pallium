"""Shared redaction helper for values that may carry secrets before storage.

Owned by the `semantic` layer so both derived-memory pipelines
(agent_work_trace family) and future consumers can share one source of
truth for the redaction rule set. Hook-layer callers are expected to
migrate to this helper in a follow-up change; this module does not
alter existing hook behavior.

Two shapes:

- :func:`redact_sensitive` — mutate free text, replacing token
  substrings with ``[REDACTED]`` markers. Used when the value is embedded
  in a larger string (a command line, a fragment) and other tokens
  around it are legitimate.
- :func:`is_sensitive_artifact` — predicate over an artifact whose
  ENTIRE identity is the secret (e.g. `~/.ssh/id_rsa` as an
  operational_fact artifact). Callers should SKIP emission rather than
  redact the artifact to ``[REDACTED]`` — a redacted-artifact row is
  useless memory and collides all N distinct SSH-key rows into a
  single junk record. See W4 follow-up 2026-07-02.
"""

from __future__ import annotations

import re
from typing import Final

_BEARER_RE: Final = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_API_KEY_HEADER_RE: Final = re.compile(
    r"(x-api-key|api[_-]?key)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_ENV_VAR_SECRET_RE: Final = re.compile(
    # Left AND right word boundaries: only redact the RHS of env-var
    # assignments whose NAME is exactly one of the sensitive keywords.
    # Prevents false-positives on MYPASSWORD, HOTKEY_MAPPING, AUTHOR, etc.
    # Broadened 2026-07-02 to include APIKEY / APITOKEN / PAT /
    # CREDENTIAL(S) / PRIVATE_KEY / ACCESS_KEY. Tradeoff: still does not
    # catch bare API_TOKEN=... without a `=`, but the yaml-style `:`
    # separator is picked up by the yaml env-secret rule below.
    r"(?<![A-Za-z0-9_])"
    r"(PASSWORD|PASSWD|PWD|SECRET|TOKEN|KEY|AUTH|APIKEY|APITOKEN|PAT|"
    r"CREDENTIALS?|PRIVATE_KEY|ACCESS_KEY|SIGNING_KEY|CLIENT_SECRET|"
    r"REFRESH_TOKEN|SESSION_ID|WEBHOOK_SECRET)"
    r"(?![A-Za-z0-9_])\s*=\s*\S+",
    re.IGNORECASE,
)
_ENV_VAR_YAML_SECRET_RE: Final = re.compile(
    # yaml-style ``password: value`` — case-insensitive full-word key.
    # The value stops at newline or closing quote to preserve inline
    # comments and multi-key documents.
    r"(?<![A-Za-z0-9_])"
    r"(password|passwd|pwd|secret|token|apikey|api[_-]?key|"
    r"credentials?|private[_-]?key|access[_-]?key|signing[_-]?key|"
    r"client[_-]?secret|refresh[_-]?token|session[_-]?id|"
    r"webhook[_-]?secret|authorization)"
    r"(?![A-Za-z0-9_])"
    r"\s*:\s*[\"\']?[^\"\'\r\n]+",
    re.IGNORECASE,
)
_PRIVATE_KEY_BLOCK_RE: Final = re.compile(
    r"-----BEGIN [A-Z ]+KEY-----.*?-----END[^\n]*",
    re.IGNORECASE | re.DOTALL,
)
_CONNECTION_STRING_RE: Final = re.compile(
    r"(mongodb|postgres|postgresql|mysql|redis|amqp|amqps)://\S+",
    re.IGNORECASE,
)
_SENSITIVE_HEADER_RE: Final = re.compile(
    # Terminate value at newline OR closing quote so surrounding argv
    # (e.g. the URL after -H "Authorization: ...") is preserved.
    r"(Authorization|Cookie|Set-Cookie|Proxy-Authorization)\s*:\s*[^\n\r\"']+",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# Tier A — provider-specific token shapes (2026-07-02 expansion)              #
# --------------------------------------------------------------------------- #
#
# Ordering matters: longer / more-specific prefixes must run BEFORE the
# shorter/generic ones on the same substring so ``sk-ant-...`` isn't
# downgraded to a generic ``sk-`` hit. See :func:`redact_sensitive` for
# the execution order.
#
# All regexes are bounded (explicit upper bound on quantifiers) so a
# hostile input can't cause catastrophic backtracking.

# GitHub tokens — one regex covers ghp_ (PAT), gho_ (OAuth), ghu_ (user
# token), ghs_ (server-to-server), ghr_ (refresh). Character class is
# strict base62 (no punctuation), which matches GitHub's actual token
# alphabet and rules out any prose false-positive.
_GITHUB_TOKEN_RE: Final = re.compile(
    r"\b(gh[pousr])_[A-Za-z0-9]{30,255}\b"
)

# Slack tokens — strict form catches modern bot/user/app tokens
# (xoxb-<team>-<user>-<secret>); the looser fallback catches legacy
# formats. Both anchored with \b.
_SLACK_TOKEN_STRICT_RE: Final = re.compile(
    r"\b(xox[abpr])-\d{6,20}-\d{6,20}-[A-Za-z0-9]{20,64}\b"
)
_SLACK_TOKEN_FALLBACK_RE: Final = re.compile(
    r"\b(xox[a-z])-[A-Za-z0-9\-]{20,255}\b"
)

# Anthropic and OpenAI-project keys — anchor on their fixed prefixes
# BEFORE the generic ``sk-`` rule that would otherwise consume them.
_ANTHROPIC_KEY_RE: Final = re.compile(
    r"\bsk-ant-(?:api\d{2}-)?[A-Za-z0-9_\-]{20,255}\b"
)
_OPENAI_PROJ_KEY_RE: Final = re.compile(
    r"\bsk-proj-[A-Za-z0-9_\-]{20,255}\b"
)
_OPENAI_GENERIC_KEY_RE: Final = re.compile(
    r"\bsk-[A-Za-z0-9_\-]{20,255}\b"
)

# AWS access key IDs — 20-char shape starting with AKIA (long-lived
# access keys) or ASIA (STS session credentials).
_AWS_KEY_ID_RE: Final = re.compile(
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
)

# JWT — 3-part dotted structure where each part is at least 10 chars.
# ``eyJ`` is the base64 encoding of ``{"``, which is JWT-specific.
_JWT_RE: Final = re.compile(
    r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"
)

# Basic-auth URLs — preserve scheme and host so the URL remains
# readable in narrative; only the user:pass part is redacted.
_BASIC_AUTH_URL_RE: Final = re.compile(
    r"\b(https?)://([^:/\s@]+):([^@/\s]+)@"
)


def redact_sensitive(text: str) -> str:
    """Strip secrets from free text.

    Idempotent: safe to call on already-redacted input. Preserves the
    surrounding shape of the text so downstream code that parses argv
    or headers still works after redaction.

    Execution order (established 2026-07-02) — must not be reordered:

    1. ``_PRIVATE_KEY_BLOCK_RE`` — multi-line, greedy, must run first
       before any other pattern chews part of a PEM block.
    2. Header-value rules (``_SENSITIVE_HEADER_RE``) — consume the
       value of Authorization/Cookie headers to newline boundary.
       Runs BEFORE token-shape rules so ``Authorization: Bearer eyJ...``
       becomes ``Authorization: [REDACTED]`` without partial JWT
       exposure.
    3. Generic bearer / api-key headers (``_BEARER_RE``, ``_API_KEY_HEADER_RE``).
    4. Env-var and yaml-style secret KVs.
    5. Connection strings.
    6. Basic-auth URLs (preserves scheme+host, redacts credentials).
    7. **Tier A provider-specific token shapes** — most-specific prefix
       first (``sk-ant-`` before ``sk-proj-`` before generic ``sk-``),
       then GitHub, Slack, AWS, JWT.
    8. **Tier B entropy+context heuristic** — catches unknown-shape
       secrets sitting near cue words. Runs LAST so Tier A markers
       (which contain ``[`` characters outside Tier B's token class)
       are never re-touched.
    """
    if not text:
        return text
    out = text
    # 1-6: pre-existing rules preserved verbatim for backward compat.
    out = _PRIVATE_KEY_BLOCK_RE.sub("[REDACTED KEY BLOCK]", out)
    out = _SENSITIVE_HEADER_RE.sub(r"\1: [REDACTED]", out)
    out = _BEARER_RE.sub("Bearer [REDACTED]", out)
    out = _API_KEY_HEADER_RE.sub(r"\1=[REDACTED]", out)
    out = _ENV_VAR_SECRET_RE.sub(r"\1=[REDACTED]", out)
    out = _ENV_VAR_YAML_SECRET_RE.sub(r"\1: [REDACTED]", out)
    out = _CONNECTION_STRING_RE.sub(r"\1://[REDACTED]", out)
    out = _BASIC_AUTH_URL_RE.sub(r"\1://\2:[REDACTED]@", out)
    # 7: Tier A — most-specific prefix first per Section A of the PR-0
    # architect review. Order within provider families matters.
    out = _ANTHROPIC_KEY_RE.sub("[REDACTED]", out)
    out = _OPENAI_PROJ_KEY_RE.sub("[REDACTED]", out)
    out = _OPENAI_GENERIC_KEY_RE.sub("[REDACTED]", out)
    out = _GITHUB_TOKEN_RE.sub("[REDACTED]", out)
    out = _SLACK_TOKEN_STRICT_RE.sub("[REDACTED]", out)
    out = _SLACK_TOKEN_FALLBACK_RE.sub("[REDACTED]", out)
    out = _AWS_KEY_ID_RE.sub("[REDACTED]", out)
    out = _JWT_RE.sub("[REDACTED]", out)
    # 8: Tier B — entropy+context fallback. Uses ``[REDACTED-Nc]``
    # markers so post-hoc analysis can distinguish tier-A vs tier-B
    # redactions in stored payloads.
    out = redact_probable_secrets(out)
    return out


def redact_command(cmd: str) -> str:
    """Alias of :func:`redact_sensitive`. Named for use at callsites that
    are specifically redacting a shell command line."""
    return redact_sensitive(cmd)


# --------------------------------------------------------------------------- #
# Tier B — entropy + context heuristic for unknown-shape secrets              #
# --------------------------------------------------------------------------- #
#
# Rationale (2026-07-02 audit): the live DB carried unredacted Slack
# and GitHub tokens because the tier-A regexes did not cover them at
# ingest time. Tier-A now catches them, but the design cannot keep
# up with every future provider's token format. Tier B fires on any
# ≥20-char run of secret-alphabet characters whose Shannon entropy
# clears ~4.0 bits/char AND which sits within ~30 chars of a
# secret-cue word. False-positive guards short-circuit git SHAs,
# UUIDs, and content-addressed hashes.

import math

_TIER_B_MIN_TOKEN_LEN: Final[int] = 20
_TIER_B_ENTROPY_THRESHOLD: Final[float] = 4.0
_TIER_B_CUE_WINDOW: Final[int] = 30
# Hard cap on scan size. Long content still gets tier-A coverage; tier
# B skips to bound worst-case per-write cost.
_TIER_B_MAX_INPUT_LEN: Final[int] = 1_000_000

# Candidate token character class. Deliberately includes URL-safe
# base64 (`-`, `_`) and `.` so JWT-like ``eyJ.eyJ.abc`` is one token.
# Deliberately EXCLUDES ``=``, ``:``, ``?``, ``&``, whitespace, quotes,
# and shell separators — those are the natural boundaries between an
# assignment name/key and its value.  Including ``=`` would swallow
# ``NAME=value`` as one 20+ char token and false-positive on plain
# environment-variable prose that mentions ``password`` in the name.
_TIER_B_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9+/_\-.]{20,}")

# Full-token shape guards — checked BEFORE entropy computation. These
# are the anti-false-positive patterns discussed in the PR-0
# architect review §H.
_GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_UUID_RE: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_CONTENT_HASH_RE: Final = re.compile(r"^[0-9a-f]{32,64}$")

# Cue words that indicate a nearby token is likely a secret. Kept
# small and case-insensitive to bound false positives — ``key`` alone
# is intentionally excluded (would false-positive on ``keyboard
# shortcut``, ``primary key``, etc.); the compound forms below cover
# the real cases.
_TIER_B_CUE_WORDS: Final[frozenset[str]] = frozenset({
    "password", "passwd", "pwd",
    "secret", "secrets",
    "token", "tokens",
    "apikey", "api_key", "api-key",
    "auth", "authorization",
    "bearer",
    "credential", "credentials",
    "access_key", "access-key", "accesskey",
    "private_key", "private-key", "privatekey",
    "signing_key", "signing-key",
    "session", "sessionid", "session_id",
    "webhook",
    "client_secret", "client-secret", "clientsecret",
    "refresh_token", "refresh-token",
})


def _shannon_entropy(token: str) -> float:
    """Shannon entropy over characters, in bits per character.

    Character-based (not byte-based) so a base64-alphabet token
    reaches ~5.7 bits/char, matching what a probable secret looks
    like. Hex-only strings land at ~3.9-4.0 — the FP guards catch
    those before this function runs.
    """
    if not token:
        return 0.0
    from collections import Counter
    counts = Counter(token)
    length = len(token)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _tier_b_is_fp_shape(token: str) -> bool:
    """Return True if the token matches a known non-secret shape.

    Short-circuits BEFORE entropy computation — cheap regex checks
    for the shapes that would otherwise straddle the entropy
    threshold (git SHAs at ~3.9 bits/char sit right on the border).
    """
    if _GIT_SHA_RE.match(token):
        return True
    if _UUID_RE.match(token):
        return True
    if _CONTENT_HASH_RE.match(token):
        return True
    return False


def redact_probable_secrets(text: str) -> str:
    """Tier B redaction — high-entropy tokens near secret-cue words.

    Deterministic and idempotent. Runs after tier-A redaction inside
    :func:`redact_sensitive`, so tier-A markers (which contain ``[``
    outside the token character class) are never re-matched.

    Replacement form: ``[REDACTED-Nc]`` where N is the length of the
    redacted token — retains a size signal for post-hoc analysis
    without exposing the value.
    """
    if not text:
        return text
    if len(text) > _TIER_B_MAX_INPUT_LEN:
        # Bounded worst-case: skip tier B on pathological input.
        # Tier A still applied by the caller.
        return text

    text_lower = text.lower()
    replacements: list[tuple[int, int, str]] = []

    for match in _TIER_B_TOKEN_RE.finditer(text):
        token = match.group(0)
        if len(token) < _TIER_B_MIN_TOKEN_LEN:
            continue
        if _tier_b_is_fp_shape(token):
            continue
        if _shannon_entropy(token) < _TIER_B_ENTROPY_THRESHOLD:
            continue
        start, end = match.span()
        window_start = max(0, start - _TIER_B_CUE_WINDOW)
        window_end = min(len(text), end + _TIER_B_CUE_WINDOW)
        window = text_lower[window_start:window_end]
        if not any(cue in window for cue in _TIER_B_CUE_WORDS):
            continue
        replacements.append((start, end, f"[REDACTED-{len(token)}c]"))

    if not replacements:
        return text

    # Reassemble right-to-left so earlier spans keep their offsets.
    replacements.sort(key=lambda spec: spec[0])
    parts: list[str] = []
    cursor = 0
    for start, end, marker in replacements:
        parts.append(text[cursor:start])
        parts.append(marker)
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


# --------------------------------------------------------------------------- #
# is_sensitive_artifact — skip emission when the ARTIFACT ITSELF is a secret  #
# --------------------------------------------------------------------------- #
#
# Different semantics from redact_sensitive: this predicate returns True
# when an operational_fact / typed-shadow / other memory candidate's
# artifact value should not be stored at all. Callers skip the emission
# rather than mutate the artifact to ``[REDACTED]``.
#
# Rationale from live-data analysis 2026-07-02: seven distinct
# operational_fact rows on the roni container had ``artifact =
# ~/.ssh/ronnylinder_dh_rsa``. Text-redaction would collapse them all to
# ``[REDACTED]`` — useless as memory. The correct semantic is "these
# artifacts should never have been captured; don't emit."

# --- Filesystem-path shapes commonly holding key/credential material ---

# Canonical SSH key filenames — with or without .pub sibling.
_SSH_CANONICAL_KEY_RE: Final = re.compile(
    r"(?:^|[/\\])\.ssh[/\\]id_(?:rsa|ed25519|ecdsa|dsa)(?:\.pub)?$",
    re.IGNORECASE,
)

# Custom-named SSH keys in ~/.ssh/ (e.g. `~/.ssh/ronnylinder_dh_rsa`).
_SSH_CUSTOM_KEY_RE: Final = re.compile(
    r"(?:^|[/\\])\.ssh[/\\][\w.\-]+_(?:rsa|ed25519|ecdsa|dsa)(?:\.pub)?$",
    re.IGNORECASE,
)

# Any file directly under ~/.ssh with a common private-key extension.
_SSH_PEM_RE: Final = re.compile(
    r"(?:^|[/\\])\.ssh[/\\][\w.\-]+\.(?:pem|key)$",
    re.IGNORECASE,
)

# Generic key-material files anywhere on disk.
_GENERIC_KEY_FILE_RE: Final = re.compile(
    r"[/\\][\w.\-]+\.(?:pem|key|pfx|p12)$",
    re.IGNORECASE,
)

# Well-known credentials-config paths.
_CREDS_CONFIG_RE: Final = re.compile(
    r"(?:^|[/\\])"
    r"(?:"
    r"\.aws[/\\](?:credentials|config)"
    r"|\.docker[/\\]config\.json"
    r"|\.kube[/\\]config"
    r"|\.gnupg[/\\][\w.\-]+"
    r"|\.netrc"
    r"|_netrc"
    r")$",
    re.IGNORECASE,
)

# SSH connection targets `user@host` — context-gated, see logic below.
_SSH_TARGET_RE: Final = re.compile(
    r"^[\w.\-]+@[\w.\-]+\.[a-zA-Z]{2,}$",
)

# Command heads that indicate an argv token is an SSH target, not an
# email in prose. Used as the context gate for _SSH_TARGET_RE hits.
_SSH_CONTEXT_HEADS: Final = frozenset({
    "ssh", "scp", "sftp", "rsync", "git", "ssh-copy-id", "ssh-add",
    "ssh-keygen", "ssh-keyscan",
})


def _first_argv_token(context: str) -> str:
    """Return the first argv-shaped token of `context`, lower-cased.

    Best-effort — used only for SSH-target disambiguation. Empty
    string when context is empty or unparseable.
    """
    if not context:
        return ""
    for tok in context.strip().split():
        # strip wrapper prefixes like `env FOO=1` / `sudo`
        if "=" in tok and not tok.startswith(("-", "/", "\\", "~", ".")):
            continue
        low = tok.lower()
        if low in {"env", "sudo", "time", "xargs", "nice", "nohup", "exec"}:
            continue
        return low.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return ""


def is_sensitive_artifact(artifact: str, *, context: str = "") -> bool:
    """Return True iff `artifact` is a secret whose emission should be skipped.

    Different semantic from :func:`redact_sensitive` — that mutates text
    in place. This predicate answers a boolean skip question for a
    candidate whose entire identity IS the artifact (e.g. an
    operational_fact whose ``artifact`` field IS the secret path).

    ``context`` is the surrounding argv or fragment used to disambiguate
    a `user@host` token that could be either an SSH target (secret,
    reveals infra) or an email address in prose (not a secret). Empty
    context is treated as untrusted — for `user@host` we then require a
    stronger shape signal before flagging.

    Fail-open when ambiguous. Better to over-emit a non-secret artifact
    than to over-block legitimate operational memory.
    """
    if not artifact:
        return False
    art = artifact.strip()
    if not art:
        return False

    # Direct filesystem-path secret shapes.
    if _SSH_CANONICAL_KEY_RE.search(art):
        return True
    if _SSH_CUSTOM_KEY_RE.search(art):
        return True
    if _SSH_PEM_RE.search(art):
        return True
    if _CREDS_CONFIG_RE.search(art):
        return True
    if _GENERIC_KEY_FILE_RE.search(art):
        return True

    # user@host — context-gated to avoid false-positive on email addresses.
    if _SSH_TARGET_RE.match(art):
        head = _first_argv_token(context)
        if head in _SSH_CONTEXT_HEADS:
            return True
        # Even without explicit ssh context, some hosts are clearly infra:
        # long dashed hostnames, cloud-provider shapes. Conservative sample.
        low = art.lower()
        if (
            ".compute.amazonaws.com" in low
            or ".dreamhost.com" in low
            or ".ec2." in low
            or ".gcp." in low
            or re.search(r"@[\w.\-]*(prod|staging|internal|infra|dh|dh_)", low)
        ):
            return True
        return False

    return False


__all__ = [
    "redact_sensitive",
    "redact_command",
    "redact_probable_secrets",
    "is_sensitive_artifact",
]
