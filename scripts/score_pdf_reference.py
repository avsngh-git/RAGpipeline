"""Score parser outputs against the human-verified P1-07 reference annotations.

The JSON report contains only IDs, measurements, and counts. It is written to
Git-ignored local-reference/ and never prints source text.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ANNOTATIONS = ROOT / "local-reference/phase1-discovery-v1/draft-annotations"
DEFAULT_OUTPUT_ROOT = ROOT / "local-reference/phase1-discovery-v1/comparison"
PIPELINES = {
    "standard": "standard-reviewed-pages",
    "granite-vlm": "granite-vlm-reviewed-pages",
}
WORD = re.compile(r"[^\W_]+", flags=re.UNICODE)
NUMBER = re.compile(r"(?<![\w.])[+-]?\d+(?:[.,]\d+)*(?![\w.])")


def tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return WORD.findall(normalized)


def ordered_coverage(expected: list[str], observed: list[str]) -> float | None:
    if not expected:
        return None
    cursor = 0
    matched = 0
    for token in expected:
        try:
            cursor = observed.index(token, cursor) + 1
            matched += 1
        except ValueError:
            continue
    return round(matched / len(expected), 4)


def contiguous_coverage(expected: list[str], observed: list[str]) -> float | None:
    if not expected:
        return None
    previous = [0] * (len(observed) + 1)
    longest = 0
    for token in expected:
        current = [0]
        for index, candidate in enumerate(observed, 1):
            score = previous[index - 1] + 1 if token == candidate else 0
            current.append(score)
            longest = max(longest, score)
        previous = current
    return round(longest / len(expected), 4)


def load_page(
    pipeline_dir: Path, openalex_id: str, page_number: int
) -> tuple[dict[str, Any], str] | None:
    directory = pipeline_dir / openalex_id / f"page-{page_number:04d}"
    json_path = directory / "document.json"
    markdown_path = directory / "document.md"
    if not json_path.is_file() or not markdown_path.is_file():
        return None
    return json.loads(json_path.read_text(encoding="utf-8")), markdown_path.read_text(
        encoding="utf-8"
    )


def source_location_metrics(
    document: dict[str, Any], expected_page: int
) -> dict[str, int | float]:
    elements = [
        *document.get("texts", []),
        *document.get("tables", []),
        *document.get("pictures", []),
    ]
    located = 0
    wrong = 0
    for item in elements:
        provenances = item.get("prov", [])
        if not provenances:
            continue
        located += 1
        if any(
            provenance.get("page_no") != expected_page for provenance in provenances
        ):
            wrong += 1
    return {
        "element_count": len(elements),
        "located_element_count": located,
        "wrong_page_element_count": wrong,
    }


def reference_caption_texts(
    table: dict[str, Any], document: dict[str, Any]
) -> list[str]:
    texts_by_ref = {
        item.get("self_ref"): item.get("text", "") for item in document.get("texts", [])
    }
    captions = []
    for reference in table.get("captions", []):
        if isinstance(reference, dict):
            caption = texts_by_ref.get(reference.get("$ref"), "")
        else:
            caption = texts_by_ref.get(reference, "")
        if caption:
            captions.append(caption)
    return captions


def score_table(
    annotation: dict[str, Any], candidates: list[tuple[dict[str, Any], dict[str, Any]]]
) -> dict[str, Any]:
    expected_caption = tokens(annotation["caption_draft"])
    expected_row = tokens(annotation["selected_row_or_cell_draft"])
    expected_numbers = list(
        dict.fromkeys(NUMBER.findall(annotation["selected_row_or_cell_draft"]))
    )
    best: dict[str, Any] = {
        "candidate_table_count": sum(
            len(document.get("tables", [])) for document, _ in candidates
        ),
        "caption_ordered_token_coverage": None,
        "caption_contiguous_token_coverage": None,
        "selected_row_ordered_token_coverage": None,
        "selected_numeric_value_coverage": None,
        "best_row_numeric_value_coverage": None,
        "table_rows": None,
        "table_columns": None,
        "table_cell_count": None,
        "header_cell_count": None,
        "footnote_reference_count": None,
    }
    best_score = -1.0
    for document, _markdown in candidates:
        for table in document.get("tables", []):
            data = table.get("data", {})
            grid = data.get("grid", [])
            cells = [cell for row in grid for cell in row if isinstance(cell, dict)]
            cell_tokens = tokens(" ".join(cell.get("text", "") for cell in cells))
            captions = reference_caption_texts(table, document)
            caption_coverage = max(
                (
                    ordered_coverage(expected_caption, tokens(caption)) or 0.0
                    for caption in captions
                ),
                default=0.0,
            )
            row_coverage = ordered_coverage(expected_row, cell_tokens) or 0.0
            present_numbers = {
                number
                for number in expected_numbers
                if any(number in NUMBER.findall(cell.get("text", "")) for cell in cells)
            }
            numeric_coverage = (
                len(present_numbers) / len(expected_numbers)
                if expected_numbers
                else 1.0
            )
            row_numeric_coverages = []
            for row in grid:
                row_text = " ".join(
                    cell.get("text", "") for cell in row if isinstance(cell, dict)
                )
                row_numbers = set(NUMBER.findall(row_text))
                row_numeric_coverages.append(
                    len(row_numbers.intersection(expected_numbers))
                    / len(expected_numbers)
                    if expected_numbers
                    else 1.0
                )
            score = caption_coverage + row_coverage + numeric_coverage
            if score <= best_score:
                continue
            best_score = score
            best = {
                "candidate_table_count": sum(
                    len(doc.get("tables", [])) for doc, _ in candidates
                ),
                "caption_ordered_token_coverage": caption_coverage,
                "caption_contiguous_token_coverage": max(
                    (
                        contiguous_coverage(expected_caption, tokens(caption)) or 0.0
                        for caption in captions
                    ),
                    default=0.0,
                ),
                "selected_row_ordered_token_coverage": row_coverage,
                "selected_numeric_value_coverage": round(numeric_coverage, 4),
                "expected_unique_numeric_value_count": len(expected_numbers),
                "found_unique_numeric_value_count": len(present_numbers),
                "best_row_numeric_value_coverage": round(
                    max(row_numeric_coverages, default=0.0), 4
                ),
                "table_rows": data.get("num_rows"),
                "table_columns": data.get("num_cols"),
                "table_cell_count": len(cells),
                "header_cell_count": sum(
                    bool(cell.get("column_header") or cell.get("row_header"))
                    for cell in cells
                ),
                "footnote_reference_count": len(table.get("footnotes", [])),
            }
    return best


def evaluate_pipeline(pipeline: str, output_root: Path) -> dict[str, Any]:
    pipeline_dir = output_root / PIPELINES[pipeline]
    run_summary_path = pipeline_dir / "run-summary.json"
    run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
    paper_results = []
    prose_coverages: list[float] = []
    table_caption_coverages: list[float] = []
    table_numeric_coverages: list[float] = []
    table_row_coverages: list[float] = []
    numeric_found_total = 0
    numeric_expected_total = 0
    correct_page_elements = 0
    total_page_elements = 0
    table_count = 0
    table_cell_count = 0
    image_count = 0
    formula_count = 0

    for annotation_path in sorted(ANNOTATIONS.glob("W*.json")):
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        openalex_id = annotation_path.stem
        section_metrics = []
        for section in annotation["sections"]:
            page_number = section["page_index_zero_based"] + 1
            loaded = load_page(pipeline_dir, openalex_id, page_number)
            if loaded is None:
                section_metrics.append(
                    {"sample_id": section["sample_id"], "status": "missing_output"}
                )
                continue
            document, markdown = loaded
            expected = tokens(section["review_excerpt"])
            ordered = ordered_coverage(expected, tokens(markdown))
            contiguous = contiguous_coverage(expected, tokens(markdown))
            location = source_location_metrics(document, page_number)
            section_metrics.append(
                {
                    "sample_id": section["sample_id"],
                    "page_number_1_based": page_number,
                    "expected_word_token_count": len(expected),
                    "ordered_word_token_coverage": ordered,
                    "longest_contiguous_word_token_coverage": contiguous,
                    "location": location,
                    "document_page_numbers": sorted(
                        int(value) for value in document.get("pages", {})
                    ),
                }
            )
            if ordered is not None:
                prose_coverages.append(ordered)

        table_metrics = []
        for table_annotation in annotation["tables"]:
            candidates = []
            missing_pages = []
            for zero_based_page in table_annotation["page_indices_zero_based"]:
                page_number = zero_based_page + 1
                loaded = load_page(pipeline_dir, openalex_id, page_number)
                if loaded is None:
                    missing_pages.append(page_number)
                else:
                    candidates.append(loaded)
            metric = score_table(table_annotation, candidates)
            metric.update(
                {
                    "sample_id": table_annotation["sample_id"],
                    "source_page_numbers_1_based": [
                        p + 1 for p in table_annotation["page_indices_zero_based"]
                    ],
                    "missing_output_page_numbers_1_based": missing_pages,
                }
            )
            table_metrics.append(metric)
            if metric.get("caption_ordered_token_coverage") is not None:
                table_caption_coverages.append(metric["caption_ordered_token_coverage"])
            if metric.get("selected_row_ordered_token_coverage") is not None:
                table_row_coverages.append(
                    metric["selected_row_ordered_token_coverage"]
                )
            if metric.get("expected_unique_numeric_value_count", 0):
                table_numeric_coverages.append(
                    metric["selected_numeric_value_coverage"]
                )
                numeric_found_total += metric["found_unique_numeric_value_count"]
                numeric_expected_total += metric["expected_unique_numeric_value_count"]

        paper_results.append(
            {
                "openalex_id": openalex_id,
                "sections": section_metrics,
                "tables": table_metrics,
            }
        )

    output_bytes = sum(
        record.get("outputs", {}).get(key, {}).get("bytes", 0)
        for paper in run_summary.get("papers", [])
        for record in paper.get("pages", [])
        for key in ("document_json", "document_markdown")
    )
    page_records = [
        record
        for paper in run_summary.get("papers", [])
        for record in paper.get("pages", [])
    ]
    for record in page_records:
        loaded = load_page(
            pipeline_dir,
            record["openalex_id"],
            record["page_number_1_based"],
        )
        if loaded is None:
            continue
        document, _markdown = loaded
        location = source_location_metrics(document, record["page_number_1_based"])
        correct_page_elements += (
            location["located_element_count"] - location["wrong_page_element_count"]
        )
        total_page_elements += location["element_count"]
        table_count += len(document.get("tables", []))
        table_cell_count += sum(
            len(table.get("data", {}).get("table_cells", []))
            for table in document.get("tables", [])
        )
        image_count += len(document.get("pictures", []))
        formula_count += sum(
            item.get("label") == "formula" for item in document.get("texts", [])
        )
    gpu_peak = max(
        (
            record.get("gpu_memory", {}).get("peak_reserved_bytes", 0)
            for record in page_records
        ),
        default=0,
    )
    return {
        "pipeline": pipeline,
        "config_id": run_summary["config_id"],
        "paper_count": run_summary["paper_count"],
        "reviewed_page_count": run_summary["reviewed_page_count"],
        "failure_count": run_summary["failure_count"],
        "elapsed_seconds": run_summary["elapsed_seconds"],
        "peak_rss_bytes": run_summary["peak_rss_bytes"],
        "peak_gpu_reserved_bytes": gpu_peak,
        "serialized_output_bytes": output_bytes,
        "prose_ordered_token_coverage_mean": round(
            sum(prose_coverages) / len(prose_coverages), 4
        )
        if prose_coverages
        else None,
        "table_caption_token_coverage_mean": round(
            sum(table_caption_coverages) / len(table_caption_coverages), 4
        )
        if table_caption_coverages
        else None,
        "table_numeric_value_coverage_mean": round(
            sum(table_numeric_coverages) / len(table_numeric_coverages), 4
        )
        if table_numeric_coverages
        else None,
        "table_numeric_value_count_recall": round(
            numeric_found_total / numeric_expected_total, 4
        )
        if numeric_expected_total
        else None,
        "expected_unique_numeric_value_count": numeric_expected_total,
        "found_unique_numeric_value_count": numeric_found_total,
        "selected_row_ordered_token_coverage_mean": round(
            sum(table_row_coverages) / len(table_row_coverages), 4
        )
        if table_row_coverages
        else None,
        "page_element_location_accuracy": round(
            correct_page_elements / total_page_elements, 4
        )
        if total_page_elements
        else None,
        "located_page_element_count": total_page_elements,
        "parsed_table_count": table_count,
        "parsed_table_cell_count": table_cell_count,
        "parsed_picture_count": image_count,
        "parsed_formula_count": formula_count,
        "papers": paper_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pipeline",
        choices=tuple(PIPELINES),
        help="Score one pipeline; default scores both.",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    try:
        args.output_root.resolve().relative_to((ROOT / "local-reference").resolve())
    except ValueError:
        parser.error("The score report must remain under Git-ignored local-reference/")

    selected = (args.pipeline,) if args.pipeline else tuple(PIPELINES)
    report = {
        "schema_version": 1,
        "scoring_method": "ordered and contiguous normalized token coverage; numeric value presence in structured table cells; page provenance against the annotated PDF positions",
        "pipelines": {
            pipeline: evaluate_pipeline(pipeline, args.output_root)
            for pipeline in selected
        },
    }
    report_path = args.output_root / "quality-score.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for pipeline, result in report["pipelines"].items():
        print(
            f"{pipeline}: prose {result['prose_ordered_token_coverage_mean']}; "
            f"caption {result['table_caption_token_coverage_mean']}; "
            f"table values {result['table_numeric_value_coverage_mean']}; "
            f"location {result['page_element_location_accuracy']}; "
            f"{result['elapsed_seconds']:.1f}s"
        )
    print(f"metrics only: {report_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
