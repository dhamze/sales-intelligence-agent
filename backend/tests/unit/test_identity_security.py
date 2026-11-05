import hashlib

from argon2 import PasswordHasher

from sia.modules.identity.security import (
    hash_password,
    hash_token,
    new_session_token,
    normalize_email,
    password_needs_rehash,
    verify_password,
)


async def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = await hash_password("correct horse battery staple")

    assert hashed.startswith("$argon2id$")
    assert "correct horse" not in hashed
    assert await verify_password(hashed, "correct horse battery staple")
    assert not await verify_password(hashed, "correct horse battery stapler")


async def test_same_password_hashes_differently_each_time() -> None:
    """Random salts: identical passwords must not produce identical hashes."""
    assert await hash_password("same-password-123") != await hash_password("same-password-123")


async def test_verify_rejects_malformed_hash_instead_of_crashing() -> None:
    assert not await verify_password("not-a-hash", "anything")
    assert not await verify_password("", "anything")


async def test_weaker_hashes_are_flagged_for_upgrade() -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash("pw-123456789")

    assert password_needs_rehash(weak)
    assert not password_needs_rehash(await hash_password("pw-123456789"))


def test_session_tokens_are_long_random_and_unique() -> None:
    tokens = {new_session_token() for _ in range(1000)}

    assert len(tokens) == 1000
    assert all(len(t) >= 43 for t in tokens)  # 32 bytes, URL-safe base64


def test_token_hash_is_sha256_and_deterministic() -> None:
    token = new_session_token()

    assert hash_token(token) == hashlib.sha256(token.encode()).digest()
    assert len(hash_token(token)) == 32


def test_email_normalization() -> None:
    assert normalize_email("  Alice.Smith@Example.COM ") == "alice.smith@example.com"


def test_unknown_emails_cost_one_verification_like_known_ones() -> None:
    """Login for an unknown email must take as long as for a real account (no enumeration by
    timing). That holds only if the dummy hash is computed once, not on every attempt."""
    from sia.modules.identity import security

    assert security._dummy_hash() is security._dummy_hash()
