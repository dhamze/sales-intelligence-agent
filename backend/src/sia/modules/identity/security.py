"""Credential primitives: password hashing, session tokens, identifier hashing.

Argon2id (via argon2-cffi) with the library's RFC 9106 "low memory" profile. Hashing is
deliberately slow (~40 ms) and memory-hard to make offline guessing expensive, so it runs in a
worker thread to avoid blocking the event loop.
"""

import asyncio
import hashlib
import secrets
from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

SESSION_TOKEN_BYTES = 32  # 256 bits of randomness


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(_verify)


def password_needs_rehash(password_hash: str) -> bool:
    """True if the hash used weaker parameters than today's; it is upgraded at next login."""
    return _hasher.check_needs_rehash(password_hash)


@cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


async def burn_password_check(password: str) -> None:
    """Spend the same time as a real verification. Used when the account does not exist, so
    response timing does not reveal which email addresses are registered."""
    await verify_password(await asyncio.to_thread(_dummy_hash), password)


def new_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_token(token: str) -> bytes:
    """Session tokens are stored only as SHA-256 hashes. A fast hash is appropriate here (unlike
    passwords) because the token is 256 random bits: it cannot be guessed, only stolen, and a
    stolen database then contains nothing usable."""
    return hashlib.sha256(token.encode()).digest()


def hash_identifier(value: str) -> bytes:
    """Pseudonymise an identifier (e.g. an email in login_attempts) for throttling lookups."""
    return hashlib.sha256(value.encode()).digest()
