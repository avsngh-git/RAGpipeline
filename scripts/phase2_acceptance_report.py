"""Render a Phase 2 gate report from frozen criteria and aggregate observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_platform.evaluation.acceptance_report import (
    AcceptanceReportError,
    build_acceptance_gate_report,
    load_acceptance_config,
    render_acceptance_gate_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        observations_value = json.loads(
            arguments.observations.read_text(encoding="utf-8")
        )
        if not isinstance(observations_value, dict):
            raise AcceptanceReportError("observations must be a JSON object")
        report = build_acceptance_gate_report(
            load_acceptance_config(arguments.acceptance), observations_value
        )
        markdown = render_acceptance_gate_markdown(report)
        if arguments.output is None:
            print(markdown, end="")
        else:
            if arguments.output.exists():
                raise AcceptanceReportError("output already exists")
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(markdown, encoding="utf-8")
    except (OSError, json.JSONDecodeError, AcceptanceReportError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
