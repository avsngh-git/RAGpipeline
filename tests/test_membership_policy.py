"""Decision rules of the ingestion membership policy (P35-26)."""

from __future__ import annotations

from research_platform.config import DiscoverySettings
from research_platform.ingestion.membership_policy import _Candidate, decide

SETTINGS = DiscoverySettings()


def _decide(candidate: _Candidate, *, duplicate=False, accepted=0, maximum=5):
    return decide(
        "W1",
        candidate,
        settings=SETTINGS,
        duplicate=duplicate,
        accepted_for_run=accepted,
        max_papers=maximum,
    ).reason


def test_reasons_follow_the_fixed_order() -> None:
    # Every rule would refuse; the first one in the order wins.
    everything = _Candidate(in_papers=False, indexed=True, year=2010, language="de")
    assert _decide(everything, duplicate=True, accepted=5) == "unknown_paper"
    indexed = _Candidate(in_papers=True, indexed=True, year=2010, language="de")
    assert _decide(indexed, duplicate=True, accepted=5) == "already_indexed"
    old = _Candidate(in_papers=True, indexed=False, year=2010, language="de")
    assert _decide(old, duplicate=True, accepted=5) == "out_of_scope_year"
    german = _Candidate(in_papers=True, indexed=False, year=2024, language="de")
    assert _decide(german, duplicate=True, accepted=5) == "out_of_scope_language"
    fine = _Candidate(in_papers=True, indexed=False, year=2024, language="en")
    assert _decide(fine, duplicate=True, accepted=5) == "duplicate_request"
    assert _decide(fine, accepted=5) == "run_paper_limit"
    assert _decide(fine, accepted=4) == "accepted"


def test_unknown_year_and_language_are_not_refused() -> None:
    unknown = _Candidate(in_papers=True, indexed=False, year=None, language=None)
    assert _decide(unknown) == "accepted"


def test_run_limit_counts_earlier_acceptances() -> None:
    import asyncio
    from uuid import uuid4

    from research_platform.tools.fakes import FakeIngestionPolicy

    catalog = {f"W{i}": (False, 2024, "en") for i in range(4)}
    policy = FakeIngestionPolicy(catalog)
    run_id = uuid4()

    first = asyncio.run(
        policy.submit(
            run_id=run_id, requested_by="run", paper_ids=["W0", "W1"], max_papers=3
        )
    )
    second = asyncio.run(
        policy.submit(
            run_id=run_id, requested_by="run", paper_ids=["W2", "W3"], max_papers=3
        )
    )

    assert [d.reason for d in first.decisions] == ["accepted", "accepted"]
    assert [d.reason for d in second.decisions] == ["accepted", "run_paper_limit"]
