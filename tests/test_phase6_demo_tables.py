"""Pure checks for the public demo database allowlist."""

from __future__ import annotations

import re

from research_platform.demo.database import DEMO_TABLES, EXCLUDED_TABLES


def test_table_names_are_unique_and_disjoint() -> None:
    names = [table.name for table in DEMO_TABLES]

    assert len(names) == 36
    assert len(names) == len(set(names))
    assert set(names).isdisjoint(EXCLUDED_TABLES)


def test_every_query_reads_its_own_table() -> None:
    for table in DEMO_TABLES:
        assert re.search(rf"\bFROM\s+{re.escape(table.name)}\b", table.query)


def test_parameters_are_consistent() -> None:
    for table in DEMO_TABLES:
        assert "$2" not in table.query or "$1" in table.query
        assert "$3" not in table.query


def test_parents_come_before_children() -> None:
    positions = {table.name: index for index, table in enumerate(DEMO_TABLES)}

    assert positions["papers"] < positions["documents"]
    assert positions["documents"] < positions["document_artifacts"]
    assert positions["document_artifacts"] < positions["extractions"]
    assert positions["extractions"] < positions["chunks"]
    assert positions["chunks"] < positions["snapshot_items"]
    assert positions["snapshot_items"] < positions["snapshot_item_chunks"]
    assert positions["collections"] < positions["index_generations"]
    assert positions["index_generations"] < positions["index_generation_pointers"]
    assert positions["research_runs"] < positions["claims"]
    assert positions["claims"] < positions["claim_evidence"]
