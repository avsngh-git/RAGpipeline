# Phase 2 run records

Status: schema v2 and the fake-service evaluation runner completed for P2-05/P2-11.

`research_platform.evaluation.run_records` captures one calibrated query and its
search attempts in an immutable, versioned record. The dataset hash and split policy
identify the reviewed question set; query and family IDs select the exact calibration
entry. The record also pins the accepted snapshot, source alignment and matching
policy, scoring policy, Git revision, and (for a dirty tree) a checksum of the diff.

Each attempt stores the request operation, filters, result limit, requested and
actual retrieval modes, retrieval-profile and effective-configuration IDs, request
ID, status, warning count, truncation, omitted count, exact eligible count, derived
result status and `ranking_only` interpretation, elapsed milliseconds and cold or
warm timing classification. Successful responses retain returned paper/chunk IDs,
ranks, source provenance and component ranks/scores. Failed attempts store a bounded
failure category and elapsed time; exception messages are not copied. Hardware data
includes platform/CPU/Python facts, with optional RAM and accelerator measurements.
Random seed, experiment/comparison IDs and UTC start time are retained when supplied.

## Local and sanitized artifacts

`write_run_record` writes canonical compact JSON only below the ignored
`local-reference/phase2-runs/` directory. It creates private directories and files,
uses an atomic no-overwrite write, and rejects paths that resolve outside the
repository run directory. The writer never stores query text, evidence excerpts,
paper titles or free-text warnings/errors; those remain retrievable only through the
locally held calibration and source data. It does store source/result identities and
locations, so raw files still belong in ignored local storage and must not be copied
into a report or CI fixture.

`sanitized_run_summary` keeps experiment and benchmark lineage, hardware, timing,
status/counts and scores while omitting returned result identities and locations. Its
`raw_record_sha256` hashes the exact canonical bytes emitted by the writer, linking a
report summary to the local record. A report should include only examples already
cleared for sharing; use aggregate summaries otherwise.

## Evaluation runner

`research_platform.evaluation.runner.evaluate_calibration` is the async execution
entry point. Its `SearchService` protocol receives ordinary typed `SearchRequest`
values, so an adapter and a fake use the same boundary. The runner sends one paper
search and one evidence search for each canonical or paraphrase query, preserves
structured failures, and scores only when both responses are valid. Callers provide
the exact calibration/alignment file hashes, retrieval profile, source-region lookup,
and eligible paper IDs for metadata-filtered queries. The P2-05.5 suite exercises this
entry point with a deterministic fake and no corpus service.

The record schema version is `2`, which added the P2-11 eligibility count, result
status and ranking-only interpretation. Additive or incompatible persisted fields
require a schema-version decision and a reference update. Run IDs identify query runs;
attempt IDs identify individual requests. Writers refuse to overwrite an existing
record so reruns retain their own history.
