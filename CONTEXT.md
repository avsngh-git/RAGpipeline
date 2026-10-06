# Scientific Research Platform

Vocabulary for collecting scientific literature and preserving traceable evidence.

## Language

**Paper**:
A logical scholarly work that may have multiple identifiable document versions.
_Avoid_: PDF when referring to the work itself.

**Document version**:
A particular source representation of a paper, such as a preprint revision or
published article, from which evidence is extracted.

**Collection**:
A selection of papers within a declared research scope.

**Snapshot**:
A fixed, versioned record of a collection's selected papers, document versions
and evidence configuration.
_Avoid_: Live collection when referring to a fixed selection.

**Evidence unit**:
A source-linked passage or structured table unit available to support a claim.
Its identity includes the document version from which it was derived.

**Metadata-only record**:
A paper record available for discovery or citation relationships without ingested
full-text evidence.

**Manifest**:
The record of a snapshot's membership, acquisition provenance and selection reasons.

**Draft snapshot**:
A snapshot undergoing processing or inspection whose evidence has not yet been
accepted for normal research use.

**Finalized snapshot**:
A snapshot with validated, fixed membership, selected evidence versions and
configuration, accepted for normal research use.

**Unresolved citation reference**:
A known external paper identifier at the end of a citation relationship whose
corresponding local paper record has not yet been established. Retrieved metadata
may be retained without creating a local paper record.


**Original artifact**:
The exact file bytes obtained from a source, identified by their content checksum.
Multiple document versions may refer to the same original artifact.

**Permission evidence**:
A reviewed record of the source, applicable license and separate decisions for storing, indexing and displaying passages from a document version.


**Retrieval profile**:
A fixed selection of retrieval and ranking choices bound to a particular corpus
snapshot and its evidence representation.

**Paper hit**:
A search result for one logical paper that retains its paper-level and supporting-evidence contributions.

**Evidence hit**:
A ranked match to a source evidence unit, identified with its document version and source location.

**Retrieval mode**:
The named combination of search and ranking methods requested for a paper or evidence search.

**Private evidence inspection**:
Trusted local review of retained evidence when storage and indexing are permitted; this is separate from public passage display.

**Experimental variant**:
A separately identifiable corpus representation used to compare retrieval choices
while preserving the source selection and lineage of an accepted snapshot.

**Source evidence judgment**:
A relevance assessment of a passage or table cell in a specific document version,
independent of the boundaries of searchable chunks.

**Evidence requirement group**:
The source evidence pieces needed together to address an information need, with
alternative supporting passages distinguished from additional required pieces.

**Question family**:
One research information need and its paraphrases or closely related variants.

**Variant lineage**:
The relationship between an experimental variant and the finalized snapshot selection from which it was derived. It identifies the source snapshot and evidence selection inherited before the variant changes its representation.

**Research run**:
One persisted execution of a research question in a research mode, with its status, answer, claims, tool calls, budgets and provenance.

**Research mode**:
How a research run gathers evidence: `quick` follows a fixed search sequence; `deep_research` lets the model plan action batches and decide when evidence is sufficient.

**Action batch**:
A validated list of typed tool calls proposed by the model in one planning or evaluation step and executed by code.

**Evidence handle**:
A short run-scoped label (`E1` to `E40`) shown to the model in place of a chunk ID and mapped back to the chunk by code.

**Answer outcome**:
How well a completed research run's answer is supported: answered, partially supported, or insufficient evidence.

**Failure category**:
The fixed classification recorded when a research run fails, such as an invalid model output or an exhausted budget.

**Support label**:
The recorded support of one claim against its cited passage: supported, partial or unsupported. A claim kept by quote verification is supported; partial and unsupported appear only in runs checked by the earlier support judge.

**Claim quote**:
The sentence, or the part of one labeled table row, that a claim copies word for word from the passage it cites.
_Avoid_: snippet, excerpt

**Quote verification**:
The check that a claim's quote occurs in its cited passage and that the claim states nothing the quote does not; a claim that fails it is dropped.
_Avoid_: support judge, faithfulness score

**Labeled table row**:
A table row shown with every value next to its column headers, so a value can be read without counting columns.

**Generation**:
A numbered, finalized snapshot of a collection published to the search index; generation N adds papers to generation N−1. A research run reads one generation and changes it only at a recorded switch.
_Avoid_: release, index version

**Catalog paper**:
A paper record known from scholarly metadata, with or without ingested full text, that discovery can rank and propose for ingestion.

**Abstract evidence**:
A paper's metadata abstract used as citable evidence and labelled separately from full-text passages.

**Ingestion request**:
A queued, policy-checked request to ingest named catalog papers into the next generation, created by a research run, the API or a terminal command.

**Run record**:
The authoritative PostgreSQL record of what a research run did: its effective configuration, tool calls, model calls, drafted claims with verdicts, and outcome. Traces add timing; run records decide.
_Avoid_: log, trace when meaning the stored record

**Trace content level**:
How much content traces and stored model-call text may hold: `none` (names, timings, counts), `ids` (plus identifiers and scores) or `full` (plus prompts, model output and query text). Logs never hold text at any level.

**Drafted claim**:
A claim as the model wrote it during synthesis, before verification, kept with its verdict: kept, unknown handle, not shown, or failed checks.

**Diagnosis stage**:
The single stage to which a failed or partial research run is attributed from its run records, such as retrieval, evidence, generation or verification.

**Experiment record**:
One evaluation run of a named suite over a versioned dataset, with its configuration, component versions, hardware, metrics, failures and private per-item results.

**Principal**:
The named caller behind an API key; a research run belongs to the principal that started it.
_Avoid_: user, account
