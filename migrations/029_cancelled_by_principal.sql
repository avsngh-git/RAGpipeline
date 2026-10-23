-- Phase 6: a principal can cancel its own research run (ADR-0034).
ALTER TABLE research_runs DROP CONSTRAINT research_runs_failure_category_check;
ALTER TABLE research_runs ADD CONSTRAINT research_runs_failure_category_check
    CHECK (failure_category IN ('model_unavailable', 'invalid_model_output',
        'budget_exhausted', 'timeout', 'retrieval_error', 'resume_exhausted',
        'configuration_changed', 'internal', 'cancelled_by_principal'));
