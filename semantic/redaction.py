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
    # Tradeoff: does not catch API_TOKEN=..., MY_SECRET=... — hook-layer
    # allow-lists are the proper place for tighter policy.
    r"(?<![A-Za-z0-9_])(PASSWORD|SECRET|TOKEN|KEY|AUTH)(?![A-Za-z0-9_])\s*=\s*\S+",
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


def redact_sensitive(text: str) -> str:
    """Strip secrets from free text.

    Idempotent: safe to call on already-redacted input. Preserves the
    surrounding shape of the text so downstream code that parses argv
    or headers still works after redaction.
    """
    if not text:
        return text
    out = text
    # Order matters: private-key block first (multi-line); then header lines;
    # then bearer / api-key headers; then env-var secrets; then connection
    # strings. Each pattern replaces its own value only; other characters are
    # untouched.
    out = _PRIVATE_KEY_BLOCK_RE.sub("[REDACTED KEY BLOCK]", out)
    out = _SENSITIVE_HEADER_RE.sub(r"\1: [REDACTED]", out)
    out = _BEARER_RE.sub("Bearer [REDACTED]", out)
    out = _API_KEY_HEADER_RE.sub(r"\1=[REDACTED]", out)
    out = _ENV_VAR_SECRET_RE.sub(r"\1=[REDACTED]", out)
    out = _CONNECTION_STRING_RE.sub(r"\1://[REDACTED]", out)
    return out


def redact_command(cmd: str) -> str:
    """Alias of :func:`redact_sensitive`. Named for use at callsites that
    are specifically redacting a shell command line."""
    return redact_sensitive(cmd)


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
    "is_sensitive_artifact",
]
