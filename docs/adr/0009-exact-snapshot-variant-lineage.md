---
status: accepted
date: 2026-09-26
---

# Persist exact evidence selection and variant ancestry

A nullable chunk configuration cannot identify an immutable evidence set: it previously expanded to every chunk under an extraction, so a later rechunk could change a finalized snapshot. Persist selected chunk IDs per snapshot member, backfill existing snapshots using their prior selection rule, and make finalized selections immutable. A variant is a draft copied from a finalized parent, initially sharing its paper, document, extraction and exact chunks; record the parent snapshot and canonical parent selection identity, then allow only the draft's own selection to change. This keeps PostgreSQL authoritative and makes each derived index use an exact evidence set.
