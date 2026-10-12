---
status: accepted
date: 2026-10-12
---

# Phase 5: which evidence text an external client may receive

Accepted by the project owner on 2026-10-12 in the Phase 5 planning interview
([owner decisions](../reference/phase-5-owner-decisions.md), Q6 and Q11). It is the first
decision on passage exposure since section 9.4 said "public passage exposure requires a
separate decision".

## Context

- Every paper in the corpus was stored and indexed under permission evidence that allows
  private local use. `passage_display_permitted` is false on all 102 document artifacts and
  all 103 rights reviews in `research_phase1_review` (checked 2026-10-12). The corpus includes
  CC BY-NC-ND and personal-use papers.
- The HTTP API returns passage text only under the server profile `trusted_private_local`,
  and `EvidenceAccessPolicy.can_display_public` returns false for every record.
- An external client such as Claude Code or Claude Desktop forwards tool results to its model
  provider. That is a new data boundary: text leaves the machine.
- Claim quotes in research answers are verbatim passage text.

## Decision

1. **Text exposure policy.** A server-wide setting, `RESEARCH_PLATFORM_MCP_TEXT_POLICY`:
   - `public_display_only` (default): MCP results carry passage text only where public display
     is permitted. Today that is never, because the access policy permits no public display.
   - `trusted_private_client`: MCP results carry the same text as private evidence inspection
     over HTTP. It is accepted only when the evidence access profile is
     `trusted_private_local` and the environment is not `production`; otherwise the API refuses
     to start.
   A request can never change the policy.
2. **What is withheld.** Under `public_display_only`:
   - search results keep identifiers, titles, years, ranks, scores, page and section, and set
     `text` to null with `text_withheld: true`; table cells are withheld with the text;
   - research run views keep the answer, claim text, evidence identifiers and paper metadata,
     and set each claim's `quote` to null. Claim text is model-written and bound by quote
     verification to its quote, so it is kept;
   - `get_paper` and the citation tools return metadata only, as over HTTP.
3. **The owner's private client.** The owner sets `trusted_private_client` only on their own
   laptop, for their own key and client, and records that this, including the client sending
   tool results to its model provider, is private non-commercial use. That is the owner's rights
   judgement, not a finding of this ADR.
4. **Per-paper public display later.** Where a paper's permission evidence one day allows public
   display, the access policy changes first; this ADR's default then exposes that paper's text
   without further change to the MCP adapter.

## Alternatives set aside

- **The HTTP rule unchanged:** treats a third-party model provider as private local inspection.
- **Never return text:** makes the owner's own client useless for reading evidence.
- **Short quotes only:** quotation exceptions vary by licence and jurisdiction; NC-ND forbids
  derivatives, not quotation, so this is no safer than the owner's explicit judgement.
- **A per-paper display reader now:** no paper permits display, so it would change nothing today.

## Consequences

- A fresh checkout and any deployed demo withhold all passage text from MCP clients by default.
- The Phase 5 security suite checks that no passage or quote text reaches an MCP result under the
  default policy.
- Turning on `trusted_private_client` is an owner action recorded in the decision record, not a
  code change.
