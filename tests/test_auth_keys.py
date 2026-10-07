"""Offline tests for API key generation and management."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_platform.auth import cli
from research_platform.auth.keys import (
    InMemoryApiKeyStore,
    Scope,
    generate_api_key,
    hash_api_key,
    validate_principal_name,
)
from research_platform.config import Settings


def test_generated_key_format() -> None:
    key = generate_api_key()

    assert key.startswith("rsk_")
    assert len(key) == 47


def test_hash_is_sha256_hex() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", hash_api_key("synthetic"))


def test_in_memory_create_and_authenticate() -> None:
    store = InMemoryApiKeyStore()
    record, key = asyncio.run(store.create("scientist", [Scope.READ, Scope.RESEARCH]))

    principal = asyncio.run(store.authenticate(key))

    assert principal is not None
    assert principal.name == "scientist"
    assert principal.scopes == record.scopes == frozenset({Scope.READ, Scope.RESEARCH})
    assert principal.key_id == record.key_id


def test_wrong_or_malformed_key_rejected() -> None:
    store = InMemoryApiKeyStore()

    assert asyncio.run(store.authenticate("wrong")) is None
    assert asyncio.run(store.authenticate("rsk_" + "x" * 42)) is None


def test_revoked_key_rejected() -> None:
    store = InMemoryApiKeyStore()
    record, key = asyncio.run(store.create("scientist", [Scope.READ]))

    assert asyncio.run(store.revoke(record.key_id))
    assert asyncio.run(store.authenticate(key)) is None
    assert not asyncio.run(store.revoke(record.key_id))


def test_admin_has_every_scope() -> None:
    from research_platform.auth.keys import Principal

    principal = Principal("operator", frozenset({Scope.ADMIN}))

    assert all(principal.has(scope) for scope in Scope)


def test_principal_name_validation() -> None:
    assert validate_principal_name("team.owner-1") == "team.owner-1"
    with pytest.raises(ValueError):
        validate_principal_name("Invalid Name")


def test_cli_create_prints_key_once(monkeypatch, capsys) -> None:
    class FakePool:
        closed = False

        async def close(self) -> None:
            self.closed = True

    class FakeStore:
        async def create(self, principal: str, scopes: list[Scope]):
            from research_platform.auth.keys import ApiKeyRecord

            return (
                ApiKeyRecord(
                    key_id=uuid4(),
                    principal=principal,
                    key_prefix="abcdefgh",
                    scopes=frozenset(scopes),
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    revoked_at=None,
                ),
                "rsk_" + "x" * 43,
            )

    pool = FakePool()

    async def create_pool(database_url: str, *, min_size: int, max_size: int):
        assert database_url.endswith("/research_test")
        assert (min_size, max_size) == (1, 2)
        return pool

    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(database_url="postgresql://test:test@localhost/research_test"),
    )
    monkeypatch.setattr(cli.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(cli, "PostgresApiKeyStore", lambda _pool: FakeStore())

    cli.main(["create", "--principal", "scientist", "--scope", "read"])

    captured = capsys.readouterr()
    assert captured.out.count("rsk_" + "x" * 43) == 1
    assert "Store this key now; it cannot be shown again." in captured.err
    assert pool.closed
