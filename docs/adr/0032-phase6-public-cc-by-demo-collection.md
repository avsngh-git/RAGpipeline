---
status: accepted
date: 2026-10-13
---

# Phase 6: the accepted corpus becomes a public CC BY demo collection

Accepted by the project owner on 2026-10-13 in the Phase 6 planning interview
([owner decisions](../reference/phase-6-owner-decisions.md), Q2 and Q8). It amends the
"passage display off" choice that [ADR-0031](0031-phase5-external-passage-exposure.md) builds on.

## Context

- A reviewer must be able to clone the repository, run a small mode and see the system work
  without private knowledge (source of truth section 21, Phase 6 gate). The product's main claim
  is claim → quote → passage → paper provenance; a demo that withholds the passage cannot show it.
- The accepted 100-paper snapshot `4b11fab3-d4a5-4e7a-a58e-8654accf2c6c` is CC BY throughout.
  In `research_phase1_review` (checked 2026-10-13) all 103 rows of `document_permission_evidence`
  (102 documents) carry `license_id = 'cc-by'`: 99 from OpenAlex `best_oa_location` licence
  metadata, most with a recorded source terms URL (ACL Anthology, TACL, Springer, MDPI and others),
  and 3 from pinned arXiv CC BY 4.0 records. `passage_display_permitted` is false on every row
  because the owner had not approved display, not because a licence forbids it.
- **Correction to ADR-0031's context:** it says the corpus includes CC BY-NC-ND and personal-use
  papers. Those are the six follow-up files acquired on 2026-09-25, which were never associated with
  a snapshot. The accepted snapshot contains none of them.
- CC BY 4.0 permits copying and redistribution, including of excerpts, with attribution: credit,
  a link to the licence, and an indication of changes.
- OpenAlex metadata (titles, authors, abstracts' inverted indexes, citations) is CC0.

## Decision

1. **The accepted snapshot is the public demo collection.** Its text, evidence units, chunks,
   Qdrant payloads and the selected showcase research runs may be redistributed in a public
   **demo bundle** attached to a GitHub Release, and shown in the UI, the recorded video and
   documentation.
2. **Display is recorded per document, not assumed.** Before export, a reviewed display decision
   is recorded for every document artifact reachable from the accepted snapshot's 100 paper
   members (currently 102 source documents): the reviewer opens the recorded terms URL (or the
   pinned arXiv record) and confirms a CC BY licence on that exact version. For each confirmed
   document a new `document_permission_evidence` row is inserted with
   `passage_display_permitted = true`, a `permission_basis` naming the checked URL, and the reviewer
   `assistant acting under explicit user delegation (ADR-0032)`. The matching `document_artifacts`
   row is repointed to it and its `passage_display_permitted` set to true. A document that cannot be
   confirmed stays non-displayable and blocks the export until the owner decides.
3. **The exporter enforces it.** The bundle exporter refuses to export a snapshot unless every
   selected document's artifact and permission evidence both have `passage_display_permitted = true`
   and a `license_id` in `cc-by`, `cc0` or `public-domain`.
4. **Attribution.** The bundle carries `ATTRIBUTION.md`, generated from the database: for each paper
   its title, authors, year, DOI or source URL, licence and licence URL, and the statement that
   passages are extracted and chunked excerpts (changes indicated). The README and the UI link to it.
   The README includes a takedown contact for embedded third-party material.
5. **The private corpus remains private where it is private.** The six follow-up files, the
   leave-out collections, discovery records, model-call payloads, checkpoints, experiments, API keys
   and development benchmark questions are never exported (ADR-0033 decision 4).
6. **Serving is unchanged.** No per-paper public-display reader is added to the access policy. A
   reviewer runs the bundle on their own machine with the existing `trusted_private_local` profile.
   The MCP text policy default (`public_display_only`) stays; a hosted demo would need the
   per-paper reader that ADR-0031 decision 4 anticipates.

## Alternatives set aside

- **A smaller CC BY subset** of 10–30 papers: the benchmark numbers would describe a different
  corpus than the demo.
- **Bundle without text** (metadata, claims and handles only): hides the provenance the project is
  about.
- **Trusting OpenAlex licence metadata without a per-document check:** OpenAlex licence fields are
  occasionally wrong; one reviewed check per document is cheap.

## Consequences

- The demo bundle and the recorded video show real passages with attribution.
- Embedded third-party figures or tables inside a CC BY paper may carry other terms. Figures are not
  interpreted or exported as images (Phase 1 policy), table text is; the takedown note covers the
  residual risk.
- Online ingestion keeps `passage_display_permitted = false` for new papers (ADR-0024); they are not
  part of the bundle.
