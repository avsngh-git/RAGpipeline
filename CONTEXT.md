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
