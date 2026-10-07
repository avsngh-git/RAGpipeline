-- Phase 4: a drafted claim that failed its checks may be kept as its verified quote.
ALTER TABLE draft_claims DROP CONSTRAINT draft_claims_verdict_check;
ALTER TABLE draft_claims ADD CONSTRAINT draft_claims_verdict_check
    CHECK (verdict IN ('kept', 'kept_as_quote', 'unknown_handle', 'not_shown', 'failed_checks'));
