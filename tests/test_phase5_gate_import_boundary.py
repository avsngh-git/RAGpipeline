"""Architecture checks for the shared research capabilities boundary."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "research_platform"

FORBIDDEN_PREFIXES = (
    "asyncpg",
    "qdrant_client",
    "torch",
    "sentence_transformers",
    "langgraph",
    "research_platform.agents",
    "research_platform.llm",
    "research_platform.ingestion",
    "research_platform.runs.repository",
    "research_platform.runs.checkpointing",
    "research_platform.search.application",
    "research_platform.search.hybrid_search",
    "research_platform.search.dense_search",
    "research_platform.search.lexical",
    "research_platform.search.sparse_lexical",
    "research_platform.search.reranker",
    "research_platform.search.generation_search",
    "research_platform.tools.research_tools",
    "research_platform.api.routes",
    "research_platform.api.research_routes",
    "research_platform.api.ingestion_routes",
    "research_platform.api.app",
)

ALLOWED_EXCEPTIONS: dict[str, frozenset[str]] = {
    "research_platform.ingestion.indexing": frozenset({"SnapshotIndexMismatch"}),
    "research_platform.ingestion.evidence": frozenset(
        {"EvidenceKind", "EvidenceSourceSpan", "SourceLocation"}
    ),
    "research_platform.ingestion.identity": frozenset({"DocumentVersionKind"}),
    "research_platform.runs.repository": frozenset(
        {"RunNotFound", "InvalidRunTransition"}
    ),
}

DIRECT_SERVICE_METHODS = frozenset(
    {
        "execute",
        "read_paper",
        "read_one_hop",
        "find_related",
        "create_run",
        "get_run_view",
        "submit",
    }
)


@dataclass(frozen=True)
class ImportRecord:
    module: str
    imported_names: frozenset[str] | None


def _module_name(path: Path) -> str:
    relative = path.relative_to(SOURCE).with_suffix("")
    parts = ("research_platform", *relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def scan_source(source: str, module_name: str) -> tuple[ImportRecord, ...]:
    tree = ast.parse(source)
    package = (
        module_name
        if module_name.endswith(".__init__")
        else module_name.rpartition(".")[0]
    )
    records: list[ImportRecord] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            records.extend(ImportRecord(alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_name = "." * node.level + (node.module or "")
                imported_module = resolve_name(relative_name, package)
            else:
                imported_module = node.module or ""
            records.append(
                ImportRecord(
                    imported_module,
                    frozenset(alias.name for alias in node.names),
                )
            )
    return tuple(records)


def _is_forbidden(record: ImportRecord) -> bool:
    if record.module not in FORBIDDEN_PREFIXES and not any(
        record.module.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES
    ):
        return False
    allowed_names = ALLOWED_EXCEPTIONS.get(record.module)
    return not (
        allowed_names is not None
        and record.imported_names is not None
        and record.imported_names <= allowed_names
    )


def _scanned_files() -> tuple[Path, ...]:
    mcp_files = tuple(
        path for path in (SOURCE / "mcp").rglob("*.py") if path.name != "testing.py"
    )
    capability_files = tuple(
        SOURCE / "services" / f"{name}.py"
        for name in ("capabilities", "text_exposure", "citation_cursor", "errors")
    )
    return (*mcp_files, *capability_files)


def _direct_service_calls(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in DIRECT_SERVICE_METHODS:
            continue
        receiver = node.func.value
        is_capability = (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Name)
            and receiver.func.id == "capabilities"
        ) or (isinstance(receiver, ast.Attribute) and receiver.attr == "capabilities")
        if not is_capability:
            calls.append(node.func.attr)
    return tuple(calls)


def test_allowed_exceptions_are_name_limited() -> None:
    forbidden = scan_source(
        "from research_platform.runs.repository import RunRepository",
        "tests.synthetic",
    )
    allowed = scan_source(
        "from research_platform.runs.repository import RunNotFound",
        "tests.synthetic",
    )
    assert any(_is_forbidden(record) for record in forbidden)
    assert not any(_is_forbidden(record) for record in allowed)


def test_adapter_and_capabilities_import_no_infrastructure() -> None:
    violations = [
        f"{path.relative_to(ROOT)}: {record.module}"
        for path in _scanned_files()
        for record in scan_source(path.read_text(encoding="utf-8"), _module_name(path))
        if _is_forbidden(record)
    ]
    assert not violations, "Forbidden imports:\n" + "\n".join(violations)


def test_boundary_scan_finds_imports() -> None:
    records = {
        (_module_name(path), record.module)
        for path in _scanned_files()
        for record in scan_source(path.read_text(encoding="utf-8"), _module_name(path))
    }
    assert any(
        module_name.startswith("research_platform.mcp.")
        and imported_module == "research_platform.services.capabilities"
        for module_name, imported_module in records
    )
    assert (
        "research_platform.mcp.server",
        "mcp.server",
    ) in records


def test_http_routes_call_no_services_directly() -> None:
    route_files = (
        SOURCE / "api" / "routes.py",
        SOURCE / "api" / "research_routes.py",
    )
    for path in route_files:
        assert not _direct_service_calls(path), str(path)


def test_mcp_tools_do_not_reach_services_directly() -> None:
    tool_files = (
        SOURCE / "mcp" / "search_tools.py",
        SOURCE / "mcp" / "paper_tools.py",
        SOURCE / "mcp" / "run_tools.py",
    )
    for path in tool_files:
        assert not _direct_service_calls(path), str(path)
