# Phase 3.5 discovery report

Status: development-only Gate C measurement; reported, not gated.

The leave-out corpus excludes every directly judged paper from selected development families. OpenAlex search uses each question with wildcard punctuation removed; candidate ranking keeps the original question and uses the published leave-out generation.

| Measure | Result |
|---|---:|
| Selected development families | 10 |
| Families completed | 10 |
| Families with discovery errors | 0 |
| Mean hidden-paper recall@10 | 0.100 |
| Median hidden-paper recall@10 | 0.000 |
| Hidden-paper hits at 10 (with repeats) | 1 |
| Hits with a recorded permitted source route | 1 |
| OpenAlex search requests | 10 |
| OpenAlex search spend | $0.010 |

## Limitations

- This is a development-only diagnostic; it does not establish production discovery quality.
- The family sample is small and selected from tasks with direct-evidence paper judgments.
- Recall is based on OpenAlex work identifiers and a top-10 candidate limit; metrics are unavailable when every family fails.
- A recorded permitted route means stored permission evidence allows storage and indexing; it does not guarantee a new download will succeed.

Raw family-level inputs and outputs remain under `local-reference/phase35/` and are not part of this report.
