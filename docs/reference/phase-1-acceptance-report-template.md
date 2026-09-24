# Phase 1 corpus acceptance report

**Status:** Template. Do not report acceptance until the approved 100-paper pilot
has run and all listed evidence is attached.

## Run identity

- Report date: `TODO`
- Approved manifest ID, version and checksum: `TODO`
- Finalized snapshot ID and configuration ID: `TODO`
- Code revision and environment lock checksum: `TODO`
- Reviewer(s): `TODO`
- Execution profile and hardware snapshot: `TODO`
- Artifact retention cutoff and configured byte ceiling: `TODO`

## Discovery and selection

| Measure | Count / value | Evidence or definition |
| --- | ---: | --- |
| Configured queries and older-paper exceptions | `TODO` | Discovery config ID |
| Requests used / configured ceiling | `TODO` | Discovery run |
| Query pages and truncated queries | `TODO` | Discovery query checkpoints |
| Distinct discovered candidates | `TODO` | Discovery run result count |
| Shortlist candidates | `TODO` | Manifest version |
| Included / excluded / undecided | `TODO` | Approved manifest decisions |
| Reviewer inclusion share among reviewed candidates | `TODO` | Included / (included + excluded); not corpus recall |
| Coverage decisions for hybrid/dense, reranking/latency, chunking/citation | `TODO` | Reviewer notes and coverage report |
| Published / preprint / other selected versions | `TODO` | Selected document versions |
| Sources and license categories | `TODO` | Permission evidence |

Describe shortlist relevance, coverage gaps, selection skews, query overlap,
truncation and limitations. The reviewed shortlist is not a complete reference
set of OpenAlex works and does not support a corpus-wide recall claim.

## Acquisition and processing outcomes

| Outcome | Papers |
| --- | ---: |
| Selected snapshot members | `TODO` |
| Accepted full-text papers | `TODO` |
| Metadata-only | `TODO` |
| Acquisition failed | `TODO` |
| Extraction failed | `TODO` |
| Partial | `TODO` |
| Skipped | `TODO` |
| Completed | `TODO` |

Explain every replacement, exclusion and failure. Count only permitted, accepted
full-text papers toward the 100-paper target. Separate acquisition availability,
processing status and snapshot membership.

## Extraction assessment

- Parser and exact version/configuration: `TODO`
- Comparison candidates and versions: `TODO`
- Reference protocol version and checked papers/samples: `TODO`
- Human-checked prose sections and source locations: `TODO`
- Human-checked tables, cells and header associations: `TODO`
- Omission/read-order error counts and denominators: `TODO`
- Table structure/value/context error counts and denominators: `TODO`
- Figure/equation scope and observed limitations: `TODO`
- Acceptance thresholds and when they were fixed: `TODO`
- Reference annotations and comparison artifacts: `TODO`

Do not describe uninspected pages or cells as verified. Link the versioned,
human-checked reference records and comparison outputs.

## Resource use and recovery

| Measure | Result | Collection method |
| --- | ---: | --- |
| Total and per-stage elapsed time | `TODO` | Persisted stage attempts |
| Peak RAM | `TODO` | `TODO` |
| Peak VRAM | `TODO` | `TODO` |
| Artifact bytes before / after | `TODO` | Storage inspection |
| Configured artifact byte ceiling | `TODO` | Acquisition configuration |
| Retry counts by stage and failure category | `TODO` | Stage attempts |
| Interrupted-run recovery result | `TODO` | Job and attempt IDs |
| Targeted retry result and reason | `TODO` | Job and attempt IDs |

## Evidence and index integrity

- Snapshot validation report: `TODO`
- Selected paper/document/extraction counts: `TODO`
- Text chunk and structured table counts: `TODO`
- Missing-source, permission or provenance issues: `TODO`
- Index configuration ID and collection: `TODO`
- PostgreSQL/Qdrant expected and observed point counts: `TODO`
- Exact evidence-ID fingerprints: `TODO`
- Rebuild command, result, timing and reconciliation evidence: `TODO`
- Orphan/cleanup preview and resulting accounting: `TODO`

## Limitations and decision record

Record unresolved source coverage, parser errors, layout limitations, resource
constraints, permission exclusions, remaining uncertainty and the concrete inputs
needed before Phase 2. State explicitly whether the snapshot passed every threshold
that was fixed before the pilot. Do not claim Phase 1 acceptance if any required
quality, integrity, permission or 100-paper condition remains unmet.
