"""Internal B1 codec for persisted Relay parts; public multipart remains disabled."""
from __future__ import annotations

import json
import unicodedata

from redaction import redact_sensitive

MAX_PARTS = 8
MAX_PART_CODEPOINTS = 1500
MAX_RENDER_CODEPOINTS = 16384
MAX_RENDER_BYTES = 65536
MAX_STORED_BYTES = 131072
_MASK = "[REDACTED]"


class RelayCodecError(ValueError):
    pass


def _validate_parts(parts: list[str]) -> None:
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS:
        raise RelayCodecError("parts must contain 1 to 8 strings")
    if any(
        not isinstance(part, str)
        or not part.strip()
        or len(part) > MAX_PART_CODEPOINTS
        or any(
            (unicodedata.category(char) == "Cc" and char not in "\n\r\t")
            or unicodedata.category(char) in {"Cs", "Zl", "Zp"}
            for char in part
        )
        for part in parts
    ):
        raise RelayCodecError("invalid Relay part")


def encode_parts(parts: list[str]) -> str:
    """Low-level canonical encoder; callers must redact before persisting."""
    _validate_parts(parts)
    rendered = "".join(parts)
    if len(rendered) > MAX_RENDER_CODEPOINTS or len(rendered.encode("utf-8")) > MAX_RENDER_BYTES:
        raise RelayCodecError("rendered Relay parts exceed bounds")
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_STORED_BYTES:
        raise RelayCodecError("stored Relay parts exceed bounds")
    return encoded


def decode_parts(payload: str) -> list[str]:
    if not isinstance(payload, str):
        raise RelayCodecError("stored Relay parts must be text")
    try:
        stored_bytes = len(payload.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise RelayCodecError("stored Relay parts contain invalid Unicode") from exc
    if stored_bytes > MAX_STORED_BYTES:
        raise RelayCodecError("stored Relay parts exceed bounds")
    try:
        parts = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RelayCodecError("malformed Relay parts") from exc
    if encode_parts(parts) != payload:
        raise RelayCodecError("noncanonical Relay parts")
    return parts


def prepare_parts(parts: list[str]) -> str:
    """Validate, redact, then canonically encode ordered parts for persistence."""
    _validate_parts(parts)
    joined = "".join(parts)
    if redact_sensitive(joined) != joined:
        # ponytail: whole-part masking; preserve exact part count until B2 needs span mapping.
        redacted = [_MASK] * len(parts)
    else:
        redacted = [redact_sensitive(part) for part in parts]
    return encode_parts(redacted)


def parts_projection(payload: str) -> str:
    """Return the complete, validated text projection of stored canonical parts."""
    return "".join(decode_parts(payload))