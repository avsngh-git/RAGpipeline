"""Fast checks for LangGraph checkpoint configuration helpers."""

from uuid import UUID

from psycopg.conninfo import conninfo_to_dict

from research_platform.runs.checkpointing import checkpoint_conninfo, thread_config


def test_conninfo_sets_search_path_and_keeps_credentials() -> None:
    for database_url in (
        "postgresql://research:secret@localhost:5432/research_test",
        "postgresql://research:secret@localhost:5432/research_test?sslmode=disable",
    ):
        conninfo = conninfo_to_dict(checkpoint_conninfo(database_url))

        assert conninfo["user"] == "research"
        assert conninfo["password"] == "secret"
        assert conninfo["host"] == "localhost"
        assert conninfo["dbname"] == "research_test"
        assert conninfo["options"] == "-c search_path=langgraph"
        if "?" in database_url:
            assert conninfo["sslmode"] == "disable"


def test_thread_config_uses_run_id() -> None:
    run_id = UUID("2e0d7d17-926c-4e7e-a679-837fb723c669")

    assert thread_config(run_id) == {"configurable": {"thread_id": str(run_id)}}
