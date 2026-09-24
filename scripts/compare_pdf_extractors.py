"""Compare Docling PDF pipelines on the human-reviewed reference pages.

Full document text and serialized parser output are written only under the
Git-ignored ``local-reference/`` directory. Console output contains IDs and
measurements, never extracted text. Pages use PDF positions numbered from 1.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.resources
import json
import os
import resource
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil
import torch
from docling.datamodel import vlm_model_specs
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, VlmPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.vlm_pipeline import VlmPipeline
from huggingface_hub import HfApi
from pypdfium2 import PdfDocument

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANNOTATION_DIR = (
    REPOSITORY_ROOT / "local-reference/phase1-discovery-v1/draft-annotations"
)
ACQUISITION_FILE = (
    REPOSITORY_ROOT / "manifests/phase1-discovery-v1-pdf-acquisition.json"
)
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "local-reference/phase1-discovery-v1/comparison"
EXPECTED_DOCLING_VERSION = "2.130.0"
DOCLING_LAYOUT_REVISION = "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"
EXPECTED_REFERENCE_COUNT = 10


@dataclass(frozen=True)
class ReferencePaper:
    openalex_id: str
    pdf_path: Path
    source_sha256: str
    source_bytes: int
    page_count: int
    reviewed_page_numbers: tuple[int, ...]


class PeakRssSampler:
    """Sample process RSS while a parser pipeline is running."""

    def __init__(self) -> None:
        self._process = psutil.Process()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._peak_bytes = self._process.memory_info().rss
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.wait(0.1):
            current = self._process.memory_info().rss
            with self._lock:
                self._peak_bytes = max(self._peak_bytes, current)

    def start(self) -> None:
        self._thread.start()

    def checkpoint(self) -> int:
        current = self._process.memory_info().rss
        with self._lock:
            self._peak_bytes = max(self._peak_bytes, current)
            return self._peak_bytes

    def stop(self) -> int:
        self._stop.set()
        self._thread.join()
        return self.checkpoint()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    content = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )
    atomic_write(path, content + b"\n")


def load_reference_set() -> list[ReferencePaper]:
    inventory = json.loads(ACQUISITION_FILE.read_text(encoding="utf-8"))
    if inventory.get("approval", {}).get("status") != "approved":
        raise RuntimeError("The PDF acquisition inventory is not approved")
    acquired = {item["openalex_id"]: item for item in inventory["items"]}
    annotation_paths = sorted(ANNOTATION_DIR.glob("W*.json"))
    if len(annotation_paths) != EXPECTED_REFERENCE_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_REFERENCE_COUNT} reviewed annotations; found {len(annotation_paths)}"
        )

    papers: list[ReferencePaper] = []
    for annotation_path in annotation_paths:
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        openalex_id = annotation_path.stem
        if annotation.get("record_status") != "human_verified" or not annotation.get(
            "review_complete"
        ):
            raise RuntimeError(f"Reference {openalex_id} is not human-verified")
        item = acquired.get(openalex_id)
        if item is None or item.get("result") != "acquired":
            raise RuntimeError(f"Reference {openalex_id} has no acquired PDF")
        if not item.get("storage_permitted") or not item.get("indexing_permitted"):
            raise RuntimeError(
                f"Reference {openalex_id} lacks local processing permission"
            )
        if item.get("passage_display_permitted"):
            raise RuntimeError(
                f"Reference {openalex_id} unexpectedly permits public passage display"
            )

        zero_based_pages = {
            section["page_index_zero_based"] for section in annotation["sections"]
        }
        for table in annotation["tables"]:
            zero_based_pages.update(table["page_indices_zero_based"])
        if not zero_based_pages:
            raise RuntimeError(
                f"Reference {openalex_id} has no reviewed evidence pages"
            )
        reviewed_page_numbers = tuple(sorted(page + 1 for page in zero_based_pages))

        pdf_path = REPOSITORY_ROOT / "data/artifacts" / item["storage_path"]
        if not pdf_path.is_file():
            raise FileNotFoundError(
                f"The approved local PDF is missing for {openalex_id}"
            )
        digest = sha256_file(pdf_path)
        if digest != item["sha256"] or pdf_path.stat().st_size != item["byte_size"]:
            raise RuntimeError(
                f"The approved PDF checksum or size changed for {openalex_id}"
            )
        with PdfDocument(str(pdf_path)) as pdf:
            page_count = len(pdf)
        if any(
            page_number < 1 or page_number > page_count
            for page_number in reviewed_page_numbers
        ):
            raise RuntimeError(
                f"A reviewed page is outside the source PDF for {openalex_id}"
            )
        papers.append(
            ReferencePaper(
                openalex_id=openalex_id,
                pdf_path=pdf_path,
                source_sha256=digest,
                source_bytes=pdf_path.stat().st_size,
                page_count=page_count,
                reviewed_page_numbers=reviewed_page_numbers,
            )
        )
    return papers


def build_converter(pipeline: str) -> tuple[DocumentConverter, dict[str, Any]]:
    accelerator = AcceleratorOptions(num_threads=4, device=AcceleratorDevice.CUDA)
    if pipeline == "standard":
        layout_defaults = PdfPipelineOptions().layout_options
        pinned_layout_model = layout_defaults.model_spec.model_copy(
            update={"revision": DOCLING_LAYOUT_REVISION}
        )
        pinned_layout = layout_defaults.model_copy(
            update={"model_spec": pinned_layout_model}
        )
        options = PdfPipelineOptions(
            layout_options=pinned_layout,
            accelerator_options=accelerator,
            generate_page_images=False,
            generate_picture_images=False,
        )
        options_dict = options.model_dump(mode="json", exclude_none=True)
        options_dict.pop("artifacts_path", None)
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        return converter, {
            "pipeline": "Docling StandardPdfPipeline",
            "options": options_dict,
            "model_revisions": {
                "layout": {
                    "repo_id": "docling-project/docling-layout-heron",
                    "revision": DOCLING_LAYOUT_REVISION,
                },
                "table_structure": {
                    "repo_id": "docling-project/docling-models",
                    "revision": "v2.3.0",
                },
            },
        }

    model_info = HfApi().model_info("ibm-granite/granite-docling-258M", revision="main")
    model_revision = model_info.sha
    model_options = vlm_model_specs.GRANITEDOCLING_TRANSFORMERS.model_copy(
        update={"revision": model_revision}
    )
    options = VlmPipelineOptions(
        accelerator_options=accelerator,
        generate_page_images=False,
        generate_picture_images=False,
        vlm_options=model_options,
    )
    options_dict = options.model_dump(mode="json", exclude_none=True)
    options_dict.pop("artifacts_path", None)
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=VlmPipeline,
                pipeline_options=options,
            )
        }
    )
    return converter, {
        "pipeline": "Docling VlmPipeline",
        "options": options_dict,
        "model_repo_id": "ibm-granite/granite-docling-258M",
        "model_revision": model_revision,
        "model_license": "Apache-2.0",
    }


def dependency_versions(pipeline: str) -> dict[str, str]:
    names = [
        "docling",
        "docling-core",
        "docling-ibm-models",
        "docling-parse",
        "torch",
        "transformers",
    ]
    if pipeline == "standard":
        names.append("rapidocr")
    return {name: importlib.metadata.version(name) for name in names}


def rapidocr_asset_fingerprints() -> dict[str, str]:
    model_directory = importlib.resources.files("rapidocr").joinpath("models")
    fingerprints: dict[str, str] = {}
    for asset in sorted(
        (
            item
            for item in model_directory.iterdir()
            if item.suffix in {".onnx", ".pth"}
        ),
        key=lambda item: item.name,
    ):
        digest = hashlib.sha256()
        with asset.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        fingerprints[asset.name] = digest.hexdigest()
    return fingerprints


def reusable_page(
    record_path: Path,
    output_dir: Path,
    paper: ReferencePaper,
    page_number: int,
    config_id: str,
) -> dict[str, Any] | None:
    if not record_path.is_file():
        return None
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if (
        record.get("status") != "success"
        or record.get("config_id") != config_id
        or record.get("source_sha256") != paper.source_sha256
        or record.get("page_number_1_based") != page_number
    ):
        return None
    for output in record.get("outputs", {}).values():
        path = output_dir / output["path"]
        if not path.is_file() or sha256_file(path) != output["sha256"]:
            return None
    return record


def run(args: argparse.Namespace) -> int:
    if not torch.cuda.is_available():
        raise RuntimeError("The comparison profile requires the available CUDA GPU")
    if importlib.metadata.version("docling") != EXPECTED_DOCLING_VERSION:
        raise RuntimeError(
            f"Install pinned Docling {EXPECTED_DOCLING_VERSION} for this run"
        )

    output_root = args.output_root.resolve()
    try:
        output_root.relative_to((REPOSITORY_ROOT / "local-reference").resolve())
    except ValueError as error:
        raise ValueError(
            "Full parser output must remain under Git-ignored local-reference/"
        ) from error
    pipeline_suffix = (
        "standard-reviewed-pages"
        if args.pipeline == "standard"
        else "granite-vlm-reviewed-pages"
    )
    output_dir = output_root / pipeline_suffix
    papers = load_reference_set()
    if args.limit is not None:
        papers = papers[: args.limit]

    started_at = datetime.now(UTC).isoformat()
    run_started = time.perf_counter()
    sampler = PeakRssSampler()
    sampler.start()
    converter, pipeline_config = build_converter(args.pipeline)
    versions = dependency_versions(args.pipeline)
    config = {
        "schema_version": 1,
        "docling_version": versions["docling"],
        "dependencies": versions,
        "python_version": sys.version,
        "device": torch.cuda.get_device_name(0),
        "cuda_runtime": torch.version.cuda,
        "num_threads": 4,
        "page_selection": "only pages annotated in the human-verified P1-07 reference set",
        "page_range_api": "one inclusive, 1-based PDF page per conversion",
        "pipeline_config": pipeline_config,
        "model_asset_sha256s": (
            rapidocr_asset_fingerprints() if args.pipeline == "standard" else {}
        ),
    }
    config_id = canonical_hash(config)
    paper_records: list[dict[str, Any]] = []
    resumed_pages = 0
    processed_pages = 0
    failures = 0

    for paper in papers:
        page_records: list[dict[str, Any]] = []
        for page_number in paper.reviewed_page_numbers:
            page_dir = output_dir / paper.openalex_id / f"page-{page_number:04d}"
            record_path = page_dir / "record.json"
            cached = (
                reusable_page(record_path, output_dir, paper, page_number, config_id)
                if args.resume
                else None
            )
            if cached is not None:
                resumed_pages += 1
                page_records.append(cached)
                print(f"{paper.openalex_id} page {page_number}: reused checked output")
                continue

            processed_pages += 1
            started = time.perf_counter()
            try:
                torch.cuda.reset_peak_memory_stats()
                result = converter.convert(
                    str(paper.pdf_path), page_range=(page_number, page_number)
                )
                torch.cuda.synchronize()
                document = result.document
                document_json = json.dumps(
                    document.export_to_dict(), ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                markdown = document.export_to_markdown().encode("utf-8")
                json_path = page_dir / "document.json"
                markdown_path = page_dir / "document.md"
                atomic_write(json_path, document_json)
                atomic_write(markdown_path, markdown)
                elapsed = time.perf_counter() - started
                conversion_status = getattr(result.status, "value", str(result.status))
                page_status = "success" if conversion_status == "success" else "partial"
                record = {
                    "openalex_id": paper.openalex_id,
                    "page_number_1_based": page_number,
                    "status": page_status,
                    "conversion_status": conversion_status,
                    "source_sha256": paper.source_sha256,
                    "source_bytes": paper.source_bytes,
                    "source_page_count": paper.page_count,
                    "config_id": config_id,
                    "elapsed_seconds": round(elapsed, 3),
                    "rss_high_water_bytes_so_far": sampler.checkpoint(),
                    "gpu_memory": {
                        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                    },
                    "document_item_counts": {
                        "texts": len(document.texts),
                        "tables": len(document.tables),
                        "pictures": len(document.pictures),
                    },
                    "parser_error_count": len(result.errors),
                    "document_page_numbers": sorted(document.pages),
                    "outputs": {
                        "document_json": {
                            "path": f"{paper.openalex_id}/page-{page_number:04d}/document.json",
                            "bytes": len(document_json),
                            "sha256": hashlib.sha256(document_json).hexdigest(),
                        },
                        "document_markdown": {
                            "path": f"{paper.openalex_id}/page-{page_number:04d}/document.md",
                            "bytes": len(markdown),
                            "sha256": hashlib.sha256(markdown).hexdigest(),
                        },
                    },
                }
                if page_status != "success":
                    failures += 1
                del result, document
                page_records.append(record)
                print(
                    f"{paper.openalex_id} page {page_number}: {page_status}; {elapsed:.1f}s; "
                    f"{record['document_item_counts']['tables']} tables; "
                    f"{len(document_json) + len(markdown)} output bytes"
                )
            except (
                Exception
            ) as error:  # Do not persist exception text or extracted content.
                failures += 1
                record = {
                    "openalex_id": paper.openalex_id,
                    "page_number_1_based": page_number,
                    "status": "failure",
                    "exception_type": type(error).__name__,
                    "source_sha256": paper.source_sha256,
                    "source_bytes": paper.source_bytes,
                    "source_page_count": paper.page_count,
                    "config_id": config_id,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                }
                page_records.append(record)
                print(
                    f"{paper.openalex_id} page {page_number}: failed "
                    f"({record['exception_type']}); will retry next run"
                )
            atomic_write_json(record_path, record)
        paper_records.append(
            {
                "openalex_id": paper.openalex_id,
                "source_sha256": paper.source_sha256,
                "source_bytes": paper.source_bytes,
                "source_page_count": paper.page_count,
                "reviewed_page_numbers_1_based": paper.reviewed_page_numbers,
                "pages": page_records,
            }
        )

    peak_rss = sampler.stop()
    summary = {
        "schema_version": 1,
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "pipeline_key": args.pipeline,
        "config_id": config_id,
        "config": config,
        "paper_count": len(papers),
        "total_pdf_pages": sum(paper.page_count for paper in papers),
        "reviewed_page_count": sum(len(p.reviewed_page_numbers) for p in papers),
        "processed_page_count": processed_pages,
        "reused_completed_page_count": resumed_pages,
        "failure_count": failures,
        "elapsed_seconds": round(time.perf_counter() - run_started, 3),
        "peak_rss_bytes": peak_rss,
        "peak_rss_platform_value_bytes": resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss
        * 1024,
        "papers": paper_records,
    }
    atomic_write_json(output_dir / "run-summary.json", summary)
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pipeline", choices=("standard", "granite-vlm"), required=True
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--limit",
        type=int,
        help="Process only the first N papers (for a bounded smoke run).",
    )
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
