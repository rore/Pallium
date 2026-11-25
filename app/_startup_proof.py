"""Private proof that a managed startup probe reached its own launch."""

import hmac
import re


CHALLENGE_HEADER = "X-Pallium-Startup-Challenge"
PROOF_HEADER = "X-Pallium-Startup-Proof"


def startup_proof(nonce: str, challenge: str) -> str | None:
    if re.fullmatch(r"[0-9a-f]{32}", challenge) is None:
        return None
    return hmac.new(
        nonce.encode("utf-8"), b"pallium:api-startup:v1\0" + bytes.fromhex(challenge), "sha256",
    ).hexdigest()
