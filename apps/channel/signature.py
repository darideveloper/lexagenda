"""gowa signs the raw body with HMAC-SHA256 in `X-Hub-Signature-256`."""

import hashlib
import hmac


def verify(secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
