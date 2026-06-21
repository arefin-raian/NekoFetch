"""Cryptographic helpers.

Distribution-bot tokens are sensitive: they grant control of a public bot. They are
encrypted at rest with Fernet, keyed by ``SECRET_KEY`` from the environment.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _derive_fernet_key(secret: str) -> bytes:
    """Accept any ``SECRET_KEY`` string and derive a valid 32-byte urlsafe key."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class TokenCipher:
    """Symmetric encryption for bot tokens and other small secrets."""

    def __init__(self, secret_key: str) -> None:
        self._fernet = Fernet(_derive_fernet_key(secret_key))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
