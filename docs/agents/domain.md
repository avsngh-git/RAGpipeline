# Domain docs

## Read order

1. Read `docs/agents/scientific-research-platform-source-of-truth.md`.
2. Read root `CONTEXT.md`, when present, for domain terminology.
3. Read relevant accepted ADRs under `docs/adr/`.

Follow the source-of-truth document's precedence and change-control rules.
Surface conflicts explicitly; resolve them before implementing a conflicting
decision.

## Layout

Use one root `CONTEXT.md` and one `docs/adr/` directory.

If domain documents are absent, proceed without creating placeholders.
Use the domain-modeling skill to record terminology and decisions as they
are resolved.

## Vocabulary and decisions

Use glossary terms consistently in code, tests, plans, and issues.
Flag missing concepts for domain modeling.

Keep the project specification authoritative. Domain documents elaborate
terminology and decisions without duplicating the high-level plan.
