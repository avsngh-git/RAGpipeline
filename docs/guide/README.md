# Documentation guide

This guide is the complete documentation for the Scientific Research Platform. It is written for engineers who want to run, use, operate or change the system without prior knowledge of the project. The [README](../../README.md) is the short version.

Read the chapters in order the first time; afterwards use them as reference.

| Chapter | What it covers |
| --- | --- |
| [1. Concepts](01-concepts.md) | What the platform does and the vocabulary used everywhere else |
| [2. Getting started](02-getting-started.md) | The CPU demo, live research runs on a GPU, and a development environment |
| [3. How it works](03-how-it-works.md) | The architecture and the path from PDF to verified answer |
| [4. HTTP API](04-http-api.md) | Endpoints, authentication, request and response shapes, errors, limits |
| [5. MCP server](05-mcp.md) | Tools and resources for external AI clients |
| [6. Command-line tools](06-cli.md) | The eight `research-*` commands |
| [7. Configuration](07-configuration.md) | Every environment variable and its default |
| [8. Corpus and ingestion](08-corpus-and-ingestion.md) | Discovery, permissions, extraction, snapshots, index generations, online ingestion |
| [9. Search](09-search.md) | The retrieval pipeline, modes, filters and result semantics |
| [10. Research runs](10-research-runs.md) | Modes, budgets, quote verification, outcomes, failures, provenance |
| [11. Evaluation](11-evaluation.md) | Evaluation suites, measured results, run diagnosis and reproduction |
| [12. Observability and security](12-observability-and-security.md) | Logs, metrics, traces, keys, scopes, text exposure, threat model |
| [13. Operations](13-operations.md) | Releases, migrations, backup, rollback, recovery, retention |
| [14. Development](14-development.md) | Code layout, tests, CI, conventions and how decisions are recorded |

## Other documents

The guide summarizes and links to these; they hold the full detail.

- [Architecture overview](../architecture/overview.md): component table and sequence diagrams.
- [Architecture decision records](../adr/): why each significant choice was made (ADR-0001 to ADR-0033).
- [Benchmarks](../reference/benchmarks.md) and [failure analysis](../reference/failure-analysis.md): measured results.
- [Operations guides](../operations/): procedures for deployment, search, the generator, MCP, authentication, observability, evaluation and retention.
- [Project specification](../agents/scientific-research-platform-source-of-truth.md): requirements and the decision process. Where this guide and the specification disagree, the specification wins.
- [Glossary](../../CONTEXT.md): the canonical domain vocabulary.
- [Project history](../history.md): what each delivery phase produced.
