from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jsonschema import Draft202012Validator

from slidethus.constants import find_repository_root
from slidethus.gates import evaluate_gate
from slidethus.schema_registry import SchemaRegistry
from slidethus.validation import format_report, validate_workspace
from slidethus.wireframe import render_wireframes


def main() -> int:
    root = find_repository_root()
    registry = SchemaRegistry(root / "schemas")
    failures: list[str] = []

    for artifact_type in sorted(registry.entries):
        try:
            Draft202012Validator.check_schema(registry.schema(artifact_type))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"schema {artifact_type}: {exc}")

    example = root / "examples/minimal_project"
    report = validate_workspace(example, check_hashes=True)
    if not report.ok:
        failures.append(format_report(report))

    for gate_id in ["G0", "G1", "G2", "G3", "G4", "G5A", "G5B", "G6"]:
        result = evaluate_gate(example, gate_id)
        if not result.passed:
            failures.append(f"{gate_id}: {result.reasons}")
    if evaluate_gate(example, "G7").passed:
        failures.append("G7 unexpectedly passed; the bootstrap example must not claim final rendering")

    with tempfile.TemporaryDirectory(prefix="slidethus-wireframes-") as directory:
        outputs = render_wireframes(example, Path(directory))
        if len(outputs) != 3:
            failures.append(f"wireframe count: expected 3, got {len(outputs)}")
        for output in outputs:
            text = output.read_text(encoding="utf-8")
            if 'viewBox="0 0 1280 720"' not in text:
                failures.append(f"invalid wireframe canvas: {output}")

    source_manifest = json.loads((root / "source_material/manifest.json").read_text(encoding="utf-8"))
    if not source_manifest.get("files"):
        failures.append("source manifest is empty")

    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"PASS: {len(registry.entries)} schemas, example workspace, G0-G6, G7 negative control, and 3 wireframes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
