# ADR-0007: Bounded direct-source PDF downloads

- Status: Accepted under user delegation
- Date: 2026-09-25

## Context

Phase 1 currently has a permission-gated OpenAlex adapter pinned to
`content.openalex.org`. The approved Phase 1 plan permits a bounded set of
supported publisher and repository sources, while the exact source adapters remain
open. Ten expansion follow-ups were separately authorized for download. Several
reviewed exact versions are hosted by their publisher or repository and have no
matching OpenAlex cached-PDF route.

## Decision

Add a distinct direct-source PDF adapter for exact reviewed routes from:

- Springer Nature (`link.springer.com`)
- arXiv (`arxiv.org`)
- University of Glasgow repository (`eprints.gla.ac.uk`)

Each route must pin its exact URL, source, document version, and item-specific
license identifier in the run configuration. arXiv URLs must include an explicit
version suffix and use arXiv’s canonical extensionless PDF endpoint (for example,
`https://arxiv.org/pdf/2405.13576v2`). The `.pdf` alias redirects and is rejected;
unversioned “latest” URLs are rejected. Acquisition must also receive matching
`PermissionEvidence` that explicitly permits storage and indexing. The existing
request, retry, timeout, file-size, total-store, PDF-validation, checksum, and
atomic-publication limits apply. The adapter accepts HTTPS on port 443 only,
rejects credentials and fragments, uses a fixed source-host allowlist, and does
not follow redirects. Any new host requires separate review and a code/config
change. Per-run license allowlists remain explicit; the OpenAlex project default
continues to allow only CC BY and public domain.

Downloaded files remain outside Git. Follow-up artifacts stay unassociated until
a new, explicitly approved corpus manifest selects their exact versions. This adapter does not support ACM
Digital Library or PMC. ACM copies require confirmation that the user is entitled
to access the exact articles. PMC author-manuscript retrieval must use PMC's
current dataset services and may return XML rather than a PDF; it needs a separate
format and source decision.

## Alternatives

1. Broaden the OpenAlex adapter to accept arbitrary URLs. Rejected because it
   would weaken its fixed-host and metadata-permission checks.
2. Use one-off `curl` or browser downloads outside the acquisition controls.
   Rejected because limits, checksums, source evidence, and atomic storage would
   not be enforced by the project adapter.
3. Keep OpenAlex as the only supported source. Rejected after the user explicitly
   added arXiv as an allowed route and delegated the source review.

## Consequences

The supported network destination set grows by three fixed hosts, with no
redirect-following and item-level permission checks. This decision implements
the user-approved arXiv route while retaining exact-version and permission checks.
Tests must prove URL/host validation, permission matching, bounded PDF storage,
and redirect rejection. The
per-file inventory must retain exact URL, terms, version, permission basis,
checksum, and configuration identity. This proposal does not change the locked
Phase 1 corpus policy or authorize public passage display.
