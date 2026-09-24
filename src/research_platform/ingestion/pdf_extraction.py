"""Optional Docling-backed extraction for permitted local PDF artifacts.

Docling is imported only when the adapter is used so the core package and CI
remain usable without the large PDF/model dependency set.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.resources
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from research_platform.ingestion.evidence import (
    COORDINATE_SYSTEM,
    ExtractedSection,
    ExtractedTable,
    ExtractionResult,
    SourceLocation,
    TableCell,
)

DoclingPipeline = Literal["standard", "granite-vlm"]
DOCLING_VERSION = "2.130.0"
GRANITE_DOCLING_REVISION = "982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe"
DOCLING_LAYOUT_REVISION = "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"
TABLEFORMER_REVISION = "v2.3.0"


@dataclass(frozen=True)
class DoclingPdfConfig:
    """Reproducible, locally executed PDF extraction configuration."""

    pipeline: DoclingPipeline = "standard"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    num_threads: int = 4
    expected_version: str = DOCLING_VERSION

    def __post_init__(self) -> None:
        if self.pipeline not in {"standard", "granite-vlm"}:
            raise ValueError("unsupported Docling PDF pipeline")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto, cpu or cuda")
        if (
            isinstance(self.num_threads, bool)
            or not isinstance(self.num_threads, int)
            or self.num_threads <= 0
        ):
            raise ValueError("num_threads must be a positive integer")
        if not isinstance(self.expected_version, str) or not self.expected_version:
            raise ValueError("expected_version must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "engine": "docling",
            "engine_version": self.expected_version,
            "pipeline": self.pipeline,
            "device": self.device,
            "num_threads": self.num_threads,
            "model_revisions": (
                {
                    "layout": {
                        "repo_id": "docling-project/docling-layout-heron",
                        "revision": DOCLING_LAYOUT_REVISION,
                    },
                    "table_structure": {
                        "repo_id": "docling-project/docling-models",
                        "revision": TABLEFORMER_REVISION,
                        "resolved_commit": "fc0f2d45e2218ea24bce5045f58a389aed16dc23",
                    },
                }
                if self.pipeline == "standard"
                else {
                    "vision_language_model": {
                        "repo_id": "ibm-granite/granite-docling-258M",
                        "revision": GRANITE_DOCLING_REVISION,
                        "license": "Apache-2.0",
                    }
                }
            ),
            "remote_services_enabled": False,
            "figure_interpretation": "caption-only; source PDF retained",
        }

    @property
    def configuration_id(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PdfExtractionError(RuntimeError):
    """Safe parser error that does not include source-controlled exception text."""

    def __init__(self, category: str) -> None:
        if not category or not category.replace("_", "").isalnum():
            raise ValueError("failure category must be a simple identifier")
        self.category = category
        super().__init__(f"PDF extraction failed; failure_category={category}")


class DoclingPdfExtractor:
    """Convert a PDF to source-linked sections and structured table cells."""

    def __init__(self, config: DoclingPdfConfig = DoclingPdfConfig()) -> None:
        self.config = config
        self._prepared_converter: tuple[Any, dict[str, object]] | None = None

    def prepare(self) -> tuple[dict[str, object], str]:
        """Load the pinned pipeline once and return its effective identity."""
        if self._prepared_converter is None:
            self._prepared_converter = self._build_converter()
        _converter, pipeline_options = self._prepared_converter
        configuration = self._effective_configuration(pipeline_options)
        return configuration, _configuration_id(configuration)

    def extract(
        self,
        pdf_path: Path,
        *,
        document_id: UUID,
        extraction_id: UUID,
        source_artifact_id: UUID | None = None,
    ) -> ExtractionResult:
        if not pdf_path.is_file():
            raise PdfExtractionError("source_artifact_missing")
        try:
            if self._prepared_converter is None:
                self._prepared_converter = self._build_converter()
            converter, pipeline_options = self._prepared_converter
            conversion = converter.convert(str(pdf_path))
        except PdfExtractionError:
            raise
        except Exception as error:
            # Do not expose a parser exception that might include document text.
            category = (
                "parser_unavailable"
                if isinstance(error, ImportError)
                else "parser_error"
            )
            raise PdfExtractionError(category) from None

        status_value = getattr(conversion.status, "value", conversion.status)
        if status_value != "success":
            raise PdfExtractionError("parser_partial")
        return self.result_from_document(
            conversion.document,
            document_id=document_id,
            extraction_id=extraction_id,
            source_artifact_id=source_artifact_id,
            pipeline_options=pipeline_options,
        )

    def result_from_document(
        self,
        document: Any,
        *,
        document_id: UUID,
        extraction_id: UUID,
        source_artifact_id: UUID | None = None,
        pipeline_options: Mapping[str, object] | None = None,
    ) -> ExtractionResult:
        """Translate a Docling document object; kept pure for adapter testing."""
        sections: list[ExtractedSection] = []
        tables: list[ExtractedTable] = []
        heading_path: tuple[str, ...] = ()
        current_heading_section: int | None = None

        for item, _tree_depth in document.iterate_items(
            with_groups=True, traverse_pictures=True
        ):
            label = _label(item)
            if label in {"page_header", "page_footer"}:
                continue
            if label == "section_header":
                heading_path = _updated_heading_path(heading_path, item)
                text = _text(item)
                if text:
                    sections.append(
                        ExtractedSection(
                            ordinal=len(sections),
                            heading_path=heading_path,
                            text=text,
                            source_location=_source_location(item, document),
                        )
                    )
                    current_heading_section = len(sections) - 1
                continue
            if label == "table":
                tables.append(
                    _convert_table(
                        item,
                        document,
                        ordinal=len(tables),
                        section_ordinal=current_heading_section,
                    )
                )
                continue
            if label in {"picture", "figure"}:
                caption = _caption_text(item, document)
                if caption:
                    sections.append(
                        ExtractedSection(
                            ordinal=len(sections),
                            heading_path=heading_path + ("Figure caption",),
                            text=caption,
                            source_location=_source_location(item, document),
                        )
                    )
                continue
            if label == "caption":
                # Table captions are repeated automatically in table row groups;
                # picture captions are emitted at their parent picture's position.
                continue

            text = _text(item)
            if text:
                item_heading_path = heading_path
                if label in {"formula", "equation"}:
                    item_heading_path += ("Equation",)
                sections.append(
                    ExtractedSection(
                        ordinal=len(sections),
                        heading_path=item_heading_path,
                        text=text,
                        source_location=_source_location(item, document),
                    )
                )

        if not sections and not tables:
            raise PdfExtractionError("no_usable_content")

        configuration = self._effective_configuration(pipeline_options)
        versions = configuration["dependencies"]
        if not isinstance(versions, dict):
            raise PdfExtractionError("parser_configuration_invalid")
        extractor_revision = ";".join(
            f"{name}=={version}" for name, version in sorted(versions.items())
        )
        configuration_id = _configuration_id(configuration)
        return ExtractionResult(
            document_id=document_id,
            extraction_id=extraction_id,
            source_artifact_id=source_artifact_id,
            extractor_name="docling",
            extractor_revision=extractor_revision,
            configuration_id=configuration_id,
            status="completed",
            sections=tuple(sections),
            tables=tuple(tables),
            configuration=configuration,
        )

    def _effective_configuration(
        self, pipeline_options: Mapping[str, object] | None
    ) -> dict[str, object]:
        configuration = self.config.to_dict()
        configuration["dependencies"] = _dependency_versions()
        if pipeline_options is not None:
            configuration["pipeline_options"] = dict(pipeline_options)
        configuration["model_asset_sha256s"] = (
            _rapidocr_asset_hashes() if self.config.pipeline == "standard" else {}
        )
        return configuration

    def _build_converter(self) -> tuple[Any, dict[str, object]]:
        try:
            accelerator_module = importlib.import_module(
                "docling.datamodel.accelerator_options"
            )
            base_models = importlib.import_module("docling.datamodel.base_models")
            pipeline_options = importlib.import_module(
                "docling.datamodel.pipeline_options"
            )
            converter_module = importlib.import_module("docling.document_converter")
            AcceleratorDevice = accelerator_module.AcceleratorDevice
            AcceleratorOptions = accelerator_module.AcceleratorOptions
            InputFormat = base_models.InputFormat
            PdfPipelineOptions = pipeline_options.PdfPipelineOptions
            LayoutObjectDetectionOptions = pipeline_options.LayoutObjectDetectionOptions
            VlmPipelineOptions = pipeline_options.VlmPipelineOptions
            DocumentConverter = converter_module.DocumentConverter
            PdfFormatOption = converter_module.PdfFormatOption
        except ImportError:
            raise PdfExtractionError("parser_unavailable") from None

        expected_packages = {
            "docling": self.config.expected_version,
            "docling-core": "2.98.0",
            "docling-ibm-models": "4.0.3",
            "docling-parse": "7.21.0",
            "rapidocr": "3.9.2",
        }
        if self.config.pipeline == "granite-vlm":
            expected_packages["transformers"] = "5.17.0"
        try:
            matches_expected = all(
                importlib.metadata.version(name) == version
                for name, version in expected_packages.items()
            )
        except importlib.metadata.PackageNotFoundError:
            matches_expected = False
        if not matches_expected:
            raise PdfExtractionError("parser_dependency_version_mismatch")

        device = {
            "auto": AcceleratorDevice.AUTO,
            "cpu": AcceleratorDevice.CPU,
            "cuda": AcceleratorDevice.CUDA,
        }[self.config.device]
        accelerator = AcceleratorOptions(
            num_threads=self.config.num_threads,
            device=device,
        )
        if self.config.pipeline == "standard":
            layout_defaults = LayoutObjectDetectionOptions()
            pinned_layout_model = layout_defaults.model_spec.model_copy(
                update={"revision": DOCLING_LAYOUT_REVISION}
            )
            pinned_layout = layout_defaults.model_copy(
                update={"model_spec": pinned_layout_model}
            )
            options = PdfPipelineOptions(
                layout_options=pinned_layout,
                accelerator_options=accelerator,
                enable_remote_services=False,
                generate_page_images=False,
                generate_picture_images=False,
                generate_table_images=False,
            )
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=options)
                }
            )
            return converter, _json_options(options)

        vlm_model_specs = importlib.import_module("docling.datamodel.vlm_model_specs")
        vlm_pipeline = importlib.import_module("docling.pipeline.vlm_pipeline")
        VlmPipeline = vlm_pipeline.VlmPipeline
        model = vlm_model_specs.GRANITEDOCLING_TRANSFORMERS.model_copy(
            update={"revision": GRANITE_DOCLING_REVISION}
        )
        options = VlmPipelineOptions(
            accelerator_options=accelerator,
            enable_remote_services=False,
            generate_page_images=False,
            generate_picture_images=False,
            vlm_options=model,
        )
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=VlmPipeline,
                    pipeline_options=options,
                )
            }
        )
        return converter, _json_options(options)


def tables_requiring_vision_review(
    extraction: ExtractionResult,
) -> tuple[int, ...]:
    """Return sparse, multi-header tables for optional VLM-assisted review.

    The rule is a pilot heuristic measured on the ten reviewed PDFs. Its output
    requests review; it never causes VLM cells to replace the structured table.
    """
    flagged: list[int] = []
    for table in extraction.tables:
        total = table.row_count * table.column_count
        if total == 0:
            continue
        blank_count = sum(not cell.text.strip() for cell in table.cells)
        blank_fraction = blank_count / total
        if table.header_rows >= 2 and blank_fraction >= 0.20:
            flagged.append(table.ordinal)
    return tuple(flagged)


def _convert_table(
    item: Any,
    document: Any,
    *,
    ordinal: int,
    section_ordinal: int | None,
) -> ExtractedTable:
    data = item.data
    grid = data.grid
    row_count = int(data.num_rows)
    column_count = int(data.num_cols)
    if len(grid) != row_count or any(len(row) != column_count for row in grid):
        raise PdfExtractionError("invalid_table_grid")

    owner_by_coordinate: dict[tuple[int, int], Any | None] = {}
    owner_coordinate: dict[tuple[int, int], tuple[int, int]] = {}
    for row_index, row in enumerate(grid):
        for column_index, cell in enumerate(row):
            owner_by_coordinate[(row_index, column_index)] = cell
            if cell is None:
                owner_coordinate[(row_index, column_index)] = (
                    row_index,
                    column_index,
                )
                continue
            start_row = int(cell.start_row_offset_idx)
            start_column = int(cell.start_col_offset_idx)
            owner_coordinate[(row_index, column_index)] = (start_row, start_column)

    converted_cells: list[TableCell] = []
    header_rows = 0
    for row_index in range(row_count):
        if any(
            bool(getattr(cell, "column_header", False))
            for cell in grid[row_index]
            if cell is not None
        ):
            if row_index == header_rows:
                header_rows += 1
        else:
            break

    for row_index in range(row_count):
        for column_index in range(column_count):
            raw_cell = owner_by_coordinate[(row_index, column_index)]
            if raw_cell is None:
                converted_cells.append(
                    TableCell(row=row_index, column=column_index, text="")
                )
                continue
            start_row = int(raw_cell.start_row_offset_idx)
            end_row = int(raw_cell.end_row_offset_idx)
            start_column = int(raw_cell.start_col_offset_idx)
            end_column = int(raw_cell.end_col_offset_idx)
            owner = (start_row, start_column)
            is_owner = (row_index, column_index) == owner
            merged_range = None
            if end_row - start_row > 1 or end_column - start_column > 1:
                merged_range = (
                    start_row,
                    start_column,
                    end_row - 1,
                    end_column - 1,
                )

            row_headers = {
                owner_coordinate[(row_index, prior_column)]
                for prior_column in range(column_index)
                if grid[row_index][prior_column] is not None
                and bool(getattr(grid[row_index][prior_column], "row_header", False))
            }
            column_headers = {
                owner_coordinate[(prior_row, column_index)]
                for prior_row in range(row_index)
                if grid[prior_row][column_index] is not None
                and bool(getattr(grid[prior_row][column_index], "column_header", False))
            }
            row_headers.discard(owner)
            column_headers.discard(owner)
            converted_cells.append(
                TableCell(
                    row=row_index,
                    column=column_index,
                    text=_text(raw_cell) if is_owner else "",
                    row_header_cells=tuple(sorted(row_headers)),
                    column_header_cells=tuple(sorted(column_headers)),
                    merged_range=merged_range,
                )
            )

    caption = _caption_text(item, document) or None
    footnotes = _footnotes(item, document)
    return ExtractedTable(
        ordinal=ordinal,
        caption=caption,
        units=None,
        footnotes=footnotes,
        header_rows=header_rows,
        cells=tuple(converted_cells),
        source_location=_source_location(item, document),
        section_ordinal=section_ordinal,
    )


def _source_location(item: Any, document: Any) -> SourceLocation:
    provenance = getattr(item, "prov", None) or ()
    if not provenance:
        return SourceLocation()
    record = provenance[0]
    page_number = getattr(record, "page_no", None)
    if (
        isinstance(page_number, bool)
        or not isinstance(page_number, int)
        or page_number < 1
    ):
        return SourceLocation()

    page = getattr(document, "pages", {}).get(page_number)
    page_size = getattr(page, "size", None)
    width = getattr(page_size, "width", None)
    height = getattr(page_size, "height", None)
    bbox = getattr(record, "bbox", None)
    if (
        not isinstance(width, (int, float))
        or not isinstance(height, (int, float))
        or width <= 0
        or height <= 0
        or bbox is None
    ):
        return SourceLocation(page_index_zero_based=page_number - 1)

    left = float(bbox.l) / float(width)
    right = float(bbox.r) / float(width)
    top_raw = float(bbox.t)
    bottom_raw = float(bbox.b)
    origin = getattr(getattr(bbox, "coord_origin", None), "value", "TOPLEFT")
    if origin == "BOTTOMLEFT":
        top = (float(height) - top_raw) / float(height)
        bottom = (float(height) - bottom_raw) / float(height)
    else:
        top = top_raw / float(height)
        bottom = bottom_raw / float(height)
    normalized = tuple(
        max(0.0, min(1.0, value)) for value in (left, top, right, bottom)
    )
    x1, y1, x2, y2 = normalized
    if x1 >= x2 or y1 >= y2:
        return SourceLocation(page_index_zero_based=page_number - 1)
    return SourceLocation(
        page_index_zero_based=page_number - 1,
        bounding_box=(x1, y1, x2, y2),
        coordinate_system=COORDINATE_SYSTEM,
    )


def _updated_heading_path(previous: tuple[str, ...], item: Any) -> tuple[str, ...]:
    title = _text(item)
    if not title:
        return previous
    level = getattr(item, "level", None)
    if isinstance(level, bool) or not isinstance(level, int) or level < 1:
        level = len(previous) + 1
    return previous[: level - 1] + (title,)


def _caption_text(item: Any, document: Any) -> str:
    method = getattr(item, "caption_text", None)
    if callable(method):
        value = method(document)
        if isinstance(value, str):
            return _clean_text(value)
    captions = getattr(item, "captions", ()) or ()
    resolved: list[str] = []
    for reference in captions:
        caption = _resolve_reference(reference, document)
        text = _text(caption)
        if text:
            resolved.append(text)
    return _clean_text(" ".join(resolved))


def _footnotes(item: Any, document: Any) -> tuple[str, ...]:
    method = getattr(item, "footnote_text", None)
    if callable(method):
        value = method(document)
        if isinstance(value, str):
            cleaned = _clean_text(value)
            if cleaned:
                return tuple(
                    line.strip() for line in cleaned.splitlines() if line.strip()
                )
    notes: list[str] = []
    for reference in getattr(item, "footnotes", ()) or ():
        note = _text(_resolve_reference(reference, document))
        if note:
            notes.append(note)
    return tuple(notes)


def _resolve_reference(reference: Any, document: Any) -> Any:
    resolver = getattr(reference, "resolve", None)
    if not callable(resolver):
        raise PdfExtractionError("invalid_document_reference")
    try:
        return resolver(doc=document)
    except Exception:
        raise PdfExtractionError("invalid_document_reference") from None


def _text(item: Any) -> str:
    value = getattr(item, "text", "")
    return _clean_text(value) if isinstance(value, str) else ""


def _clean_text(value: str) -> str:
    """Remove NUL sentinels emitted by PDF text extraction.

    PostgreSQL text and JSONB cannot represent U+0000. It is not printable PDF
    content, so discard it at the source-adapter boundary before chunking.
    """
    return value.replace("\x00", "").strip()


def _configuration_id(configuration: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(configuration), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _label(item: Any) -> str:
    label = getattr(item, "label", "")
    value = getattr(label, "value", label)
    return value if isinstance(value, str) else ""


def _json_options(options: Any) -> dict[str, object]:
    serialized = options.model_dump(mode="json", exclude_none=True)
    if not isinstance(serialized, dict):
        raise PdfExtractionError("invalid_parser_configuration")
    serialized.pop("artifacts_path", None)
    return serialized


def _rapidocr_asset_hashes() -> dict[str, str]:
    """Fingerprint packaged OCR weights without retaining or printing them."""
    try:
        model_directory = importlib.resources.files("rapidocr").joinpath("models")
        assets = sorted(
            (
                asset
                for asset in model_directory.iterdir()
                if asset.name.endswith(".onnx")
            ),
            key=lambda asset: asset.name,
        )
    except (ImportError, ModuleNotFoundError, FileNotFoundError):
        return {}

    fingerprints: dict[str, str] = {}
    for asset in assets:
        digest = hashlib.sha256()
        with asset.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        fingerprints[asset.name] = digest.hexdigest()
    return fingerprints


def _dependency_versions() -> dict[str, str]:
    names = ("docling", "docling-core", "docling-ibm-models", "docling-parse")
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions
