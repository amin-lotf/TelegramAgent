from __future__ import annotations

import base64
import binascii
import getpass
import hashlib
import hmac
import os


_ALGORITHM = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 600_000


def normalize_password_hash(encoded: str) -> str:
    normalized = encoded.strip()
    if (
        len(normalized) >= 2
        and normalized[0] in {"'", '"'}
        and normalized[-1] == normalized[0]
    ):
        normalized = normalized[1:-1]
    return normalized


def hash_password(
    password: str,
    *,
    iterations: int = _DEFAULT_ITERATIONS,
    salt: bytes | None = None,
) -> str:
    if not password:
        raise ValueError("Password must not be empty")
    if iterations < 1:
        raise ValueError("Iterations must be positive")
    actual_salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        actual_salt,
        iterations,
    )
    return "$".join(
        (
            _ALGORITHM,
            str(iterations),
            base64.urlsafe_b64encode(actual_salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        normalized = normalize_password_hash(encoded)
        algorithm, iterations_text, salt_text, expected_text = normalized.split("$", 3)
        if algorithm != _ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
    except (ValueError, TypeError, binascii.Error):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


if __name__ == "__main__":
    first = getpass.getpass("Administrator password: ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    print(hash_password(first))
