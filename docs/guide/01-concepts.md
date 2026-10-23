# 1. Concepts

## What the platform does

The platform answers research questions from a fixed, versioned collection of scientific papers. Given a question, it:

1. searches the collection for relevant papers and passages (prose or tables);
2. optionally follows citation links and, in `deep_research` mode, can discover and ingest new papers from OpenAlex;
3. asks a local language model to write claims, each of which must quote a passage it was shown;
4. checks every quote against its passage in code, and drops claims that fail;
5. stores the answer with its full provenance, so the run can later be explained and its configuration rebuilt.

It is a backend system first. It exposes a versioned HTTP API, an MCP server for external AI clients, a set of command-line tools and a small web page. There is no chat interface.

## Design principles

These come from the [project specification](../agents/scientific-research-platform-source-of-truth.md#4-architectural-principles) and explain most of the structure:

- **Evidence before prose.** The system gathers and validates evidence before it writes anything.
- **The agent decides; tools act.** The model chooses the next action. Typed tools perform it, and code enforces budgets and permissions. Prompts alone are never trusted to do this.
- **Provenance is a product feature.** Every claim traces to an immutable chunk identifier, a document version and a paper.
- **Measure components separately.** A bad answer must be diagnosable as a retrieval, evidence, generation or verification failure.
- **Configuration is versioned.** Models, prompts, the retrieval profile, the chunker and the parser all form part of a run's recorded configuration.
- **PostgreSQL is authoritative; Qdrant is derived.** The search index can always be verified against and rebuilt from the database.
- **Framework-independent core.** Retrieval and paper services do not live inside LangGraph or the MCP adapter; those are thin layers over the same services.

## Vocabulary

The canonical definitions are in the [glossary](../../CONTEXT.md). These are the terms you need to read the rest of the guide.

### Corpus

| Term | Meaning |
| --- | --- |
| **Paper** | A logical scholarly work, identified by an OpenAlex ID such as `W2741809807`. One paper can have several document versions. |
| **Document version** | One concrete source of a paper, such as a published article or an arXiv revision, from which evidence is extracted. |
| **Permission evidence** | A reviewed record of a document's license and separate decisions for storing, indexing and publicly displaying its passages. Downloadable does not mean permitted. |
| **Evidence unit** | A source-linked passage, table, table row group, caption, figure text or equation extracted from a document version. Evidence kinds are `text`, `table`, `table_row_group`, `caption`, `figure` and `equation`. |
| **Chunk** | The searchable form of an evidence unit, with a stable ID and source offsets. |
| **Collection** | A set of papers within a declared research scope. The served collection is `research-corpus`. |
| **Snapshot** | A fixed record of a collection's papers, the document version chosen for each, and the evidence configuration. A *draft* snapshot can be inspected; only a *finalized* snapshot, whose integrity has been validated, is used for research. |
| **Index generation** | A numbered, finalized snapshot published into Qdrant. Generation N+1 adds papers to generation N. Each research run pins the generation it started on. |
| **Metadata-only record** | A paper known from OpenAlex metadata but without ingested full text. Its abstract can be cited as labelled *abstract evidence*. |

### Search

| Term | Meaning |
| --- | --- |
| **Retrieval profile** | A frozen set of retrieval choices (models, revisions, analyzer, fusion constant, candidate pools, limits) bound to a snapshot, identified by a `sha256:` ID. The served profile is `v10-qdrant`. |
| **Retrieval mode** | Which stages a search uses: `lexical`, `dense`, `hybrid` or `reranked`. |
| **Paper hit** | One result per paper, with its own scores and up to five supporting passages. |
| **Evidence hit** | One ranked evidence unit with its document version, source location and component scores. |

### Research runs

| Term | Meaning |
| --- | --- |
| **Research run** | One persisted execution of a question. It has a status (`queued`, `running`, `waiting_for_ingestion`, `completed`, `failed`), an answer, claims, tool calls, budgets and provenance. |
| **Research mode** | `quick` follows a fixed search sequence; `deep_research` lets the model plan tool calls and decide when evidence is sufficient. |
| **Evidence handle** | A short run-local label (`E1` to `E40`) that the model sees instead of a chunk ID. Code maps it back. A claim citing an unknown handle is rejected. |
| **Claim quote** | The sentence, or part of a labelled table row, that a claim copies word for word from its cited passage. |
| **Quote verification** | The code check that a quote occurs in its cited passage and that the claim says nothing the quote does not. |
| **Answer outcome** | `answered`, `partially_supported` or `insufficient_evidence`. |
| **Failure category** | Why a run failed: `model_unavailable`, `invalid_model_output`, `budget_exhausted`, `timeout`, `retrieval_error`, `resume_exhausted`, `configuration_changed` or `internal`. |
| **Run record** | The authoritative PostgreSQL record of what a run did. Traces add timing; run records decide. |
| **Diagnosis stage** | The single stage a failed or partial run is attributed to, such as `retrieval`, `evidence`, `generation` or `verification`. |

### Access

| Term | Meaning |
| --- | --- |
| **Principal** | The named caller behind an API key. A research run belongs to the principal that started it. |
| **Scope** | What a key may do: `read`, `research`, `ingest` or `admin`. |
| **Private evidence inspection** | Trusted local access to stored passage text, enabled on the server by `RESEARCH_PLATFORM_EVIDENCE_ACCESS_PROFILE=trusted_private_local`. A request cannot grant it. |
| **External client** | A program, such as an AI assistant, that uses the platform through MCP. What it receives may leave the machine, so passage text is withheld unless public display is permitted. |

## What is deliberately not here

Generator fine-tuning, multi-agent personas, a graph database, Spark, Kubernetes, a hosted demo and a chat-style frontend are all out of scope. The [specification's non-goals](../agents/scientific-research-platform-source-of-truth.md#32-non-goals--locked) explain why: each component must have a technical reason to exist.

Next: [Getting started](02-getting-started.md).
