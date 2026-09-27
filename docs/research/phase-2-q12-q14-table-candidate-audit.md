# P2-12.3 q12/q14 table-candidate source audit

**Reviewer:** assistant · **Date:** 2026-09-27 · **Scope:** visually checked pooled q12/q14 table cards and independently found table anchors. The separate origin maps were not opened.

## q12 — Document Segmentation Matters for Retrieval-Augmented Generation

The accepted PDF checksum is `6b159bd9266e22ef915f020d131cda2efb26949dd70cbbd94d586d63b3f3b6d7`; the local checksum-addressed artifact matches. The official [ACL PDF](https://aclanthology.org/2025.findings-acl.422.pdf) was rendered with a temporary PyMuPDF 1.28.2 tool installed under `/tmp`.

- Table 1 is on zero-based PDF page 4. It reports retrieval Hits@k and shows PIC above Proposition in the Average columns at both Top-5 (58.4 vs 57.7) and Top-20 (69.5 vs 68.9). No Table 1 row-group card exists in this pool; this remains an independently source-found anchor and is not inserted into retrieved rankings.
- Table 2 is on page 5. Its caption identifies Exact Match for end-to-end QA. Candidate `EV-8e2a672fb796964b` contains the Meta-Llama Proposition and PIC rows, including their average values (50.1/52.3 vs 51.0/53.5), and is direct support (label 2).
- `EV-1f5d397dd2e8c157` and `EV-b2b8f624c4f461dc` each contain only one side of the Qwen Proposition/PIC comparison. They are useful but incomplete support (label 1), not separate direct comparisons.
- PIC's average improves in the displayed retrieval and QA comparisons. This does not mean PIC wins every table cell: the visually checked Table 2 includes lower PIC values than Proposition for some SQuAD settings.

The private q12 review record maps the direct/incomplete row groups, updates the evidence requirement alternatives, and records the source-found Table 1 anchor. This table-specific visual audit judged six relevant row-group candidates. The subsequent full q12 candidate review resolved all 106 evidence and 16 paper candidates. The independently found Table 1 anchor remains outside the ranked pool, and the card gap remains disclosed.

## q14 — CodeRAG-Bench: Can Retrieval Augment Code Generation?

The accepted PDF checksum is `edc8bb5feee4b2ca802ae8a95bce8ba072f3a7b6b43ce0472730a8a97b9c266d`; the local checksum-addressed artifact matches. The official [ACL PDF](https://aclanthology.org/2025.findings-naacl.176.pdf) was rendered with the same temporary PyMuPDF tool.

- Table 1 is on zero-based page 2. Candidate `EV-2d4be5c5ea141ecf` maps to its overview rows and directly supports the benchmark's basic-programming, open-domain and repository-level task taxonomy (label 2).
- Table 2 on the same page is the direct retrieval-datastore inventory: programming solutions, online tutorials, library documentation, StackOverflow posts and GitHub files. No Table 2 candidate is in the pool, so it is recorded as an independent source-found anchor, not as a retrieved result.
- Four pooled row groups (`EV-acd2505eedf52027`, `EV-0efe6d8016a50480`, `EV-21a3133a672ab119`, `EV-c651a501b9a0acc3`) map to Table 6 on page 6. The table reports code-generation performance by task categories; these groups are useful context but do not enumerate the datastore sources (label 1).
- Table 7 compares retrieval-source performance and abbreviates the source columns; it is not the collection-inventory table. This corrects the earlier audit's conflation of Table 7 with the direct source list.

The private q14 review record includes the visually checked table judgments, a source-found Table 2 anchor, and a two-piece evidence requirement. This table-specific visual audit judged 13 relevant row-group candidates. The subsequent full q14 candidate review resolved all 107 evidence and 16 paper candidates. The source-list table is independent evidence and is not inserted into system rankings.

## Review limits

Rendered source pages confirmed table captions, row associations and the relevant headers. The records identify the accepted PDF checksum, local source and zero-based PDF page. This is assistant-only review, not independent human validation. Unjudged candidates remain unjudged; this audit does not infer scientific absence from pooled non-matches.

## Exact development alignment

**Reviewer:** assistant · **Date:** 2026-09-27 · **Alignment:**
phase2-development-source-alignment-v1. The scorer validates these coordinates
against the exact accepted extraction and PDF checksum before counting support.
Coordinates below are zero-based table row and column indexes.

- q12 Table 1 (source-found, page 4): target cells (6,13), (6,14), (7,13),
  (7,14). Each match also requires the Average header (0,13), Top-5/Top-20
  header (1,2), and its Proposition/PIC row label in column 0. This anchor was
  independently source-found and is not inserted into a ranked candidate pool.
- q12 Table 2 (candidate-linked, page 5): target cells (14,13), (14,14),
  (15,13), (15,14). Full support also requires the Average and Exact Match
  headers (0,13) and (1,2), the Meta-Llama group label (9,0), and both row
  labels (14,0) and (15,0). Matching may union the group-label evidence from a
  separate ranked row-group hit; one hit does not need to contain the whole table.
- q14 Table 1 (candidate-linked, page 2): target taxonomy cells (1,0), (2,0),
  (3,0) and the table header (0,0).
- q14 Table 2 (source-found, page 2): target cells (1,0) through (5,0) and
  the table header (0,0). The source-only anchor is evaluated independently and
  is not inserted into ranked candidates.

The checked-in source-alignment manifest has eight calibration table alignments and
an explicit empty prose-alignment list. Its two q12 table rows use the corrected
accepted extraction identity recorded by the calibration packet. Four q11–q19
development anchors (27 prose, 4 table) are scored alongside the ten calibration
families. The two source-found table anchors stay in the recall denominator but
never become system results. See the development report for denominators and the
small-pool limitations.
