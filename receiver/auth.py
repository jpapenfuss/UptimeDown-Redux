"""Authentication module for the receiver."""

import hmac
import logging

logger = logging.getLogger("receiver")


def load_tokens(path: str) -> set[str]:
    """
    Load authentication tokens from a plain text file.

    Format: one token per line. Blank lines and lines starting with '#' are
    ignored. Tokens must be at least 32 characters; shorter tokens are logged
    as warnings and skipped.

    Args:
        path: Path to the token file.

    Returns:
        Set of valid tokens (strings).

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    tokens = set()
    with open(path, "r") as f:
        for line_no, line in enumerate(f, 1):
            line = line.rstrip("\n\r")

            # Skip blank lines
            if not line or not line.strip():
                continue

            # Skip comments
            if line.strip().startswith("#"):
                continue

            # Check minimum length
            if len(line) < 32:
                logger.warning(
                    "Token at line %d is too short (< 32 chars); skipping", line_no
                )
                continue

            tokens.add(line)

    return tokens


def check_auth(headers, valid_tokens: set) -> bool:
    """
    Check if the request has valid Bearer authentication.

    Expects "Authorization: Bearer <token>" header. Uses constant-time
    comparison (hmac.compare_digest) to prevent timing attacks.

    **CRITICAL**: Compares against ALL tokens to prevent timing attacks.
    Does NOT short-circuit on first match.

    Args:
        headers: HTTP message headers (http.client.HTTPMessage).
        valid_tokens: Set of valid bearer tokens.

    Returns:
        True if the Authorization header contains a valid Bearer token;
        False otherwise (missing header, wrong format, or no match).
    """
    auth_header = headers.get("Authorization")
    if not auth_header:
        return False

    # Parse "Bearer <token>" format
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0] != "Bearer":
        return False

    token = parts[1]

    # Compare against ALL tokens using constant-time comparison
    # Do NOT short-circuit on first match
    matched = False
    for valid_token in valid_tokens:
        if hmac.compare_digest(token, valid_token):
            matched = True

    return matched
