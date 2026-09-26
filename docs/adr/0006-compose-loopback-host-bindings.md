# ADR-0006: Loopback-only host bindings for local Compose services

- Status: Accepted as the local-development default
- Date: 2026-09-25

## Context

The Compose file published PostgreSQL, Qdrant, and the API without a host IP,
which binds those ports on all host interfaces. Local development uses these
services from the same host, while Phase 1 may store and index papers whose
permissions are limited to private local use. The API has no authentication
boundary in the local profile, and PostgreSQL/Qdrant are not configured for
remote access.

## Decision

Bind the published PostgreSQL, Qdrant, and API ports to `127.0.0.1`. Keep the
existing configurable host port numbers. Containers continue communicating over
the Compose network by service name. A remote demonstration is a separate
deployment and needs its own access-control decision.

## Alternatives considered

1. **Leave ports on all host interfaces.** Rejected because it exposes
   unauthenticated development services beyond the local machine.
2. **Make the host interface configurable.** Deferred; no current local workflow
   requires LAN access, and a broad override would make accidental exposure easy.
3. **Remove host ports entirely.** Rejected because local development and manual
   API/database inspection use host-side clients.

## Consequences

Local clients continue connecting through `localhost` on the configured ports.
Other devices on the host network cannot reach these Compose ports. Applying the
mapping change recreates the containers; named database and vector volumes remain
persistent. Remote access must use a separately reviewed deployment path.
