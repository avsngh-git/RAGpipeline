"""API key generation, authentication, and storage."""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol, cast
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]

KEY_PREFIX: Final = "rsk_"
_PRINCIPAL_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")


class Scope(StrEnum):
    READ = "read"
    RESEARCH = "research"
    INGEST = "ingest"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    """An authenticated caller."""

    name: str
    scopes: frozenset[Scope]
    key_id: UUID | None = None

    def has(self, scope: Scope) -> bool:
        return scope in self.scopes or Scope.ADMIN in self.scopes


LOCAL_PRINCIPAL: Final = Principal("local", frozenset(Scope))


@dataclass(frozen=True)
class ApiKeyRecord:
    key_id: UUID
    principal: str
    key_prefix: str
    scopes: frozenset[Scope]
    created_at: datetime
    revoked_at: datetime | None


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def key_prefix(key: str) -> str:
    return key[4:12]


def validate_principal_name(name: str) -> str:
    if not _PRINCIPAL_PATTERN.fullmatch(name):
        raise ValueError("principal name must match the required format")
    return name


class ApiKeyStore(Protocol):
    async def create(
        self, principal: str, scopes: Collection[Scope]
    ) -> tuple[ApiKeyRecord, str]: ...

    async def authenticate(self, key: str) -> Principal | None: ...

    async def list(self) -> tuple[ApiKeyRecord, ...]: ...

    async def revoke(self, key_id: UUID) -> bool: ...


class PostgresApiKeyStore:
    """Asyncpg storage adapter for hashed API keys."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(
        self, principal: str, scopes: Collection[Scope]
    ) -> tuple[ApiKeyRecord, str]:
        name = validate_principal_name(principal)
        selected = frozenset(scopes)
        _validate_scopes(selected)
        for attempt in range(3):
            plain_key = generate_api_key()
            try:
                async with self._pool.acquire() as connection:
                    row = await connection.fetchrow(
                        """
                        INSERT INTO api_keys (principal, key_prefix, key_sha256, scopes)
                        VALUES ($1, $2, $3, $4::text[])
                        RETURNING key_id, principal, key_prefix, scopes,
                                  created_at, revoked_at
                        """,
                        name,
                        key_prefix(plain_key),
                        hash_api_key(plain_key),
                        sorted(scope.value for scope in selected),
                    )
            except asyncpg.UniqueViolationError:
                if attempt == 2:
                    raise
                continue
            return _record(row), plain_key
        raise RuntimeError("API key creation failed")

    async def authenticate(self, key: str) -> Principal | None:
        if not _well_formed_key(key):
            return None
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """SELECT key_id, principal, scopes FROM api_keys
                   WHERE key_sha256 = $1 AND revoked_at IS NULL""",
                hash_api_key(key),
            )
        if row is None:
            return None
        return Principal(
            name=row["principal"],
            scopes=frozenset(Scope(scope) for scope in row["scopes"]),
            key_id=row["key_id"],
        )

    async def list(self) -> tuple[ApiKeyRecord, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT key_id, principal, key_prefix, scopes, created_at, revoked_at
                   FROM api_keys ORDER BY created_at DESC, key_id DESC"""
            )
        return tuple(_record(row) for row in rows)

    async def revoke(self, key_id: UUID) -> bool:
        async with self._pool.acquire() as connection:
            result = await connection.execute(
                "UPDATE api_keys SET revoked_at = now() WHERE key_id = $1 AND revoked_at IS NULL",
                key_id,
            )
        return cast(str, result) == "UPDATE 1"


class InMemoryApiKeyStore:
    """In-memory API key store for offline use and tests."""

    def __init__(self) -> None:
        self._records: dict[UUID, ApiKeyRecord] = {}
        self._hashes: dict[str, UUID] = {}

    async def create(
        self, principal: str, scopes: Collection[Scope]
    ) -> tuple[ApiKeyRecord, str]:
        name = validate_principal_name(principal)
        selected = frozenset(scopes)
        _validate_scopes(selected)
        for _ in range(3):
            plain_key = generate_api_key()
            digest = hash_api_key(plain_key)
            prefix = key_prefix(plain_key)
            if digest not in self._hashes and all(
                record.key_prefix != prefix for record in self._records.values()
            ):
                break
        else:
            raise RuntimeError("API key prefix collision limit exceeded")
        record = ApiKeyRecord(
            key_id=uuid4(),
            principal=name,
            key_prefix=prefix,
            scopes=selected,
            created_at=datetime.now(UTC),
            revoked_at=None,
        )
        self._records[record.key_id] = record
        self._hashes[digest] = record.key_id
        return record, plain_key

    async def authenticate(self, key: str) -> Principal | None:
        if not _well_formed_key(key):
            return None
        key_id = self._hashes.get(hash_api_key(key))
        record = self._records.get(key_id) if key_id is not None else None
        if record is None or record.revoked_at is not None:
            return None
        return Principal(record.principal, record.scopes, record.key_id)

    async def list(self) -> tuple[ApiKeyRecord, ...]:
        return tuple(
            sorted(
                self._records.values(),
                key=lambda record: (record.created_at, record.key_id),
                reverse=True,
            )
        )

    async def revoke(self, key_id: UUID) -> bool:
        record = self._records.get(key_id)
        if record is None or record.revoked_at is not None:
            return False
        self._records[key_id] = replace(record, revoked_at=datetime.now(UTC))
        return True


def _validate_scopes(scopes: frozenset[Scope]) -> None:
    if not scopes:
        raise ValueError("at least one scope is required")
    if any(not isinstance(scope, Scope) for scope in scopes):
        raise ValueError("scopes must be Scope values")


def _well_formed_key(key: str) -> bool:
    return key.startswith(KEY_PREFIX) and len(key) == 47


def _record(row: asyncpg.Record) -> ApiKeyRecord:
    return ApiKeyRecord(
        key_id=row["key_id"],
        principal=row["principal"],
        key_prefix=row["key_prefix"],
        scopes=frozenset(Scope(scope) for scope in row["scopes"]),
        created_at=row["created_at"],
        revoked_at=row["revoked_at"],
    )
