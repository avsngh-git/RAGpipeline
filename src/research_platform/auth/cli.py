"""Manage API keys from the command line."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from research_platform.auth.keys import ApiKeyRecord, PostgresApiKeyStore, Scope
from research_platform.config import Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-keys")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="create an API key")
    create.add_argument("--principal", required=True)
    create.add_argument(
        "--scope",
        action="append",
        choices=[scope.value for scope in Scope],
        required=True,
    )
    commands.add_parser("list", help="list API keys")
    revoke = commands.add_parser("revoke", help="revoke an API key")
    revoke.add_argument("key_id", type=UUID)
    return parser


async def _execute(args: argparse.Namespace, settings: Settings) -> None:
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
    try:
        store = PostgresApiKeyStore(pool)
        if args.command == "create":
            record, plain_key = await store.create(
                args.principal, [Scope(scope) for scope in args.scope]
            )
            print(
                json.dumps(
                    {
                        "key_id": str(record.key_id),
                        "principal": record.principal,
                        "scopes": sorted(scope.value for scope in record.scopes),
                        "api_key": plain_key,
                    }
                )
            )
            print("Store this key now; it cannot be shown again.", file=sys.stderr)
        elif args.command == "list":
            for record in await store.list():
                print(json.dumps(_record_json(record)))
        else:
            print(json.dumps({"revoked": await store.revoke(args.key_id)}))
    finally:
        await pool.close()


def _record_json(record: ApiKeyRecord) -> dict[str, object]:
    return {
        "key_id": str(record.key_id),
        "principal": record.principal,
        "key_prefix": record.key_prefix,
        "scopes": sorted(scope.value for scope in record.scopes),
        "created_at": record.created_at.isoformat(),
        "revoked_at": record.revoked_at.isoformat() if record.revoked_at else None,
    }


def main(argv: Sequence[str] | None = None) -> None:
    """Run an API key management command."""
    args = _parser().parse_args(argv)
    asyncio.run(_execute(args, Settings()))


if __name__ == "__main__":
    main()
