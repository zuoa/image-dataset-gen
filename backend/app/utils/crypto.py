from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _normalized_key(raw_key: str) -> bytes:
    decoded = base64.b64decode(raw_key)
    if len(decoded) != 32:
        raise ValueError("ENCRYPTION_KEY must decode to exactly 32 bytes")
    return decoded


def encrypt_secret(secret: str, raw_key: str) -> str:
    key = _normalized_key(raw_key)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, secret.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_secret(token: str, raw_key: str) -> str:
    blob = base64.b64decode(token)
    nonce = blob[:12]
    ciphertext = blob[12:]
    aesgcm = AESGCM(_normalized_key(raw_key))
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
